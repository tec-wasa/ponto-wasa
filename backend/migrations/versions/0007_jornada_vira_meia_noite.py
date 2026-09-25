"""jornada que pode terminar no dia seguinte (turno da noite); o padrão é encerrar à meia-noite

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schedules", sa.Column("crosses_midnight", sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("schedules") as batch:
        batch.drop_column("crosses_midnight")
