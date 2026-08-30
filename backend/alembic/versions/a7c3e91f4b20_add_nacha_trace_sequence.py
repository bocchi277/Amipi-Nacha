"""add database sequence for NACHA trace numbers

The starting trace sequence was derived by loading the most recent NachaFileRecord,
splitting ``raw_content`` into lines, finding the last type-6 record and parsing
characters 88-94. That approach had two failure modes:

* **Collision under concurrency.** Two generations running at once both read the same
  "last" file and produced identical trace numbers in two different files.
* **Silent reset to 1.** If no prior file existed, ``raw_content`` was empty, or the
  slice failed to parse, the function returned 1 and re-issued trace numbers the bank
  had already seen. Trace numbers are the handle used to trace and dispute an entry,
  so duplicates across live files are a reconciliation problem.

A PostgreSQL sequence makes allocation atomic and monotonic. It is seeded above the
highest trace number already present in the database so existing deployments continue
where they left off rather than restarting.

Revision ID: a7c3e91f4b20
Revises: f1a2b3c4d5e6
Create Date: 2026-08-30
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a7c3e91f4b20"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 7-digit field (positions 88-94 of the Entry Detail record).
_MAX_TRACE = 9_999_999


def upgrade() -> None:
    op.execute("CREATE SEQUENCE IF NOT EXISTS nacha_trace_sequence AS BIGINT START WITH 1 MINVALUE 1")

    # Seed past any trace number already issued. payments.trace_number holds the full
    # 15-character trace (8-digit ODFI + 7-digit sequence), so take the last 7 digits.
    op.execute(
        f"""
        DO $$
        DECLARE
            highest BIGINT;
        BEGIN
            SELECT COALESCE(MAX(NULLIF(RIGHT(trace_number, 7), '')::BIGINT), 0)
              INTO highest
              FROM payments
             WHERE trace_number IS NOT NULL
               AND trace_number ~ '[0-9]{{7}}$';

            IF highest IS NULL OR highest < 1 THEN
                highest := 0;
            END IF;

            IF highest >= {_MAX_TRACE} THEN
                RAISE WARNING 'Existing trace numbers have reached the 7-digit ceiling; '
                              'sequence will wrap and must be reviewed.';
            END IF;

            PERFORM setval('nacha_trace_sequence', highest + 1, false);
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS nacha_trace_sequence")
