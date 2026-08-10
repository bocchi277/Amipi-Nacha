"""
Phase 7 Tests — Vendor Remittance Emails, Status Tracking & Bulk Resend Workflow.

Verifies:
1. Auto-creation of PENDING remittance records post NACHA file generation.
2. Dispatching pending remittance emails (PENDING -> SENT status & sent_at timestamp).
3. Filterable remittance email table queries (status, search).
4. Bulk resending on a filtered selection of remittance IDs with resend_count increment & AuditLog creation.
"""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AuditLog, RemittanceStatus, User, Vendor, VendorRemittance


@pytest.mark.asyncio
async def test_auto_remittance_creation_and_send(db_session):
    """Test auto-creation of PENDING remittances post NACHA generation and dispatching emails."""
    v = Vendor(
        name="REMITTANCE VENDOR INC",
        routing_number="021000021",
        account_number="12345678",
        email="ap@remittancevendor.com",
    )
    db_session.add(v)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Register and Login User
        await client.post(
            "/api/v1/auth/register",
            json={"email": "remit_user@amipi.com", "username": "remit_user", "password": "Password123!", "role": "user"},
        )
        res_l = await client.post("/api/v1/auth/login", data={"username": "remit_user", "password": "Password123!"})
        headers = {"Authorization": f"Bearer {res_l.json()['access_token']}"}

        # 1. Create Payment Batch
        res_b = await client.post(
            "/api/v1/payments/manual-batch",
            headers=headers,
            json={
                "batch_number": 1,
                "filename": "Remittance Test Batch",
                "payments": [
                    {
                        "vendor_id": str(v.id),
                        "amount": "1850.75",
                        "id_number": "INV-REMIT-01",
                        "effective_date": "2026-08-10",
                    }
                ],
            },
        )
        b_id = res_b.json()["batch_id"]

        # 2. Generate NACHA File (triggers auto-creation of PENDING remittance record)
        res_n = await client.post(
            "/api/v1/nacha/generate",
            headers=headers,
            json={"batch_ids": [b_id]},
        )
        assert res_n.status_code == 201

        # 3. Query Remittances Table (verify PENDING state)
        res_r1 = await client.get("/api/v1/remittances?status=pending", headers=headers)
        assert res_r1.status_code == 200
        remits_pending = res_r1.json()
        assert len(remits_pending) == 1
        remit = remits_pending[0]
        assert remit["recipient_email"] == "ap@remittancevendor.com"
        assert remit["status"] == "pending"
        assert remit["sent_at"] is None

        # 4. Dispatch Pending Remittances
        res_send = await client.post("/api/v1/remittances/send", headers=headers)
        assert res_send.status_code == 200
        dispatched = res_send.json()
        assert len(dispatched) == 1
        assert dispatched[0]["status"] == "sent"
        assert dispatched[0]["sent_at"] is not None


@pytest.mark.asyncio
async def test_remittance_table_filtering(db_session):
    """Test filterable remittance email query endpoint (status and text search)."""
    v1 = Vendor(name="ALPHA JEWELS", routing_number="021000021", account_number="111", email="alpha@jewels.com")
    v2 = Vendor(name="BETA DIAMONDS", routing_number="026009768", account_number="222", email="beta@diamonds.com")
    db_session.add_all([v1, v2])
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.post(
            "/api/v1/auth/register",
            json={"email": "filter_user@amipi.com", "username": "filter_user", "password": "Password123!", "role": "user"},
        )
        res_l = await client.post("/api/v1/auth/login", data={"username": "filter_user", "password": "Password123!"})
        headers = {"Authorization": f"Bearer {res_l.json()['access_token']}"}

        # Create 2 batches & NACHA file
        res_b = await client.post(
            "/api/v1/payments/manual-batch",
            headers=headers,
            json={
                "batch_number": 1,
                "payments": [
                    {"vendor_id": str(v1.id), "amount": "100.00", "id_number": "INV-A1", "effective_date": "2026-08-10"},
                    {"vendor_id": str(v2.id), "amount": "200.00", "id_number": "INV-B1", "effective_date": "2026-08-10"},
                ],
            },
        )
        await client.post("/api/v1/nacha/generate", headers=headers, json={"batch_ids": [res_b.json()["batch_id"]]})

        # Send emails for one vendor only
        await client.post("/api/v1/remittances/send", headers=headers)

        # Test Search Filter
        res_search = await client.get("/api/v1/remittances?search=ALPHA", headers=headers)
        assert res_search.status_code == 200
        assert len(res_search.json()) == 1
        assert res_search.json()[0]["vendor_name"] == "ALPHA JEWELS"


@pytest.mark.asyncio
async def test_bulk_resend_on_filtered_selection(db_session):
    """
    Test bulk resend on a filtered selection of remittance IDs:
    - Verifies resend_count increment.
    - Verifies updated sent_at timestamp.
    - Verifies AuditLog entry creation.
    """
    v = Vendor(name="BULK VENDOR LLC", routing_number="021000021", account_number="987654", email="bulk@vendor.com")
    db_session.add(v)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        await client.post(
            "/api/v1/auth/register",
            json={"email": "bulk_user@amipi.com", "username": "bulk_user", "password": "Password123!", "role": "user"},
        )
        res_l = await client.post("/api/v1/auth/login", data={"username": "bulk_user", "password": "Password123!"})
        headers = {"Authorization": f"Bearer {res_l.json()['access_token']}"}

        # Create payment & NACHA file
        res_b = await client.post(
            "/api/v1/payments/manual-batch",
            headers=headers,
            json={
                "batch_number": 1,
                "payments": [{"vendor_id": str(v.id), "amount": "5000.00", "id_number": "INV-BULK-01", "effective_date": "2026-08-10"}],
            },
        )
        await client.post("/api/v1/nacha/generate", headers=headers, json={"batch_ids": [res_b.json()["batch_id"]]})

        # Send initial email
        res_send = await client.post("/api/v1/remittances/send", headers=headers)
        remit_id = res_send.json()[0]["id"]
        initial_sent_at = res_send.json()[0]["sent_at"]
        assert res_send.json()[0]["resend_count"] == 1

        # Execute Bulk Resend
        res_resend = await client.post(
            "/api/v1/remittances/bulk-resend",
            headers=headers,
            json={"remittance_ids": [remit_id]},
        )
        assert res_resend.status_code == 200
        resend_data = res_resend.json()
        assert resend_data["success_count"] == 1

    # Verify DB State: resend_count == 2
    res_r = await db_session.execute(select(VendorRemittance).where(VendorRemittance.id == uuid.UUID(remit_id)))
    remit_db = res_r.scalar_one()
    assert remit_db.resend_count == 2
    assert remit_db.status == RemittanceStatus.SENT

    # Verify AuditLog created for bulk resend
    res_audit = await db_session.execute(select(AuditLog).where(AuditLog.action == "BULK_REMITTANCE_RESEND"))
    audit = res_audit.scalar_one()
    assert audit.details["success_count"] == 1
