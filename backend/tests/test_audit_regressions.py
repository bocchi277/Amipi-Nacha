"""
Regression guards for the security & correctness audit.

Every test here corresponds to a defect that was CONFIRMED present by executable
proof before being fixed. They exist so the same class of bug cannot silently
return. Each test names the concrete risk it protects against.

All tests are marked ``real_auth`` because they assert genuine authentication and
authorization behaviour and must not receive an injected identity.
"""
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AccountType, Payment, User, UserRole, Vendor
from app.services.spreadsheet_parser import _compress_invoices, match_vendor
from tests._helpers import create_admin_user


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def _admin_headers(client: AsyncClient, db_session, tag: str) -> dict[str, str]:
    await create_admin_user(
        db_session, username=f"reg_admin_{tag}", email=f"reg_admin_{tag}@amipi.test",
        password="RegAdminPass123!",
    )
    res = await client.post(
        "/api/v1/auth/login",
        data={"username": f"reg_admin_{tag}", "password": "RegAdminPass123!"},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_bank_data_and_money_endpoints_require_authentication(db_session):
    """
    Endpoints exposing bank details or moving money must reject anonymous callers.

    Risk: `GET /vendors` previously returned every vendor's DECRYPTED routing and
    account number to anyone, and `GET /nacha/{id}/download` served the complete ACH
    file. `POST /nacha/generate` and the payment endpoints accepted anonymous writes.
    """
    protected = [
        ("GET", "/api/v1/vendors"),
        ("GET", "/api/v1/nacha/latest"),
        ("GET", "/api/v1/nacha/next-trace-sequence"),
        ("GET", f"/api/v1/nacha/{uuid.uuid4()}/download"),
        ("GET", f"/api/v1/payments/batches/{uuid.uuid4()}"),
        ("POST", "/api/v1/payments/upload"),
        ("POST", "/api/v1/payments/manual-batch"),
        ("POST", "/api/v1/nacha/generate"),
        ("PUT", f"/api/v1/payments/{uuid.uuid4()}"),
    ]
    async with _client() as client:
        for method, path in protected:
            res = await client.request(method, path)
            assert res.status_code == 401, (
                f"{method} {path} must require authentication, got {res.status_code}"
            )


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_self_registration_cannot_grant_admin_role(db_session):
    """
    Risk: public registration accepted a caller-supplied `role`, so anyone could
    create themselves an administrator account and gain full access.
    """
    async with _client() as client:
        res = await client.post("/api/v1/auth/register", json={
            "email": "escalate_guard@amipi.test", "username": "escalate_guard",
            "password": "Password123!", "role": "admin",
        })
        assert res.status_code == 422, f"role smuggling must be rejected: {res.text}"

        res_ok = await client.post("/api/v1/auth/register", json={
            "email": "plain_guard@amipi.test", "username": "plain_guard",
            "password": "Password123!",
        })
        assert res_ok.status_code == 201
        assert res_ok.json()["role"] == "user"

    row = await db_session.execute(select(User).where(User.username == "plain_guard"))
    assert row.scalar_one().role == UserRole.USER


# ---------------------------------------------------------------------------
# Money-state guards
# ---------------------------------------------------------------------------

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_batch_cannot_be_regenerated_into_a_second_nacha_file(db_session):
    """
    Risk: a batch already written into a NACHA file could be generated again,
    producing a SECOND set of ACH credits for invoices that were already paid.
    """
    async with _client() as client:
        headers = await _admin_headers(client, db_session, "reuse")

        v = Vendor(name="REUSE GUARD VENDOR", routing_number="021000021",
                   account_number="123456789", account_type=AccountType.CHECKING,
                   email="ap@reuse.example")
        db_session.add(v)
        await db_session.commit()
        await db_session.refresh(v)

        res_b = await client.post("/api/v1/payments/manual-batch", headers=headers, json={
            "batch_number": 1, "filename": "reuse.csv",
            "payments": [{"vendor_id": str(v.id), "amount": "100.00",
                          "id_number": "INV-REUSE", "effective_date": "2026-09-01"}],
        })
        assert res_b.status_code == 201
        batch_id = res_b.json()["batch_id"]

        payload = {"batch_ids": [batch_id], "company_name": "AMIPI INC",
                   "company_account": "785957066", "effective_entry_date": "2026-09-01"}

        first = await client.post("/api/v1/nacha/generate", headers=headers, json=payload)
        assert first.status_code == 201, first.text

        second = await client.post("/api/v1/nacha/generate", headers=headers, json=payload)
        assert second.status_code == 409, (
            f"Reusing a PROCESSED batch must be refused, got {second.status_code}"
        )

        # Supplying the same batch twice in one request is the same double-pay risk.
        dup = await client.post("/api/v1/nacha/generate", headers=headers,
                                json={**payload, "batch_ids": [batch_id, batch_id]})
        assert dup.status_code in (400, 409)


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_payment_is_immutable_after_nacha_generation(db_session):
    """
    Risk: a payment's amount could be rewritten after the NACHA file was generated
    and sent to Chase, desynchronising our records from what the bank actually paid.
    """
    async with _client() as client:
        headers = await _admin_headers(client, db_session, "immut")

        v = Vendor(name="IMMUTABLE VENDOR", routing_number="021000021",
                   account_number="987654321", account_type=AccountType.CHECKING,
                   email="ap@immutable.example")
        db_session.add(v)
        await db_session.commit()
        await db_session.refresh(v)

        res_b = await client.post("/api/v1/payments/manual-batch", headers=headers, json={
            "batch_number": 1, "filename": "immut.csv",
            "payments": [{"vendor_id": str(v.id), "amount": "250.00",
                          "id_number": "INV-IMMUT", "effective_date": "2026-09-01"}],
        })
        batch_id = res_b.json()["batch_id"]
        payment_id = res_b.json()["valid_payments"][0]["payment_id"]

        # Editable while still PENDING.
        pre = await client.put(f"/api/v1/payments/{payment_id}", headers=headers,
                               json={"amount": "300.00"})
        assert pre.status_code == 200

        gen = await client.post("/api/v1/nacha/generate", headers=headers, json={
            "batch_ids": [batch_id], "company_name": "AMIPI INC",
            "company_account": "785957066", "effective_entry_date": "2026-09-01"})
        assert gen.status_code == 201, gen.text

        post = await client.put(f"/api/v1/payments/{payment_id}", headers=headers,
                                json={"amount": "999999.00"})
        assert post.status_code == 409, (
            f"Editing a generated payment must be refused, got {post.status_code}"
        )

    row = await db_session.execute(select(Payment).where(Payment.id == uuid.UUID(payment_id)))
    assert row.scalar_one().amount == Decimal("300.00"), "amount must not have changed"


# ---------------------------------------------------------------------------
# Vendor data integrity
# ---------------------------------------------------------------------------

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_bulk_confirm_rejects_invalid_routing_numbers(db_session):
    """
    Risk: `/vendors/bulk-confirm` trusted its client payload and skipped ABA
    check-digit validation, so a vendor with a 3-digit routing number could be
    inserted straight into the database and produce a bank-rejected file.
    """
    async with _client() as client:
        headers = await _admin_headers(client, db_session, "bulk")

        res = await client.post("/api/v1/vendors/bulk-confirm", headers=headers, json={
            "new_vendors": [
                {"name": "BAD ROUTING CO", "routing_number": "123",
                 "account_number": "555", "account_type": "checking"},
                {"name": "BAD CHECKSUM CO", "routing_number": "021000022",
                 "account_number": "556", "account_type": "checking"},
                {"name": "GOOD ROUTING CO", "routing_number": "021000021",
                 "account_number": "557", "account_type": "checking"},
            ],
            "updated_vendors": [], "apply_updates": True, "allow_bank_updates": False,
        })
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["inserted_count"] == 1, f"only the valid vendor may insert: {body}"
        assert len(body["rejected"]) == 2, f"both invalid rows must be reported: {body}"

    names = {v.name for v in (await db_session.execute(select(Vendor))).scalars().all()}
    assert "BAD ROUTING CO" not in names
    assert "BAD CHECKSUM CO" not in names
    assert "GOOD ROUTING CO" in names


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_duplicate_bank_details_are_detected_despite_encryption(db_session):
    """
    Risk: routing/account are stored as Fernet ciphertext with a random IV, so the
    old `WHERE routing_number = :rt` never matched and two vendors could share the
    same bank account under different names without warning.
    """
    async with _client() as client:
        headers = await _admin_headers(client, db_session, "dupbank")

        first = await client.post("/api/v1/vendors", headers=headers, json={
            "name": "ORIGINAL PAYEE", "routing_number": "021000021",
            "account_number": "555000111", "account_type": "checking"})
        assert first.status_code == 201, first.text

        second = await client.post("/api/v1/vendors", headers=headers, json={
            "name": "DIFFERENT PAYEE", "routing_number": "021000021",
            "account_number": "555000111", "account_type": "checking"})
        assert second.status_code == 409, (
            f"identical bank details must conflict, got {second.status_code}"
        )
        assert second.json()["detail"]["same_bank_different_name"] is True


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_deduplicate_merges_by_bank_details_not_only_name(db_session):
    """
    Risk: `/vendors/deduplicate` documented merging by name OR identical bank
    details but only ever grouped by name, so same-account/different-name duplicates
    were never merged.
    """
    async with _client() as client:
        headers = await _admin_headers(client, db_session, "dedup")

        for name, rt, acc in [
            ("ACME SUPPLIES INC", "021000021", "111111111"),
            ("ACME SUPPLIES LLC", "021000021", "111111111"),   # same bank, other name
            ("GAMMA UNIQUE CO", "026013356", "444444444"),     # must be untouched
        ]:
            db_session.add(Vendor(name=name, routing_number=rt, account_number=acc,
                                  account_type=AccountType.CHECKING))
        await db_session.commit()

        res = await client.post("/api/v1/vendors/deduplicate", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["merged_count"] == 1, res.json()

        remaining = (await client.get("/api/v1/vendors", headers=headers)).json()
        names = sorted(v["name"] for v in remaining)
        assert names == ["ACME SUPPLIES INC", "GAMMA UNIQUE CO"], names


# ---------------------------------------------------------------------------
# Parser correctness
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Audit trail integrity
# ---------------------------------------------------------------------------

@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_audit_log_rows_cannot_be_altered_or_deleted(db_session):
    """
    Risk: the README advertised append-only audit logs "via DB triggers", but no
    trigger existed and any UPDATE or DELETE on audit_logs succeeded. For a payments
    audit trail that is the difference between evidence and a suggestion.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, IntegrityError

    await db_session.execute(text(
        "INSERT INTO audit_logs (id, action, entity_type, details) "
        "VALUES ('22222222-2222-2222-2222-222222222222', 'IMMUTABLE_PROBE', "
        "'Test', '{\"v\": 1}'::jsonb)"
    ))
    await db_session.commit()

    for statement, label in [
        ("UPDATE audit_logs SET action = 'TAMPERED' "
         "WHERE id = '22222222-2222-2222-2222-222222222222'", "action change"),
        ("UPDATE audit_logs SET details = '{\"v\": 999}'::jsonb "
         "WHERE id = '22222222-2222-2222-2222-222222222222'", "details change"),
        ("DELETE FROM audit_logs "
         "WHERE id = '22222222-2222-2222-2222-222222222222'", "deletion"),
    ]:
        with pytest.raises((DBAPIError, IntegrityError)) as exc:
            await db_session.execute(text(statement))
            await db_session.commit()
        assert "append-only" in str(exc.value), (
            f"{label} was not blocked by the immutability trigger: {exc.value}"
        )
        await db_session.rollback()

    # The row must still be intact and unmodified.
    row = (await db_session.execute(text(
        "SELECT action, details FROM audit_logs "
        "WHERE id = '22222222-2222-2222-2222-222222222222'"
    ))).first()
    assert row is not None, "audit row was deleted despite the trigger"
    assert row[0] == "IMMUTABLE_PROBE"
    assert row[1] == {"v": 1}


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_audit_entries_record_originating_ip_address(db_session):
    """
    Risk: AuditLog.ip_address existed and the README claimed IP tracking, but no code
    ever populated it, so the audit trail could not answer where a suspicious
    bank-detail change came from.
    """
    from sqlalchemy import select as sa_select

    from app.models import AuditLog

    transport = ASGITransport(app=app, client=("203.0.113.99", 5555))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = await _admin_headers(client, db_session, "ipaudit")
        res = await client.post("/api/v1/vendors", headers=headers, json={
            "name": "IP AUDIT VENDOR", "routing_number": "021000021",
            "account_number": "556677889", "account_type": "checking"})
        assert res.status_code == 201, res.text

    rows = (await db_session.execute(
        sa_select(AuditLog).where(AuditLog.action == "VENDOR_CREATED")
    )).scalars().all()
    assert rows, "creating a vendor must write an audit entry"
    assert rows[0].ip_address == "203.0.113.99", (
        f"expected the caller IP to be recorded, got {rows[0].ip_address!r}"
    )
    # Full bank account numbers must not be duplicated into the audit trail.
    details = rows[0].details or {}
    assert "account_number" not in details
    assert details.get("account_number_last4") == "7889"


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_proxy_forwarded_ip_is_preferred_over_socket_peer(db_session):
    """Behind Render/Netlify the socket peer is the proxy, not the caller."""
    from sqlalchemy import select as sa_select

    from app.models import AuditLog

    transport = ASGITransport(app=app, client=("10.0.0.1", 1))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        headers = await _admin_headers(client, db_session, "fwdip")
        res = await client.post(
            "/api/v1/vendors",
            headers={**headers, "X-Forwarded-For": "198.51.100.23, 10.0.0.1"},
            json={"name": "FWD AUDIT VENDOR", "routing_number": "021000021",
                  "account_number": "334455667", "account_type": "checking"},
        )
        assert res.status_code == 201, res.text

    rows = (await db_session.execute(
        sa_select(AuditLog).where(AuditLog.action == "VENDOR_CREATED")
    )).scalars().all()
    assert rows[0].ip_address == "198.51.100.23", rows[0].ip_address


# ---------------------------------------------------------------------------
# Vendor name matching (misrouting)
# ---------------------------------------------------------------------------

class _FakeVendor:
    """Minimal stand-in; match_vendor only reads .name."""

    def __init__(self, name: str):
        self.name = name

    def __repr__(self):
        return f"<Vendor {self.name!r}>"


def _book(*names: str) -> dict[str, _FakeVendor]:
    return {n.strip().upper(): _FakeVendor(n) for n in names}


def test_similar_vendor_prefix_does_not_misroute_payment():
    """
    Risk (money misrouting): matching accepted the FIRST substring hit with a >=4
    character overlap while iterating vendors in database row order. Both 'KIRA' and
    'KIRAN GEMS USA INC' are real AMIPI payees, so the common QuickBooks spelling
    'KIRAN GEMS USA INC.' (trailing period) resolved to 'KIRA' and would have paid a
    different company. The outcome also flipped with database row order.
    """
    names = ("KIRA", "KIRAN GEMS USA INC")
    variants = [
        "KIRAN GEMS USA INC.",
        "KIRAN GEMS USA, INC",
        "Kiran Gems USA Inc",
        "KIRAN GEMS USA INC\n212-555-0100",
    ]
    for variant in variants:
        for order in (names, tuple(reversed(names))):
            vendor, how, ambiguous = match_vendor(variant, _book(*order))
            assert vendor is not None, f"{variant!r} should match ({how})"
            assert vendor.name == "KIRAN GEMS USA INC", (
                f"{variant!r} misrouted to {vendor.name!r} via {how} "
                f"with book order {order}"
            )
            assert not ambiguous

    # The short name itself must still resolve to itself.
    vendor, how, _ = match_vendor("KIRA", _book(*names))
    assert vendor.name == "KIRA", how


def test_vendor_matching_is_independent_of_database_row_order():
    """The same input must never resolve differently based on vendor row order."""
    variant = "KIRAN GEMS USA INC."
    a, _, _ = match_vendor(variant, _book("KIRA", "KIRAN GEMS USA INC"))
    b, _, _ = match_vendor(variant, _book("KIRAN GEMS USA INC", "KIRA"))
    assert a.name == b.name == "KIRAN GEMS USA INC"


def test_known_quickbooks_spelling_variants_resolve_via_alias_map():
    """
    'BRINKS GLOBLE SERVICES' and 'BRINKS GLOBAL SERVICES' both appear in AMIPI's real
    transmit files; the misspelled QuickBooks form previously matched nothing.
    """
    book = _book("BRINKS GLOBAL SERVICES", "DIAMEX INC", "BELGIUM LGD LLC")
    for incoming, expected in [
        ("BRINKS GLOBLE SERVICES USA INC", "BRINKS GLOBAL SERVICES"),
        ("DIAMEX INC.", "DIAMEX INC"),
        ("BELGIUM LGD LLC.", "BELGIUM LGD LLC"),
    ]:
        vendor, how, ambiguous = match_vendor(incoming, book)
        assert vendor is not None, f"{incoming!r} unmatched ({how})"
        assert vendor.name == expected, f"{incoming!r} -> {vendor.name!r} via {how}"
        assert not ambiguous


def test_genuinely_ambiguous_vendor_name_is_flagged_not_guessed():
    """
    When two vendors are equally good candidates the parser must refuse to choose,
    because guessing means paying the wrong bank account.
    """
    book = _book("ACME TRADING EAST", "ACME TRADING WEST")
    vendor, how, ambiguous = match_vendor("ACME TRADING", book)
    assert vendor is None, f"must not guess, picked {vendor!r} via {how}"
    assert ambiguous, how


def test_unicode_homograph_name_cannot_fuzzy_match_a_latin_vendor():
    """
    Risk (payment spoofing): scoring matched a Cyrillic lookalike to a Latin vendor
    on a shared word alone. '\u0410DMIN VENDOR' (Cyrillic A) scored 0.50 against
    'ADMIN VENDOR' via the common word 'VENDOR'. Non-ASCII names must match exactly.
    """
    book = _book("ADMIN VENDOR", "KIRAN GEMS USA INC")
    vendor, how, ambiguous = match_vendor("\u0410DMIN VENDOR", book)
    assert vendor is None, f"homograph must not match, got {vendor!r} via {how}"
    assert not ambiguous


def test_unrelated_vendor_name_does_not_match_anything():
    book = _book("KIRA", "KIRAN GEMS USA INC", "DIAMEX INC")
    vendor, how, ambiguous = match_vendor("COMPLETELY UNRELATED LLC", book)
    assert vendor is None, f"unexpected match {vendor!r} via {how}"
    assert not ambiguous


def test_invoice_compression_retains_every_invoice_number():
    """
    Risk: multiple invoice numbers were joined with '/' and hard-truncated to 15
    characters, so ['UDI261954','UDI261965','UDI261955'] became 'UDI261954/UDI26'
    and two invoices vanished -- the vendor could not reconcile the payment.

    15 chars is the NACHA Individual ID field width, so compression must keep every
    invoice identifiable within it.
    """
    # Common prefix factored out; each invoice's differing tail is preserved.
    assert _compress_invoices(["UDI261954", "UDI261965", "UDI261955"]) == "UDI261954/65/55"
    assert _compress_invoices(["SI-5872", "SI-5919", "SI-5871"]) == "SI-5872/919/871"

    # Short unrelated invoices still fit verbatim.
    assert _compress_invoices(["101", "202", "303"]) == "101/202/303"

    # Duplicates collapse rather than consuming field width.
    assert _compress_invoices(["INV-9", "INV-9"]) == "INV-9"


def test_invoice_compression_signals_overflow_instead_of_silent_truncation():
    """
    When unrelated long invoice numbers genuinely cannot fit in 15 characters the
    field must make it EXPLICIT that more invoices are covered, instead of looking
    like a single-invoice payment. The full list stays in `invoice_breakdown`.
    """
    got = _compress_invoices(["875886", "2425708", "876153"])
    assert len(got) <= 15
    assert got.startswith("875886")
    assert got.endswith("+2"), f"must signal 2 further invoices, got {got!r}"


def test_invoice_compression_never_exceeds_the_nacha_field_width():
    cases = [
        ["UDI261954", "UDI261965", "UDI261955"],
        ["SI-5872", "SI-5919", "SI-5871"],
        ["875886", "2425708", "876153"],
        ["A" * 20, "B" * 20, "C" * 20],
        ["INVOICE-2026-000001", "INVOICE-2026-000002"],
    ]
    for invoices in cases:
        got = _compress_invoices(invoices)
        assert len(got) <= 15, f"{invoices} -> {got!r} is {len(got)} chars"


def test_single_invoice_is_passed_through_unchanged():
    assert _compress_invoices(["INV-12345"]) == "INV-12345"
    assert _compress_invoices([]) == "EPAY"
