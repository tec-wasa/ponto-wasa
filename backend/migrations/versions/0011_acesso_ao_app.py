"""Acesso ao aplicativo por pessoa (app_access) e e-mail opcional para quem só usa a Central

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("app_access", sa.Boolean(), nullable=False, server_default=sa.true()))
        b.alter_column("email", existing_type=sa.String(200), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("users") as b:
        b.alter_column("email", existing_type=sa.String(200), nullable=False)
        b.drop_column("app_access")
