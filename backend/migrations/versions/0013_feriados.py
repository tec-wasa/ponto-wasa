"""Feriados: cadastro da empresa (estaduais/municipais) e opção de Carnaval e Corpus Christi

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "holidays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("recurring", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.add_column("companies", sa.Column("holiday_carnaval", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("companies", sa.Column("holiday_corpus_christi", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("companies", "holiday_corpus_christi")
    op.drop_column("companies", "holiday_carnaval")
    op.drop_table("holidays")
