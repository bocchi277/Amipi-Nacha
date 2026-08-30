"""
Add the database-level unique index on normalised vendor name.

Deliberately NOT an Alembic migration. Migrations run automatically during deploy, and
creating a unique index while duplicates still exist aborts the transaction and fails
the whole deploy. Vendor duplicates cannot be resolved automatically -- when two rows
share a name but hold different bank details, picking one is a money decision -- so this
is an explicit step you run once the audit is clean.

    export DATABASE_URL="<connection string>"
    export BANK_DETAILS_ENCRYPTION_KEY="<key>"

    python3 scripts/audit_vendor_duplicates.py        # must report no blocking rows
    python3 scripts/enforce_unique_vendor_names.py --dry-run
    python3 scripts/enforce_unique_vendor_names.py

The application already rejects duplicates by normalised name; this closes the gap for
anything that writes to the table without going through that check.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _db_preflight import relax_sync_database_url, require_database_url  # noqa: E402

require_database_url()
relax_sync_database_url()

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.vendor_identity import SQL_NORMALIZED_NAME  # noqa: E402

INDEX_NAME = "uq_vendors_normalized_name"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="check only, create nothing")
    parser.add_argument("--drop", action="store_true", help="remove the index again")
    args = parser.parse_args()

    engine = create_engine(settings.SYNC_DATABASE_URL, future=True)

    with engine.begin() as conn:
        exists = conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE indexname = :n"
        ), {"n": INDEX_NAME}).first()

        if args.drop:
            if not exists:
                print(f"{INDEX_NAME} is not present; nothing to drop.")
                return 0
            conn.execute(text(f"DROP INDEX {INDEX_NAME}"))
            print(f"Dropped {INDEX_NAME}.")
            return 0

        if exists:
            print(f"{INDEX_NAME} already exists. Nothing to do.")
            return 0

        # Find collisions first, so the failure is a readable list rather than a
        # constraint violation from inside a DDL statement.
        clashes = conn.execute(text(f"""
            SELECT {SQL_NORMALIZED_NAME} AS norm,
                   COUNT(*) AS n,
                   string_agg(name, ' | ' ORDER BY name) AS names
              FROM vendors
             GROUP BY {SQL_NORMALIZED_NAME}
            HAVING COUNT(*) > 1
             ORDER BY COUNT(*) DESC, 1
        """)).mappings().all()

        if clashes:
            print("=" * 70)
            print(" CANNOT CREATE THE UNIQUE INDEX")
            print("=" * 70)
            print(f" {len(clashes)} normalised name(s) are used by more than one vendor:\n")
            for row in clashes:
                print(f"   {row['norm']!r}  ({row['n']} rows)")
                print(f"     {row['names']}")
            print()
            print(" Resolve these first, with 'Merge Duplicates' in the Vendor Book or by")
            print(" correcting the names. Run scripts/audit_vendor_duplicates.py to see")
            print(" whether their bank details agree: where they differ, one record is")
            print(" wrong and merging would silently discard an account number.")
            print("=" * 70)
            return 1

        total = conn.execute(text("SELECT COUNT(*) FROM vendors")).scalar()
        print(f"{total} vendors, no normalised-name collisions.")

        if args.dry_run:
            print(f"Dry run: would create {INDEX_NAME}. Nothing was changed.")
            return 0

        conn.execute(text(
            f"CREATE UNIQUE INDEX {INDEX_NAME} ON vendors ({SQL_NORMALIZED_NAME})"
        ))
        print(f"Created {INDEX_NAME}.")
        print("Duplicate vendor names are now rejected by the database, not only by the "
              "application.")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"\nFAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        raise SystemExit(3)
