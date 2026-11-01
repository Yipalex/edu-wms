"""初始 schema：全部表 + 索引 + 视图 v_inventory_value

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-19

说明：初始迁移直接引用 app.models 的 metadata 建表，保证 migration 与 ORM
模型 1:1 一致（模型是唯一真源）。PG 专属对象（pg_trgm 模糊搜索索引）在
create_all 之后按方言单独创建。后续 schema 变更请用 alembic autogenerate
产出显式 op 指令。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.db import Base
import app.models  # noqa: F401

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VIEW_SQL = """
CREATE VIEW v_inventory_value AS
SELECT i.id AS inventory_id, i.item_id, i.location_id, i.qty_on_hand,
       it.suggest_price, COALESCE(it.suggest_price,0) * i.qty_on_hand AS stock_value
FROM inventory i JOIN items it ON it.id = i.item_id
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)

    op.execute(sa.text(VIEW_SQL))

    if bind.dialect.name == "postgresql":
        # 契约 §3：items.name 模糊搜索用 gin_trgm_ops（PG 专属）
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        op.execute(sa.text("DROP INDEX IF EXISTS idx_items_name"))
        op.execute(sa.text(
            "CREATE INDEX idx_items_name ON items USING gin (name gin_trgm_ops)"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    op.execute(sa.text("DROP VIEW IF EXISTS v_inventory_value"))
    Base.metadata.drop_all(bind=bind)
