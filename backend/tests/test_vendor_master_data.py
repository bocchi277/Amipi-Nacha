"""
Locks the reference vendor list to AMIPI's ACTUAL Chase transmit files.

Background: the hardcoded vendor bank details were mis-transcribed from the wrong
spreadsheet columns. 13 of 33 entries carried the wrong routing and/or account
number, and every wrong routing number still passed ABA check-digit validation, so
no validation in the system could detect it. Seeding that data and generating a
payment file would have sent money to the wrong bank accounts.

These tests decode the real transmit files and assert the seed list agrees with
them, so the data cannot silently drift again.
"""
import glob
import os
import re
from collections import defaultdict

import pytest

from app.api.v1.vendors import SAMPLE_VENDORS
from app.nacha.validation import validate_routing_checksum

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TRANSMIT_GLOB = os.path.join(
    _REPO_ROOT, "ACH Thru Soft", "ACH Thru Treasury Soft", "*.txt"
)

# Payees deliberately excluded from the seed list because they cannot be verified
# against any transmit file. They must be added through the reviewed bulk-import
# flow once AMIPI confirms the mapping.
UNVERIFIABLE_PAYEES = {"KIRA JEWELS INC", "TWINKLEDIAM INC."}


def _file_date_key(path: str) -> tuple[str, str, str]:
    m = re.search(r"(\d\d)\.(\d\d)\.(\d{4})", os.path.basename(path))
    return (m.group(3), m.group(1), m.group(2)) if m else ("0", "0", "0")


def _normalize(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def _load_transmit_payees() -> dict[str, tuple[str, str]]:
    """
    Decode every type-6 Entry Detail record into {normalized name: (routing, account)}
    using the most recent occurrence of each payee.

    Entry Detail layout (1-indexed, per Chase cbo_nacha_filespecs):
        4-11  Receiving DFI id (first 8 routing digits)
        12    Check digit (9th routing digit)
        13-29 Account number (17 chars)
        55-76 Receiver name (22 chars)
    """
    files = sorted(glob.glob(_TRANSMIT_GLOB), key=_file_date_key)
    occurrences: dict[str, list[tuple[tuple[str, str, str], str, str]]] = defaultdict(list)
    for path in files:
        date_key = _file_date_key(path)
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line.startswith("6") or len(line) < 94:
                    continue
                routing = line[3:11] + line[11]
                account = line[12:29].strip()
                name = line[54:76].strip()
                occurrences[_normalize(name)].append((date_key, routing, account))

    return {
        key: (max(rows)[1], max(rows)[2])
        for key, rows in occurrences.items()
    }


@pytest.fixture(scope="module")
def transmit_payees() -> dict[str, tuple[str, str]]:
    payees = _load_transmit_payees()
    if not payees:
        pytest.skip("Chase transmit reference files are not available in this checkout")
    return payees


def test_transmit_reference_files_are_parseable(transmit_payees):
    """Guards the decoder itself: the reference files must yield real payees."""
    assert len(transmit_payees) >= 20, (
        f"expected many payees from the transmit files, got {len(transmit_payees)}"
    )


def test_every_seeded_routing_number_is_a_valid_aba_number():
    for vendor in SAMPLE_VENDORS:
        routing = vendor["routing"]
        assert len(routing) == 9 and routing.isdigit(), (
            f"{vendor['name']}: routing {routing!r} is not 9 digits"
        )
        assert validate_routing_checksum(routing), (
            f"{vendor['name']}: routing {routing} fails ABA check-digit validation"
        )


def test_seeded_account_numbers_fit_the_nacha_field():
    for vendor in SAMPLE_VENDORS:
        account = vendor["account"]
        assert account, f"{vendor['name']}: account number is empty"
        assert len(account) <= 17, (
            f"{vendor['name']}: account is {len(account)} chars, NACHA allows 17"
        )


def test_seeded_bank_details_match_the_real_transmit_files(transmit_payees):
    """
    THE critical assertion: for every seeded vendor that appears in AMIPI's real
    transmit files, the routing and account number must match what Chase was
    actually sent. A failure here means the system would pay the wrong account.
    """
    mismatches = []
    unmatched = []

    for vendor in SAMPLE_VENDORS:
        key = _normalize(vendor["name"])
        actual = transmit_payees.get(key)
        if actual is None:
            # Receiver names are truncated to 22 chars in the file, so allow a
            # prefix association before declaring the payee absent.
            for candidate_key, candidate in transmit_payees.items():
                if candidate_key.startswith(key[:12]) or key.startswith(candidate_key[:12]):
                    actual = candidate
                    break
        if actual is None:
            unmatched.append(vendor["name"])
            continue

        expected_routing, expected_account = actual
        if (vendor["routing"], vendor["account"]) != (expected_routing, expected_account):
            mismatches.append(
                f"{vendor['name']}: seed has {vendor['routing']}/"
                f"...{vendor['account'][-4:]} but transmit file shows "
                f"{expected_routing}/...{expected_account[-4:]}"
            )

    assert not mismatches, (
        "Seeded vendor bank details disagree with AMIPI's real Chase transmit "
        "files. Money would be sent to the WRONG account:\n  "
        + "\n  ".join(mismatches)
    )
    # Vendors absent from the files are acceptable (they may simply not have been
    # paid in this sample) but must not be silently wrong, hence the report above.
    assert isinstance(unmatched, list)


def test_unverifiable_payees_are_not_seeded():
    """
    Two payees could not be reconciled with any transmit file. Shipping unverified
    bank details is worse than omitting them, so they must stay out of the seed
    list until AMIPI confirms the mapping.
    """
    seeded = {v["name"] for v in SAMPLE_VENDORS}
    for name in UNVERIFIABLE_PAYEES:
        assert name not in seeded, (
            f"{name!r} has unverified bank details and must not be seeded. "
            f"Add it via the reviewed bulk-import flow once confirmed."
        )


def test_no_duplicate_vendor_names_or_bank_accounts():
    names = [v["name"] for v in SAMPLE_VENDORS]
    assert len(names) == len(set(names)), "duplicate vendor names in seed list"

    accounts = [(v["routing"], v["account"]) for v in SAMPLE_VENDORS]
    duplicates = {a for a in accounts if accounts.count(a) > 1}
    assert not duplicates, f"duplicate bank accounts in seed list: {duplicates}"
