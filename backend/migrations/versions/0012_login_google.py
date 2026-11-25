"""Login com Google: vínculo da conta (users.google_sub) e senha permitida por empresa (companies.password_login)

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(64), nullable=True))
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.add_column("companies", sa.Column("password_login", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("companies", "password_login")
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "google_sub")
