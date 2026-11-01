"""盘点单路由（DESIGN §6）：按库位+类目生成待盘行，扫码录实盘数，过账按差异校正库存。

- GET    /stocktakes                          列表
- POST   /stocktakes                          新建（按 location_id + category_id 生成待盘行，快照 qty_book）
- GET    /stocktakes/{id}                     详情（含盘点行）
- POST   /stocktakes/{id}/scan                扫码录入实盘数（不在单内则自动加行）
- PATCH  /stocktakes/{id}/items/{row_id}      改实盘数/处理结果/备注
- POST   /stocktakes/{id}/post                过账（按差异写 adjust 流水校正库存，state→done）

注意：stocktake_state 枚举只有 draft/counting/done（无 voided），盘点单不支持作废；
盘错了就再开一张盘点单校正（契约设计如此）。

⚠️ stocktake_items.variance 是数据库**生成列**（Computed("qty_counted - qty_book")），
写入时绝不能显式赋值；读取前需 flush + refresh 才能拿到数据库算出的值。
"""
import logging
from datetime import date

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import Category, Inventory, Item, Location, Stocktake, StocktakeItem, User
from app.schemas.common import BizError, not_found, ok, ok_page
from app.services import stock
from app.services.audit import write_audit
from app.services.docno import PREFIX_STOCKTAKE, next_doc_no

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stocktakes", tags=["盘点"])

AdminUser = require_role("admin")

MAX_STOCKTAKE_ROWS = 5000


# ---------- Pydantic ----------

class StocktakeCreate(BaseModel):
    location_id: int
    category_id: int | None = Field(default=None, description="留空=全类目")
    stocktake_date: date | None = None
    remark: str = Field(default="", max_length=2000)


class StocktakePatch(BaseModel):
    stocktake_date: date | None = None
    remark: str | None = Field(default=None, max_length=2000)


class ScanBody(BaseModel):
    barcode: str = Field(min_length=1, max_length=20)
    qty_counted: int = Field(ge=0, description="实盘数量")


class RowPatch(BaseModel):
    qty_counted: int | None = Field(default=None, ge=0)
    handle_result: str | None = Field(default=None, max_length=100)
    remark: str | None = Field(default=None, max_length=300)


# ---------- 序列化 ----------

def _diff_state(qty_book: int, qty_counted: int | None) -> str:
    """差异状态：未盘=空，相符/盘盈/盘亏（应用层写，便于筛选）。"""
    if qty_counted is None:
        return ""
    if qty_counted > qty_book:
        return "盘盈"
    if qty_counted < qty_book:
        return "盘亏"
    return "相符"


def row_out(r: StocktakeItem) -> dict:
    return {
        "id": r.id, "stocktake_id": r.stocktake_id, "item_id": r.item_id,
        "barcode_snapshot": r.barcode_snapshot, "name_snapshot": r.name_snapshot,
        "qty_book": r.qty_book, "qty_counted": r.qty_counted,
        "variance": r.variance,          # 数据库生成列，只读
        "diff_state": r.diff_state or "",
        "handle_result": r.handle_result or "",
        "remark": r.remark or "",
        "sort_order": r.sort_order,
    }


def stocktake_row(s: Stocktake) -> dict:
    return {
        "id": s.id, "doc_no": s.doc_no,
        "location_id": s.location_id,
        "location_name": s.location.name if s.location else None,
        "category_id": s.category_id,
        "state": s.state,
        "stocktake_date": s.stocktake_date.isoformat() if s.stocktake_date else None,
        "remark": s.remark or "",
        "operator_id": s.operator_id,
        "posted_at": s.posted_at.isoformat() if s.posted_at else None,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }


def stocktake_detail(db: Session, s: Stocktake) -> dict:
    d = stocktake_row(s)
    rows = db.scalars(
        select(StocktakeItem).where(StocktakeItem.stocktake_id == s.id)
        .order_by(StocktakeItem.sort_order, StocktakeItem.id)
    ).all()
    d["items"] = [row_out(r) for r in rows]
    counted = [r for r in rows if r.qty_counted is not None]
    d["stats"] = {
        "row_count": len(rows),
        "counted_count": len(counted),
        "uncounted_count": len(rows) - len(counted),
        "variance_count": sum(1 for r in counted if (r.variance or 0) != 0),
    }
    return d


# ---------- 内部工具 ----------

def _get_stocktake(db: Session, st_id: int) -> Stocktake:
    s = db.get(Stocktake, st_id)
    if s is None:
        raise not_found("盘点单不存在")
    return s


def _check_counting(s: Stocktake, user: User) -> None:
    if s.state == "done":
        raise BizError("该盘点单已过账，不能再录入或修改", code="ERR_DOC_NOT_DRAFT", status=409)


def _book_qty(db: Session, item_id: int, location_id: int) -> int:
    return db.scalar(
        select(func.coalesce(Inventory.qty_on_hand, 0))
        .where(Inventory.item_id == item_id, Inventory.location_id == location_id)
    ) or 0


def _set_counted(r: StocktakeItem, qty_counted: int | None) -> None:
    """写实盘数与差异状态。**绝不写 variance**（数据库生成列）。"""
    r.qty_counted = qty_counted
    r.diff_state = _diff_state(r.qty_book, qty_counted)


# ---------- 路由 ----------

@router.get("")
def list_stocktakes(
    page: int = 1, page_size: int = 20,
    state: str | None = None,
    location_id: int | None = None,
    category_id: int | None = None,
    start: date | None = None, end: date | None = None,
    sort_by: str = "id", sort_dir: str = "desc",
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(200, max(1, page_size))
    conds = []
    if state:
        conds.append(Stocktake.state == state)
    if location_id is not None:
        conds.append(Stocktake.location_id == location_id)
    if category_id is not None:
        conds.append(Stocktake.category_id == category_id)
    if start:
        conds.append(Stocktake.stocktake_date >= start)
    if end:
        conds.append(Stocktake.stocktake_date <= end)

    cq = select(func.count(Stocktake.id))
    for c in conds:
        cq = cq.where(c)
    total = db.scalar(cq) or 0

    sortable = {"id": Stocktake.id, "doc_no": Stocktake.doc_no,
                "stocktake_date": Stocktake.stocktake_date, "created_at": Stocktake.created_at}
    col = sortable.get(sort_by, Stocktake.id)
    order_by = col.desc() if sort_dir == "desc" else col.asc()

    q_stmt = select(Stocktake).order_by(order_by, Stocktake.id.desc()) \
        .offset((page - 1) * page_size).limit(page_size)
    for c in conds:
        q_stmt = q_stmt.where(c)
    rows = db.scalars(q_stmt).all()
    return ok_page([stocktake_row(s) for s in rows], page=page, page_size=page_size, total=total)


@router.post("")
def create_stocktake(body: StocktakeCreate, request: Request,
                     user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """新建盘点单：从 inventory 按库位(+类目)生成待盘行，**快照 qty_book**。"""
    loc = db.get(Location, body.location_id)
    if loc is None:
        raise not_found("库位不存在")
    if body.category_id is not None and db.get(Category, body.category_id) is None:
        raise not_found("类目不存在")

    doc_no = next_doc_no(db, PREFIX_STOCKTAKE)
    s = Stocktake(
        doc_no=doc_no,
        location_id=body.location_id,
        category_id=body.category_id,
        state="draft",
        stocktake_date=body.stocktake_date or date.today(),
        remark=body.remark,
        operator_id=user.id,
    )
    db.add(s)
    db.flush()   # 拿到 s.id

    q = (
        select(Inventory, Item)
        .join(Item, Item.id == Inventory.item_id)
        .where(Inventory.location_id == body.location_id)
    )
    if body.category_id is not None:
        q = q.where(Item.category_id == body.category_id)
    q = q.order_by(Item.name, Item.id)
    pairs = db.execute(q).all()
    if len(pairs) > MAX_STOCKTAKE_ROWS:
        db.rollback()
        raise BizError(f"待盘行超过 {MAX_STOCKTAKE_ROWS} 行，请按类目分批盘点", code="ERR_TOO_MANY_ROWS")

    for idx, (inv, item) in enumerate(pairs):
        db.add(StocktakeItem(
            stocktake_id=s.id,
            item_id=item.id,
            barcode_snapshot=item.barcode,
            name_snapshot=item.name,
            qty_book=inv.qty_on_hand,       # 账面数快照
            qty_counted=None,
            diff_state="",
            handle_result="",
            remark="",
            sort_order=idx,
        ))

    write_audit(db, action="create", entity="stocktake", entity_id=s.id, user=user,
                detail={"doc_no": doc_no, "location_id": s.location_id,
                        "category_id": s.category_id, "rows": len(pairs)}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(stocktake_detail(db, _get_stocktake(db, s.id)))


@router.get("/{st_id}")
def get_stocktake(st_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(stocktake_detail(db, _get_stocktake(db, st_id)))


@router.patch("/{st_id}")
def patch_stocktake(st_id: int, body: StocktakePatch, request: Request,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _get_stocktake(db, st_id)
    _check_counting(s, user)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(s, k, v)
    write_audit(db, action="update", entity="stocktake", entity_id=s.id, user=user,
                detail={"fields": sorted(data.keys())}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(stocktake_detail(db, _get_stocktake(db, s.id)))


@router.post("/{st_id}/scan")
def scan_stocktake(st_id: int, body: ScanBody, request: Request,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """扫码录入实盘数。条码对应物品不在本盘点单内则**自动加行**（现场发现漏盘物品）。

    同一条码重复扫码 = 覆盖该行的实盘数（现场录错可重扫修正）。
    """
    s = _get_stocktake(db, st_id)
    _check_counting(s, user)
    code = body.barcode.strip()
    item = db.scalar(select(Item).where(Item.barcode == code))
    if item is None:
        raise BizError(f"条码 {code} 未登记，请先在物品档案中登记该物品",
                       code="ERR_BARCODE_NOT_FOUND", status=404)
    if item.status != "active":
        raise BizError(f"物品「{item.name}」已停用或已合并，不能盘点",
                       code="ERR_ITEM_STATUS", status=409)

    r = db.scalar(
        select(StocktakeItem).where(
            StocktakeItem.stocktake_id == s.id, StocktakeItem.item_id == item.id
        )
    )
    created = False
    if r is None:
        # 自动加行：账面数取当前 inventory（该库位）
        max_sort = db.scalar(
            select(func.max(StocktakeItem.sort_order)).where(StocktakeItem.stocktake_id == s.id)
        ) or 0
        r = StocktakeItem(
            stocktake_id=s.id, item_id=item.id,
            barcode_snapshot=item.barcode, name_snapshot=item.name,
            qty_book=_book_qty(db, item.id, s.location_id),
            diff_state="", handle_result="", remark="扫码时自动加行",
            sort_order=max_sort + 1,
        )
        db.add(r)
        created = True

    _set_counted(r, body.qty_counted)
    # draft → counting（首次录入即进入盘点中）；done 已被 _check_counting 拦截
    if s.state == "draft":
        s.state = "counting"
    db.flush()
    db.refresh(r)      # 读回数据库生成列 variance
    write_audit(db, action="scan_count", entity="stocktake", entity_id=s.id, user=user,
                detail={"doc_no": s.doc_no, "barcode": code, "item_id": item.id,
                        "qty_counted": body.qty_counted, "added_row": created}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok({"created_row": created, "item_name": item.name, "row": row_out(r)})


@router.patch("/{st_id}/items/{row_id}")
def patch_stocktake_row(st_id: int, row_id: int, body: RowPatch, request: Request,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = _get_stocktake(db, st_id)
    _check_counting(s, user)
    r = db.get(StocktakeItem, row_id)
    if r is None or r.stocktake_id != s.id:
        raise not_found("盘点行不存在")

    data = body.model_dump(exclude_unset=True)
    if "qty_counted" in data:
        _set_counted(r, data["qty_counted"])
    for k in ("handle_result", "remark"):
        if k in data:
            setattr(r, k, data[k])
    if s.state == "draft" and r.qty_counted is not None:
        s.state = "counting"
    db.flush()
    db.refresh(r)      # 读回生成列 variance
    write_audit(db, action="update", entity="stocktake_item", entity_id=r.id, user=user,
                detail={"stocktake_id": s.id, "fields": sorted(data.keys())}, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(row_out(r))


@router.post("/{st_id}/post")
def post_stocktake(st_id: int, request: Request,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """过账：按差异写 adjust 流水校正库存（盘盈加、盘亏减），state→done。幂等。"""
    s = _get_stocktake(db, st_id)
    db.refresh(s)  # 确保拿到最新 state
    try:
        stock.post_stocktake_adjust(db, s, operator_id=user.id)
        write_audit(db, action="post", entity="stocktake", entity_id=s.id, user=user,
                    detail={"doc_no": s.doc_no}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok(stocktake_detail(db, _get_stocktake(db, st_id)))
