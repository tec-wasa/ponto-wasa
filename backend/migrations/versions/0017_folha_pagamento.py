"""Exportação para a folha de pagamento: verbas da empresa e matrícula de cada pessoa na folha

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("payroll_export", sa.JSON(), nullable=True))
    op.add_column("users", sa.Column("payroll_code", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "payroll_code")
    op.drop_column("companies", "payroll_export")
