"""出库/调拨单路由（DESIGN §6）：总校办 → 校区。

kind=transfer（调拨给校区）：过账时 from 减 + to 增（同一事务、两条 movement、防超卖）
kind=issue（领用消耗）：过账只减 from

- GET    /outbound-orders            列表（kind/state/日期/库位/q 筛选 + 分页）
- POST   /outbound-orders            新建草稿
- GET    /outbound-orders/{id}       详情
- PATCH  /outbound-orders/{id}       改草稿（仅 draft；仅创建者或 admin）
- POST   /outbound-orders/{id}/post  过账（幂等）
- POST   /outbound-orders/{id}/void  作废冲销（A）
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import Location, OutboundItem, OutboundOrder, Item, User
from app.schemas.common import BizError, not_found, ok, ok_page
from app.services import stock
from app.services.audit import write_audit
from app.services.docno import PREFIX_OUTBOUND, next_doc_no

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/outbound-orders", tags=["出库单"])

AdminUser = require_role("admin")


# ---------- Pydantic ----------

class OutboundLineIn(BaseModel):
    item_id: int
    qty: int = Field(gt=0, description="数量必须大于 0")


class OutboundCreate(BaseModel):
    kind: str = Field(default="transfer", pattern=r"^(transfer|issue)$",
                      description="transfer=调拨给校区 | issue=领用消耗")
    from_location_id: int
    to_location_id: int | None = None
    order_date: date | None = None
    remark: str = Field(default="", max_length=2000)
    items: list[OutboundLineIn] = Field(default_factory=list)


class OutboundPatch(BaseModel):
    kind: str | None = Field(default=None, pattern=r"^(transfer|issue)$")
    from_location_id: int | None = None
    to_location_id: int | None = None
    order_date: date | None = None
    remark: str | None = Field(default=None, max_length=2000)
    items: list[OutboundLineIn] | None = None


# ---------- 序列化 ----------

def line_row(l: OutboundItem) -> dict:
    return {
        "id": l.id, "item_id": l.item_id,
        "barcode_snapshot": l.barcode_snapshot, "name_snapshot": l.name_snapshot,
        "qty": l.qty, "sort_order": l.sort_order,
    }


def order_row(o: OutboundOrder) -> dict:
    return {
        "id": o.id, "doc_no": o.doc_no, "kind": o.kind,
        "from_location_id": o.from_location_id,
        "from_location_name": o.from_location.name if o.from_location else None,
        "to_location_id": o.to_location_id,
        "to_location_name": o.to_location.name if o.to_location else None,
        "state": o.state,
        "order_date": o.order_date.isoformat() if o.order_date else None,
        "remark": o.remark or "",
        "operator_id": o.operator_id,
        "posted_at": o.posted_at.isoformat() if o.posted_at else None,
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "updated_at": o.updated_at.isoformat() if o.updated_at else None,
    }


def order_detail(o: OutboundOrder) -> dict:
    d = order_row(o)
    d["items"] = [line_row(l) for l in (o.items or [])]
    return d


# ---------- 内部工具 ----------

def _get_order(db: Session, order_id: int) -> OutboundOrder:
    o = db.scalar(
        select(OutboundOrder).options(selectinload(OutboundOrder.items))
        .where(OutboundOrder.id == order_id)
    )
    if o is None:
        raise not_found("出库单不存在")
    return o


def _validate_locations(db: Session, kind: str, from_id: int, to_id: int | None) -> None:
    if db.get(Location, from_id) is None:
        raise not_found("调出库位不存在")
    if kind == "transfer":
        if to_id is None:
            raise BizError("调拨单必须选择调入库位（领取校区）", code="ERR_NO_TARGET_LOCATION")
        if db.get(Location, to_id) is None:
            raise not_found("调入库位不存在")
        if to_id == from_id:
            raise BizError("调出与调入库位相同，无需调拨", code="ERR_SAME_LOCATION")


def _build_lines(db: Session, lines: list[OutboundLineIn]) -> list[OutboundItem]:
    out: list[OutboundItem] = []
    for idx, ln in enumerate(lines):
        item = db.get(Item, ln.item_id)
        if item is None:
            raise not_found(f"物品不存在（id={ln.item_id}）")
        if item.status != "active":
            raise BizError(f"物品「{item.name}」不是正常状态，不能加入出库单",
                           code="ERR_ITEM_STATUS", status=409)
        out.append(OutboundItem(
            item_id=item.id,
            barcode_snapshot=item.barcode,
            name_snapshot=item.name,
            qty=ln.qty,
            sort_order=idx,
        ))
    return out


def _check_editable(o: OutboundOrder, user: User) -> None:
    if o.state != "draft":
        raise BizError("只有草稿状态的单据才能修改；已过账的单据请先作废（管理员）",
                       code="ERR_DOC_NOT_DRAFT", status=409)
    if user.role not in ("admin", "superadmin") and o.operator_id != user.id:
        raise BizError("只能修改自己创建的草稿单", code="ERR_FORBIDDEN", status=403)


# ---------- 路由 ----------

@router.get("")
def list_outbound_orders(
    page: int = 1, page_size: int = 20,
    kind: str | None = None,
    state: str | None = None,
    location_id: int | None = None,
    start: date | None = None, end: date | None = None,
    q: str | None = None,
    sort_by: str = "id", sort_dir: str = "desc",
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    conds = []
    if kind:
        conds.append(OutboundOrder.kind == kind)
    if state:
        conds.append(OutboundOrder.state == state)
    if location_id is not None:
        conds.append(or_(
            OutboundOrder.from_location_id == location_id,
            OutboundOrder.to_location_id == location_id,
        ))
    if start:
        conds.append(OutboundOrder.order_date >= start)
    if end:
        conds.append(OutboundOrder.order_date <= end)
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(
            OutboundOrder.doc_no.like(like),
            OutboundOrder.remark.like(like),
        ))

    cq = select(func.count(OutboundOrder.id))
    for c in conds:
        cq = cq.where(c)
    total = db.scalar(cq) or 0

    sortable = {"id": OutboundOrder.id, "doc_no": OutboundOrder.doc_no,
                "order_date": OutboundOrder.order_date, "created_at": OutboundOrder.created_at}
    col = sortable.get(sort_by, OutboundOrder.id)
    order_by = col.desc() if sort_dir == "desc" else col.asc()

    q_stmt = select(OutboundOrder).order_by(order_by, OutboundOrder.id.desc()) \
        .offset((page - 1) * page_size).limit(page_size)
    for c in conds:
        q_stmt = q_stmt.where(c)
    rows = db.scalars(q_stmt).all()
    return ok_page([order_row(o) for o in rows], page=page, page_size=page_size, total=total)


@router.post("")
def create_outbound_order(body: OutboundCreate, request: Request,
                          user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _validate_locations(db, body.kind, body.from_location_id, body.to_location_id)
    doc_no = next_doc_no(db, PREFIX_OUTBOUND)
    o = OutboundOrder(
        doc_no=doc_no,
        kind=body.kind,
        from_location_id=body.from_location_id,
        to_location_id=body.to_location_id if body.kind == "transfer" else None,
        state="draft",
        order_date=body.order_date or date.today(),
        remark=body.remark,
        operator_id=user.id,
    )
    o.items = _build_lines(db, body.items)
    db.add(o)
    write_audit(db, action="create", entity="outbound_order", user=user,
                detail={"doc_no": doc_no, "kind": body.kind, "lines": len(o.items)}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))


@router.get("/{order_id}")
def get_outbound_order(order_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(order_detail(_get_order(db, order_id)))


@router.patch("/{order_id}")
def patch_outbound_order(order_id: int, body: OutboundPatch, request: Request,
                         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    _check_editable(o, user)
    data = body.model_dump(exclude_unset=True)

    new_kind = data.get("kind", o.kind) or o.kind
    new_from = data.get("from_location_id", o.from_location_id) or o.from_location_id
    new_to = data.get("to_location_id", o.to_location_id) if "to_location_id" in data else o.to_location_id
    _validate_locations(db, new_kind, new_from, new_to)

    o.kind = new_kind
    o.from_location_id = new_from
    o.to_location_id = new_to if new_kind == "transfer" else None
    for k in ("order_date", "remark"):
        if k in data:
            setattr(o, k, data[k])

    if "items" in data and data["items"] is not None:
        for old_line in list(o.items or []):
            db.delete(old_line)
        db.flush()
        o.items = _build_lines(db, body.items or [])

    write_audit(db, action="update", entity="outbound_order", entity_id=o.id, user=user,
                detail={"fields": sorted(data.keys())}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))


@router.post("/{order_id}/post")
def post_outbound_order(order_id: int, request: Request,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    if not (o.items or []):
        raise BizError("单据没有明细行，无法过账；请先扫码或手动添加物品", code="ERR_DOC_EMPTY")
    try:
        stock.post_outbound_transfer(db, o, operator_id=user.id)
        write_audit(db, action="post", entity="outbound_order", entity_id=o.id, user=user,
                    detail={"doc_no": o.doc_no, "kind": o.kind}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))


@router.post("/{order_id}/void")
def void_outbound_order(order_id: int, request: Request,
                        admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    o = _get_order(db, order_id)
    try:
        stock.void_outbound(db, o, admin_id=admin.id)
        write_audit(db, action="void", entity="outbound_order", entity_id=o.id, user=admin,
                    detail={"doc_no": o.doc_no}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(order_detail(_get_order(db, o.id)))
