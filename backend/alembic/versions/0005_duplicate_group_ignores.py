"""duplicate group ignores

Revision ID: 0005_duplicate_group_ignores
Revises: 0004_teacher_prices
Create Date: 2026-11-06

去重合并页支持「忽略」：人工判定不是重复的分组按成员集合(group_key)忽略，
后续检测不再出现；已忽略列表可恢复（恢复后分组重新出现）。
SQLite 本地测试库由 ORM metadata.create_all 兜底。
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_duplicate_group_ignores"
down_revision = "0004_teacher_prices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "duplicate_group_ignores",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("group_key", sa.String(200), nullable=False),
        sa.Column("match_type", sa.String(20), nullable=True),
        sa.Column("suggested_name", sa.String(200), nullable=True),
        sa.Column("members", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False, server_default=""),
        sa.Column("operator_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("group_key", name="uq_dup_ignore_key"),
    )


def downgrade() -> None:
    op.drop_table("duplicate_group_ignores")
