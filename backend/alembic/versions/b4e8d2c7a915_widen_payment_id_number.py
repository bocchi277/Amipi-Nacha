"""widen payments.id_number to hold the readable invoice reference

``payments.id_number`` was ``VARCHAR(15)``, matching the width of the NACHA Individual
Identification Number field, so the column and the bank field were the same thing.

They are now separate concerns:

* The **database** stores the human-readable reference, which may list several invoices
  with separators, e.g. ``UDI261954/65/55`` or ``875886/2425708/876153``. Keeping it
  readable is what lets the UI, the audit trail and the remittance advice show which
  invoices a payment covers.
* The **file** value is derived at generation time by ``app.nacha.id_field`` which
  strips to alphanumerics and truncates to 15, because every one of the 97 ID fields in
  AMIPI's real Chase transmit files is purely alphanumeric.

80 characters matches the readable reference width the v7 prototype used and the
existing ``vendor_remittances.invoice_reference`` column, so the two stay consistent.

Revision ID: b4e8d2c7a915
Revises: a7c3e91f4b20
Create Date: 2026-08-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4e8d2c7a915"
down_revision: Union[str, Sequence[str], None] = "a7c3e91f4b20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "payments",
        "id_number",
        existing_type=sa.VARCHAR(length=15),
        type_=sa.String(length=80),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Truncate before narrowing so the column change cannot fail on existing data.
    op.execute("UPDATE payments SET id_number = LEFT(id_number, 15) WHERE LENGTH(id_number) > 15")
    op.alter_column(
        "payments",
        "id_number",
        existing_type=sa.String(length=80),
        type_=sa.VARCHAR(length=15),
        existing_nullable=False,
    )
