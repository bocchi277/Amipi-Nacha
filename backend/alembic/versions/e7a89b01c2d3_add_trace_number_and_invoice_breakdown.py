"""add_trace_number_and_invoice_breakdown

Revision ID: e7a89b01c2d3
Revises: 6db80fc79756
Create Date: 2026-08-25 18:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e7a89b01c2d3'
down_revision: Union[str, Sequence[str], None] = '6db80fc79756'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add invoice_breakdown and trace_number to payments if not exists
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS invoice_breakdown JSONB;"))
    conn.execute(sa.text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS trace_number VARCHAR(30);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_payments_trace_number ON payments (trace_number);"))

    # Add body_html and trace_number to vendor_remittances if not exists
    conn.execute(sa.text("ALTER TABLE vendor_remittances ADD COLUMN IF NOT EXISTS body_html TEXT;"))
    conn.execute(sa.text("ALTER TABLE vendor_remittances ADD COLUMN IF NOT EXISTS trace_number VARCHAR(30);"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_vendor_remittances_trace_number ON vendor_remittances (trace_number);"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP INDEX IF EXISTS ix_vendor_remittances_trace_number;"))
    conn.execute(sa.text("ALTER TABLE vendor_remittances DROP COLUMN IF EXISTS trace_number;"))
    conn.execute(sa.text("ALTER TABLE vendor_remittances DROP COLUMN IF EXISTS body_html;"))

    conn.execute(sa.text("DROP INDEX IF EXISTS ix_payments_trace_number;"))
    conn.execute(sa.text("ALTER TABLE payments DROP COLUMN IF EXISTS trace_number;"))
    conn.execute(sa.text("ALTER TABLE payments DROP COLUMN IF EXISTS invoice_breakdown;"))
