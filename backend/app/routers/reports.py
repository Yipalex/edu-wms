"""报表与导出路由（DESIGN §6）。

- GET /reports/stock       库存余量多维查询（group_by=item/location/category）
- GET /reports/movements   出入库流水统计汇总（group_by=doc_type/date/item/location）
- GET /exports/{kind}      导出 CSV（kind=items/inventory/movements；中文表头 + UTF-8 BOM，
                           用户用 Excel 直接打开不乱码）

全部只读，AO（admin + operator）开放。流水/库存数据一律现查 stock_movements / inventory，
不依赖快照。本模块通过顶层 `router` 聚合 reports/exports 两个子路由暴露给自动发现机制。
"""
import csv
import io
import logging
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, no_teacher
from app.models import Category, Inventory, Item, Location, StockMovement, User
from app.schemas.common import BizError, ok, ok_page

logger = logging.getLogger(__name__)

# ---------- 子路由（顶层 router 在文件末尾聚合） ----------

reports_router = APIRouter(prefix="/reports", tags=["报表"], dependencies=[Depends(no_teacher("查看报表"))])
exports_router = APIRouter(prefix="/exports", tags=["导出"], dependencies=[Depends(no_teacher("导出报表"))])


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min)


def _mv_conds(*, start, end, location_id, item_id, doc_type, operator_id):
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
    return conds


# ==================== 库存报表 ====================

@reports_router.get("/stock")
def stock_report(
    group_by: str = "item",
    location_id: int | None = None,
    category_id: int | None = None,
    below_safety: bool | None = None,
    q: str | None = None,
    page: int = 1, page_size: int = 50,
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """库存余量多维查询。

    group_by=item    → 每「物品 × 库位」一行（最细粒度，支持分页）
    group_by=location→ 每库位汇总（SKU 数/件数/金额）
    group_by=category→ 每类目汇总（SKU 数/件数/金额）
    """
    page = max(1, page)
    page_size = min(500, max(1, page_size))
    conds = []
    if location_id is not None:
        conds.append(Inventory.location_id == location_id)
    if category_id is not None:
        conds.append(Item.category_id == category_id)
    if below_safety is True:
        conds.append(Inventory.qty_on_hand < Inventory.safety_stock)
    elif below_safety is False:
        conds.append(Inventory.qty_on_hand >= Inventory.safety_stock)
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(Item.name.like(like), Item.barcode.like(like)))

    if group_by == "location":
        rows = db.execute(
            select(
                Inventory.location_id,
                func.count(func.distinct(Inventory.item_id)).label("sku"),
                func.coalesce(func.sum(Inventory.qty_on_hand), 0).label("qty"),
                func.coalesce(func.sum(func.coalesce(Item.suggest_price, 0) * Inventory.qty_on_hand), 0).label("value"),
            ).join(Item, Item.id == Inventory.item_id)
            .group_by(Inventory.location_id)
            .order_by(Inventory.location_id)
        ).all()
        loc_map = {l.id: l for l in db.scalars(select(Location)).all()}
        data = [{
            "location_id": loc_id,
            "location_name": loc_map[loc_id].name if loc_id in loc_map else None,
            "location_code": loc_map[loc_id].code if loc_id in loc_map else None,
            "sku_count": sku, "total_qty": int(qty), "total_value": round(float(value), 2),
        } for loc_id, sku, qty, value in rows]
        return ok(data, meta={"group_by": "location", "total": len(data)})

    if group_by == "category":
        cq = select(
            Item.category_id,
            func.count(func.distinct(Inventory.item_id)).label("sku"),
            func.coalesce(func.sum(Inventory.qty_on_hand), 0).label("qty"),
            func.coalesce(func.sum(func.coalesce(Item.suggest_price, 0) * Inventory.qty_on_hand), 0).label("value"),
        ).join(Item, Item.id == Inventory.item_id).group_by(Item.category_id)
        for c in conds:
            cq = cq.where(c)
        rows = db.execute(cq.order_by(Item.category_id)).all()
        cat_map = {c.id: c for c in db.scalars(select(Category)).all()}
        data = [{
            "category_id": cat_id,
            "category_name": cat_map[cat_id].name if cat_id in cat_map else None,
            "sku_count": sku, "total_qty": int(qty), "total_value": round(float(value), 2),
        } for cat_id, sku, qty, value in rows]
        return ok(data, meta={"group_by": "category", "total": len(data)})

    # 默认 group_by=item：物品 × 库位 明细，支持筛选 + 分页
    cq = select(func.count(Inventory.id)).join(Item, Item.id == Inventory.item_id)
    for c in conds:
        cq = cq.where(c)
    total = db.scalar(cq) or 0
    q_stmt = select(Inventory).join(Item, Item.id == Inventory.item_id) \
        .order_by(Item.name, Inventory.location_id) \
        .offset((page - 1) * page_size).limit(page_size)
    for c in conds:
        q_stmt = q_stmt.where(c)
    rows = db.scalars(q_stmt).all()
    data = []
    for inv in rows:
        item = inv.item
        price = float(item.suggest_price) if (item and item.suggest_price is not None) else None
        qty = inv.qty_on_hand or 0
        data.append({
            "item_id": inv.item_id,
            "barcode": item.barcode if item else None,
            "item_name": item.name if item else None,
            "category_id": item.category_id if item else None,
            "category_name": item.category.name if (item and item.category) else None,
            "spec": (item.spec if item else "") or "",
            "unit": item.unit if item else None,
            "location_id": inv.location_id,
            "location_name": inv.location.name if inv.location else None,
            "location_code": inv.location.code if inv.location else None,
            "qty_on_hand": qty,
            "qty_reserved": inv.qty_reserved or 0,
            "safety_stock": inv.safety_stock or 0,
            "suggest_price": price,
            "stock_value": round(price * qty, 2) if price is not None else 0.0,
            "below_safety": qty < (inv.safety_stock or 0),
        })
    return ok_page(data, page=page, page_size=page_size, total=total)


# ==================== 流水汇总 ====================

@reports_router.get("/movements")
def movements_report(
    group_by: str = "doc_type",
    start: date | None = None, end: date | None = None,
    location_id: int | None = None,
    doc_type: str | None = None,
    operator_id: int | None = None,
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """出入库流水统计汇总。

    group_by=doc_type → 按单据类型汇总入库量/出库量/笔数
    group_by=date     → 按日汇总
    group_by=item     → 按物品汇总
    group_by=location → 按库位汇总
    均含 overall 总计行。
    """
    conds = _mv_conds(start=start, end=end, location_id=location_id,
                      item_id=None, doc_type=doc_type, operator_id=operator_id)

    in_expr = func.coalesce(func.sum(case((StockMovement.change_qty > 0, StockMovement.change_qty), else_=0)), 0)
    out_expr = func.coalesce(func.sum(case((StockMovement.change_qty < 0, -StockMovement.change_qty), else_=0)), 0)

    def _run(group_col, label):
        stmt = select(
            group_col.label(label),
            func.count(StockMovement.id).label("movement_count"),
            in_expr.label("in_qty"),
            out_expr.label("out_qty"),
        ).group_by(group_col)
        for c in conds:
            stmt = stmt.where(c)
        return db.execute(stmt).all()

    if group_by == "date":
        rows = _run(func.date(StockMovement.created_at), "bucket")
        data = [{
            "date": str(bucket), "movement_count": cnt,
            "in_qty": int(in_q), "out_qty": int(out_q),
            "net_qty": int(in_q) - int(out_q),
        } for bucket, cnt, in_q, out_q in sorted(rows, key=lambda r: str(r[0]))]
    elif group_by == "item":
        rows = _run(StockMovement.item_id, "bucket")
        item_map = {i.id: i for i in db.scalars(select(Item)).all()}
        data = [{
            "item_id": bid,
            "item_name": item_map[bid].name if bid in item_map else None,
            "barcode": item_map[bid].barcode if bid in item_map else None,
            "movement_count": cnt, "in_qty": int(in_q), "out_qty": int(out_q),
            "net_qty": int(in_q) - int(out_q),
        } for bid, cnt, in_q, out_q in sorted(rows, key=lambda r: r[0])]
    elif group_by == "location":
        rows = _run(StockMovement.location_id, "bucket")
        loc_map = {l.id: l for l in db.scalars(select(Location)).all()}
        data = [{
            "location_id": bid,
            "location_name": loc_map[bid].name if bid in loc_map else None,
            "location_code": loc_map[bid].code if bid in loc_map else None,
            "movement_count": cnt, "in_qty": int(in_q), "out_qty": int(out_q),
            "net_qty": int(in_q) - int(out_q),
        } for bid, cnt, in_q, out_q in sorted(rows, key=lambda r: r[0])]
    else:  # doc_type
        rows = _run(StockMovement.doc_type, "bucket")
        data = [{
            "doc_type": str(bucket), "movement_count": cnt,
            "in_qty": int(in_q), "out_qty": int(out_q),
            "net_qty": int(in_q) - int(out_q),
        } for bucket, cnt, in_q, out_q in sorted(rows, key=lambda r: str(r[0]))]

    overall = {
        "movement_count": sum(r["movement_count"] for r in data),
        "in_qty": sum(r["in_qty"] for r in data),
        "out_qty": sum(r["out_qty"] for r in data),
        "net_qty": sum(r["net_qty"] for r in data),
    }
    return ok({"group_by": group_by, "rows": data, "overall": overall})


# ==================== CSV 导出 ====================

def _csv_response(headers: list[str], rows: list[list], filename: str) -> Response:
    """CSV（中文表头 + UTF-8 BOM）：Excel 双击打开直接可读，不乱码。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    writer.writerows(rows)
    content = "\ufeff" + buf.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _today_stamp() -> str:
    return date.today().strftime("%Y%m%d")


@exports_router.get("/{kind}")
def export_csv(
    kind: str,
    start: date | None = None, end: date | None = None,
    location_id: int | None = None, item_id: int | None = None,
    category_id: int | None = None, doc_type: str | None = None,
    below_safety: bool | None = None,
    _: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """导出 CSV。kind=items/inventory/movements，与对应列表页同筛选口径。"""
    if kind == "items":
        conds = []
        if category_id is not None:
            conds.append(Item.category_id == category_id)
        stmt = select(Item).order_by(Item.id)
        for c in conds:
            stmt = stmt.where(c)
        rows = db.scalars(stmt).all()
        data = [[
            it.barcode or "", it.name,
            it.category.name if it.category else "",
            it.spec or "", it.unit or "",
            float(it.suggest_price) if it.suggest_price is not None else "",
            "是" if it.need_label else "否", it.status,
            it.created_at.strftime("%Y-%m-%d %H:%M:%S") if it.created_at else "",
        ] for it in rows]
        return _csv_response(
            ["条码", "物品名称", "类目", "规格", "单位", "建议售价", "是否贴码", "状态", "创建时间"],
            data, f"items-{_today_stamp()}.csv",
        )

    if kind == "inventory":
        conds = []
        if location_id is not None:
            conds.append(Inventory.location_id == location_id)
        if category_id is not None:
            conds.append(Item.category_id == category_id)
        if below_safety is True:
            conds.append(Inventory.qty_on_hand < Inventory.safety_stock)
        stmt = select(Inventory).join(Item, Item.id == Inventory.item_id) \
            .order_by(Item.name, Inventory.location_id)
        for c in conds:
            stmt = stmt.where(c)
        rows = db.scalars(stmt).all()
        data = []
        for inv in rows:
            item = inv.item
            price = float(item.suggest_price) if (item and item.suggest_price is not None) else None
            qty = inv.qty_on_hand or 0
            data.append([
                item.barcode if item else "", item.name if item else "",
                item.category.name if (item and item.category) else "",
                inv.location.name if inv.location else "", qty,
                inv.qty_reserved or 0, inv.safety_stock or 0,
                round(price * qty, 2) if price is not None else 0.0,
            ])
        return _csv_response(
            ["条码", "物品名称", "类目", "库位", "当前库存", "待领取", "安全库存", "库存金额"],
            data, f"inventory-{_today_stamp()}.csv",
        )

    if kind == "movements":
        conds = _mv_conds(start=start, end=end, location_id=location_id,
                          item_id=item_id, doc_type=doc_type, operator_id=None)
        stmt = select(StockMovement).join(Item, Item.id == StockMovement.item_id) \
            .order_by(StockMovement.id.desc())
        for c in conds:
            stmt = stmt.where(c)
        rows = db.scalars(stmt).all()
        data = [[
            m.created_at.strftime("%Y-%m-%d %H:%M:%S") if m.created_at else "",
            m.doc_type or "", m.doc_no or "",
            m.item.name if m.item else "", m.item.barcode if m.item else "",
            m.location.name if m.location else "",
            m.change_qty, m.qty_before, m.qty_after,
            m.operator.display_name if m.operator else "", m.note or "",
        ] for m in rows]
        return _csv_response(
            ["时间", "单据类型", "单号", "物品名称", "条码", "库位",
             "变动数量", "变动前", "变动后", "操作人", "备注"],
            data, f"movements-{_today_stamp()}.csv",
        )

    raise BizError(f"不支持的导出类型：{kind}（可选 items/inventory/movements）",
                   code="ERR_BAD_EXPORT_KIND", status=400)


# ---------- 顶层 router（自动发现机制只认这个变量） ----------

router = APIRouter(dependencies=[Depends(no_teacher("导出报表"))])
router.include_router(reports_router)
router.include_router(exports_router)
