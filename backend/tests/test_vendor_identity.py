"""
Vendor identity and duplicate prevention.

A vendor's name decides which bank account a spreadsheet row is paid into, so duplicate
or ambiguous vendor records are a money-routing hazard, not a tidiness problem.
"""
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.vendor_identity import (
    NACHA_RECEIVER_NAME_WIDTH,
    VENDOR_NAME_MAX_LENGTH,
    clean_vendor_name,
    nacha_receiver_name,
    normalize_vendor_name,
)
from app.main import app
from tests._helpers import create_admin_user

pytestmark = pytest.mark.real_auth


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _admin_headers(client, db_session, username="vid_admin"):
    await create_admin_user(db_session, username, f"{username}@example.com", "VidAdmin123!")
    await db_session.commit()
    r = await client.post("/api/v1/auth/login", data={"username": username, "password": "VidAdmin123!"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------------------------------------------------------------------------
# The normal form
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("KIRAN GEMS USA INC.", "KIRAN GEMS USA INC"),      # the real misrouting pair
    ("B. H. C. DIAMONDS", "BHC DIAMONDS"),
    ("LAB-GROWN DIAMOND USA", "LAB GROWN DIAMOND USA"),
    ("DUPTEST GEMS, INC", "DUPTEST GEMS INC"),
    ("DUPTEST  GEMS  INC", "DUPTEST GEMS INC"),
    ("Artn Design Inc", "ARTN DESIGN INC"),
    ("  SPACED NAME  ", "SPACED NAME"),
])
def test_names_that_are_the_same_vendor_share_a_normal_form(a, b):
    assert normalize_vendor_name(a) == normalize_vendor_name(b)


@pytest.mark.parametrize("a,b", [
    # These differ only after character 22 and previously collapsed into one record.
    ("INTERNATIONAL DIAMOND ALPHA CORP", "INTERNATIONAL DIAMOND BRAVO CORP"),
    ("KIRA JEWELS INC", "KIRAN GEMS USA INC"),
    ("BELGIUM DIA LLC", "BELGIUM NEW YORK LLC"),
])
def test_distinct_vendors_keep_distinct_normal_forms(a, b):
    assert normalize_vendor_name(a) != normalize_vendor_name(b)


def test_truncation_no_longer_reintroduces_trailing_whitespace():
    """
    The old code did `" ".join(name.strip().split())[:22]`, truncating AFTER normalising.
    When character 22 landed on a space the result kept a trailing space, while the SQL
    side compared `trim(name)`. The two never matched and the duplicate was created.
    """
    name = "INTERNATIONAL DIAMOND ALPHA CORP"
    old_behaviour = " ".join(name.strip().split())[:22]
    assert old_behaviour == "INTERNATIONAL DIAMOND "
    assert old_behaviour != old_behaviour.strip(), "this trailing space is the bug"

    # Nothing produced now carries edge whitespace.
    assert clean_vendor_name(name) == name
    assert nacha_receiver_name(name) == nacha_receiver_name(name).rstrip() + (
        " " * (len(nacha_receiver_name(name)) - len(nacha_receiver_name(name).rstrip()))
    )
    assert clean_vendor_name(name) == clean_vendor_name(name).strip()


def test_the_22_character_limit_applies_only_to_the_file():
    long_name = "INTERNATIONAL DIAMOND ALPHA CORPORATION LIMITED"
    assert len(clean_vendor_name(long_name)) == len(long_name), "stored name must not be cut"
    written = nacha_receiver_name(long_name)
    assert len(written) == NACHA_RECEIVER_NAME_WIDTH
    assert long_name.startswith(written.rstrip())


def test_clean_name_respects_the_column_width():
    assert len(clean_vendor_name("A" * 400)) == VENDOR_NAME_MAX_LENGTH


# ---------------------------------------------------------------------------
# The API refuses duplicates
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_punctuation_and_case_variants_are_refused_as_duplicates(db_session):
    """
    Every one of these previously created a SECOND vendor row with different bank
    details. A later spreadsheet naming the vendor then matched more than one record.
    """
    async with _client() as client:
        headers = await _admin_headers(client, db_session, "dupe_admin")

        first = await client.post("/api/v1/vendors", headers=headers, json={
            "name": "DUPTEST GEMS INC", "routing_number": "021000021",
            "account_number": "111111111", "account_type": "checking"})
        assert first.status_code == 201, first.text

        for variant in [
            "DUPTEST GEMS INC",     # identical
            "DUPTEST GEMS INC.",    # trailing period
            "DUPTEST  GEMS  INC",   # doubled spaces
            "DUPTEST GEMS, INC",    # comma
            "duptest gems inc",     # lowercase
            "  DUPTEST GEMS INC  ", # padded
        ]:
            r = await client.post("/api/v1/vendors", headers=headers, json={
                "name": variant, "routing_number": "021000021",
                "account_number": "222222222", "account_type": "checking"})
            assert r.status_code == 409, f"{variant!r} was accepted as a new vendor ({r.status_code})"


@pytest.mark.asyncio
async def test_vendors_differing_after_22_characters_remain_separate(db_session):
    """
    The counterpart risk: over-eager matching would merge two real companies. These
    share a 22-character prefix and must stay distinct, each keeping its own account.
    """
    async with _client() as client:
        headers = await _admin_headers(client, db_session, "long_admin")

        a = await client.post("/api/v1/vendors", headers=headers, json={
            "name": "INTERNATIONAL DIAMOND ALPHA CORP", "routing_number": "021000021",
            "account_number": "666666666", "account_type": "checking"})
        b = await client.post("/api/v1/vendors", headers=headers, json={
            "name": "INTERNATIONAL DIAMOND BRAVO CORP", "routing_number": "021000021",
            "account_number": "777777777", "account_type": "checking"})
        assert a.status_code == 201, a.text
        assert b.status_code == 201, b.text

        rows = (await client.get("/api/v1/vendors", headers=headers)).json()
        stored = sorted(r["name"] for r in rows if r["name"].startswith("INTERNATIONAL DIAMOND"))
        assert stored == [
            "INTERNATIONAL DIAMOND ALPHA CORP",
            "INTERNATIONAL DIAMOND BRAVO CORP",
        ], f"names were truncated or merged: {stored}"

        accounts = {r["account_number"] for r in rows if r["name"].startswith("INTERNATIONAL DIAMOND")}
        assert accounts == {"666666666", "777777777"}


@pytest.mark.asyncio
async def test_a_long_vendor_name_still_produces_a_valid_nacha_record(db_session):
    """The record must stay 94 characters regardless of how long the stored name is."""
    from tests._helpers import valid_effective_date_str

    async with _client() as client:
        headers = await _admin_headers(client, db_session, "nacha_admin")
        await client.post("/api/v1/vendors", headers=headers, json={
            "name": "INTERNATIONAL DIAMOND ALPHA CORPORATION LIMITED",
            "routing_number": "021000021", "account_number": "123456789",
            "account_type": "checking", "email": "ap@example.com"})

        csv = (b"Vendor Name,Amount,Invoice Number\n"
               b"INTERNATIONAL DIAMOND ALPHA CORPORATION LIMITED,123.45,INV-1\n")
        up = await client.post("/api/v1/payments/upload", headers=headers,
                               files={"file": ("l.csv", csv, "text/csv")},
                               data={"batch_number": "1"})
        assert up.status_code == 201, up.text
        assert up.json()["summary"]["valid_rows"] == 1, up.json().get("errors")

        gen = await client.post("/api/v1/nacha/generate", headers=headers, json={
            "batch_ids": [up.json()["batch_id"]], "company_name": "AMIPI INC",
            "company_account": "785957066",
            "effective_entry_date": valid_effective_date_str()})
        assert gen.status_code == 201, gen.text

        lines = [l for l in gen.json()["raw_content"].split("\r\n") if l]
        assert all(len(l) == 94 for l in lines), [len(l) for l in lines]
        entries = [l for l in lines if l.startswith("6")]
        assert len(entries) == 1
        assert len(entries[0][54:76]) == NACHA_RECEIVER_NAME_WIDTH
        assert entries[0][54:76] == "INTERNATIONAL DIAMOND "
