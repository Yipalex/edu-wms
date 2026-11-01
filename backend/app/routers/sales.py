"""销售对接 API（yj.zexishuhua.com 销量系统调用，DESIGN 范围外补充端点）。

yj 侧每成交一笔调用 POST /sales/deduct 扣减本系统库存：
- 幂等键 = sale_ref：yj 侧唯一标识。重放同一 sale_ref 返回 duplicated=true 不重复扣减。
- 以 remark='yj销售|{sale_ref}' 在 outbound_orders 上查重（人工也能在单据列表看到来源）。
- 走标准出库流程：建 issue 单（领用消耗）→ stock.post_outbound_transfer 立即过账，
  防超卖、stock_movements 同事务，不绕过 stock.py 直接改库存。

权限 AO（admin/operator 均可）：yj 使用专用服务账号调用。
"""
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models import (
    Inventory, Item, Location, OutboundItem, OutboundOrder, User,
)
from app.schemas.common import BizError, ok
from app.services import stock
from app.services.audit import write_audit
from app.services.docno import PREFIX_OUTBOUND, next_doc_no

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sales", tags=["销售对接"])


class SaleDeductBody(BaseModel):
    barcode: str = Field(pattern=r"^[0-9]{8,14}$")
    location_code: str = Field(min_length=1, max_length=20)
    qty: int = Field(default=1, gt=0)
    sale_ref: str = Field(min_length=1, max_length=64, description="yj 侧唯一标识=幂等键")
    sold_at: datetime | None = None
    note: str = Field(default="", max_length=300)


def _remark(sale_ref: str) -> str:
    return f"yj销售|{sale_ref}"


def _find_by_sale_ref(db: Session, sale_ref: str) -> OutboundOrder | None:
    return db.scalar(select(OutboundOrder).where(OutboundOrder.remark == _remark(sale_ref)))


@router.post("/deduct")
def sale_deduct(body: SaleDeductBody, request: Request,
                user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """按条码扣减指定库位库存（yj 成交回调）。"""
    # ① 幂等查重：同一 sale_ref 重放 → 返回已有单据信息，不重复扣
    existing = _find_by_sale_ref(db, body.sale_ref)
    if existing is not None:
        line = (existing.items or [None])[0]
        return ok({
            "doc_no": existing.doc_no,
            "order_id": existing.id,
            "item_id": line.item_id if line else None,
            "item_name": line.name_snapshot if line else None,
            "barcode": line.barcode_snapshot if line else None,
            "qty": line.qty if line else None,
            "duplicated": True,
            "message": f"该销售单（{body.sale_ref}）已扣减过，单号 {existing.doc_no}",
        })

    # ② 物品按条码查 active
    item = db.scalar(select(Item).where(Item.barcode == body.barcode))
    if item is None:
        raise BizError("条码未登记", code="ERR_BARCODE_NOT_REGISTERED", status=404)
    if item.status == "merged":
        keeper = item.merged_into
        hint = f"该物品已合并至「{keeper.name}」" if keeper else "该物品已合并"
        if keeper and keeper.barcode:
            hint += f"，现用码 {keeper.barcode}"
        raise BizError(hint, code="ERR_ITEM_MERGED", status=409)
    if item.status != "active":
        raise BizError(f"物品「{item.name}」已停用，不能销售扣减",
                       code="ERR_ITEM_RETIRED", status=409)

    # ③ 库位按 code 查
    location = db.scalar(select(Location).where(Location.code == body.location_code))
    if location is None:
        raise BizError(f"库位编码不存在：{body.location_code}",
                       code="ERR_LOCATION_NOT_FOUND", status=404)

    # ④ 建 issue 出库单（快照明细）并立即过账（防超卖、写流水，同事务）
    doc_no = next_doc_no(db, PREFIX_OUTBOUND)
    order = OutboundOrder(
        doc_no=doc_no,
        kind="issue",
        from_location_id=location.id,
        to_location_id=None,
        state="draft",
        order_date=body.sold_at.date() if body.sold_at else date.today(),
        remark=_remark(body.sale_ref),
        operator_id=user.id,
    )
    order.items = [OutboundItem(
        item_id=item.id,
        barcode_snapshot=item.barcode,
        name_snapshot=item.name,
        qty=body.qty,
        sort_order=0,
    )]
    db.add(order)
    try:
        db.flush()
        stock.post_outbound_transfer(db, order, operator_id=user.id)

        qty_after = db.scalar(
            select(func.coalesce(func.sum(Inventory.qty_on_hand), 0))
            .where(Inventory.item_id == item.id, Inventory.location_id == location.id)
        ) or 0

        # ⑤ 审计（与业务同一事务）
        write_audit(db, action="sale_deduct", entity="outbound_order", entity_id=order.id,
                    user=user, detail={
                        "doc_no": doc_no, "sale_ref": body.sale_ref,
                        "barcode": item.barcode, "item_id": item.id,
                        "location_code": location.code, "qty": body.qty,
                    }, request=request)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ok({
        "doc_no": doc_no,
        "item_id": item.id,
        "item_name": item.name,
        "barcode": item.barcode,
        "location_id": location.id,
        "location_name": location.name,
        "qty": body.qty,
        "qty_after": qty_after,
        "duplicated": False,
    })


@router.get("/deduct/check")
def sale_deduct_check(sale_ref: str,
                      _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """查询某 sale_ref 是否已扣减（yj 侧对账/重试前调用）。"""
    existing = _find_by_sale_ref(db, sale_ref) if sale_ref else None
    return ok({
        "deducted": existing is not None,
        "doc_no": existing.doc_no if existing else None,
    })


@router.get("/catalog")
def sale_catalog(q: str | None = None,
                 _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """在售物品全量清单（不分页），供 yj 侧同步商品档案与库存。"""
    stmt = select(Item).where(Item.status == "active")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Item.name.like(like))
    stmt = stmt.order_by(Item.id)
    items = db.scalars(stmt).all()
    if not items:
        return ok([])

    ids = [i.id for i in items]
    locs = {loc.id: loc.code for loc in db.scalars(select(Location)).all()}
    inv_rows = db.execute(
        select(Inventory.item_id, Inventory.location_id, func.sum(Inventory.qty_on_hand))
        .where(Inventory.item_id.in_(ids))
        .group_by(Inventory.item_id, Inventory.location_id)
    ).all()
    stock_map: dict[int, dict[str, int]] = {iid: {} for iid in ids}
    total_map: dict[int, int] = {iid: 0 for iid in ids}
    for item_id, location_id, qty in inv_rows:
        code = locs.get(location_id)
        if code:
            stock_map[item_id][code] = (stock_map[item_id].get(code, 0) + (qty or 0))
            total_map[item_id] += qty or 0

    return ok([
        {
            "item_id": i.id,
            "barcode": i.barcode,
            "name": i.name,
            "spec": i.spec or "",
            "unit": i.unit,
            "category_name": i.category.name if i.category else None,
            "suggest_price": float(i.suggest_price) if i.suggest_price is not None else None,
            "stock_by_location": stock_map.get(i.id, {}),
            "total_qty": total_map.get(i.id, 0),
        }
        for i in items
    ])