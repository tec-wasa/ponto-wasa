"""Perfis acumuláveis (roles) e "registra ponto" (tracks_time)

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("roles", sa.String(60), nullable=False, server_default=""))
    op.add_column("users", sa.Column("tracks_time", sa.Boolean(), nullable=False, server_default=sa.true()))
    # quem já tinha um perfil de gestão passa a tê-lo na lista (gestor/RH/administrador/auditor)
    op.execute("UPDATE users SET roles = role WHERE role <> 'employee'")


def downgrade() -> None:
    op.drop_column("users", "tracks_time")
    op.drop_column("users", "roles")
