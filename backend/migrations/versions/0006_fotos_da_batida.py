"""foto opcional na batida: consentimento por pessoa, habilitação por empresa e tabela de fotos (apagadas no fechamento do mês)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("photo_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("photo_consent_at", sa.DateTime(), nullable=True))
    op.create_table(
        "punch_photos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("punch_id", sa.Integer(), sa.ForeignKey("punches.id"), nullable=False, unique=True),
        sa.Column("month", sa.String(7), nullable=False, index=True),
        sa.Column("storage_key", sa.String(200), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("punch_photos")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("photo_consent_at")
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("photo_enabled")
