"""条码引擎（DESIGN §2 / §3 关键约束 3、6）。

编码规则：8 位纯数字 = prefix("2") + region("10") + 分类位(1) + 流水(4)。
一物一码不含校区。外部码（商品原装 EAN-13 等）沿用不套本机构码。

并发防护（allocate）：
- PostgreSQL：事务内 SELECT ... FOR UPDATE 锁 barcode_sequences 行，
  串行化同分类的流水分配（DESIGN §3 关键约束 3）。
- SQLite：不支持行级锁，`with_for_update()` 会被方言编译为空操作；
  兜底策略 = 单事务内「重查 next_seq → 生成 → 校验 items.barcode 唯一
  → 回写」，配合 items.barcode 部分唯一索引（uq_items_barcode），
  并发写重了会在 commit 时触发 IntegrityError，由调用方（路由层）重试。
  SQLite 仅用于本地开发/测试，生产 PG 有真行锁。
"""
import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, lazyload

from app.models import BarcodeRule, BarcodeSequence, Category, Item
from app.schemas.common import BizError

logger = logging.getLogger(__name__)

CODE_PATTERN = re.compile(r"^[0-9]{8,14}$")

# 分配冲突重试上限（全局唯一性兜底）
MAX_ALLOC_RETRY = 3


@dataclass
class ParsedCode:
    is_internal: bool
    prefix: str = ""
    region: str = ""
    category_digit: str = ""
    seq: int | None = None


def get_rule(db: Session) -> BarcodeRule:
    rule = db.get(BarcodeRule, 1)
    if rule is None:
        raise BizError("编码规则未初始化，请联系管理员执行种子数据", code="ERR_RULE_MISSING", status=500)
    return rule


def build_code(prefix: str, region: str, cat_digit: str, seq: int, seq_width: int = 4) -> str:
    """按规则拼装条码。seq 超出位宽直接报错（不静默截断）。"""
    if seq < 0:
        raise BizError("流水号不能为负数", code="ERR_BAD_SEQ")
    seq_str = str(seq).zfill(seq_width)
    if len(seq_str) > seq_width:
        raise BizError(
            f"流水号 {seq} 超出 {seq_width} 位上限，请调整编码规则或归档旧码",
            code="ERR_SEQ_OVERFLOW", status=409,
        )
    return f"{prefix}{region}{cat_digit}{seq_str}"


def is_internal_code(code: str, rule: BarcodeRule) -> bool:
    """内部码判定（DESIGN §2）：全数字 + 长度=total_length + 以配置 prefix 开头 + region 匹配。"""
    if not code.isdigit():
        return False
    if len(code) != rule.total_length:
        return False
    if not code.startswith(rule.prefix):
        return False
    rest = code[len(rule.prefix):]
    return rest.startswith(rule.region_code)


def parse_code(code: str, rule: BarcodeRule) -> ParsedCode:
    """解析条码。外部码返回 is_internal=False，不解析地区/分类/流水。"""
    code = (code or "").strip()
    if not is_internal_code(code, rule):
        return ParsedCode(is_internal=False)
    body = code[len(rule.prefix) + len(rule.region_code):]
    cat_digit = body[0]
    seq_part = body[1:]
    try:
        seq = int(seq_part)
    except ValueError:
        return ParsedCode(is_internal=False)
    return ParsedCode(
        is_internal=True,
        prefix=rule.prefix,
        region=rule.region_code,
        category_digit=cat_digit,
        seq=seq,
    )


def is_valid(code: str, rule: BarcodeRule) -> tuple[bool, str]:
    """校验条码格式。返回 (是否合法, 中文错误信息)。

    - 所有码：纯数字 + 长度 8~14（外部码规则）
    - 长度恰为 total_length 且以 prefix 开头的「疑似内部码」：region 必须匹配
    """
    code = (code or "").strip()
    if not code:
        return False, "条码不能为空"
    if not CODE_PATTERN.match(code):
        return False, "条码必须是 8~14 位纯数字"
    if len(code) == rule.total_length and code.startswith(rule.prefix):
        # 疑似内部码：region 必须匹配，否则视为非法（防止 21xxx 之外的假内部码混入）
        if not is_internal_code(code, rule):
            return False, f"条码以 {rule.prefix} 开头且长度为 {rule.total_length}，但地区码不是 {rule.region_code}，不是合法的本机构码；如需录入商品原装码请确认长度或联系管理员"
    return True, ""


def category_by_digit(db: Session, digit: str) -> Category | None:
    return db.scalar(select(Category).where(Category.digit == digit))


def _lock_sequence(db: Session, category_id: int) -> BarcodeSequence:
    """锁定流水行。PG 编译为 FOR UPDATE；SQLite 编译为空操作（见模块注释）。"""
    seq = db.scalar(
        select(BarcodeSequence)
        .where(BarcodeSequence.category_id == category_id)
        # BarcodeSequence.category 是 lazy="joined"，会生成 LEFT OUTER JOIN；
        # PG 禁止对可空侧加 FOR UPDATE（与 services/stock.py 同一坑），必须先卸载
        .options(lazyload(BarcodeSequence.category))
        .with_for_update()
    )
    if seq is None:
        raise BizError("该类目尚未初始化流水种子，请联系管理员", code="ERR_SEQ_MISSING", status=409)
    return seq


def allocate(db: Session, category_id: int, n: int = 1) -> list[str]:
    """给指定类目分配 n 个连续内部码并占用流水（不自动挂到物品上）。

    事务语义：调用方负责 commit；本函数内校验与 items.barcode 无冲突，
    冲突时推进流水重试，最多 MAX_ALLOC_RETRY 次。
    """
    if n < 1 or n > 500:
        raise BizError("分配数量必须在 1~500 之间", code="ERR_BAD_COUNT")
    rule = get_rule(db)
    cat = db.get(Category, category_id)
    if cat is None:
        raise BizError("类目不存在", code="ERR_NOT_FOUND", status=404)

    for attempt in range(MAX_ALLOC_RETRY):
        seq_row = _lock_sequence(db, category_id)
        start = seq_row.next_seq
        codes = [
            build_code(rule.prefix, rule.region_code, cat.digit, start + i, rule.seq_width)
            for i in range(n)
        ]
        # 全局唯一性兜底：生成的码不得已存在于 items.barcode
        existing = db.scalars(select(Item.barcode).where(Item.barcode.in_(codes))).all()
        if existing:
            # 有冲突：把流水推进到冲突码之后，重试
            max_conflict_seq = max(parse_code(c, rule).seq or 0 for c in existing)
            logger.warning(
                "allocate: 类目 %s 流水 %s 与存量条码冲突（最大冲突流水 %s），第 %s 次推进重试",
                cat.digit, start, max_conflict_seq, attempt + 1,
            )
            seq_row.next_seq = max_conflict_seq + 1
            db.flush()
            continue
        seq_row.next_seq = start + n
        db.flush()
        return codes

    raise BizError(
        "条码流水与存量数据反复冲突，无法分配，请联系管理员检查 barcode_sequences 种子",
        code="ERR_ALLOC_CONFLICT", status=409,
    )


def preview_next(db: Session, category_id: int, n: int = 1) -> list[str]:
    """只试算不占用：返回接下来 n 个码（不写库）。"""
    rule = get_rule(db)
    cat = db.get(Category, category_id)
    if cat is None:
        raise BizError("类目不存在", code="ERR_NOT_FOUND", status=404)
    seq_row = db.scalar(select(BarcodeSequence).where(BarcodeSequence.category_id == category_id))
    if seq_row is None:
        raise BizError("该类目尚未初始化流水种子", code="ERR_SEQ_MISSING", status=409)
    return [
        build_code(rule.prefix, rule.region_code, cat.digit, seq_row.next_seq + i, rule.seq_width)
        for i in range(max(1, n))
    ]


def check_barcode_for_item(db: Session, code: str, category_id: int, *, exclude_item_id: int | None = None) -> str:
    """新建/改档案时校验条码：格式 + 全局唯一 +（内部码则分类位必须与 category 一致）。

    返回 barcode_origin：'internal' | 'external'。校验失败抛 BizError（中文提示）。
    """
    rule = get_rule(db)
    valid, msg = is_valid(code, rule)
    if not valid:
        raise BizError(msg, code="ERR_BAD_BARCODE")
    q = select(Item.id).where(Item.barcode == code)
    if exclude_item_id is not None:
        q = q.where(Item.id != exclude_item_id)
    if db.scalar(q) is not None:
        raise BizError(f"条码 {code} 已被其他物品占用，一物一码不能重复", code="ERR_BARCODE_DUP", status=409)
    parsed = parse_code(code, rule)
    if parsed.is_internal:
        cat = db.get(Category, category_id)
        if cat is None or cat.digit != parsed.category_digit:
            raise BizError(
                f"条码 {code} 的分类位是 {parsed.category_digit}，与所选类目不一致，请重新选择类目或更换条码",
                code="ERR_BARCODE_CAT_MISMATCH",
            )
        return "internal"
    if not rule.allow_external:
        raise BizError("当前编码规则不允许录入商品原装外部码", code="ERR_EXTERNAL_DISABLED")
    return "external"
