"""
TEMPORARY audit script #2 — verifies vendor master data against the REAL Chase
transmit files, and proves the parser/matching bugs. Deleted after the audit.
"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRANSMIT_GLOB = os.path.join(REPO, "ACH Thru Soft", "ACH Thru Treasury Soft", "*.txt")


def parse_entry_details(path):
    """Extract (name, routing, account, amount_cents, id_ref) from type-6 records."""
    out = []
    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line.startswith("6") or len(line) < 94:
                continue
            rdfi8 = line[3:11]
            check = line[11]
            routing = rdfi8 + check
            account = line[12:29].strip()
            amount = int(line[29:39])
            id_ref = line[39:54].strip()
            name = line[54:76].strip()
            out.append({
                "name": name, "routing": routing, "account": account,
                "amount_cents": amount, "id_ref": id_ref,
                "file": os.path.basename(path),
            })
    return out


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


print("=" * 78)
print("PART 1 — Vendor bank details: code SAMPLE_VENDORS vs REAL transmit files")
print("=" * 78)

real = []
files = sorted(glob.glob(TRANSMIT_GLOB))
for f in files:
    real.extend(parse_entry_details(f))
print(f"\nParsed {len(real)} entry-detail records from {len(files)} transmit files")

# Build authoritative map: normalized name -> set of (routing, account)
real_map = {}
for e in real:
    real_map.setdefault(norm(e["name"]), set()).add((e["routing"], e["account"]))

from app.api.v1.vendors import SAMPLE_VENDORS  # noqa: E402

def mask(acct):
    return acct if len(acct) <= 4 else "*" * (len(acct) - 4) + acct[-4:]

mismatch, match, absent, ambiguous = [], [], [], []

for sv in SAMPLE_VENDORS:
    key = norm(sv["name"])
    # exact, then prefix match (real file names are truncated to 22 chars)
    cands = real_map.get(key)
    if cands is None:
        for rk, rv in real_map.items():
            if rk and (rk.startswith(key[:14]) or key.startswith(rk[:14])):
                cands = rv
                key = rk
                break
    if cands is None:
        absent.append(sv)
        continue
    pairs = {(sv["routing"], sv["account"])}
    if pairs & cands:
        match.append(sv)
    elif len(cands) > 1:
        ambiguous.append((sv, cands))
    else:
        mismatch.append((sv, sorted(cands)[0]))

print(f"\n  MATCH    : {len(match)}")
print(f"  MISMATCH : {len(mismatch)}   <-- WRONG BANK DETAILS")
print(f"  AMBIGUOUS: {len(ambiguous)}")
print(f"  ABSENT   : {len(absent)}  (not in any transmit file - need AMIPI confirmation)")

if mismatch:
    print("\n  --- MISMATCHED (account numbers masked, last 4 shown) ---")
    print(f"  {'VENDOR':<26} {'CODE routing/acct':<26} {'REAL routing/acct':<26}")
    for sv, realpair in sorted(mismatch, key=lambda x: x[0]["name"]):
        codes = f"{sv['routing']}/{mask(sv['account'])}"
        reals = f"{realpair[0]}/{mask(realpair[1])}"
        rflag = "" if sv["routing"] == realpair[0] else " R!"
        print(f"  {sv['name'][:25]:<26} {codes:<26} {reals:<26}{rflag}")

if absent:
    print("\n  --- ABSENT from transmit files (cannot verify) ---")
    for sv in sorted(absent, key=lambda x: x["name"]):
        print(f"    {sv['name']}")

# Do the bad routing numbers still pass ABA checksum? (why validation misses this)
from app.nacha.validation import validate_routing_checksum  # noqa: E402
bad_but_valid = [sv for sv, _ in mismatch if validate_routing_checksum(sv["routing"])]
print(f"\n  {len(bad_but_valid)}/{len(mismatch)} incorrect entries STILL PASS ABA checksum")
print("  -> no existing validation can catch this class of error")

print("\n" + "=" * 78)
print("PART 2 — Vendor name-matching: misrouting risk")
print("=" * 78)

# Reproduce the exact matching logic from _process_qb_vendor_block
def current_match_logic(incoming_name, db_names):
    v_upper = incoming_name.strip().upper()
    vendor_map = {n.strip().upper(): n for n in db_names}
    v_obj = vendor_map.get(v_upper)
    if v_obj:
        return v_obj, "exact"
    v_clean = re.sub(r"[^A-Z0-9]", "", v_upper)
    for db_name, real in vendor_map.items():
        db_clean = re.sub(r"[^A-Z0-9]", "", db_name.strip().upper())
        if (
            (len(db_clean) >= 4 and db_clean in v_clean)
            or (len(v_clean) >= 4 and v_clean in db_clean)
            or (len(db_clean) >= 4 and v_clean.startswith(db_clean))
            or db_name in v_upper
        ):
            return real, "fuzzy-substring"
    return None, "none"

# These two vendor names BOTH appear in the real transmit files
db_names = ["KIRA", "KIRAN GEMS USA INC"]
for incoming in ["KIRAN GEMS USA INC", "KIRA"]:
    got, how = current_match_logic(incoming, db_names)
    ok = got == incoming
    print(f"\n  incoming {incoming!r}")
    print(f"    -> matched {got!r} via {how}")
    print(f"    {'✓ correct' if ok else '✗ MISROUTED - pays the WRONG vendor'}")

# Confirm both names are genuinely in the real files
print("\n  Both names present in real transmit files?")
for n in ["KIRA", "KIRAN GEMS USA INC"]:
    hits = [e for e in real if e["name"].upper() == n]
    accts = {mask(h["account"]) for h in hits}
    print(f"    {n!r}: {len(hits)} record(s), distinct accounts={sorted(accts)}")

print("\n" + "=" * 78)
print("PART 3 — Invoice reference compression (data loss)")
print("=" * 78)

from app.services.spreadsheet_parser import _compress_invoices  # noqa: E402

cases = [
    ["UDI261954", "UDI261965", "UDI261955"],
    ["875886", "2425708", "876153"],
    ["SI-5872", "SI-5919", "SI-5871"],
]
for c in cases:
    got = _compress_invoices(c)
    lost = [x for x in c if x.split("-")[-1][-3:] not in got and x not in got]
    print(f"\n  invoices {c}")
    print(f"    current -> {got!r} (len {len(got)})")
    print(f"    {'✗ LOST: ' + str(lost) if lost else '✓ all retained'}")

# Compare with real ID refs actually used by Chase
print("\n  Real ID refs seen in transmit files (15-char field):")
seen = sorted({e["id_ref"] for e in real if e["id_ref"] and e["id_ref"] != "EPAY"})[:8]
for s in seen:
    print(f"    {s!r}")
