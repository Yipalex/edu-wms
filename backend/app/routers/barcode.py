"""条码路由（DESIGN §6）：

- GET  /barcode-rules（AO）
- PUT  /barcode-rules（A，prefix/region 必须纯数字）
- POST /barcode/preview（AO，试算不占用）
- POST /barcode/allocate（AO，body: item_id 或 category_id+count）
- POST /items/{id}/reassign-barcode（A，写 barcode_history type=reassign，旧码不释放）
- GET  /items/{id}/barcode-history（AO）
- GET  /barcode/history（A，type/时间段/操作人筛选 + 分页）
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_role
from app.models import BarcodeHistory, BarcodeRule, BarcodeSequence, Item, User
from app.schemas.common import BizError, ok, ok_page
from app.services import barcode as bc
from app.services.audit import write_audit

router = APIRouter(tags=["条码"])

AdminUser = require_role("admin")

# 分配时数据库唯一索引冲突的重试次数（并发兜底，配合 services/barcode.py 内部重试）
ALLOC_DB_RETRY = 3


# ---------- 编码规则 ----------

class RuleUpdate(BaseModel):
    prefix: str = Field(min_length=1, max_length=4, pattern=r"^[0-9]+$", description="必须纯数字（易知鸟硬约束）")
    region_code: str = Field(min_length=1, max_length=4, pattern=r"^[0-9]+$")
    seq_width: int = Field(ge=1, le=8)
    total_length: int = Field(ge=4, le=14)
    allow_external: bool = True


def rule_row(r: BarcodeRule) -> dict:
    return {
        "id": r.id, "prefix": r.prefix, "region_code": r.region_code,
        "seq_width": r.seq_width, "total_length": r.total_length,
        "allow_external": r.allow_external,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("/barcode-rules")
def get_rules(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return ok(rule_row(bc.get_rule(db)))


@router.put("/barcode-rules")
def update_rules(body: RuleUpdate, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    rule = bc.get_rule(db)
    if len(body.prefix) + len(body.region_code) + 1 + body.seq_width != body.total_length:
        raise BizError(
            "总长度必须等于 前缀 + 地区码 + 分类位(1) + 流水位数，请核对后再保存",
            code="ERR_RULE_LENGTH",
        )
    old = rule_row(rule)
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    rule.updated_by = admin.id
    write_audit(db, action="update", entity="barcode_rule", entity_id=1, user=admin,
                detail={"old": old, "new": rule_row(rule)}, request=request)
    db.commit()
    db.refresh(rule)
    return ok(rule_row(rule))


# ---------- 流水种子（迁移 / 存量条码对齐用） ----------

class SequenceSeedBody(BaseModel):
    category_digit: str | None = Field(default=None, description="类目分类位（1~9）")
    category_id: int | None = Field(default=None, description="或类目 id")
    next_seq: int = Field(ge=1, le=99999999, description="下一个可用流水号")


@router.put("/barcode-rules/sequences")
def set_sequence_seed(body: SequenceSeedBody, request: Request,
                      admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    """把某类目的流水推进到指定值（数据迁移时对齐存量条码，避免新分配的码与存量撞号）。

    只推进不回退：若请求的 next_seq 小于当前值，保持当前值并返回 applied=current。
    """
    if body.category_digit is None and body.category_id is None:
        raise BizError("必须提供 category_digit 或 category_id", code="ERR_BAD_REQUEST")
    cat = None
    if body.category_id is not None:
        cat = db.get(Category, body.category_id)
    if cat is None and body.category_digit is not None:
        cat = bc.category_by_digit(db, body.category_digit)
    if cat is None:
        raise BizError("类目不存在", code="ERR_NOT_FOUND", status=404)

    seq_row = db.scalar(select(BarcodeSequence).where(BarcodeSequence.category_id == cat.id))
    if seq_row is None:
        raise BizError("该类目尚未初始化流水种子，请检查种子数据", code="ERR_SEQ_MISSING", status=409)
    old = seq_row.next_seq
    applied = max(old, body.next_seq)
    changed = applied != old
    if changed:
        seq_row.next_seq = applied
        write_audit(db, action="set_barcode_sequence", entity="category", entity_id=cat.id,
                    user=admin,
                    detail={"category": cat.name, "digit": cat.digit,
                            "old_next_seq": old, "new_next_seq": applied},
                    request=request)
        db.commit()
        db.refresh(seq_row)
    return ok({
        "category_id": cat.id, "category_name": cat.name, "category_digit": cat.digit,
        "old_next_seq": old, "requested_next_seq": body.next_seq,
        "next_seq": seq_row.next_seq, "applied": applied, "changed": changed,
    })


# ---------- 预览与分配 ----------

class PreviewBody(BaseModel):
    category_id: int
    count: int = Field(default=1, ge=1, le=500)


@router.post("/barcode/preview")
def preview(body: PreviewBody, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    codes = bc.preview_next(db, body.category_id, body.count)
    return ok({"codes": codes})


class AllocateBody(BaseModel):
    item_id: int | None = None
    category_id: int | None = None
    count: int = Field(default=1, ge=1, le=500)


@router.post("/barcode/allocate")
def allocate(body: AllocateBody, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """两种模式：
    - item_id：给单个待编码物品分配并绑定（写 barcode_history type=assign）
    - category_id + count：只分配 n 个连续码返回（不绑定物品，用于批量打印等）
    """
    if body.item_id is None and body.category_id is None:
        raise BizError("必须提供 item_id 或 category_id", code="ERR_BAD_REQUEST")

    if body.item_id is not None:
        item = db.get(Item, body.item_id)
        if item is None:
            raise BizError("物品不存在", code="ERR_NOT_FOUND", status=404)
        if item.status != "active":
            raise BizError("只有正常状态的物品才能分配条码", code="ERR_ITEM_STATUS", status=409)
        if item.barcode:
            raise BizError(f"该物品已有条码 {item.barcode}，如需更换请使用「重分配条码」", code="ERR_HAS_BARCODE", status=409)
        codes = _allocate_with_retry(db, item.category_id, 1)
        code = codes[0]
        item.barcode = code
        item.barcode_origin = "internal"
        db.add(BarcodeHistory(
            item_id=item.id, old_barcode=None, new_barcode=code,
            change_type="assign", reason="分配条码", operator_id=user.id,
        ))
        write_audit(db, action="assign_barcode", entity="item", entity_id=item.id, user=user,
                    detail={"barcode": code}, request=request)
        db.commit()
        return ok({"codes": [code], "item_id": item.id})

    codes = _allocate_with_retry(db, body.category_id, body.count)
    write_audit(db, action="allocate_barcode", entity="category", entity_id=body.category_id, user=user,
                detail={"count": body.count, "codes": codes}, request=request)
    db.commit()
    return ok({"codes": codes, "category_id": body.category_id})


def _allocate_with_retry(db: Session, category_id: int, n: int) -> list[str]:
    """并发兜底：SQLite 无行锁，唯一索引冲突（IntegrityError）时回滚重试。
    PG 下 FOR UPDATE 已串行化，此重试几乎不会触发。"""
    last_err: Exception | None = None
    for _ in range(ALLOC_DB_RETRY):
        try:
            return bc.allocate(db, category_id, n)
        except IntegrityError as e:  # pragma: no cover - 并发路径
            db.rollback()
            last_err = e
    raise BizError("条码分配冲突，请重试", code="ERR_ALLOC_CONFLICT", status=409) from last_err


# ---------- 重分配 ----------

class ReassignBody(BaseModel):
    new_barcode: str | None = Field(default=None, description="留空=自动分配新内部码")
    reason: str = Field(min_length=1, max_length=300)


def history_row(h: BarcodeHistory) -> dict:
    return {
        "id": h.id, "item_id": h.item_id,
        "item_name": h.item.name if h.item else None,
        "old_barcode": h.old_barcode, "new_barcode": h.new_barcode,
        "change_type": h.change_type, "reason": h.reason,
        "operator_id": h.operator_id,
        "operator_name": h.operator.display_name if h.operator else None,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }


@router.post("/items/{item_id}/reassign-barcode")
def reassign_barcode(item_id: int, body: ReassignBody, request: Request, admin: User = Depends(AdminUser), db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if item is None:
        raise BizError("物品不存在", code="ERR_NOT_FOUND", status=404)
    if item.status != "active":
        raise BizError("只有正常状态的物品才能重分配条码", code="ERR_ITEM_STATUS", status=409)

    old = item.barcode
    if body.new_barcode:
        # 手动指定新码：完整校验（格式+唯一+内部码分类位一致）
        origin = bc.check_barcode_for_item(db, body.new_barcode, item.category_id, exclude_item_id=item.id)
        new_code = body.new_barcode.strip()
        item.barcode_origin = origin
    else:
        new_code = _allocate_with_retry(db, item.category_id, 1)[0]
        item.barcode_origin = "internal"

    item.barcode = new_code
    # 旧码不释放复用：写入历史，扫码旧码时可溯源提示（DESIGN §3 关键约束 6）
    db.add(BarcodeHistory(
        item_id=item.id, old_barcode=old, new_barcode=new_code,
        change_type="reassign", reason=body.reason, operator_id=admin.id,
    ))
    write_audit(db, action="reassign_barcode", entity="item", entity_id=item.id, user=admin,
                detail={"old": old, "new": new_code, "reason": body.reason}, request=request)
    db.commit()
    return ok({"item_id": item.id, "old_barcode": old, "new_barcode": new_code})


# ---------- 历史查询 ----------

@router.get("/items/{item_id}/barcode-history")
def item_barcode_history(item_id: int, _: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if db.get(Item, item_id) is None:
        raise BizError("物品不存在", code="ERR_NOT_FOUND", status=404)
    rows = db.scalars(
        select(BarcodeHistory).where(BarcodeHistory.item_id == item_id)
        .order_by(BarcodeHistory.created_at.desc(), BarcodeHistory.id.desc())
    ).all()
    return ok([history_row(h) for h in rows])


@router.get("/barcode/history")
def global_barcode_history(
    page: int = 1, page_size: int = 20,
    change_type: str | None = None,
    start: datetime | None = None, end: datetime | None = None,
    operator_id: int | None = None,
    _: User = Depends(AdminUser), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    q = select(BarcodeHistory)
    cq = select(BarcodeHistory.id)
    if change_type:
        q = q.where(BarcodeHistory.change_type == change_type)
        cq = cq.where(BarcodeHistory.change_type == change_type)
    if start:
        q = q.where(BarcodeHistory.created_at >= start)
        cq = cq.where(BarcodeHistory.created_at >= start)
    if end:
        q = q.where(BarcodeHistory.created_at <= end)
        cq = cq.where(BarcodeHistory.created_at <= end)
    if operator_id:
        q = q.where(BarcodeHistory.operator_id == operator_id)
        cq = cq.where(BarcodeHistory.operator_id == operator_id)
    total = len(db.scalars(cq).all())
    rows = db.scalars(
        q.order_by(BarcodeHistory.created_at.desc(), BarcodeHistory.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return ok_page([history_row(h) for h in rows], page=page, page_size=page_size, total=total)
