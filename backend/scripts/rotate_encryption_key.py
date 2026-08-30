#!/usr/bin/env python3
"""
Re-encrypt all stored bank details with the current primary encryption key.

Run this after changing ``BANK_DETAILS_ENCRYPTION_KEY``, with the previous key present
in ``BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS`` so existing rows can still be read.

    export BANK_DETAILS_ENCRYPTION_KEY="<new key>"
    export BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS="<old key>"
    python scripts/rotate_encryption_key.py --dry-run     # report only
    python scripts/rotate_encryption_key.py               # apply

Once it reports every row re-encrypted, remove the fallback key.

Safety
------
* ``--dry-run`` changes nothing and reports what would happen.
* A row that cannot be decrypted with any configured key is reported and SKIPPED, never
  overwritten, so a missing fallback key cannot destroy data.
* Values are only written back when the round-trip (decrypt then re-encrypt then
  decrypt) reproduces the original plaintext exactly.
* Bank details are never printed. Only last-4 digits appear in output.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(__file__))

# Validate the connection string before app.db.session builds its engines.
from _db_preflight import require_database_url  # noqa: E402

require_database_url()

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.encryption import (  # noqa: E402
    _FERNET_PREFIX,
    decrypt_bank_detail,
    encrypt_bank_detail,
    get_cipher,
)

# (table, primary key column, [encrypted columns])
TARGETS = [
    ("vendors", "id", ["routing_number", "account_number"]),
    ("vendor_change_requests", "id", ["requested_routing_number", "requested_account_number"]),
]


def mask(value: str) -> str:
    if not value:
        return "(empty)"
    return f"...{value[-4:]}" if len(value) > 4 else "*" * len(value)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    args = parser.parse_args()

    try:
        get_cipher()
    except RuntimeError as exc:
        print(exc)
        return 2

    engine = create_engine(settings.SYNC_DATABASE_URL, future=True)

    total = rewritten = already = skipped = failed = 0

    with Session(engine) as session:
        for table, pk, columns in TARGETS:
            exists = session.execute(text(
                "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
            ), {"t": table}).first()
            if not exists:
                print(f"[skip] table {table} does not exist")
                continue

            col_list = ", ".join(columns)
            rows = session.execute(
                text(f"SELECT {pk}, {col_list} FROM {table}")
            ).mappings().all()
            print(f"\n=== {table}: {len(rows)} row(s) ===")

            for row in rows:
                updates: dict[str, str] = {}
                for col in columns:
                    stored = row[col]
                    total += 1
                    if stored is None or stored == "":
                        continue

                    plaintext = decrypt_bank_detail(stored)

                    # decrypt_bank_detail returns the input unchanged when it cannot
                    # read it. Detect that so we never overwrite an unreadable value.
                    if stored.startswith(_FERNET_PREFIX) and plaintext == stored:
                        print(f"  [FAIL] {table}.{col} {row[pk]}: not decryptable with "
                              f"any configured key - SKIPPED (add its key to "
                              f"BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS)")
                        failed += 1
                        continue

                    recrypted = encrypt_bank_detail(plaintext) if not plaintext.startswith(_FERNET_PREFIX) else plaintext
                    # Force a fresh encryption under the primary key.
                    recrypted = get_cipher().encrypt(plaintext.encode("utf-8")).decode("utf-8")

                    # Verify the round trip before trusting it.
                    if decrypt_bank_detail(recrypted) != plaintext:
                        print(f"  [FAIL] {table}.{col} {row[pk]}: round-trip mismatch - SKIPPED")
                        failed += 1
                        continue

                    # Is it already readable by the PRIMARY key alone?
                    primary_only = get_cipher()._fernets[0]  # noqa: SLF001
                    try:
                        primary_only.decrypt(stored.encode("utf-8"))
                        already += 1
                        continue
                    except Exception:
                        pass

                    updates[col] = recrypted
                    print(f"  [{'would rewrite' if args.dry_run else 'rewrite'}] "
                          f"{table}.{col} {row[pk]} ({mask(plaintext)})")

                if updates and not args.dry_run:
                    assignments = ", ".join(f"{c} = :{c}" for c in updates)
                    session.execute(
                        text(f"UPDATE {table} SET {assignments} WHERE {pk} = :pk"),
                        {**updates, "pk": row[pk]},
                    )
                    rewritten += len(updates)
                elif updates:
                    rewritten += len(updates)

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    print("\n" + "=" * 62)
    print(f"  values inspected            : {total}")
    print(f"  already on the primary key  : {already}")
    print(f"  {'would be re-encrypted     ' if args.dry_run else 're-encrypted              '}: {rewritten}")
    print(f"  undecryptable (skipped)     : {failed}")
    print("=" * 62)

    if failed:
        print("\nSome values could not be decrypted. Add the key they were written "
              "with to BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS and re-run. Nothing was "
              "overwritten for those rows.")
        return 1
    if args.dry_run:
        print("\nDry run: no changes were written. Re-run without --dry-run to apply.")
    else:
        print("\nDone. Once this reports 0 re-encrypted on a second run, remove the "
              "old key from BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
