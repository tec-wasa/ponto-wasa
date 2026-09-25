"""Política de batida por pessoa: aplicativo e Central, ou só a Central

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("punch_policy", sa.String(8), nullable=False, server_default="both"))


def downgrade() -> None:
    op.drop_column("users", "punch_policy")
