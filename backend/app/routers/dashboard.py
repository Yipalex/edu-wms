"""仪表盘汇总路由（DESIGN §6：GET /reports/dashboard）。

返回：
- 物品种数（active）、库存总件数、待领取总数、盘点次数（全部盘点单）
- 各库位库存汇总（SKU 数/件数/金额）
- 今日出入库笔数（stock_movements 当日正负笔数）
- 待盘点数（draft/counting 状态盘点单）
- 低库存预警（qty_on_hand < safety_stock，阈值即每行安全库存，可经
  PATCH /inventory/{id} 配置；top N）
- 最近流水 top N（默认 10 条）

只读，AO（admin + operator）开放。
"""
import logging
from datetime import datetime, time

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, no_teacher
from app.models import Inventory, Item, Location, StockMovement, Stocktake, User
from app.models import utcnow
from app.schemas.common import ok

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["仪表盘"], dependencies=[Depends(no_teacher("查看仪表盘"))])

LOW_STOCK_LIMIT = 20


def _mv_brief(m: StockMovement) -> dict:
    return {
        "id": m.id,
        "item_id": m.item_id,
        "item_name": m.item.name if m.item else None,
        "barcode": m.item.barcode if m.item else None,
        "location_id": m.location_id,
        "location_name": m.location.name if m.location else None,
        "change_qty": m.change_qty,
        "doc_type": m.doc_type,
        "doc_no": m.doc_no,
        "operator_name": m.operator.display_name if m.operator else None,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


@router.get("/dashboard")
def dashboard(
    recent_limit: int = 10, low_stock_limit: int = LOW_STOCK_LIMIT,
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    recent_limit = min(50, max(1, recent_limit))
    low_stock_limit = min(100, max(1, low_stock_limit))

    today = utcnow().date()
    today_start = datetime.combine(today, time.min)

    # 顶部统计卡
    item_count = db.scalar(select(func.count(Item.id)).where(Item.status == "active")) or 0
    total_qty = db.scalar(select(func.coalesce(func.sum(Inventory.qty_on_hand), 0))) or 0
    total_reserved = db.scalar(select(func.coalesce(func.sum(Inventory.qty_reserved), 0))) or 0
    stocktake_count = db.scalar(select(func.count(Stocktake.id))) or 0
    pending_stocktakes = db.scalar(
        select(func.count(Stocktake.id)).where(Stocktake.state.in_(("draft", "counting")))
    ) or 0

    today_in = db.scalar(select(func.count(StockMovement.id)).where(
        StockMovement.created_at >= today_start, StockMovement.change_qty > 0)) or 0
    today_out = db.scalar(select(func.count(StockMovement.id)).where(
        StockMovement.created_at >= today_start, StockMovement.change_qty < 0)) or 0

    # 各库位库存金额（契约：各库位库存金额）
    by_loc_rows = db.execute(
        select(
            Inventory.location_id,
            func.count(func.distinct(Inventory.item_id)).label("sku"),
            func.coalesce(func.sum(Inventory.qty_on_hand), 0).label("qty"),
            func.coalesce(func.sum(func.coalesce(Item.suggest_price, 0) * Inventory.qty_on_hand), 0).label("value"),
        ).join(Item, Item.id == Inventory.item_id)
        .group_by(Inventory.location_id)
    ).all()
    loc_map = {l.id: l for l in db.scalars(select(Location)).all()}
    by_location = [{
        "location_id": loc_id,
        "location_name": loc_map[loc_id].name if loc_id in loc_map else None,
        "location_code": loc_map[loc_id].code if loc_id in loc_map else None,
        "sku_count": sku, "total_qty": int(qty), "total_value": round(float(value), 2),
    } for loc_id, sku, qty, value in sorted(by_loc_rows, key=lambda r: r[0])]

    # 低库存预警（在手 < 安全库存）
    low_rows = db.scalars(
        select(Inventory)
        .where(Inventory.safety_stock > 0, Inventory.qty_on_hand < Inventory.safety_stock)
        .order_by(Inventory.qty_on_hand - Inventory.safety_stock)
        .limit(low_stock_limit)
    ).all()
    low_stock = [{
        "item_id": inv.item_id,
        "item_name": inv.item.name if inv.item else None,
        "barcode": inv.item.barcode if inv.item else None,
        "location_id": inv.location_id,
        "location_name": inv.location.name if inv.location else None,
        "qty_on_hand": inv.qty_on_hand or 0,
        "safety_stock": inv.safety_stock or 0,
    } for inv in low_rows]

    # 最近流水
    recent = db.scalars(
        select(StockMovement).order_by(StockMovement.id.desc()).limit(recent_limit)
    ).all()

    return ok({
        "item_count": item_count,
        "total_qty": int(total_qty),
        "total_reserved": int(total_reserved),
        "stocktake_count": stocktake_count,
        "pending_stocktakes": pending_stocktakes,
        "today_in_count": today_in,
        "today_out_count": today_out,
        "by_location": by_location,
        "low_stock": low_stock,
        "recent_movements": [_mv_brief(m) for m in recent],
    })
