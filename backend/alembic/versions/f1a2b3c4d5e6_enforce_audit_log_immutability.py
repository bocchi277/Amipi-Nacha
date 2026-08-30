"""enforce audit log immutability with a database trigger

The README advertised audit logs as "append-only via DB triggers", but no trigger
existed: any UPDATE or DELETE against audit_logs succeeded. For a payments audit
trail that is the difference between evidence and a suggestion, so this adds the
enforcement the documentation already claimed.

Note on tests: this is a row-level BEFORE UPDATE OR DELETE trigger. TRUNCATE does not
fire row-level triggers, so the test suite's per-test TRUNCATE still works.

Revision ID: f1a2b3c4d5e6
Revises: e7a89b01c2d3
Create Date: 2026-08-30
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e7a89b01c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION amipi_audit_logs_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION
                    'audit_logs is append-only: DELETE of audit log % is not permitted',
                    OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;

            -- Deleting a user nullifies audit_logs.user_id via ON DELETE SET NULL.
            -- That is legitimate referential maintenance which PRESERVES the audit
            -- row, so permit exactly that one transition and nothing else.
            IF NEW.user_id IS NULL
               AND OLD.user_id IS NOT NULL
               AND NEW.action           IS NOT DISTINCT FROM OLD.action
               AND NEW.entity_type      IS NOT DISTINCT FROM OLD.entity_type
               AND NEW.entity_id        IS NOT DISTINCT FROM OLD.entity_id
               AND NEW.details          IS NOT DISTINCT FROM OLD.details
               AND NEW.ip_address       IS NOT DISTINCT FROM OLD.ip_address
               AND NEW.created_at       IS NOT DISTINCT FROM OLD.created_at
               AND NEW.id               IS NOT DISTINCT FROM OLD.id
            THEN
                RETURN NEW;
            END IF;

            RAISE EXCEPTION
                'audit_logs is append-only: UPDATE of audit log % is not permitted',
                OLD.id
                USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;
        CREATE TRIGGER trg_audit_logs_immutable
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW
            EXECUTE FUNCTION amipi_audit_logs_immutable();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS amipi_audit_logs_immutable();")
