"""
Read-only report of duplicate and suspicious vendor records.

Run this before applying the unique-name index, because creating that index while
duplicates exist aborts the migration and fails the deploy.

    export DATABASE_URL="<connection string>"
    export BANK_DETAILS_ENCRYPTION_KEY="<key>"
    python3 scripts/audit_vendor_duplicates.py

Makes no writes. Prints only the last 4 digits of any account number.

Four categories are reported, in descending order of risk:

1. SAME BANK ACCOUNT, DIFFERENT NAMES -- the highest risk. These are one real
   counterparty entered more than once, and because vendor names are what spreadsheet
   rows match against, an ambiguous name can send a payment to whichever row the
   database returns first.
2. SAME NORMALISED NAME -- 'KIRAN GEMS USA INC.' against 'KIRAN GEMS USA INC'. If the
   bank details differ these are NOT safely mergeable; one of them is wrong.
3. TRUNCATED AT EXACTLY 22 CHARACTERS -- probable victims of the old
   truncate-on-write behaviour. The lost characters are not recoverable from the
   database and must be restored from bank records.
4. NAMES THAT COLLIDE IN THE FIRST 22 CHARACTERS -- these will share a receiver name
   in the output file. Legitimate, but worth knowing, since the file alone will not
   distinguish them.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from _db_preflight import relax_sync_database_url, require_database_url  # noqa: E402

require_database_url()
relax_sync_database_url()

from sqlalchemy import create_engine, text  # noqa: E402

from app.config import settings  # noqa: E402
from app.core.vendor_identity import (  # noqa: E402
    NACHA_RECEIVER_NAME_WIDTH,
    normalize_vendor_name,
)
from app.core.encryption import decrypt_bank_detail  # noqa: E402


def tail(value: str | None) -> str:
    if not value:
        return "(none)"
    return f"...{value[-4:]}" if len(value) > 4 else "*" * len(value)


def main() -> int:
    engine = create_engine(settings.SYNC_DATABASE_URL, future=True)
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, routing_number, account_number, is_active FROM vendors ORDER BY name"
        )).mappings().all()

    vendors = []
    for r in rows:
        vendors.append({
            "id": str(r["id"]),
            "name": r["name"],
            "routing": decrypt_bank_detail(r["routing_number"]) or "",
            "account": decrypt_bank_detail(r["account_number"]) or "",
            "active": r["is_active"],
        })

    print("=" * 74)
    print(f" VENDOR DUPLICATE AUDIT   ({len(vendors)} vendors)")
    print("=" * 74)

    blocking = 0

    # ---- 1. same bank account, different names
    by_bank = defaultdict(list)
    for v in vendors:
        if v["routing"] and v["account"]:
            by_bank[(v["routing"], v["account"])].append(v)
    bank_dupes = {k: g for k, g in by_bank.items() if len(g) > 1}

    print(f"\n1. SAME BANK ACCOUNT, DIFFERENT NAMES : {len(bank_dupes)} group(s)")
    if bank_dupes:
        print("   One counterparty entered more than once. Highest risk: a spreadsheet")
        print("   name that is ambiguous between these can pick either row.")
    for (rt, acc), group in sorted(bank_dupes.items(), key=lambda kv: -len(kv[1])):
        print(f"\n   routing {rt}  account {tail(acc)}")
        for v in group:
            print(f"     - {v['name']!r:<44} active={v['active']}")

    # ---- 2. same normalised name
    by_norm = defaultdict(list)
    for v in vendors:
        by_norm[normalize_vendor_name(v["name"])].append(v)
    name_dupes = {k: g for k, g in by_norm.items() if len(g) > 1 and k}

    print(f"\n2. SAME NORMALISED NAME               : {len(name_dupes)} group(s)")
    if name_dupes:
        blocking += sum(len(g) - 1 for g in name_dupes.values())
        print("   These BLOCK the unique-name index until resolved.")
    for norm, group in sorted(name_dupes.items()):
        banks = {(v["routing"], v["account"]) for v in group}
        verdict = "same bank details - safe to merge" if len(banks) == 1 else \
                  "DIFFERENT bank details - one of these is wrong, do NOT merge blindly"
        print(f"\n   normal form {norm!r}  ({verdict})")
        for v in group:
            print(f"     - {v['name']!r:<44} routing {v['routing'] or '(none)'} account {tail(v['account'])}")

    # ---- 3. probable truncation victims
    truncated = [v for v in vendors if len(v["name"]) == NACHA_RECEIVER_NAME_WIDTH]
    print(f"\n3. EXACTLY {NACHA_RECEIVER_NAME_WIDTH} CHARACTERS LONG           : {len(truncated)} vendor(s)")
    if truncated:
        print("   Probably cut by the old truncate-on-write behaviour. The missing")
        print("   characters cannot be recovered from the database.")
        for v in truncated[:25]:
            print(f"     - {v['name']!r:<44} account {tail(v['account'])}")
        if len(truncated) > 25:
            print(f"     ... and {len(truncated) - 25} more")

    # ---- 4. same first 22 characters
    by_prefix = defaultdict(list)
    for v in vendors:
        by_prefix[v["name"][:NACHA_RECEIVER_NAME_WIDTH].strip().upper()].append(v)
    prefix_clash = {k: g for k, g in by_prefix.items()
                    if len(g) > 1 and normalize_vendor_name(g[0]["name"]) not in name_dupes}

    print(f"\n4. SHARE THE FIRST {NACHA_RECEIVER_NAME_WIDTH} CHARACTERS      : {len(prefix_clash)} group(s)")
    if prefix_clash:
        print("   Distinct vendors that will show the SAME receiver name in the file.")
        print("   Not an error; the account number distinguishes them.")
    for prefix, group in sorted(prefix_clash.items()):
        print(f"\n   file shows {prefix!r}")
        for v in group:
            print(f"     - {v['name']!r:<44} account {tail(v['account'])}")

    print("\n" + "=" * 74)
    if blocking:
        print(f" {blocking} row(s) must be resolved before the unique-name index can be added.")
        print(" Use 'Merge Duplicates' in the Vendor Book, or correct the names, then")
        print(" re-run this audit. Where bank details differ, confirm against bank")
        print(" records first - merging picks one account and discards the other.")
    else:
        print(" No normalised-name duplicates. The unique-name index can be applied.")
    if bank_dupes:
        print(f" NOTE: {len(bank_dupes)} account(s) are shared by differently-named vendors.")
        print(" The index will NOT catch those; review them by hand.")
    print("=" * 74)
    return 1 if blocking else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        print(f"\nCOULD NOT COMPLETE: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}")
        raise SystemExit(3)
