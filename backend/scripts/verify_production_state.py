"""
Read-only production preflight check.

Reports whether the schema migrations landed and whether every stored bank detail is
currently decryptable with the configured key set. Makes no writes, so it is safe to run
against production at any time.

Usage:
    export DATABASE_URL="<Render external connection string>"
    export BANK_DETAILS_ENCRYPTION_KEY="<primary key>"
    export BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS="<old key>"
    python scripts/verify_production_state.py

Prints no secrets and no full account numbers.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

# Validate the connection string BEFORE importing app.db.session, which builds its
# engines at import time and would otherwise fail with a SQLAlchemy stack trace.
from _db_preflight import relax_sync_database_url, report, require_database_url  # noqa: E402

_DB_URL = require_database_url()
relax_sync_database_url()

from sqlalchemy import text  # noqa: E402

from cryptography.fernet import Fernet  # noqa: E402

from app.core.encryption import (  # noqa: E402
    _derive_fernet_key,
    _load_keys,
    decrypt_bank_detail,
)
from app.db.session import AsyncSessionLocal, async_engine  # noqa: E402

EXPECTED_HEAD = "b4e8d2c7a915"


def _looks_encrypted(value: str) -> bool:
    return value.startswith("gAAAAA")


async def main() -> int:
    problems: list[str] = []

    async with AsyncSessionLocal() as db:
        print("=" * 66)
        print(" SCHEMA")
        print("=" * 66)
        report(_DB_URL)

        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        ok = version == EXPECTED_HEAD
        print(f"  alembic version              : {version} {'OK' if ok else f'EXPECTED {EXPECTED_HEAD}'}")
        if not ok:
            problems.append("migrations are not at the expected head")

        seq = (
            await db.execute(
                text("SELECT COUNT(*) FROM pg_class WHERE relkind='S' AND relname='nacha_trace_sequence'")
            )
        ).scalar()
        print(f"  nacha_trace_sequence exists  : {'yes' if seq else 'NO'}")
        if not seq:
            problems.append("trace sequence is missing")
        else:
            row = (
                await db.execute(text("SELECT last_value, is_called FROM nacha_trace_sequence"))
            ).first()
            nxt = row[0] + 1 if row[1] else row[0]
            print(f"  next trace number to issue   : {nxt:07d}")

        width = (
            await db.execute(
                text(
                    "SELECT character_maximum_length FROM information_schema.columns "
                    "WHERE table_name='payments' AND column_name='id_number'"
                )
            )
        ).scalar()
        print(f"  payments.id_number width     : varchar({width}) {'OK' if width == 80 else 'EXPECTED 80'}")
        if width != 80:
            problems.append("payments.id_number was not widened")

        trg = (
            await db.execute(
                text("SELECT COUNT(*) FROM pg_trigger WHERE tgname='trg_audit_logs_immutable'")
            )
        ).scalar()
        print(f"  audit immutability trigger   : {'present' if trg else 'MISSING'}")
        if not trg:
            problems.append("audit immutability trigger is missing")

        print()
        print("=" * 66)
        print(" BANK DETAIL DECRYPTABILITY")
        print("=" * 66)

        rows = (
            await db.execute(
                text("SELECT name, routing_number, account_number FROM vendors ORDER BY name")
            )
        ).all()

        # A MultiFernet does not report which key succeeded, so test the primary key on
        # its own. Anything that only decrypts via a fallback is still on the old key and
        # rotation is not finished. Without this distinction you cannot tell completion
        # from "everything is encrypted with something".
        primary_only = None
        try:
            primary_raw, _ = _load_keys()
            primary_only = Fernet(_derive_fernet_key(primary_raw))
        except Exception:
            pass

        def on_primary_key(value: str) -> bool:
            if primary_only is None or not _looks_encrypted(value):
                return False
            try:
                primary_only.decrypt(value.encode("utf-8"))
                return True
            except Exception:
                return False

        readable = unreadable = 0
        plaintext = 0
        bad_names: list[str] = []
        rotated = pending_rotation = 0

        for name, routing_raw, account_raw in rows:
            values = [v for v in (routing_raw, account_raw) if v]
            if not values:
                continue
            encrypted = [v for v in values if _looks_encrypted(v)]
            if not encrypted:
                plaintext += 1
            elif all(on_primary_key(v) for v in encrypted):
                rotated += 1
            else:
                pending_rotation += 1

            decrypted = [decrypt_bank_detail(v) for v in values]
            if all(d and not _looks_encrypted(d) and d.isdigit() for d in decrypted):
                readable += 1
            else:
                unreadable += 1
                if len(bad_names) < 5:
                    bad_names.append(name)

        print(f"  vendors                      : {len(rows)}")
        print(f"  decryptable                  : {readable}")
        print(f"  NOT decryptable              : {unreadable}")
        if bad_names:
            print(f"    first few                  : {', '.join(bad_names)}")
        print(f"  on the CURRENT primary key   : {rotated}")
        print(f"  still on an OLD fallback key : {pending_rotation}")
        print(f"  stored as plaintext          : {plaintext}")

        if unreadable:
            problems.append(f"{unreadable} vendors cannot be decrypted with the configured keys")
        if plaintext:
            problems.append(f"{plaintext} vendors have unencrypted bank details")

        # ABA check digit is an independent proof that decryption produced real data
        # rather than merely something that is not ciphertext.
        def aba_ok(rt: str) -> bool:
            if len(rt) != 9 or not rt.isdigit():
                return False
            d = [int(c) for c in rt]
            return (3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])) % 10 == 0

        valid_aba = sum(1 for _, r, _ in rows if r and aba_ok(decrypt_bank_detail(r)))
        print(f"  routing numbers passing ABA   : {valid_aba}/{len(rows)}")
        if rows and valid_aba != len(rows):
            problems.append(f"{len(rows) - valid_aba} routing numbers fail the ABA check digit")

        print()
        print("=" * 66)
        if problems:
            print(" RESULT: NOT READY")
            for p in problems:
                print(f"   - {p}")
        else:
            print(" RESULT: READY")
            if pending_rotation:
                print(f"   {pending_rotation} vendors still hold values encrypted under an old key.")
                print("   Run scripts/rotate_encryption_key.py to move them onto the new key.")
            elif os.getenv("BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS"):
                print("   Rotation is COMPLETE - every value is on the current primary key.")
                print("   Now remove BANK_DETAILS_ENCRYPTION_KEY_FALLBACKS from the environment,")
                print("   so a stolen database dump can no longer be read with the old key.")
            else:
                print("   Rotation complete and no fallback keys are configured.")
        print("=" * 66)

    await async_engine.dispose()
    return 1 if problems else 0


def _run() -> int:
    try:
        return asyncio.run(main())
    except Exception as exc:  # connection problems, not schema problems
        name = type(exc).__name__
        print()
        print("=" * 66)
        print(" COULD NOT REACH THE DATABASE")
        print("=" * 66)
        print(f" {name}: {str(exc).splitlines()[0][:200] if str(exc) else '(no detail)'}")
        print()
        print(" The connection string parsed correctly, so this is connectivity, not")
        print(" formatting. Common causes:")
        print("   - Using Render's INTERNAL URL from outside Render. Use the")
        print("     'External Database URL' for a local run.")
        print("   - The free Postgres instance is suspended or still starting.")
        print("   - SSL required. Append '?ssl=require' for asyncpg.")
        print("   - Outbound port 5432 blocked by your network.")
        print("=" * 66)
        return 3


if __name__ == "__main__":
    raise SystemExit(_run())
