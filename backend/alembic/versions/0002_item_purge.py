"""彻底删除物品档案：superadmin 角色 + deleted_items 归档表

Revision ID: 0002_item_purge
Revises: 0001_initial
Create Date: 2026-11-04

变更内容：
1. user_role 枚举增加 'superadmin'（超级管理员）——PG 用 ALTER TYPE ADD VALUE，
   该语句在事务内执行会报错，故用 autocommit 块单独执行。
2. 新增 deleted_items 表：存放被彻底删除物品的原始快照 + 处理摘要 + 恢复痕迹。
3. items 表新增占位档案所需的索引支持（占位档案走 name 前缀 + remark 匹配，
   不建额外索引，表规模小）。

回滚：ALTER TYPE user_role DROP VALUE 会失败（PG 不支持删枚举值），
故 downgrade 只删表，保留枚举值（安全方向）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_item_purge"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 枚举加值：PG 12+ 允许在事务内执行 ALTER TYPE ... ADD VALUE
    #    （限制仅是「同一事务内不能使用新值」，本迁移只加值不用它）
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'superadmin'"))
    else:
        # SQLite：Enum 以 VARCHAR + CHECK 实现，本地测试库每次重建，故忽略
        pass

    # 2) deleted_items 归档表
    #    注：PG 生产走下面这段；SQLite 本地测试库由 ORM metadata.create_all 建表
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("""
            CREATE TABLE IF NOT EXISTS deleted_items (
                id BIGSERIAL PRIMARY KEY,
                origin_item_id BIGINT NOT NULL,
                barcode VARCHAR(20),
                name VARCHAR(200) NOT NULL,
                category_id BIGINT,
                category_name VARCHAR(100),
                spec VARCHAR(100) DEFAULT '' NOT NULL,
                unit VARCHAR(20) DEFAULT '' NOT NULL,
                suggest_price NUMERIC(10, 2),
                remark TEXT DEFAULT '' NOT NULL,
                impact JSONB NOT NULL DEFAULT '{}'::jsonb,
                reason VARCHAR(300) DEFAULT '' NOT NULL,
                operator_id BIGINT REFERENCES users(id),
                operator_name VARCHAR(50),
                deleted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                restored_at TIMESTAMPTZ,
                restored_by VARCHAR(50)
            )
        """))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_deleted_items_barcode ON deleted_items (barcode)"))
        op.execute(sa.text("CREATE INDEX IF NOT EXISTS idx_deleted_items_time ON deleted_items (deleted_at)"))


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(sa.text("DROP TABLE IF EXISTS deleted_items"))
    # user_role 的 'superadmin' 枚举值保留（PG 不支持 DROP VALUE，保留更安全）
