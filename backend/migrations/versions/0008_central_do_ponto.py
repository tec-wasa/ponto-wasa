"""Central do Ponto: aparelhos, tickets, código interno/PIN/crachá das pessoas e origem da marcação

Revision ID: 0008
Revises: 0007
"""
import secrets

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kiosks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True, index=True),
        sa.Column("pairing_hash", sa.String(64), nullable=True),
        sa.Column("pairing_expires_at", sa.DateTime(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("radius_m", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "kiosk_tickets",
        sa.Column("nonce", sa.String(64), primary_key=True),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=False, index=True),
        sa.Column("kiosk_id", sa.Integer(), sa.ForeignKey("kiosks.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.add_column("companies", sa.Column("kiosk_pin_required", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("employee_code", sa.String(8), nullable=True))
    op.add_column("users", sa.Column("pin_hash", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("pin_fails", sa.Integer(), server_default="0", nullable=False))
    op.add_column("users", sa.Column("pin_locked_until", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("pin_set_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("badge_version", sa.Integer(), server_default="1", nullable=False))
    op.add_column("users", sa.Column("badge_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("badge_last_step", sa.Integer(), nullable=True))
    op.create_index("ix_users_company_code", "users", ["company_id", "employee_code"], unique=True)
    # a tabela de marcações é append-only (gatilhos): o ALTER é do dono do banco, como toda migração
    op.add_column("punches", sa.Column("kiosk_id", sa.Integer(), nullable=True))  # sem FK (ver o modelo)
    op.add_column("punches", sa.Column("distance_m", sa.Integer(), nullable=True))

    # código interno para quem já existe (6 dígitos, único por empresa)
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, company_id FROM users ORDER BY id")).fetchall()
    used: dict[int, set[str]] = {}
    for uid, cid in rows:
        taken = used.setdefault(cid, set())
        while True:
            code = f"{secrets.randbelow(900000) + 100000}"
            if code not in taken:
                break
        taken.add(code)
        conn.execute(sa.text("UPDATE users SET employee_code = :c WHERE id = :i"), {"c": code, "i": uid})


def downgrade() -> None:
    op.drop_index("ix_users_company_code", table_name="users")
    with op.batch_alter_table("punches") as batch:
        batch.drop_column("distance_m")
        batch.drop_column("kiosk_id")
    with op.batch_alter_table("users") as batch:
        for name in ("badge_last_step", "badge_secret", "badge_version", "pin_set_at", "pin_locked_until", "pin_fails", "pin_hash", "employee_code"):
            batch.drop_column(name)
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("kiosk_pin_required")
    op.drop_table("kiosk_tickets")
    op.drop_table("kiosks")
