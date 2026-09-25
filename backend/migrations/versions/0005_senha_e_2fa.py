"""troca obrigatória de senha, versão de sessão e verificação em duas etapas (TOTP)

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("must_change_password", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("token_version", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("totp_last_step", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("totp_recovery", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        for name in ("totp_recovery", "totp_last_step", "totp_enabled", "totp_secret", "token_version", "must_change_password"):
            batch.drop_column(name)
