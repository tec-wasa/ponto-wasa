"""Ausências em lote: identificador do lote na ausência

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("absences", sa.Column("batch_id", sa.String(32), nullable=True))
    op.create_index("ix_absences_batch_id", "absences", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_absences_batch_id", table_name="absences")
    op.drop_column("absences", "batch_id")
