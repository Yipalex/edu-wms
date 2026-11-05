"""库存流水查询路由（DESIGN §6：GET /movements）。

- GET /movements           流水明细（多维筛选 + 分页，只读）
                           筛选：start/end（按流水发生日期）、location_id、item_id、
                                 doc_type（inbound/outbound/return/transfer/stocktake/adjust）、
                                 operator_id、q（单号/物品名/条码/备注模糊）
- GET /movements/{id}      单条流水详情

铁律：流水是审计真源，本模块**只读**，不提供任何写/改/删入口
（库存变动只能走单据过账，见 app/services/stock.py）。
"""
import logging
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, teacher_home_location
from app.models import Item, Location, StockMovement, User
from app.schemas.common import BizError, not_found, ok, ok_page

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/movements", tags=["库存流水"])


# ---------- 序列化 ----------

def mv_row(m: StockMovement) -> dict:
    item = m.item
    loc = m.location
    op = m.operator
    return {
        "id": m.id,
        "item_id": m.item_id,
        "item_name": item.name if item else None,
        "barcode": item.barcode if item else None,
        "category_id": item.category_id if item else None,
        "category_name": item.category.name if (item and item.category) else None,
        "location_id": m.location_id,
        "location_name": loc.name if loc else None,
        "location_code": loc.code if loc else None,
        "change_qty": m.change_qty,
        "qty_before": m.qty_before,
        "qty_after": m.qty_after,
        "doc_type": m.doc_type,
        "doc_id": m.doc_id,
        "doc_no": m.doc_no,
        "operator_id": m.operator_id,
        "operator_name": op.display_name if op else None,
        "note": m.note or "",
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


# ---------- 内部工具 ----------

def _day_start(d: date) -> datetime:
    """日期 → 当日 00:00（朴素 datetime，与 SQLite 存储格式一致；PG 侧由会话时区解释）。"""
    return datetime.combine(d, time.min)


def _build_conds(
    *, start: date | None, end: date | None,
    location_id: int | None, item_id: int | None,
    doc_type: str | None, operator_id: int | None, q: str | None,
) -> list:
    conds = []
    if start:
        conds.append(StockMovement.created_at >= _day_start(start))
    if end:
        conds.append(StockMovement.created_at < _day_start(end + timedelta(days=1)))
    if location_id is not None:
        conds.append(StockMovement.location_id == location_id)
    if item_id is not None:
        conds.append(StockMovement.item_id == item_id)
    if doc_type:
        conds.append(StockMovement.doc_type == doc_type)
    if operator_id is not None:
        conds.append(StockMovement.operator_id == operator_id)
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(
            StockMovement.doc_no.like(like),
            StockMovement.note.like(like),
            Item.name.like(like),
            Item.barcode.like(like),
        ))
    return conds


# ---------- 路由 ----------

@router.get("")
def list_movements(
    page: int = 1, page_size: int = 20,
    start: date | None = None, end: date | None = None,
    location_id: int | None = None, item_id: int | None = None,
    doc_type: str | None = None, operator_id: int | None = None,
    q: str | None = None,
    sort_by: str = "id", sort_dir: str = "desc",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(500, max(1, page_size))

    # 教师：只能看自己校区的流水
    if user.role == "teacher":
        location_id = teacher_home_location(user)

    base = select(StockMovement).join(Item, Item.id == StockMovement.item_id)
    conds = _build_conds(start=start, end=end, location_id=location_id,
                         item_id=item_id, doc_type=doc_type,
                         operator_id=operator_id, q=q)

    cq = select(func.count(StockMovement.id)).join(Item, Item.id == StockMovement.item_id)
    for c in conds:
        cq = cq.where(c)
    total = db.scalar(cq) or 0

    sortable = {
        "id": StockMovement.id, "created_at": StockMovement.created_at,
        "change_qty": StockMovement.change_qty, "item_name": Item.name,
        "doc_type": StockMovement.doc_type,
    }
    col = sortable.get(sort_by, StockMovement.id)
    order_by = col.desc() if sort_dir == "desc" else col.asc()

    q_stmt = base.order_by(order_by, StockMovement.id.desc()) \
        .offset((page - 1) * page_size).limit(page_size)
    for c in conds:
        q_stmt = q_stmt.where(c)
    rows = db.scalars(q_stmt).all()
    return ok_page([mv_row(r) for r in rows], page=page, page_size=page_size, total=total)


@router.get("/{movement_id}")
def get_movement(movement_id: int, user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    m = db.get(StockMovement, movement_id)
    if m is not None and user.role == "teacher" and m.location_id != teacher_home_location(user):
        raise BizError("只能查看本校区的流水", code="ERR_FORBIDDEN", status=403)
    if m is None:
        raise not_found("流水记录不存在")
    return ok(mv_row(m))
