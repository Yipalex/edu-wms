"""扫码解析（DESIGN §4，严格按四级解析顺序）。

GET /scan/resolve?code=xxx
1. items.barcode = code AND status='active'  → 命中：物品 + 全库位库存
2. items.barcode = code AND status='merged'  → resolved=false + 合并重定向提示
3. barcode_history.old_barcode = code（最新一条）→ resolved=false + 停用溯源提示
4. 都未命中 → resolved=false + '未登记的条码'（前端引导登记新物品）

注：retired 物品的条码仍会走 1/2 的查询（barcode 精确匹配），但 status 过滤后
不命中 active/merged，会落到第 3 级历史溯源或第 4 级；为保证 retired 旧码也能
溯源，第 3 级之前先补查一次 status='retired'。
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.deps import get_current_user
from app.models import BarcodeHistory, Inventory, Item, User
from app.schemas.common import ok
from app.services import barcode as bc

router = APIRouter(prefix="/scan", tags=["扫码"])


@router.get("/resolve")
def resolve(code: str, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code = (code or "").strip()
    rule = bc.get_rule(db)
    code_type = "internal" if bc.is_internal_code(code, rule) else "external"

    base = {
        "resolved": False,
        "code": code,
        "code_type": code_type,
        "item": None,
        "inventory": [],
        "total_qty": 0,
        "hint": None,
    }

    # ---- 1/2. 按 barcode 精确查物品 ----
    item = db.scalar(
        select(Item).options(selectinload(Item.photos), selectinload(Item.category))
        .where(Item.barcode == code)
    )
    if item is not None and item.status == "active":
        invs = db.scalars(
            select(Inventory).where(Inventory.item_id == item.id)
            .order_by(Inventory.location_id)
        ).all()
        photos = item.photos or []
        primary = next((p for p in photos if p.is_primary), photos[0] if photos else None)
        return ok({
            **base,
            "resolved": True,
            "item": {
                "id": item.id, "barcode": item.barcode, "name": item.name,
                "category": item.category.name if item.category else None,
                "spec": item.spec or "",
                "suggest_price": float(item.suggest_price) if item.suggest_price is not None else None,
                "need_label": item.need_label,
                "photo_url": f"/api/uploads/{primary.file_path}" if primary else None,
            },
            "inventory": [
                {"location_id": inv.location_id,
                 "location_name": inv.location.name if inv.location else None,
                 "qty_on_hand": inv.qty_on_hand,
                 "qty_reserved": inv.qty_reserved,
                 "safety_stock": inv.safety_stock}
                for inv in invs
            ],
            "total_qty": sum(inv.qty_on_hand for inv in invs),
        })

    if item is not None and item.status == "merged":
        keeper = db.get(Item, item.merged_into_id) if item.merged_into_id else None
        return ok({
            **base,
            "hint": f"该物品已合并至「{keeper.name if keeper else '未知物品'}」",
            "redirect_barcode": keeper.barcode if keeper else None,
        })

    if item is not None and item.status == "retired":
        # retired 旧码溯源（DESIGN §12 风险4：旧标签仍可被扫到）
        return ok({**base, "hint": "该条码对应的物品已停用（retired），请核对实物"})

    # ---- 3. 条码历史溯源（旧码不释放复用） ----
    hist = db.scalar(
        select(BarcodeHistory).where(BarcodeHistory.old_barcode == code)
        .order_by(BarcodeHistory.created_at.desc(), BarcodeHistory.id.desc())
        .limit(1)
    )
    if hist is not None:
        type_label = {
            "reassign": "重分配", "merge_retire": "合并停用",
            "manual_fix": "人工修正", "assign": "分配", "import": "导入",
        }.get(hist.change_type, hist.change_type)
        return ok({
            **base,
            "hint": f"该条码已停用（{type_label}），现用码 {hist.new_barcode}" if hist.new_barcode
                    else f"该条码已停用（{type_label}）",
            # 结构化字段，供前端做「一键用新码重查」按钮，避免正则解析中文 hint
            "new_barcode": hist.new_barcode,
            "change_type": hist.change_type,
        })

    # ---- 4. 未命中 ----
    return ok({**base, "hint": "未登记的条码"})
