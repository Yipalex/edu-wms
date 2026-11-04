"""add avatar columns to users

Revision ID: 0003_user_avatar
Revises: 0002_item_purge
Create Date: 2026-11-04

头像以 base64 PNG 存 users.avatar_data（与工作台统一账号体系同步）。
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_user_avatar"
down_revision = "0002_item_purge"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("users")}
    if "avatar_data" not in cols:
        op.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data text"))
    if "avatar_updated_at" not in cols:
        op.execute(sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_updated_at timestamptz"))


def downgrade():
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS avatar_updated_at"))
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS avatar_data"))
