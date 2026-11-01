"""物品去重合并（DESIGN §5）：相似检测 + 十步合并事务 + 回滚。

相似检测移植自 migration/clean.py（契约 §5.1）：
- normalize：去空格与标点
- 分桶键 (ptype, volume, digits)，跨桶绝不比较
- 桶内 difflib.SequenceMatcher ratio >= threshold 同组（贪心聚类，同 clean.py）
- 特殊标记优先于 fuzzy：norm 后完全相等但原名不同 → space_variant(0.99)；
  完全同名不同码 → same_name(0.98)

合并语义（契约 §5.2 十步），全部在一个事务内完成（路由层 commit）：
① 校验 keeper/merged 均 active、不自合并、merged_ids 非空不重复
② 快照 impact_snapshot（条码/名称/照片/库存/单据行 id/流水 id）
③ 库存并入 keeper（qty_on_hand/qty_reserved 相加，safety_stock 取 max），
   写 stock_movements(doc_type='adjust')，merged 库存行删除（快照留底）
④ 四类单据明细行 item_id 改指 keeper（快照字段写 merged 的码/名，历史不失真）
⑤ stock_movements.item_id 改指 keeper
⑥ item_photos 改挂 keeper（file_path 去重；keeper 无主图时把 merged 主图设主图）
⑦ merged.name / merged.barcode 写入 item_aliases(source='merge'，去重)
⑧ merged.barcode 写 barcode_history(change_type='merge_retire')，码不释放复用
⑨ merged.status='merged'、merged_into_id=keeper、barcode=None、名称加 [已合并] 前缀
⑩ 写 item_merge_log（路由层另写 audit_log）

回滚按 impact_snapshot 逆向恢复（契约 §5.2）：
库存从 keeper 减回（走 stock.apply_movement 防负库存）、单据行与流水 item_id 改回、
条码还原（撞唯一索引 → 409）、状态/名称复原、删 source='merge' 别名、照片挂回。

事务边界：本模块函数只 flush 不 commit，与调用方（路由层）同一事务。
"""
import difflib
import re
from collections import Counter
from typing import Any

from sqlalchemy import case, delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    BarcodeHistory,
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
    utcnow,
)
from app.schemas.common import BizError, conflict, not_found
from app.services import stock

# ---------- 相似检测（移植 migration/common.py，契约 §5.1） ----------

_PUNCT = " 　-_—()（）【】[]·,，.。/"


def normalize(name: str) -> str:
    """名称归一化：去空格与标点。"""
    for ch in _PUNCT:
        name = name.replace(ch, "")
    return name


def ptype(name: str) -> str:
    """品类：练习本 / 材料包 / 教材 / 费用 / 其他（不同品类必是不同物品）。"""
    if any(k in name for k in ("配套练习本", "专练本", "练习本", "练字本")):
        return "练习本"
    if "材料包" in name:
        return "材料包"
    if "教材" in name:
        return "教材"
    if any(k in name for k in ("考级", "赛事", "研学", "特权包", "新权包", "费用")):
        return "费用"
    return "其他"


def volume(name: str) -> str:
    """册次：上 / 下 / ''。"""
    m = re.search(r"(上|下)(册|教材|配套|（|\(|$)", name)
    return m.group(1) if m else ""


def digits(name: str) -> str:
    """抽出所有数字串。"""
    return "".join(c for c in name if c.isdigit())


def bucket_key(name: str) -> tuple[str, str, str]:
    """分桶键 = (ptype, volume, digits)，跨桶必是不同物品，绝不比较。"""
    return (ptype(name), volume(name), digits(name))


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def pick_unified(names: list[str]) -> str:
    """组内推荐统一名：出现次数最多者；并列取最短。"""
    cnt = Counter(names)
    top = max(cnt.values())
    cands = [n for n, c in cnt.items() if c == top]
    return min(cands, key=len)


def find_duplicate_groups(
    members: list[dict[str, Any]], threshold: float = 0.70
) -> list[dict[str, Any]]:
    """相似分组。

    members: [{"id", "barcode", "name", ...}...]，只传 status='active' 的物品。
    返回 [{group_key, match_type, confidence, suggested_name, members([id...])}]，
    只含成员数 >= 2 的组，按置信度降序。
    """
    named = [m for m in members if m.get("name") and m["name"].strip()]
    groups: list[dict[str, Any]] = []

    # 1) norm 后完全相等（最高置信，优先于 fuzzy）
    by_norm: dict[str, list[dict]] = {}
    for m in named:
        by_norm.setdefault(normalize(m["name"]), []).append(m)
    grouped_ids: set[int] = set()
    for _norm, members_ in by_norm.items():
        if len(members_) < 2:
            continue
        raw_names = {m["name"] for m in members_}
        if len(raw_names) == 1:
            mtype, conf = "same_name", 0.98
        else:
            mtype, conf = "space_variant", 0.99
        ids = sorted(m["id"] for m in members_)
        groups.append({
            "group_key": "-".join(str(i) for i in ids),
            "match_type": mtype,
            "confidence": conf,
            "suggested_name": pick_unified([m["name"] for m in members_]),
            "member_ids": ids,
        })
        grouped_ids.update(ids)

    # 2) 桶内 fuzzy 聚类（排除已进 space/same_name 组的）
    rest = [m for m in named if m["id"] not in grouped_ids]
    buckets: dict[tuple[str, str, str], list[dict]] = {}
    for m in rest:
        buckets.setdefault(bucket_key(m["name"]), []).append(m)

    for bucket_members in buckets.values():
        n = len(bucket_members)
        if n < 2:
            continue
        # 贪心聚类（同 migration/common.py cluster()）：组内两两 ratio >= threshold
        gid = [-1] * n
        g = 0
        for i in range(n):
            if gid[i] != -1:
                continue
            gid[i] = g
            for j in range(i + 1, n):
                if gid[j] == -1 and similarity(
                    bucket_members[i]["name"], bucket_members[j]["name"]
                ) >= threshold:
                    gid[j] = g
            g += 1
        clusters: dict[int, list[dict]] = {}
        for idx, item_ in enumerate(bucket_members):
            clusters.setdefault(gid[idx], []).append(item_)
        for cluster_members in clusters.values():
            if len(cluster_members) < 2:
                continue
            best = max(
                similarity(a["name"], b["name"])
                for i, a in enumerate(cluster_members)
                for b in cluster_members[i + 1:]
            )
            ids = sorted(m["id"] for m in cluster_members)
            groups.append({
                "group_key": "-".join(str(i) for i in ids),
                "match_type": "fuzzy",
                "confidence": round(best, 2),
                "suggested_name": pick_unified([m["name"] for m in cluster_members]),
                "member_ids": ids,
            })

    groups.sort(key=lambda g_: -g_["confidence"])
    return groups


# ---------- 合并（契约 §5.2 十步，单事务，只 flush 不 commit） ----------

_MERGED_PREFIX = "[已合并] "


def _snapshot_merged(db: Session, merged: Item) -> dict:
    """第②步：合并前快照（回滚的依据）。"""
    invs = db.scalars(select(Inventory).where(Inventory.item_id == merged.id)).all()
    photos = db.scalars(select(ItemPhoto).where(ItemPhoto.item_id == merged.id)).all()

    def _line_ids(model) -> list[int]:
        return [r[0] for r in db.execute(
            select(model.id).where(model.item_id == merged.id)
        )]

    return {
        "barcode": merged.barcode,
        "name": merged.name,
        "photos": [
            {"id": p.id, "file_path": p.file_path, "is_primary": p.is_primary,
             "sort_order": p.sort_order}
            for p in photos
        ],
        "inventory": [
            {"location_id": inv.location_id, "qty_on_hand": inv.qty_on_hand,
             "qty_reserved": inv.qty_reserved, "safety_stock": inv.safety_stock}
            for inv in invs
        ],
        "inbound_item_ids": _line_ids(InboundItem),
        "outbound_item_ids": _line_ids(OutboundItem),
        "return_item_ids": _line_ids(ReturnItem),
        "stocktake_item_ids": _line_ids(StocktakeItem),
        "movement_ids": [r[0] for r in db.execute(
            select(StockMovement.id).where(StockMovement.item_id == merged.id)
        )],
    }


def _merge_one(db: Session, keeper: Item, merged: Item, reason: str,
               operator_id: int | None) -> ItemMergeLog:
    """单个 merged 的十步合并（③~⑩）。调用方已做第①步校验。"""
    snap = _snapshot_merged(db, merged)
    src = merged.barcode or merged.name

    # ③ 库存并入 keeper：qty_on_hand/qty_reserved 相加，safety_stock 取 max；
    #    写 adjust 流水（stock_movements 与库存变更同事务）；merged 行删除（快照留底）
    for inv in snap["inventory"]:
        keeper_inv = stock.ensure_inventory_row(db, keeper.id, inv["location_id"])
        qty_before = keeper_inv.qty_on_hand
        db.execute(
            update(Inventory)
            .where(Inventory.id == keeper_inv.id)
            .values(
                qty_on_hand=Inventory.qty_on_hand + inv["qty_on_hand"],
                qty_reserved=Inventory.qty_reserved + inv["qty_reserved"],
                safety_stock=case(
                    (Inventory.safety_stock >= inv["safety_stock"], Inventory.safety_stock),
                    else_=inv["safety_stock"],
                ),
                updated_at=utcnow(),
            )
        )
        if inv["qty_on_hand"]:
            db.add(StockMovement(
                item_id=keeper.id,
                location_id=inv["location_id"],
                change_qty=inv["qty_on_hand"],
                qty_before=qty_before,
                qty_after=qty_before + inv["qty_on_hand"],
                doc_type="adjust",
                doc_id=None,
                doc_no=None,
                operator_id=operator_id,
                note=f"合并自 {src}"[:300],
            ))
    db.execute(delete(Inventory).where(Inventory.item_id == merged.id))

    # ④ 四类单据明细行 item_id 改指 keeper（快照字段写 merged 的码/名，历史不失真）
    for model in (InboundItem, OutboundItem, ReturnItem, StocktakeItem):
        db.execute(
            update(model)
            .where(model.item_id == merged.id)
            .values(item_id=keeper.id,
                    barcode_snapshot=merged.barcode,
                    name_snapshot=merged.name)
        )

    # ⑤ stock_movements.item_id 改指 keeper（保留原 doc_no）
    db.execute(
        update(StockMovement)
        .where(StockMovement.item_id == merged.id)
        .values(item_id=keeper.id)
    )

    # ⑥ 照片改挂 keeper：file_path 去重；keeper 无主图时把 merged 主图设主图
    keeper_photos = db.scalars(
        select(ItemPhoto).where(ItemPhoto.item_id == keeper.id)
    ).all()
    keeper_paths = {p.file_path for p in keeper_photos}
    keeper_has_primary = any(p.is_primary for p in keeper_photos)
    former_primary_id = None
    for p in snap["photos"]:
        photo = db.get(ItemPhoto, p["id"])
        if photo is None:
            continue
        if photo.file_path in keeper_paths:
            db.delete(photo)  # 与 keeper 已有照片是同一张文件，去重
            continue
        photo.item_id = keeper.id
        photo.is_primary = False  # 先全部置否，主图逻辑在下面统一处理
        if p["is_primary"] and former_primary_id is None:
            former_primary_id = photo.id
    if not keeper_has_primary and former_primary_id is not None:
        db.get(ItemPhoto, former_primary_id).is_primary = True

    # ⑦ merged.name 与 merged.barcode 写入 item_aliases（source='merge'，去重）
    keeper_aliases = {
        a.alias for a in db.scalars(
            select(ItemAlias).where(ItemAlias.item_id == keeper.id)
        )
    }
    for alias in (merged.name, merged.barcode):
        if not alias or alias in keeper_aliases:
            continue
        if alias == keeper.name or alias == keeper.barcode:
            continue
        db.add(ItemAlias(item_id=keeper.id, alias=alias, source="merge"))
        keeper_aliases.add(alias)

    # ⑧ 条码退役：码不释放复用；new_barcode 记 keeper 现码，扫旧码可溯源
    if merged.barcode:
        db.add(BarcodeHistory(
            item_id=merged.id,
            old_barcode=merged.barcode,
            new_barcode=keeper.barcode,
            change_type="merge_retire",
            reason=reason or "合并退役",
            operator_id=operator_id,
        ))

    # ⑨ 软删：status='merged'，barcode 置 NULL（唯一索引让位），名称加前缀
    merged.status = "merged"
    merged.merged_into_id = keeper.id
    merged.barcode = None
    merged.name = _MERGED_PREFIX + merged.name

    # ⑩ 写 item_merge_log
    log = ItemMergeLog(
        keeper_id=keeper.id,
        merged_id=merged.id,
        merged_barcode=snap["barcode"],
        merged_name=snap["name"],
        impact_snapshot=snap,
        reason=reason,
        operator_id=operator_id,
    )
    db.add(log)
    db.flush()
    return log


def perform_merge(
    db: Session, keeper_id: int, merged_ids: list[int], reason: str, operator_id: int | None
) -> tuple[Item, list[int]]:
    """合并入口：校验 + 逐个 merged 执行十步。返回 (keeper, log_ids)。"""
    keeper = db.get(Item, keeper_id)
    if keeper is None:
        raise not_found("保留项物品不存在")
    if keeper.status != "active":
        raise conflict(f"保留项「{keeper.name}」不是正常状态，不能作为合并目标")

    if not merged_ids:
        raise BizError("待合并物品列表不能为空", code="ERR_EMPTY_MERGE_LIST")
    if len(set(merged_ids)) != len(merged_ids):
        raise BizError("待合并物品列表存在重复 id", code="ERR_DUP_MERGE_ID")
    if keeper_id in merged_ids:
        raise BizError("不能把物品合并到它自己", code="ERR_SELF_MERGE")

    log_ids: list[int] = []
    for mid in merged_ids:
        merged = db.get(Item, mid)
        if merged is None:
            raise not_found(f"待合并物品不存在（id={mid}）")
        if merged.status != "active":
            raise conflict(f"物品「{merged.name}」不是正常状态，不能参与合并"
                           f"（已合并/已停用的物品请先回滚或恢复）")
        log = _merge_one(db, keeper, merged, reason, operator_id)
        log_ids.append(log.id)
    db.flush()
    return keeper, log_ids


# ---------- 回滚（契约 §5.2，按 impact_snapshot 逆向恢复） ----------

def rollback_merge(db: Session, log: ItemMergeLog, operator_id: int | None) -> Item:
    """回滚一次合并。守卫（已回滚 / keeper 状态）由路由层先行检查。"""
    snap = log.impact_snapshot or {}
    keeper = db.get(Item, log.keeper_id)
    merged = db.get(Item, log.merged_id)
    if merged is None:
        raise not_found("被合并的物品档案已不存在，无法回滚")
    if merged.status != "merged" or merged.merged_into_id != keeper.id:
        raise conflict(f"物品「{merged.name}」当前不处于合并到该保留项的状态，无法回滚")

    # 库存：从 keeper 减回（走 apply_movement 防负库存，不足则 409 整体回滚）
    for inv in snap.get("inventory", []):
        if inv["qty_on_hand"]:
            stock.apply_movement(
                db,
                item_id=keeper.id,
                location_id=inv["location_id"],
                change_qty=-inv["qty_on_hand"],
                doc_type="adjust",
                doc_id=None,
                doc_no=None,
                operator_id=operator_id,
                note=f"回滚合并，恢复自 {snap.get('barcode') or snap.get('name')}"[:300],
            )
        keeper_inv = db.scalar(
            select(Inventory).where(
                Inventory.item_id == keeper.id,
                Inventory.location_id == inv["location_id"],
            )
        )
        if keeper_inv is not None:
            keeper_inv.qty_reserved = max(0, keeper_inv.qty_reserved - inv["qty_reserved"])
        # merged 库存行按快照重建（合并时已删除）
        db.add(Inventory(
            item_id=merged.id,
            location_id=inv["location_id"],
            qty_on_hand=inv["qty_on_hand"],
            qty_reserved=inv["qty_reserved"],
            safety_stock=inv["safety_stock"],
        ))

    # 单据明细行与流水 item_id 改回 merged
    for model, key in ((InboundItem, "inbound_item_ids"),
                       (OutboundItem, "outbound_item_ids"),
                       (ReturnItem, "return_item_ids"),
                       (StocktakeItem, "stocktake_item_ids")):
        ids = snap.get(key) or []
        if ids:
            db.execute(
                update(model).where(model.id.in_(ids)).values(item_id=merged.id)
            )
    mv_ids = snap.get("movement_ids") or []
    if mv_ids:
        db.execute(
            update(StockMovement)
            .where(StockMovement.id.in_(mv_ids))
            .values(item_id=merged.id)
        )

    # 照片挂回 merged 并恢复主图标记
    for p in snap.get("photos", []):
        photo = db.get(ItemPhoto, p["id"])
        if photo is None:
            continue
        photo.item_id = merged.id
        photo.is_primary = p["is_primary"]
        photo.sort_order = p["sort_order"]

    # 条码还原：撞唯一索引（码已被他人占用）→ 409，整体回滚
    merged.barcode = snap.get("barcode")
    merged.name = snap.get("name") or merged.name
    merged.status = "active"
    merged.merged_into_id = None

    # 删 source='merge' 的对应别名
    alias_values = {snap.get("name"), snap.get("barcode")} - {None, ""}
    if alias_values:
        db.execute(
            delete(ItemAlias).where(
                ItemAlias.item_id == keeper.id,
                ItemAlias.source == "merge",
                ItemAlias.alias.in_(alias_values),
            )
        )

    log.rolled_back_at = utcnow()
    try:
        db.flush()
    except IntegrityError:
        raise conflict(
            f"回滚失败：原条码 {snap.get('barcode')} 已被其他物品占用，请先处理条码冲突"
        )
    return merged
