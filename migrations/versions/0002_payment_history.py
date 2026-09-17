"""create payment_history table

Revision ID: 0002_payment_history
Revises: 0001_payments_outbox
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_payment_history"
down_revision: str | Sequence[str] | None = "0001_payments_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_history",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False
        ),
        sa.Column("payment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'created', 'gateway_succeeded', 'gateway_failed', "
            "'webhook_delivered', 'webhook_delivery_failed'"
            ")",
            name="ck_payment_history_event_type",
        ),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_payment_history_payment_id_created_at",
        "payment_history",
        ["payment_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_payment_history_payment_id_created_at", table_name="payment_history"
    )
    op.drop_table("payment_history")
