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
from app.services.spreadsheet_parser import _compress_invoices
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
