"""widen vendors.name so it is no longer truncated to the NACHA field width

``vendors.name`` was ``VARCHAR(22)``, matching the width of the NACHA Entry Detail
receiver name field (positions 55-76). The name was therefore truncated when the vendor
was SAVED, which conflates two different things:

* the vendor's identity, which is what spreadsheet rows are matched against and
  therefore decides which bank account a payment reaches, and
* the 22 characters that happen to fit in one field of the output file.

Truncating on write means two genuinely different companies sharing a 22-character
prefix become indistinguishable rows with different bank accounts.
``INTERNATIONAL DIAMOND ALPHA CORP`` and ``INTERNATIONAL DIAMOND BRAVO CORP`` both
stored as ``'INTERNATIONAL DIAMOND '``. A spreadsheet naming either one then matches two
records and the choice of bank account comes down to row order.

Truncation now happens only where the limit actually applies, when the NACHA line is
written, via ``app.core.vendor_identity.nacha_receiver_name``.

This migration only widens the column. Names already stored were truncated before this
ran and cannot be recovered from the database; ``scripts/audit_vendor_duplicates.py``
reports the rows that look truncated so they can be corrected against bank records. The
unique index that enforces one vendor per normalised name is a SEPARATE migration,
applied after existing duplicates have been resolved, because creating it while
duplicates exist would abort the deploy.

Revision ID: c5f1a83b7d24
Revises: b4e8d2c7a915
Create Date: 2026-08-31
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5f1a83b7d24"
down_revision: Union[str, Sequence[str], None] = "b4e8d2c7a915"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_WIDTH = 120


def upgrade() -> None:
    op.alter_column(
        "vendors",
        "name",
        existing_type=sa.VARCHAR(length=22),
        type_=sa.String(length=_NEW_WIDTH),
        existing_nullable=False,
    )

    # Trailing whitespace left by the old truncate-after-normalise behaviour is what
    # defeated the duplicate check: the stored side was compared with SQL trim() while
    # the bind parameter kept its trailing space, so the two never matched. Clean it up
    # so the normalised comparison starts from tidy data.
    op.execute("UPDATE vendors SET name = btrim(name) WHERE name <> btrim(name)")


def downgrade() -> None:
    # Truncate before narrowing, or the column change fails on any longer name.
    op.execute(f"UPDATE vendors SET name = LEFT(name, 22) WHERE LENGTH(name) > 22")
    op.alter_column(
        "vendors",
        "name",
        existing_type=sa.String(length=_NEW_WIDTH),
        type_=sa.VARCHAR(length=22),
        existing_nullable=False,
    )
