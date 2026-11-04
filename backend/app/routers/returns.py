"""退库单路由（DESIGN §6 + 《仓库管理制度-928.docx》第十五条）：校区 → 总校办。

制度硬要求：**未拆封未使用才可退库**。
- item_condition=sealed（未拆封）：管理员验收通过（accept）后才过账增库存
- item_condition=opened（已拆封或已使用）：accept 一律拒绝（400 中文制度提示）
- reject 拒收：不动库存，state=rejected

状态字段两套：
- state（return_state）：pending / accepted / rejected —— 验收结论
- accept_state（doc_state）：draft / posted / voided —— 库存过账状态（幂等锁）

- GET    /return-orders            列表
- POST   /return-orders            新建（pending）
- GET    /return-orders/{id}       详情
- PATCH  /return-orders/{id}       改草稿（pending 且未过账；仅创建者或 admin）
- POST   /return-orders/{id}/accept  验收通过并过账（A）
- POST   /return-orders/{id}/reject  拒收（A，不动库存）
- POST   /return-orders/{id}/void    作废冲销（A，仅已过账）
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import Item, Location, ReturnItem, ReturnOrder, User
from app.schemas.common import BizError, not_found, ok, ok_page
from app.services import stock
from app.services.audit import write_audit
from app.services.docno import PREFIX_RETURN, next_doc_no

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/return-orders", tags=["退库单"])

AdminUser = require_role("admin")

REGULATION_MSG = "按《仓库管理制度》第十五条，已拆封或已使用的物品不得退库"


# ---------- Pydantic ----------

class ReturnLineIn(BaseModel):
    item_id: int
    qty: int = Field(gt=0, description="数量必须大于 0")


class ReturnCreate(BaseModel):
    from_location_id: int = Field(description="退回校区")
    to_location_id: int = Field(description="退回总校办仓库")
    item_condition: str = Field(default="sealed", pattern=r"^(sealed|opened)$",
                                description="sealed=未拆封 | opened=已拆封或已使用")
    order_date: date | None = None
    remark: str = Field(default="", max_length=2000)
    items: list[ReturnLineIn] = Field(default_factory=list)


class ReturnPatch(BaseModel):
    from_location_id: int | None = None
    to_location_id: int | None = None
    item_condition: str | None = Field(default=None, pattern=r"^(sealed|opened)$")
    order_date: date | None = None
    remark: str | None = Field(default=None, max_length=2000)
    items: list[ReturnLineIn] | None = None


# ---------- 序列化 ----------

def line_row(l: ReturnItem) -> dict:
    return {
        "id": l.id, "item_id": l.item_id,
        "barcode_snapshot": l.barcode_snapshot, "name_snapshot": l.name_snapshot,
        "qty": l.qty, "sort_order": l.sort_order,
    }


def order_row(o: ReturnOrder) -> dict:
    return {
        "id": o.id, "doc_no": o.doc_no,
        "from_location_id": o.from_location_id,
        "from_location_name": o.from_location.name if o.from_location else None,
        "to_location_id": o.to_location_id,
        "to_location_name": o.to_location.name if o.to_location else None,
        "item_condition": o.item_condition,
        "state": o.state, "accept_state": o.accept_state,
        "order_date": o.order_date.isoformat() if o.order_date else None,
        "remark": o.remark or "",
        "operator_id": o.operator_id,
        "accepted_by": o.accepted_by,
        "posted_at": o.posted_at.isoformat() if o.posted_at else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def order_detail(o: ReturnOrder) -> dict:
    d = order_row(o)
    d["items"] = [line_row(l) for l in (o.items or [])]
    return d


# ---------- 内部工具 ----------

def _get_order(db: Session, order_id: int) -> ReturnOrder:
    o = db.scalar(
        select(ReturnOrder).options(selectinload(ReturnOrder.items))
        .where(ReturnOrder.id == order_id)
    )
    if o is None:
        raise not_found("退库单不存在")
    return o


def _validate_locations(db: Session, from_id: int, to_id: int) -> None:
    if db.get(Location, from_id) is None:
        raise not_found("退回校区不存在")
    if db.get(Location, to_id) is None:
        raise not_found("接收仓库不存在")
    if from_id == to_id:
        raise BizError("退回库位与接收库位不能相同", code="ERR_SAME_LOCATION")


def _build_lines(db: Session, lines: list[ReturnLineIn]) -> list[ReturnItem]:
    out: list[ReturnItem] = []
    for idx, ln in enumerate(lines):
        item = db.get(Item, ln.item_id)
        if item is None:
            raise not_found(f"物品不存在（id={ln.item_id}）")
        if item.status != "active":
            raise BizError(f"物品「{item.name}」不是正常状态，不能加入退库单",
                           code="ERR_ITEM_STATUS", status=409)
        out.append(ReturnItem(
            item_id=item.id,
            barcode_snapshot=item.barcode,
            name_snapshot=item.name,
            qty=ln.qty,
            sort_order=idx,
        ))
    return out


def _check_editable(o: ReturnOrder, user: User) -> None:
    if o.accept_state != "draft" or o.state != "pending":
        raise BizError("该退库单已验收或已拒收，不能再修改", code="ERR_DOC_NOT_DRAFT", status=409)
    if user.role not in ("admin", "superadmin") and o.operator_id != user.id:
        raise BizError("只能修改自己创建的草稿单", code="ERR_FORBIDDEN", status=403)


# ---------- 路由 ----------

@router.get("")
def list_return_orders(
    page: int = 1, page_size: int = 20,
    state: str | None = None,
    item_condition: str | None = None,
    location_id: int | None = None,
    start: date | None = None, end: date | None = None,
    q: str | None = None,
    sort_by: str = "id", sort_dir: str = "desc",
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    conds = []
    if state:
        conds.append(ReturnOrder.state == state)
    if item_condition:
        conds.append(ReturnOrder.item_condition == item_condition)
    if location_id is not None:
        conds.append(or_(
            ReturnOrder.from_location_id == location_id,
            ReturnOrder.to_location_id == location_id,
        ))
    if start:
        conds.append(ReturnOrder.order_date >= start)
    if end:
        conds.append(ReturnOrder.order_date <= end)
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(ReturnOrder.doc_no.like(like), ReturnOrder.remark.like(like)))

    cq = select(func.count(ReturnOrder.id))
    for c in conds:
        cq = cq.where(c)
    total = db.scalar(cq) or 0

    sortable = {"id": ReturnOrder.id, "doc_no": ReturnOrder.doc_no,
                "order_date": ReturnOrder.order_date, "created_at": ReturnOrder.created_at}
    col = sortable.get(sort_by, ReturnOrder.id)
    order_by = col.desc() if sort_dir == "desc" else col.asc()

    q_stmt = select(ReturnOrder).order_by(order_by, ReturnOrder.id.desc()) \
        .offset((page - 1) * page_size).limit(page_size)
    for c in conds:
        q_stmt = q_stmt.where(c)
    rows = db.scalars(q_stmt).all()
    return ok_page([order_row(o) for o in rows], page=page, page_size=page_size, total=total)


@router.post("")
def create_return_order(body: ReturnCreate, request: Request,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _validate_locations(db, body.from_location_id, body.to_location_id)
    doc_no = next_doc_no(db, PREFIX_RETURN)
    o = ReturnOrder(
        doc_no=doc_no,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id,
        item_condition=body.item_condition,
        state="pending",
        accept_state="draft",
        order_date=body.order_date or date.today(),
        remark=body.remark,
        operator_id=user.id,
    )
    o.items = _build_lines(db, body.items)
    db.add(o)
    write_audit(db, action="create", entity="return_order", user=user,
                detail={"doc_no": doc_no, "item_condition": body.item_condition,
                        "lines": len(o.items)}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))


@router.get("/{order_id}")
def get_return_order(order_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(order_detail(_get_order(db, order_id)))


@router.patch("/{order_id}")
def patch_return_order(order_id: int, body: ReturnPatch, request: Request,
                       user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    _check_editable(o, user)
    data = body.model_dump(exclude_unset=True)

    new_from = data.get("from_location_id", o.from_location_id) or o.from_location_id
    new_to = data.get("to_location_id", o.to_location_id) or o.to_location_id
    if "from_location_id" in data or "to_location_id" in data:
        _validate_locations(db, new_from, new_to)
    o.from_location_id = new_from
    o.to_location_id = new_to
    for k in ("item_condition", "order_date", "remark"):
        if k in data:
            setattr(o, k, data[k])

    if "items" in data and data["items"] is not None:
        for old_line in list(o.items or []):
            db.delete(old_line)
        db.flush()
        o.items = _build_lines(db, body.items or [])

    write_audit(db, action="update", entity="return_order", entity_id=o.id, user=user,
                detail={"fields": sorted(data.keys())}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))


@router.post("/{order_id}/accept")
def accept_return_order(order_id: int, request: Request,
                        admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    """验收通过 → 过账（校区减、总校办增）。仅 admin。

    制度硬约束：item_condition=opened 一律拒绝。
    幂等：accept_state draft→posted 条件更新，重复提交 409。
    """
    o = _get_order(db, order_id)
    if o.state == "rejected":
        raise BizError("该退库单已拒收，不能再验收通过", code="ERR_DOC_REJECTED", status=409)
    if o.state != "pending":
        raise BizError("该退库单已验收，请勿重复提交", code="ERR_DOC_NOT_PENDING", status=409)
    if o.item_condition == "opened":
        # 《仓库管理制度-928.docx》第十五条：未拆封未使用才可退库
        raise BizError(REGULATION_MSG, code="ERR_RETURN_OPENED", status=400)
    if not (o.items or []):
        raise BizError("单据没有明细行，无法验收过账", code="ERR_DOC_EMPTY")
    try:
        o.state = "accepted"
        o.accepted_by = admin.id
        db.flush()
        stock.post_return(db, o, operator_id=admin.id)
        write_audit(db, action="accept", entity="return_order", entity_id=o.id, user=admin,
                    detail={"doc_no": o.doc_no}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))


@router.post("/{order_id}/reject")
def reject_return_order(order_id: int, request: Request,
                        admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    """拒收：state=rejected，**不动库存**。仅 admin。"""
    o = _get_order(db, order_id)
    if o.state != "pending":
        raise BizError("该退库单已处理过（验收或拒收），不能重复操作",
                       code="ERR_DOC_NOT_PENDING", status=409)
    try:
        o.state = "rejected"
        o.accepted_by = admin.id
        write_audit(db, action="reject", entity="return_order", entity_id=o.id, user=admin,
                    detail={"doc_no": o.doc_no}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))


@router.post("/{order_id}/void")
def void_return_order(order_id: int, request: Request,
                      admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    try:
        stock.void_return(db, o, admin_id=admin.id)
        write_audit(db, action="void", entity="return_order", entity_id=o.id, user=admin,
                    detail={"doc_no": o.doc_no}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))
