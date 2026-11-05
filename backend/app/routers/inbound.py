"""入库单路由（DESIGN §6）：采购到总校办前置仓，过账后 HQ（或指定库位）库存增加。

- GET    /inbound-orders                列表（state/日期范围/location_id/q 筛选 + 分页）
- POST   /inbound-orders                新建草稿（可带明细行）
- GET    /inbound-orders/{id}           详情（含明细）
- PATCH  /inbound-orders/{id}           改草稿（仅 draft；仅创建者或 admin）
- POST   /inbound-orders/{id}/post      过账（幂等，AO）
- POST   /inbound-orders/{id}/void      作废冲销（A）
- GET    /inbound-orders/{id}/yizhiniao-export  导出易知鸟 9 列模板 xlsx

明细行存 barcode/name/spec 快照：条码可能被重分配、物品可能被合并，历史单据不能失真。
"""
import io
import logging
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import can_see_cost_prices, get_current_user, require_role, teacher_home_location
from app.models import InboundItem, InboundOrder, Item, Location, User
from app.schemas.common import BizError, not_found, ok, ok_page
from app.services import stock
from app.services.audit import write_audit
from app.services.docno import PREFIX_INBOUND, next_doc_no

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inbound-orders", tags=["入库单"])

AdminUser = require_role("admin")


# ---------- Pydantic ----------

class InboundLineIn(BaseModel):
    item_id: int
    qty: int = Field(gt=0, description="数量必须大于 0")
    purchase_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    sale_price: Decimal | None = Field(default=None, ge=0, decimal_places=2)


class InboundCreate(BaseModel):
    supplier: str = Field(default="", max_length=100)
    location_id: int
    is_for_sale: bool = True
    order_date: date | None = None
    remark: str = Field(default="", max_length=2000)
    items: list[InboundLineIn] = Field(default_factory=list)


class InboundPatch(BaseModel):
    supplier: str | None = Field(default=None, max_length=100)
    location_id: int | None = None
    is_for_sale: bool | None = None
    order_date: date | None = None
    remark: str | None = Field(default=None, max_length=2000)
    items: list[InboundLineIn] | None = None


# ---------- 序列化 ----------

def line_row(l: InboundItem, user: User | None = None) -> dict:
    d = {
        "id": l.id, "item_id": l.item_id,
        "barcode_snapshot": l.barcode_snapshot, "name_snapshot": l.name_snapshot,
        "spec_snapshot": l.spec_snapshot,
        "qty": l.qty,
        "sort_order": l.sort_order,
    }
    # 采购价/内部销售价快照对教师脱敏
    if user is None or can_see_cost_prices(user):
        d["purchase_price"] = float(l.purchase_price) if l.purchase_price is not None else None
        d["sale_price"] = float(l.sale_price) if l.sale_price is not None else None
    return d


def order_row(o: InboundOrder, user: User | None = None) -> dict:
    return {
        "id": o.id, "doc_no": o.doc_no, "supplier": o.supplier or "",
        "location_id": o.location_id,
        "location_name": o.location.name if o.location else None,
        "is_for_sale": o.is_for_sale, "state": o.state,
        "order_date": o.order_date.isoformat() if o.order_date else None,
        # 单据金额来自采购价，教师不可见
        "total_amount": (float(o.total_amount) if o.total_amount is not None else 0.0)
                        if (user is None or can_see_cost_prices(user)) else None,
        "remark": o.remark or "",
        "operator_id": o.operator_id,
        "posted_at": o.posted_at.isoformat() if o.posted_at else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def order_detail(o: InboundOrder, user: User | None = None) -> dict:
    d = order_row(o, user=user)
    d["items"] = [line_row(l, user=user) for l in (o.items or [])]
    return d


# ---------- 内部工具 ----------

def _get_order(db: Session, order_id: int) -> InboundOrder:
    o = db.scalar(
        select(InboundOrder).options(selectinload(InboundOrder.items))
        .where(InboundOrder.id == order_id)
    )
    if o is None:
        raise not_found("入库单不存在")
    return o


def _get_item_active(db: Session, item_id: int) -> Item:
    item = db.get(Item, item_id)
    if item is None:
        raise not_found(f"物品不存在（id={item_id}）")
    if item.status != "active":
        raise BizError(f"物品「{item.name}」不是正常状态，不能加入入库单",
                       code="ERR_ITEM_STATUS", status=409)
    return item


def _build_lines(db: Session, lines: list[InboundLineIn]) -> list[InboundItem]:
    out: list[InboundItem] = []
    for idx, ln in enumerate(lines):
        item = _get_item_active(db, ln.item_id)
        out.append(InboundItem(
            item_id=item.id,
            barcode_snapshot=item.barcode,
            name_snapshot=item.name,
            spec_snapshot=item.spec or "",
            qty=ln.qty,
            purchase_price=ln.purchase_price,
            sale_price=ln.sale_price,
            sort_order=idx,
        ))
    return out


def _calc_total(lines: list[InboundItem]) -> Decimal:
    total = Decimal("0")
    for l in lines:
        if l.purchase_price is not None:
            total += Decimal(l.purchase_price) * l.qty
    return total


def _check_editable(o: InboundOrder, user: User) -> None:
    if o.state != "draft":
        raise BizError("只有草稿状态的单据才能修改；已过账的单据请先作废（管理员）",
                       code="ERR_DOC_NOT_DRAFT", status=409)
    if user.role not in ("admin", "superadmin") and o.operator_id != user.id:
        raise BizError("只能修改自己创建的草稿单", code="ERR_FORBIDDEN", status=403)


def _validate_location(db: Session, location_id: int) -> Location:
    loc = db.get(Location, location_id)
    if loc is None:
        raise not_found("库位不存在")
    return loc


# ---------- 路由 ----------

@router.get("")
def list_inbound_orders(
    page: int = 1, page_size: int = 20,
    state: str | None = None,
    location_id: int | None = None,
    start: date | None = None, end: date | None = None,
    q: str | None = None,
    sort_by: str = "id", sort_dir: str = "desc",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    conds = []
    # 教师：只能看自己校区的入库单
    if user.role == "teacher":
        location_id = teacher_home_location(user)
    if state:
        conds.append(InboundOrder.state == state)
    if location_id is not None:
        conds.append(InboundOrder.location_id == location_id)
    if start:
        conds.append(InboundOrder.order_date >= start)
    if end:
        conds.append(InboundOrder.order_date <= end)
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(
            InboundOrder.doc_no.like(like),
            InboundOrder.supplier.like(like),
            InboundOrder.remark.like(like),
        ))

    cq = select(func.count(InboundOrder.id))
    for c in conds:
        cq = cq.where(c)
    total = db.scalar(cq) or 0

    sortable = {"id": InboundOrder.id, "doc_no": InboundOrder.doc_no,
                "order_date": InboundOrder.order_date, "created_at": InboundOrder.created_at}
    col = sortable.get(sort_by, InboundOrder.id)
    order_by = col.desc() if sort_dir == "desc" else col.asc()

    q_stmt = select(InboundOrder).order_by(order_by, InboundOrder.id.desc()) \
        .offset((page - 1) * page_size).limit(page_size)
    for c in conds:
        q_stmt = q_stmt.where(c)
    rows = db.scalars(q_stmt).all()
    return ok_page([order_row(o, user=user) for o in rows], page=page, page_size=page_size, total=total)


@router.post("")
def create_inbound_order(body: InboundCreate, request: Request,
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # 教师：入库固定到自己校区，且不带采购/内部价格（成本信息教师不可见）
    if user.role == "teacher":
        body.location_id = teacher_home_location(user)
        body.items = [ln.model_copy(update={"purchase_price": None, "sale_price": None}) for ln in body.items]
    _validate_location(db, body.location_id)
    doc_no = next_doc_no(db, PREFIX_INBOUND)
    o = InboundOrder(
        doc_no=doc_no,
        supplier=body.supplier.strip(),
        location_id=body.location_id,
        is_for_sale=body.is_for_sale,
        state="draft",
        order_date=body.order_date or date.today(),
        remark=body.remark,
        operator_id=user.id,
    )
    o.items = _build_lines(db, body.items)
    o.total_amount = _calc_total(o.items)
    db.add(o)
    write_audit(db, action="create", entity="inbound_order", user=user,
                detail={"doc_no": doc_no, "lines": len(o.items)}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id), user=user))


@router.get("/{order_id}")
def _check_teacher_scope(o: InboundOrder, user: User) -> None:
    """教师只能查看/操作自己校区的入库单。"""
    if user.role == "teacher" and o.location_id != teacher_home_location(user):
        raise BizError("只能查看本校区的单据", code="ERR_FORBIDDEN", status=403)


@router.get("/{order_id}")
def get_inbound_order(order_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    _check_teacher_scope(o, user)
    return ok(order_detail(o, user=user))


@router.patch("/{order_id}")
def patch_inbound_order(order_id: int, body: InboundPatch, request: Request,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    _check_teacher_scope(o, user)
    _check_editable(o, user)
    data = body.model_dump(exclude_unset=True)

    if user.role == "teacher":
        data.pop("location_id", None)  # 教师单据的校区不允许变更
    if "location_id" in data and data["location_id"] is not None:
        _validate_location(db, data["location_id"])
        o.location_id = data["location_id"]
    for k in ("supplier", "is_for_sale", "order_date", "remark"):
        if k in data:
            v = data[k]
            if k == "supplier" and isinstance(v, str):
                v = v.strip()
            setattr(o, k, v)

    if "items" in data and data["items"] is not None:
        # 明细整体替换（草稿阶段前端一次性提交全量行）
        for old_line in list(o.items or []):
            db.delete(old_line)
        db.flush()
        o.items = _build_lines(db, body.items or [])
    o.total_amount = _calc_total(list(o.items or []))

    write_audit(db, action="update", entity="inbound_order", entity_id=o.id, user=user,
                detail={"fields": sorted(data.keys())}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id), user=user))


@router.post("/{order_id}/post")
def post_inbound_order(order_id: int, request: Request,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    _check_teacher_scope(o, user)
    if not (o.items or []):
        raise BizError("单据没有明细行，无法过账；请先扫码或手动添加物品", code="ERR_DOC_EMPTY")
    try:
        stock.post_inbound(db, o, operator_id=user.id)
        write_audit(db, action="post", entity="inbound_order", entity_id=o.id, user=user,
                    detail={"doc_no": o.doc_no}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id), user=user))


@router.post("/{order_id}/void")
def void_inbound_order(order_id: int, request: Request,
                       admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    try:
        stock.void_inbound(db, o, admin_id=admin.id)
        write_audit(db, action="void", entity="inbound_order", entity_id=o.id, user=admin,
                    detail={"doc_no": o.doc_no, "reversed": o.state == "voided"}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))


# ---------- 易知鸟导出 ----------

# 9 列顺序**必须严格**与易知鸟库存导入模板一致（带 * 为易知鸟必填列）
YZN_HEADERS = [
    "*物品名称", "条形编码", "*是否售卖", "规格名称", "售卖价格",
    "采购数量", "采购单价", "入库时间", "入库备注",
]


@router.get("/{order_id}/yizhiniao-export")
def yizhiniao_export(order_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """导出易知鸟库存导入模板 xlsx（9 列）。是否售卖取单据 is_for_sale（是/否）。"""
    from openpyxl import Workbook

    o = _get_order(db, order_id)
    if not (o.items or []):
        raise BizError("单据没有明细行，无法导出", code="ERR_DOC_EMPTY")

    is_sale = "是" if o.is_for_sale else "否"
    inbound_time = o.order_date.strftime("%Y-%m-%d") if o.order_date else ""
    remark = (o.remark or "").strip()

    wb = Workbook()
    ws = wb.active
    ws.title = "库存导入"
    ws.append(YZN_HEADERS)
    for l in (o.items or []):
        name = l.name_snapshot or (l.item.name if l.item else "")
        ws.append([
            name,
            l.barcode_snapshot or "",
            is_sale,
            l.spec_snapshot or "",
            float(l.sale_price) if l.sale_price is not None else "",
            l.qty,
            float(l.purchase_price) if l.purchase_price is not None else "",
            inbound_time,
            remark,
        ])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"yizhiniao-{o.doc_no}.xlsx"
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
