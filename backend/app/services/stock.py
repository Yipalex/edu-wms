"""库存变动核心（DESIGN §3 关键约束 1~6）——全系统唯一的库存写入口。

铁律：
1. 所有库存变动必须在**同一事务**内写 stock_movements（qty_before/qty_after/doc_type/
   doc_id/doc_no/operator_id/note 齐全）。报表只查 movements，不查 inventory 快照。
2. 防超卖（关键约束 2）：出库用条件更新
   `UPDATE inventory SET qty_on_hand = qty_on_hand - :q
    WHERE item_id=:i AND location_id=:l AND qty_on_hand >= :q`
   `rowcount == 0` → 409 中文「库存不足」。**不依赖先 SELECT 再判断**（有竞态）；
   SELECT ... FOR UPDATE 仅用于 PG 下锁行 + 取 qty_before（契约明文认可），
   SQLite 下 FOR UPDATE 编译为空操作，条件更新仍是最后防线。
3. 禁止负库存：models 已有 ck_qty_non_negative CHECK，但应用层先行拦截，
   给出友好中文 409（CHECK 违反会变成 500，用户看不懂）。
4. 单据过账幂等（关键约束 4）：state draft→posted 用条件更新 WHERE state='draft'，
   rowcount==0 → 409「该单据已过账，请勿重复提交」。

事务边界约定：本模块所有函数**只 flush 不 commit**。一个单据的过账/作废 = 调用方
（路由层）的一个事务：任一行失败抛 BizError → 路由层 db.rollback() 整体回滚。
"""
import logging

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, lazyload

from app.models import (
    InboundOrder,
    Inventory,
    Item,
    Location,
    OutboundOrder,
    ReturnOrder,
    StockMovement,
    Stocktake,
    utcnow,
)
from app.schemas.common import BizError, conflict

logger = logging.getLogger(__name__)


# ---------- 基础件 ----------

def ensure_inventory_row(db: Session, item_id: int, location_id: int) -> Inventory:
    """取库存行，不存在则创建 0 库存行（配合 uq_inventory_item_location 唯一约束）。"""
    inv = db.scalar(
        select(Inventory)
        .where(Inventory.item_id == item_id, Inventory.location_id == location_id)
        # Inventory.item/location 是 lazy="joined"，PG 禁止对外连接侧加 FOR UPDATE
        .options(lazyload(Inventory.item), lazyload(Inventory.location))
        .with_for_update()
    )
    if inv is not None:
        return inv
    inv = Inventory(item_id=item_id, location_id=location_id,
                    qty_on_hand=0, qty_reserved=0, safety_stock=0)
    try:
        with db.begin_nested():   # SAVEPOINT：并发首插冲突不炸外层事务
            db.add(inv)
            db.flush()
    except IntegrityError:  # pragma: no cover - 并发路径
        inv = db.scalar(
            select(Inventory)
            .where(Inventory.item_id == item_id, Inventory.location_id == location_id)
            .options(lazyload(Inventory.item), lazyload(Inventory.location))
            .with_for_update()
        )
        if inv is None:  # pragma: no cover - 理论不可达
            logger.error("ensure_inventory_row: 冲突重查仍为空 item=%s loc=%s", item_id, location_id)
            raise
    return inv


def _names(db: Session, item_id: int, location_id: int) -> tuple[str, str]:
    """库存不足提示用的中文名（identity map 命中，代价极低）。"""
    item = db.get(Item, item_id)
    loc = db.get(Location, location_id)
    return (item.name if item else f"物品#{item_id}",
            loc.name if loc else f"库位#{location_id}")


def apply_movement(
    db: Session,
    *,
    item_id: int,
    location_id: int,
    change_qty: int,
    doc_type: str,
    doc_id: int | None,
    doc_no: str | None,
    operator_id: int | None,
    note: str = "",
) -> StockMovement:
    """单条库存变动：改 inventory + 写 stock_movements，返回 movement。

    change_qty 正=入（增加库存），负=出（减少库存，防超卖拦截）。
    只 flush 不 commit，与调用方同一事务。
    """
    if change_qty == 0:
        raise BizError("库存变动数量不能为 0", code="ERR_BAD_QTY")

    if change_qty > 0:
        inv = ensure_inventory_row(db, item_id, location_id)
        qty_before = inv.qty_on_hand
        db.execute(
            update(Inventory)
            .where(Inventory.id == inv.id)
            .values(qty_on_hand=Inventory.qty_on_hand + change_qty, updated_at=utcnow())
        )
        qty_after = qty_before + change_qty
    else:
        q = -change_qty
        item_name, loc_name = _names(db, item_id, location_id)
        # PG：FOR UPDATE 锁行取当前值（友好报错用）；SQLite：空操作，仅取值
        inv = db.scalar(
            select(Inventory)
            .where(Inventory.item_id == item_id, Inventory.location_id == location_id)
            .options(lazyload(Inventory.item), lazyload(Inventory.location))
            .with_for_update()
        )
        cur = inv.qty_on_hand if inv is not None else 0
        if cur < q:
            # 应用层先行拦截：给出中文 409，而不是撞 CHECK 约束变 500
            raise BizError(
                f"库存不足：{item_name} 在 {loc_name} 只有 {cur} 件，无法出库 {q} 件",
                code="ERR_INSUFFICIENT_STOCK", status=409,
            )
        # 防超卖关键（契约 §3 约束 2）：条件更新，qty_on_hand >= q 才会命中
        result = db.execute(
            update(Inventory)
            .where(
                Inventory.item_id == item_id,
                Inventory.location_id == location_id,
                Inventory.qty_on_hand >= q,
            )
            .values(qty_on_hand=Inventory.qty_on_hand - q, updated_at=utcnow())
        )
        if result.rowcount == 0:  # pragma: no cover - 并发竞态路径
            # 锁与判断之间被并发事务抢先扣走（PG READ COMMITTED 极端情形）
            raise BizError(
                f"库存不足：{item_name} 在 {loc_name} 的库存刚被其他操作占用，无法出库 {q} 件，请刷新后重试",
                code="ERR_INSUFFICIENT_STOCK", status=409,
            )
        qty_before = cur
        qty_after = cur - q

    mv = StockMovement(
        item_id=item_id,
        location_id=location_id,
        change_qty=change_qty,
        qty_before=qty_before,
        qty_after=qty_after,
        doc_type=doc_type,
        doc_id=doc_id,
        doc_no=doc_no,
        operator_id=operator_id,
        note=note[:300] if note else "",
    )
    db.add(mv)
    db.flush()
    return mv


def _reverse_movements(
    db: Session, *, doc_type: str, doc_id: int, operator_id: int | None
) -> int:
    """作废冲销：把某单据产生的全部 movement 逐条反向（doc_type=adjust）。

    返回冲销条数。反向减少若因库存已被消耗而不足，apply_movement 会抛 409，
    由调用方事务整体回滚——不允许出现负库存的冲销。
    """
    movs = db.scalars(
        select(StockMovement).where(
            StockMovement.doc_type == doc_type, StockMovement.doc_id == doc_id
        ).order_by(StockMovement.id)
    ).all()
    for m in movs:
        apply_movement(
            db,
            item_id=m.item_id,
            location_id=m.location_id,
            change_qty=-m.change_qty,
            doc_type="adjust",
            doc_id=doc_id,
            doc_no=m.doc_no,
            operator_id=operator_id,
            note=f"作废单号 {m.doc_no} 冲销",
        )
    return len(movs)


# ---------- 状态机（幂等） ----------

def _transition(
    db: Session, model, state_col, doc_id: int,
    *, expect: tuple[str, ...], to_state: str, err_msg: str,
) -> None:
    """条件状态更新（契约 §3 约束 4）。rowcount==0 → 409。

    state_col 可以是 state（入库/出库）或 accept_state（退库），统一按列对象更新。
    """
    result = db.execute(
        update(model)
        .where(model.id == doc_id, state_col.in_(expect))
        .values({state_col.key: to_state, "posted_at": utcnow(), "updated_at": utcnow()})
    )
    if result.rowcount == 0:
        raise conflict(err_msg)


# ---------- 各单据过账 ----------

def post_inbound(db: Session, order: InboundOrder, operator_id: int) -> None:
    """入库单过账：指定库位（通常 HQ 前置仓）库存增加。整单一个事务。"""
    _transition(
        db, InboundOrder, InboundOrder.state, order.id,
        expect=("draft",), to_state="posted",
        err_msg="该单据已过账或已作废，请勿重复提交",
    )
    for line in order.items:
        apply_movement(
            db,
            item_id=line.item_id,
            location_id=order.location_id,
            change_qty=line.qty,
            doc_type="inbound",
            doc_id=order.id,
            doc_no=order.doc_no,
            operator_id=operator_id,
            note=f"入库单 {order.doc_no} 过账",
        )
    db.refresh(order)


def post_outbound_transfer(db: Session, order: OutboundOrder, operator_id: int) -> None:
    """出库/调拨单过账。

    - kind=transfer（调拨给校区）：from 减 + to 增，**两条 movement**（doc_type=transfer）
    - kind=issue（领用消耗）：只减 from（doc_type=outbound）
    先减后增：库存不足立刻失败回滚，不会先把货加到目标库位。
    """
    _transition(
        db, OutboundOrder, OutboundOrder.state, order.id,
        expect=("draft",), to_state="posted",
        err_msg="该单据已过账或已作废，请勿重复提交",
    )
    if order.kind == "transfer":
        if order.to_location_id is None:
            raise BizError("调拨单缺少目标库位，请先完善单据再过账", code="ERR_NO_TARGET_LOCATION")
        if order.to_location_id == order.from_location_id:
            raise BizError("调出与调入库位相同，无需调拨", code="ERR_SAME_LOCATION")
        for line in order.items:
            apply_movement(
                db,
                item_id=line.item_id,
                location_id=order.from_location_id,
                change_qty=-line.qty,
                doc_type="transfer",
                doc_id=order.id,
                doc_no=order.doc_no,
                operator_id=operator_id,
                note=f"调拨单 {order.doc_no} 调出",
            )
            apply_movement(
                db,
                item_id=line.item_id,
                location_id=order.to_location_id,
                change_qty=line.qty,
                doc_type="transfer",
                doc_id=order.id,
                doc_no=order.doc_no,
                operator_id=operator_id,
                note=f"调拨单 {order.doc_no} 调入",
            )
    else:  # issue
        for line in order.items:
            apply_movement(
                db,
                item_id=line.item_id,
                location_id=order.from_location_id,
                change_qty=-line.qty,
                doc_type="outbound",
                doc_id=order.id,
                doc_no=order.doc_no,
                operator_id=operator_id,
                note=f"领用出库单 {order.doc_no} 过账",
            )
    db.refresh(order)


def post_return(db: Session, order: ReturnOrder, operator_id: int) -> None:
    """退库单过账（仅验收通过后调用）：校区(from)减、总校办(to)增，doc_type=return。"""
    _transition(
        db, ReturnOrder, ReturnOrder.accept_state, order.id,
        expect=("draft",), to_state="posted",
        err_msg="该单据已过账或已作废，请勿重复提交",
    )
    for line in order.items:
        apply_movement(
            db,
            item_id=line.item_id,
            location_id=order.from_location_id,
            change_qty=-line.qty,
            doc_type="return",
            doc_id=order.id,
            doc_no=order.doc_no,
            operator_id=operator_id,
            note=f"退库单 {order.doc_no} 校区退回",
        )
        apply_movement(
            db,
            item_id=line.item_id,
            location_id=order.to_location_id,
            change_qty=line.qty,
            doc_type="return",
            doc_id=order.id,
            doc_no=order.doc_no,
            operator_id=operator_id,
            note=f"退库单 {order.doc_no} 总仓收回",
        )
    db.refresh(order)


def post_stocktake_adjust(db: Session, st: Stocktake, operator_id: int) -> None:
    """盘点单过账：对每个已录实盘数且差异非 0 的行写 adjust 流水校正库存。

    盘盈（实盘>账面）加、盘亏减。差异在 Python 侧用 qty_counted - qty_book 计算，
    **不读数据库生成列 variance**（规避生成列在事务内的读取时机问题）。
    state: draft/counting → done，条件更新保证幂等。
    """
    result = db.execute(
        update(Stocktake)
        .where(Stocktake.id == st.id, Stocktake.state.in_(("draft", "counting")))
        .values(state="done", posted_at=utcnow(), updated_at=utcnow())
    )
    if result.rowcount == 0:
        raise conflict("该盘点单已过账，请勿重复提交")
    for line in st.items:
        if line.qty_counted is None:
            continue
        variance = line.qty_counted - line.qty_book   # Python 计算，勿显式写 variance 列
        if variance == 0:
            continue
        apply_movement(
            db,
            item_id=line.item_id,
            location_id=st.location_id,
            change_qty=variance,
            doc_type="adjust",
            doc_id=st.id,
            doc_no=st.doc_no,
            operator_id=operator_id,
            note=f"盘点单 {st.doc_no} 校正（账面 {line.qty_book} / 实盘 {line.qty_counted}）",
        )
    db.refresh(st)


# ---------- 作废（冲销） ----------

def void_inbound(db: Session, order: InboundOrder, admin_id: int) -> None:
    """入库单作废：draft 直接作废；posted 先冲销库存再作废。"""
    old = order.state
    if old == "voided":
        raise conflict("该单据已作废，请勿重复操作")
    _void_transition(db, InboundOrder, InboundOrder.state, order.id, old)
    if old == "posted":
        _reverse_movements(db, doc_type="inbound", doc_id=order.id, operator_id=admin_id)
    db.refresh(order)


def void_outbound(db: Session, order: OutboundOrder, admin_id: int) -> None:
    """出库/调拨单作废：transfer 冲销 doc_type=transfer 的两条流水，issue 冲销 outbound。"""
    old = order.state
    if old == "voided":
        raise conflict("该单据已作废，请勿重复操作")
    _void_transition(db, OutboundOrder, OutboundOrder.state, order.id, old)
    if old == "posted":
        doc_type = "transfer" if order.kind == "transfer" else "outbound"
        _reverse_movements(db, doc_type=doc_type, doc_id=order.id, operator_id=admin_id)
    db.refresh(order)


def void_return(db: Session, order: ReturnOrder, admin_id: int) -> None:
    """退库单作废：仅已过账（验收通过并影响库存）的可作废，冲销 return 流水。"""
    if order.accept_state == "voided":
        raise conflict("该单据已作废，请勿重复操作")
    if order.accept_state != "posted":
        raise BizError("该退库单尚未过账（未验收通过），不涉及库存，无需作废",
                       code="ERR_NOT_POSTED", status=409)
    _void_transition(db, ReturnOrder, ReturnOrder.accept_state, order.id, "posted")
    _reverse_movements(db, doc_type="return", doc_id=order.id, operator_id=admin_id)
    db.refresh(order)


def _void_transition(db: Session, model, state_col, doc_id: int, expect: str) -> None:
    result = db.execute(
        update(model)
        .where(model.id == doc_id, state_col == expect)
        .values({state_col.key: "voided", "updated_at": utcnow()})
    )
    if result.rowcount == 0:  # pragma: no cover - 并发路径
        raise conflict("单据状态已变化，请刷新后重试")
