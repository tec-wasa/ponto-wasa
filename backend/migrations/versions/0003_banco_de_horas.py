"""banco de horas: configuração por empresa e trabalhador e lançamentos manuais append-only

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

from app import immutability

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("bank_max_minutes", sa.Integer(), nullable=True))
    op.add_column("companies", sa.Column("bank_expiry_months", sa.Integer(), server_default="6", nullable=False))
    op.add_column("users", sa.Column("hour_bank_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("hour_bank_start", sa.Date(), nullable=True))
    op.create_table(
        "hour_bank_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_hour_bank_entries_company_id"), "hour_bank_entries", ["company_id"], unique=False)
    op.create_index(op.f("ix_hour_bank_entries_user_id"), "hour_bank_entries", ["user_id"], unique=False)
    dialect = op.get_bind().dialect.name
    for statement in immutability.create_statements("hour_bank_entries", dialect):
        op.execute(statement)


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    for statement in immutability.drop_statements("hour_bank_entries", dialect):
        op.execute(statement)
    op.drop_index(op.f("ix_hour_bank_entries_user_id"), table_name="hour_bank_entries")
    op.drop_index(op.f("ix_hour_bank_entries_company_id"), table_name="hour_bank_entries")
    op.drop_table("hour_bank_entries")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("hour_bank_start")
        batch.drop_column("hour_bank_enabled")
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("bank_expiry_months")
        batch.drop_column("bank_max_minutes")
