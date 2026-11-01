"""单据号生成（DESIGN §3 doc_counters 表）。

契约格式：
- 入库 IN-YYYYMMDD-NNN、出库 OUT-YYYYMMDD-NNN、退库 RET-YYYYMMDD-NNN、盘点 STK-YYYYMMDD-NNN
- NNN 从 001 起、3 位补零、当日递增、跨日自动重置（复合主键 prefix+ymd，新的一天是新行）

并发安全（与 services/barcode.py 的 allocate() 同一风格）：
- PostgreSQL：事务内 SELECT ... FOR UPDATE 锁 doc_counters 行，串行化同前缀同日分配
- SQLite：不支持行级锁，with_for_update() 编译为空操作；兜底 = SAVEPOINT 内插入 +
  唯一主键冲突（IntegrityError）时重新锁定读取再递增。SQLite 仅用于本地开发/测试

注意：迁移专用单号 `IN-MIGRATION-<库位code>` 由迁移工具直接拼装写入，
**不经过**本模块、不占用 doc_counters 流水。
"""
import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import DocCounter

logger = logging.getLogger(__name__)

# 单据前缀（doc_counters.prefix 取值）
PREFIX_INBOUND = "IN"
PREFIX_OUTBOUND = "OUT"
PREFIX_RETURN = "RET"
PREFIX_STOCKTAKE = "STK"

SEQ_WIDTH = 3


def _today_ymd() -> str:
    """当日日期串（YYYYMMDD）。独立函数便于测试 monkeypatch 验证跨日重置。"""
    return date.today().strftime("%Y%m%d")


def _lock_counter(db: Session, prefix: str, ymd: str) -> DocCounter | None:
    """锁定计数行。PG 编译为 FOR UPDATE；SQLite 编译为空操作（见模块注释）。"""
    return db.scalar(
        select(DocCounter)
        .where(DocCounter.prefix == prefix, DocCounter.ymd == ymd)
        .with_for_update()
    )


def next_doc_no(db: Session, prefix: str) -> str:
    """分配下一个单据号，如 IN-20261019-001。

    事务语义：只 flush 不 commit，与调用方（建单路由）同一事务提交；
    建单失败回滚时该号作废（允许跳号，不追求绝对连续）。
    """
    ymd = _today_ymd()
    row = _lock_counter(db, prefix, ymd)
    if row is None:
        # 当日该前缀首次使用：SAVEPOINT 内插入，主键冲突（并发首插）则重锁读取
        row = DocCounter(prefix=prefix, ymd=ymd, seq=0)
        try:
            with db.begin_nested():
                db.add(row)
                db.flush()
        except IntegrityError:  # pragma: no cover - 并发路径
            row = _lock_counter(db, prefix, ymd)
            if row is None:  # pragma: no cover - 理论不可达
                logger.error("docno: 计数行插入冲突后仍读不到 prefix=%s ymd=%s", prefix, ymd)
                raise
    row.seq += 1
    db.flush()
    return f"{prefix}-{ymd}-{str(row.seq).zfill(SEQ_WIDTH)}"
