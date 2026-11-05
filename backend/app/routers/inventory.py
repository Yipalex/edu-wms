"""库存查询路由（DESIGN §6）。

- GET   /inventory            多维查询（item_id/category_id/location_id/q/below_safety + 分页）
- GET   /inventory/summary    按库位与按类目两个维度汇总（SKU 数/件数/金额）
- POST  /inventory/adjust     快速库存调整（仅管理员）：直接填实盘数，写 adjust 流水留痕
                              （解决建账初期「先有出库记录、库存为负」的对账问题）
- PATCH /inventory/{id}       改 safety_stock / qty_reserved（A）
                              **不允许**直接改 qty_on_hand——那必须走单据以保证流水可追溯
"""
import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import (
    can_see_cost_prices, get_current_user, require_role, teacher_home_location,
)
from app.models import Category, Inventory, Item, Location, User
from app.schemas.common import BizError, not_found, ok, ok_page
from app.services.audit import write_audit
from app.services.stock import apply_movement

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inventory", tags=["库存"])

AdminUser = require_role("admin")


# ---------- Pydantic ----------

class InventoryPatch(BaseModel):
    """只允许改安全库存与待领取数量；qty_on_hand 必须走单据，不在此列。"""
    safety_stock: int | None = Field(default=None, ge=0)
    qty_reserved: int | None = Field(default=None, ge=0)
    qty_on_hand: int | None = Field(default=None, exclude=True)  # 显式声明以便拒绝


# ---------- 序列化 ----------

def inv_row(inv: Inventory, user: User | None = None) -> dict:
    item = inv.item
    price = float(item.suggest_price) if (item and item.suggest_price is not None) else None
    qty = inv.qty_on_hand or 0
    d = {
        "id": inv.id,
        "item_id": inv.item_id,
        "item_name": item.name if item else None,
        "barcode": item.barcode if item else None,
        "category_id": item.category_id if item else None,
        "category_name": item.category.name if (item and item.category) else None,
        "spec": (item.spec if item else "") or "",
        "unit": item.unit if item else None,
        "suggest_price": price,
        "location_id": inv.location_id,
        "location_name": inv.location.name if inv.location else None,
        "location_code": inv.location.code if inv.location else None,
        "qty_on_hand": qty,
        "qty_reserved": inv.qty_reserved or 0,
        "safety_stock": inv.safety_stock or 0,
        "stock_value": round(price * qty, 2) if price is not None else 0.0,
        "below_safety": qty < (inv.safety_stock or 0),
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
    }
    # 采购价/内部销售价对教师脱敏
    if user is None or can_see_cost_prices(user):
        d["purchase_price"] = float(item.purchase_price) if (item and item.purchase_price is not None) else None
        d["internal_price"] = float(item.internal_price) if (item and item.internal_price is not None) else None
    return d


# ---------- 路由 ----------

@router.get("")
def list_inventory(
    page: int = 1, page_size: int = 20,
    item_id: int | None = None,
    category_id: int | None = None,
    location_id: int | None = None,
    q: str | None = None,
    below_safety: bool | None = None,
    sort_by: str = "item_name", sort_dir: str = "asc",
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(500, max(1, page_size))

    # 教师：只能看自己校区的库存
    if user.role == "teacher":
        location_id = teacher_home_location(user)

    # Inventory join Item（+Category 供筛选/展示）
    base = select(Inventory).join(Item, Item.id == Inventory.item_id)
    conds = []
    if item_id is not None:
        conds.append(Inventory.item_id == item_id)
    if location_id is not None:
        conds.append(Inventory.location_id == location_id)
    if category_id is not None:
        conds.append(Item.category_id == category_id)
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(Item.name.like(like), Item.barcode.like(like)))
    if below_safety is True:
        conds.append(Inventory.qty_on_hand < Inventory.safety_stock)
    elif below_safety is False:
        conds.append(Inventory.qty_on_hand >= Inventory.safety_stock)

    cq = select(func.count(Inventory.id)).join(Item, Item.id == Inventory.item_id)
    for c in conds:
        cq = cq.where(c)
    total = db.scalar(cq) or 0

    sortable = {
        "item_name": Item.name, "qty_on_hand": Inventory.qty_on_hand,
        "qty_reserved": Inventory.qty_reserved, "safety_stock": Inventory.safety_stock,
        "location_id": Inventory.location_id, "updated_at": Inventory.updated_at,
        "id": Inventory.id,
    }
    col = sortable.get(sort_by, Item.name)
    order_by = col.desc() if sort_dir == "desc" else col.asc()

    q_stmt = base.order_by(order_by, Inventory.id).offset((page - 1) * page_size).limit(page_size)
    for c in conds:
        q_stmt = q_stmt.where(c)
    rows = db.scalars(q_stmt).all()
    return ok_page([inv_row(r, user=user) for r in rows], page=page, page_size=page_size, total=total)


# ---------- 快速库存调整（仅管理员；2026-11-05） ----------

class InventoryAdjust(BaseModel):
    """直接把某库位某物品的库存校正为实盘数（差额写 adjust 流水，历史单据不动）。"""
    item_id: int
    location_id: int
    qty_actual: int = Field(ge=0, description="实盘数量（校正后的数量）")
    reason: str = Field(default="", max_length=300, description="调整原因（写入流水备注）")


@router.post("/adjust")
def adjust_inventory(
    body: InventoryAdjust, request: Request,
    admin: User = Depends(AdminUser), db: Session = Depends(get_db),
):
    """快速库存调整：账面 0 → 实盘 10 等「先有出库、库存对不上」的建账修正。

    与盘点单过账同一套机制（apply_movement + adjust 流水），只是免去建盘点单的重量流程。
    """
    item = db.get(Item, body.item_id)
    if item is None:
        raise not_found("物品不存在")
    loc = db.get(Location, body.location_id)
    if loc is None:
        raise not_found("库位不存在")
    inv = db.scalar(
        select(Inventory).where(
            Inventory.item_id == body.item_id, Inventory.location_id == body.location_id
        )
    )
    qty_book = inv.qty_on_hand if inv is not None else 0
    delta = body.qty_actual - qty_book
    if delta == 0:
        return ok({"item_id": item.id, "location_id": loc.id, "qty_before": qty_book,
                   "qty_after": qty_book, "changed": False, "message": "实盘数与账面一致，无需调整"})

    reason = (body.reason or "").strip()
    note = f"库存调整：账面 {qty_book} → 实盘 {body.qty_actual}"
    if reason:
        note += f"（{reason}）"
    try:
        mv = apply_movement(
            db,
            item_id=item.id,
            location_id=loc.id,
            change_qty=delta,
            doc_type="adjust",
            doc_id=None,
            doc_no=None,
            operator_id=admin.id,
            note=note,
        )
        write_audit(db, action="adjust_stock", entity="inventory",
                    entity_id=inv.id if inv is not None else None, user=admin,
                    detail={"item": item.name, "location": loc.name,
                            "qty_before": qty_book, "qty_after": body.qty_actual,
                            "reason": reason}, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok({"item_id": item.id, "location_id": loc.id, "qty_before": qty_book,
               "qty_after": mv.qty_after, "changed": True, "movement_id": mv.id,
               "message": f"已将「{item.name}」在 {loc.name} 的库存从 {qty_book} 调整为 {mv.qty_after}"})


@router.get("/summary")
def inventory_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """按库位与按类目两个维度汇总（SKU 数、件数、金额合计）。含全校金额，教师不可用。"""
    if user.role == "teacher":
        raise BizError("教师角色请在「库存查询」中查看本校区的库存", code="ERR_FORBIDDEN", status=403)
    # 按库位
    by_loc_rows = db.execute(
        select(
            Inventory.location_id,
            func.count(func.distinct(Inventory.item_id)).label("sku"),
            func.coalesce(func.sum(Inventory.qty_on_hand), 0).label("qty"),
        ).group_by(Inventory.location_id)
    ).all()
    loc_map = {l.id: l for l in db.scalars(select(Location)).all()}
    # 金额需 join items 取 suggest_price
    loc_value_rows = db.execute(
        select(
            Inventory.location_id,
            func.coalesce(func.sum(func.coalesce(Item.suggest_price, 0) * Inventory.qty_on_hand), 0).label("value"),
        ).join(Item, Item.id == Inventory.item_id)
        .group_by(Inventory.location_id)
    ).all()
    loc_value = {r[0]: float(r[1]) for r in loc_value_rows}
    by_location = []
    for loc_id, sku, qty in by_loc_rows:
        loc = loc_map.get(loc_id)
        by_location.append({
            "location_id": loc_id,
            "location_name": loc.name if loc else None,
            "location_code": loc.code if loc else None,
            "sku_count": sku,
            "total_qty": int(qty),
            "total_value": round(loc_value.get(loc_id, 0.0), 2),
        })

    # 按类目
    by_cat_rows = db.execute(
        select(
            Item.category_id,
            func.count(func.distinct(Inventory.item_id)).label("sku"),
            func.coalesce(func.sum(Inventory.qty_on_hand), 0).label("qty"),
            func.coalesce(func.sum(func.coalesce(Item.suggest_price, 0) * Inventory.qty_on_hand), 0).label("value"),
        ).join(Item, Item.id == Inventory.item_id)
        .group_by(Item.category_id)
    ).all()
    cat_map = {c.id: c for c in db.scalars(select(Category)).all()}
    by_category = []
    for cat_id, sku, qty, value in by_cat_rows:
        cat = cat_map.get(cat_id)
        by_category.append({
            "category_id": cat_id,
            "category_name": cat.name if cat else None,
            "sku_count": sku,
            "total_qty": int(qty),
            "total_value": round(float(value), 2),
        })

    return ok({
        "by_location": sorted(by_location, key=lambda x: x["location_id"]),
        "by_category": sorted(by_category, key=lambda x: x["category_id"]),
        "total_sku": sum(x["sku_count"] for x in by_location),
        "total_qty": sum(x["total_qty"] for x in by_location),
        "total_value": round(sum(x["total_value"] for x in by_location), 2),
    })


@router.patch("/{inv_id}")
def patch_inventory(inv_id: int, body: InventoryPatch, request: Request,
                    admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    """改安全库存/待领取数量。**不允许**直接改在手库存（必须走单据）。"""
    # 显式拦截 qty_on_hand：Pydantic exclude 后不会进 model_dump，但用户可能传了它
    raw = await_none = None  # placeholder 避免误用
    inv = db.get(Inventory, inv_id)
    if inv is None:
        raise not_found("库存记录不存在")

    data = body.model_dump(exclude_unset=True)
    if "qty_on_hand" in data:
        raise BizError(
            "库存数量只能通过入库/出库/盘点单据变更，以保证流水可追溯",
            code="ERR_QTY_IMMUTABLE", status=400,
        )
    if not data:
        raise BizError("没有需要修改的字段", code="ERR_EMPTY_PATCH")

    changes = {}
    for k in ("safety_stock", "qty_reserved"):
        if k in data and data[k] is not None:
            old = getattr(inv, k)
            if old != data[k]:
                changes[k] = {"old": old, "new": data[k]}
                setattr(inv, k, data[k])
    if changes:
        write_audit(db, action="update", entity="inventory", entity_id=inv.id, user=admin,
                    detail=changes, request=request)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(inv)
    return ok(inv_row(inv))
