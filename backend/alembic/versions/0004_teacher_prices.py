"""add teacher role + item cost prices

Revision ID: 0004_teacher_prices
Revises: 0003_user_avatar
Create Date: 2026-11-05

1. user_role 枚举增加 'teacher'（教师：只能看建议售价与本校区数量，操作仅限出入库退）。
2. items 表新增 purchase_price（真实采购价）/ internal_price（内部销售价），
   历史数据留空，由超管通过批量导入模板补录。
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_teacher_prices"
down_revision = "0003_user_avatar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1) 枚举加值：PG 12+ 允许在事务内执行 ALTER TYPE ... ADD VALUE
    if bind.dialect.name == "postgresql":
        op.execute(sa.text("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'teacher'"))

    # 2) items 加两个价格列（SQLite 本地测试库由 ORM metadata.create_all 兜底）
    if bind.dialect.name == "postgresql":
        insp = sa.inspect(bind)
        cols = {c["name"] for c in insp.get_columns("items")}
        if "purchase_price" not in cols:
            op.execute(sa.text("ALTER TABLE items ADD COLUMN purchase_price NUMERIC(10, 2)"))
        if "internal_price" not in cols:
            op.execute(sa.text("ALTER TABLE items ADD COLUMN internal_price NUMERIC(10, 2)"))


def downgrade() -> None:
    # PG 不支持 DROP VALUE / DROP COLUMN 回滚业务数据，仅保留空实现
    pass
