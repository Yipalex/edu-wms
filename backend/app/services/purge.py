"""物品档案「彻底删除」服务（2026-11-04）。

背景：仓库早期录入的不少物品，其库存数值是胡乱填写的，导致普通「删除」
（软删 status=retired）始终被「有库存/流水」拦下，管理员无法清理这些垃圾档案。
超级管理员需要能彻底删除：物品档案从名录消失、条码释放可再分配。

核心约束（不可违背）：
1. **历史业务凭证必须完整保留**。已过账的入库/出库/退货/盘点单据是真实凭证，
   绝不能因为物品被删而丢行或改金额。
2. **流水是审计真源**，不可删除（DESIGN 铁律：报表只查 movements）。
3. **库存行保留、数值归零**：物品已不在名录，库存不该再有量，但行本身留着可追溯。

因此「彻底删除」= 从 items 表移除该物品行 + 为该物品建一个专属「已删除物品」
占位档案 + 把所有引用它的行改指向这个占位档案（库存归零、其余原样保留）
+ 原始快照进 deleted_items 归档表。

占位档案为什么「每个被删物品一个」而不是全局共用一个：
  · inventory 有唯一约束 (item_id, location_id)，stocktake_items 有
    (stocktake_id, item_id)。若多个被删物品共用一个占位档案，同一库位/同一盘点单
    内会出现两行相同 (item_id, location_id) → 唯一约束冲突。
  · 专属占位档案也让「恢复」能精确还原（占位↔原物品一一对应）。
占位档案 status=retired 不进名录、barcode=NULL（条码已释放可再分配）。

引用行改指占位后，历史单据展示不受影响：明细行自带 name_snapshot /
barcode_snapshot 冗余快照，显示的是删除前的原始名称与条码。
"""
import logging
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models import (
    BarcodeHistory,
    Category,
    DeletedItem,
    InboundItem,
    Inventory,
    Item,
    ItemAlias,
    ItemMergeLog,
    ItemPhoto,
    OutboundItem,
    ReturnItem,
    StockMovement,
    StocktakeItem,
    User,
    utcnow,
)
from app.schemas.common import BizError

logger = logging.getLogger(__name__)

# 占位档案名称前缀：用于识别「已被彻底删除的物品」占位行
PLACEHOLDER_NAME_PREFIX = "【已删除物品】"

# 所有「以 item_id 指向物品」的引用模型（引用改指占位档案时统一处理）
ITEM_REF_MODELS = (
    Inventory,
    StockMovement,
    InboundItem,
    OutboundItem,
    ReturnItem,
    StocktakeItem,
    ItemPhoto,
    ItemAlias,
    BarcodeHistory,
)


def _placeholder_category_id(db: Session, origin: Item) -> int:
    """占位档案需要合法类目（items.category_id NOT NULL）。

    优先沿用原物品类目；原类目若已被删则回落到第一个可用类目。
    """
    if origin.category_id is not None and db.get(Category, origin.category_id) is not None:
        return origin.category_id
    first = db.scalar(select(Category.id).order_by(Category.id).limit(1))
    if first is None:
        raise BizError("系统缺少类目，无法执行该操作", code="ERR_NO_CATEGORY", status=409)
    return first


def ensure_placeholder_item(db: Session, origin: Item) -> Item:
    """取（或建）该物品专属的占位档案——历史引用行改指它。

    占位档案 status=retired（不进名录）、barcode=NULL（条码已释放给原物品复用）、
    remark 记录原物品信息，便于人工追溯。
    """
    marker = f"origin_item_id:{origin.id}"
    ph = db.scalar(
        select(Item)
        .where(Item.name.like(f"{PLACEHOLDER_NAME_PREFIX}%"), Item.remark.like(f"%{marker}%"))
        .limit(1)
    )
    if ph is not None:
        return ph

    ph = Item(
        barcode=None,
        name=f"{PLACEHOLDER_NAME_PREFIX}原档案已删除",
        category_id=_placeholder_category_id(db, origin),
        spec="",
        unit=origin.unit or "件",
        need_label=False,
        print_mode="label",
        status="retired",
        barcode_origin="internal",
        remark=f"占位档案：{marker} 原名「{origin.name}」条码「{origin.barcode or '无'}」",
    )
    db.add(ph)
    db.flush()
    return ph


def _count(db: Session, model, item_id: int) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.item_id == item_id)) or 0


def purge_item(
    db: Session,
    *,
    item_id: int,
    operator: User,
    reason: str = "",
    confirm_name: str = "",
) -> dict[str, Any]:
    """彻底删除物品档案（仅超级管理员）。

    :param confirm_name: 必须与物品名称完全一致，防止误触（前端要求输入名称确认）
    :param reason: 删除原因，写入归档表与审计日志
    """
    item = db.get(Item, item_id)
    if item is None:
        raise BizError("物品不存在", code="ERR_NOT_FOUND", status=404)
    if item.status == "merged":
        raise BizError("已合并的物品不能彻底删除（请先回滚合并）", code="ERR_ITEM_MERGED", status=409)
    if item.name.startswith(PLACEHOLDER_NAME_PREFIX):
        raise BizError("该行是占位档案，不能删除", code="ERR_ITEM_PLACEHOLDER", status=409)
    if confirm_name.strip() != item.name:
        raise BizError(
            f"确认名称不匹配，请输入「{item.name}」以确认删除",
            code="ERR_CONFIRM_MISMATCH", status=400,
        )

    # 本物品若是别人合并的「保留项」（别人 merged_into_id 指向它）→ 那些行要改指占位
    merged_children = db.scalars(select(Item).where(Item.merged_into_id == item_id)).all()

    placeholder = ensure_placeholder_item(db, item)

    # ---- 统计影响面（先记档，再改数据） ----
    impact: dict[str, int] = {
        "stock_rows": _count(db, Inventory, item_id),
        "stock_qty": 0,
        "movements": _count(db, StockMovement, item_id),
        "inbound_lines": _count(db, InboundItem, item_id),
        "outbound_lines": _count(db, OutboundItem, item_id),
        "return_lines": _count(db, ReturnItem, item_id),
        "stocktake_lines": _count(db, StocktakeItem, item_id),
        "photos": _count(db, ItemPhoto, item_id),
        "aliases": _count(db, ItemAlias, item_id),
        "barcode_history": _count(db, BarcodeHistory, item_id),
        # 合并日志用 keeper_id / merged_id 两个字段指向 items，单独统计
        "merge_logs": db.scalar(
            select(func.count()).select_from(ItemMergeLog)
            .where((ItemMergeLog.keeper_id == item_id) | (ItemMergeLog.merged_id == item_id))
        ) or 0,
        "merged_children": len(merged_children),
    }
    qty_sum = db.scalar(
        select(func.coalesce(func.sum(Inventory.qty_on_hand), 0)).where(Inventory.item_id == item_id)
    )
    impact["stock_qty"] = int(qty_sum or 0)

    # ---- 库存行：数量归零（行保留可追溯；物品已不在名录，库存不该再有量） ----
    db.execute(
        update(Inventory)
        .where(Inventory.item_id == item_id)
        .values(qty_on_hand=0, qty_reserved=0)
    )

    # ---- 引用行改指占位档案（行全部保留，历史单据与流水不动） ----
    for model in ITEM_REF_MODELS:
        db.execute(update(model).where(model.item_id == item_id).values(item_id=placeholder.id))
    # 合并日志：keeper_id / merged_id 两个字段都指向 items
    db.execute(update(ItemMergeLog).where(ItemMergeLog.keeper_id == item_id)
               .values(keeper_id=placeholder.id))
    db.execute(update(ItemMergeLog).where(ItemMergeLog.merged_id == item_id)
               .values(merged_id=placeholder.id))
    # 别人的 merged_into_id 指向本物品 → 改指占位（保持 merged 状态合法）
    for child in merged_children:
        child.merged_into_id = placeholder.id

    # ---- 归档快照 ----
    cat = db.get(Category, item.category_id) if item.category_id else None
    arch = DeletedItem(
        origin_item_id=item.id,
        barcode=item.barcode,
        name=item.name,
        category_id=item.category_id,
        category_name=cat.name if cat else None,
        spec=item.spec or "",
        unit=item.unit or "",
        suggest_price=item.suggest_price,
        remark=item.remark or "",
        impact=impact,
        reason=(reason or "").strip()[:300],
        operator_id=operator.id,
        operator_name=operator.display_name,
    )
    db.add(arch)
    db.flush()

    # ---- 真正移除物品行（条码随之释放，可重新分配） ----
    # 用 Core DELETE 而非 ORM delete：ORM 的 delete-orphan 级联会连带删掉
    # photos/aliases（我们已把它们改指占位，需要保留）
    db.execute(delete(Item).where(Item.id == item_id))
    db.flush()
    # 清掉 identity map 里的旧对象，避免后续 flush 时 ORM 重新写回已删行
    for model in (Item,):
        obj = db.get(model, item_id)
        if obj is not None:
            db.expunge(obj)

    return {
        "ok": True,
        "deleted": {
            "origin_item_id": item_id,
            "barcode": arch.barcode,
            "name": arch.name,
            "archive_id": arch.id,
            "placeholder_item_id": placeholder.id,
        },
        "impact": impact,
    }


def restore_item(db: Session, *, archive_id: int, operator: User) -> dict[str, Any]:
    """恢复已彻底删除的物品档案（仅超级管理员）。

    按归档快照重建 items 行（条码若已被他人占用则不恢复条码，物品仍可恢复为
    「待编码」状态），并把该物品的引用行从占位档案改回新物品。
    """
    arch = db.get(DeletedItem, archive_id)
    if arch is None:
        raise BizError("归档记录不存在", code="ERR_NOT_FOUND", status=404)
    if arch.restored_at is not None:
        raise BizError("该档案已恢复过", code="ERR_ALREADY_RESTORED", status=409)

    cat = db.get(Category, arch.category_id) if arch.category_id else None
    if cat is None:
        first = db.scalar(select(Category.id).order_by(Category.id).limit(1))
        if first is None:
            raise BizError("系统缺少类目，无法恢复物品档案", code="ERR_NO_CATEGORY", status=409)
        cat = db.get(Category, first)

    # 条码若已被占用则不恢复条码（避免唯一索引冲突），物品恢复但为「待编码」
    barcode = arch.barcode
    barcode_skipped = False
    if barcode:
        dup = db.scalar(select(Item.id).where(Item.barcode == barcode))
        if dup is not None:
            barcode = None
            barcode_skipped = True

    # 找原占位档案（专属占位，一一对应）
    marker = f"origin_item_id:{arch.origin_item_id}"
    ph = db.scalar(
        select(Item)
        .where(Item.name.like(f"{PLACEHOLDER_NAME_PREFIX}%"), Item.remark.like(f"%{marker}%"))
        .limit(1)
    )

    new_item = Item(
        barcode=barcode,
        name=arch.name,
        category_id=cat.id,
        spec=arch.spec or "",
        unit=arch.unit or "件",
        need_label=True,
        print_mode="label",
        status="active",
        barcode_origin="internal",
        remark=arch.remark or "",
    )
    db.add(new_item)
    db.flush()

    # 把该物品的引用行从占位档案改回新物品
    if ph is not None:
        for model in ITEM_REF_MODELS:
            db.execute(update(model).where(model.item_id == ph.id).values(item_id=new_item.id))
        db.execute(update(ItemMergeLog).where(ItemMergeLog.keeper_id == ph.id)
                   .values(keeper_id=new_item.id))
        db.execute(update(ItemMergeLog).where(ItemMergeLog.merged_id == ph.id)
                   .values(merged_id=new_item.id))
        # 占位档案若无其他引用则一并清理
        remaining = sum(_count(db, m, ph.id) for m in ITEM_REF_MODELS)
        remaining += db.scalar(
            select(func.count()).select_from(ItemMergeLog)
            .where((ItemMergeLog.keeper_id == ph.id) | (ItemMergeLog.merged_id == ph.id))
        ) or 0
        if remaining == 0:
            db.execute(delete(Item).where(Item.id == ph.id))
            db.flush()

    arch.restored_at = utcnow()
    arch.restored_by = operator.display_name

    return {
        "ok": True,
        "restored": {
            "item_id": new_item.id,
            "name": new_item.name,
            "barcode": new_item.barcode,
            "barcode_skipped": barcode_skipped,
            "archive_id": arch.id,
        },
    }
