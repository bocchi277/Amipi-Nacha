"""
TEMPORARY audit script #3 — rigorously tests the fuzzy vendor-matching path with
realistic QuickBooks name variants (where EXACT match fails). Deleted after audit.
"""
import re

# Exact reproduction of _process_qb_vendor_block matching logic
def current_match_logic(incoming_name, db_names):
    v_upper = incoming_name.strip().upper()
    vendor_map = {n.strip().upper(): n for n in db_names}
    if v_upper in vendor_map:
        return vendor_map[v_upper], "exact"
    v_clean = re.sub(r"[^A-Z0-9]", "", v_upper)
    for db_name, real in vendor_map.items():
        db_clean = re.sub(r"[^A-Z0-9]", "", db_name.strip().upper())
        if (
            (len(db_clean) >= 4 and db_clean in v_clean)
            or (len(v_clean) >= 4 and v_clean in db_clean)
            or (len(db_clean) >= 4 and v_clean.startswith(db_clean))
            or db_name in v_upper
        ):
            return real, "fuzzy-substring(FIRST hit wins)"
    return None, "none"


# Real vendor names taken verbatim from the Chase transmit files
DB = ["KIRA", "KIRAN GEMS USA INC", "BRINKS GLOBAL SERVICES",
      "DIAMEX INC", "SHUBH DIAM", "BELGIUM LGD LLC", "AMERGEM IMPORT"]

# Realistic QuickBooks name variants that will NOT match exactly
CASES = [
    ("KIRAN GEMS USA INC.",        "KIRAN GEMS USA INC"),
    ("KIRAN GEMS USA, INC",        "KIRAN GEMS USA INC"),
    ("Kiran Gems USA Inc-NY",      "KIRAN GEMS USA INC"),
    ("KIRAN GEMS USA INC\n212-555","KIRAN GEMS USA INC"),
    ("BRINKS GLOBLE SERVICES USA INC", "BRINKS GLOBAL SERVICES"),
    ("DIAMEX INC.",                "DIAMEX INC"),
    ("BELGIUM LGD LLC.",           "BELGIUM LGD LLC"),
]

print("=" * 78)
print("Fuzzy vendor matching — realistic QuickBooks name variants")
print("=" * 78)
print(f"\nVendor DB (verbatim from transmit files):\n  {DB}\n")

bad = 0
for incoming, expected in CASES:
    got, how = current_match_logic(incoming, DB)
    ok = (got == expected)
    if not ok:
        bad += 1
    print(f"  incoming : {incoming!r}")
    print(f"  expected : {expected!r}")
    print(f"  got      : {got!r}   [{how}]")
    print(f"  {'✓ correct' if ok else '✗✗ MISROUTED — money goes to the WRONG vendor'}\n")

print("=" * 78)
print(f"RESULT: {bad}/{len(CASES)} realistic name variants MISROUTE")
print("=" * 78)

# Demonstrate WHY: dict insertion order decides the winner, not match quality
print("\nRoot cause demonstration — order dependence:")
for order in (["KIRA", "KIRAN GEMS USA INC"], ["KIRAN GEMS USA INC", "KIRA"]):
    got, how = current_match_logic("KIRAN GEMS USA INC.", order)
    print(f"  DB order {order} -> {got!r}")
print("  Same input, different result purely from DB row order.")

# Show the prototype's scored approach handles these correctly
print("\n" + "=" * 78)
print("Prototype (v7) scored approach on the same cases")
print("=" * 78)

ALIASES = {
    "BRINKS GLOBLE SERVICES USA INC": "BRINKS GLOBAL SERVICES",
    "BRINKS GLOBAL SERVICES USA INC": "BRINKS GLOBAL SERVICES",
    "BRINKS GLOBLE SERVICES": "BRINKS GLOBAL SERVICES",
}

def norm(s):
    return re.sub(r"[^a-z0-9]", " ", str(s).lower()).strip()

def scored_match(incoming, db_names, threshold=0.45):
    incoming = str(incoming).split("\n")[0].strip()
    if incoming.upper() in ALIASES:
        target = ALIASES[incoming.upper()]
        if target in db_names:
            return target, "alias"
    q = " ".join(norm(incoming).split())
    for n in db_names:
        if " ".join(norm(n).split()) == q:
            return n, "normalized-exact"
    words = lambda s: [w for w in s.split() if len(w) > 1]
    qw = words(q)
    best, best_score = None, 0.0
    for n in db_names:
        nw = words(" ".join(norm(n).split()))
        if not nw or not qw:
            continue
        overlap = len(set(qw) & set(nw))
        score = overlap / max(len(qw), len(nw))
        if score > best_score:
            best, best_score = n, score
    return (best, f"scored({best_score:.2f})") if best_score >= threshold else (None, "no-match")

good = 0
for incoming, expected in CASES:
    got, how = scored_match(incoming, DB)
    ok = (got == expected)
    if ok:
        good += 1
    print(f"  {incoming[:34]:<36} -> {str(got):<24} [{how}] {'✓' if ok else '✗'}")

print(f"\nRESULT: {good}/{len(CASES)} correct with scored matching + alias map")
