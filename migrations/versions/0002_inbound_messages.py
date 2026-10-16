"""Add WhatsApp inbound replay protection.

Revision ID: 0002_inbound_messages
Revises: 0001_initial
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_inbound_messages"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_messages",
        sa.Column("provider_message_id", sa.String(length=200), nullable=False),
        sa.Column("sender_id", sa.String(length=100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("provider_message_id"),
    )


def downgrade() -> None:
    op.drop_table("inbound_messages")
