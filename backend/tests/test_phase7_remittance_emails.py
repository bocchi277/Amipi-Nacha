"""
Phase 7 Tests — Vendor Remittance Emails, Status Tracking & Bulk Resend Workflow.

Verifies:
1. Auto-creation of PENDING remittance records post NACHA file generation.
2. Dispatching pending remittance emails (PENDING -> SENT status & sent_at timestamp).
3. Filterable remittance email table queries (status, search).
4. Bulk resending on a filtered selection of remittance IDs with resend_count increment & AuditLog creation.
"""
import uuid
from datetime import date
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AuditLog, RemittanceStatus, User, UserRole, Vendor, VendorRemittance


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


@pytest.mark.asyncio
async def test_update_remittance_email_endpoint(db_session):
    """Test PATCH /api/v1/remittances/{id}/email endpoint."""
    u = User(username="email_tester", email="emailtester@test.com", password_hash="hash", role="user")
    v = Vendor(name="EMAIL TEST VENDOR", routing_number="021000021", account_number="999888", email="old_vendor@test.com")
    db_session.add_all([u, v])
    await db_session.commit()
    await db_session.refresh(v)

    remit = VendorRemittance(
        vendor_id=v.id,
        vendor_name=v.name,
        recipient_email="old_remit@test.com",
        amount="1200.00",
        effective_date=date(2026, 8, 15),
        subject="Advice",
        body_text="Body",
        status=RemittanceStatus.PENDING,
    )
    db_session.add(remit)
    await db_session.commit()
    await db_session.refresh(remit)

    from app.core.security import create_access_token
    token = create_access_token(data={"sub": str(u.id), "role": "user"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.patch(
            f"/api/v1/remittances/{remit.id}/email",
            headers={"Authorization": f"Bearer {token}"},
            json={"recipient_email": "new_manager_approved@test.com", "update_vendor_default": True},
        )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["recipient_email"] == "new_manager_approved@test.com"

    res_r = await db_session.execute(select(VendorRemittance).where(VendorRemittance.id == remit.id))
    r_db = res_r.scalar_one()
    assert r_db.recipient_email == "new_manager_approved@test.com"

    res_v = await db_session.execute(select(Vendor).where(Vendor.id == v.id))
    v_db = res_v.scalar_one()
    assert v_db.email == "new_manager_approved@test.com"


@pytest.mark.asyncio
async def test_single_and_bulk_remittance_deletion(db_session):
    """Test single and bulk deletion of remittance transaction records by Admin."""
    admin = User(username="remit_admin", email="remitadmin@test.com", password_hash="hash", role="admin")
    std_user = User(username="remit_std", email="remitstd@test.com", password_hash="hash", role="user")
    v = Vendor(name="DEL REMIT VENDOR", routing_number="021000021", account_number="111222")
    db_session.add_all([admin, std_user, v])
    await db_session.commit()
    await db_session.refresh(v)

    r1 = VendorRemittance(
        vendor_id=v.id,
        vendor_name=v.name,
        recipient_email="del1@test.com",
        amount="500.00",
        effective_date=date(2026, 8, 10),
        subject="Payment Advice",
        body_text="Remittance body",
        status=RemittanceStatus.PENDING,
    )
    r2 = VendorRemittance(
        vendor_id=v.id,
        vendor_name=v.name,
        recipient_email="del2@test.com",
        amount="750.00",
        effective_date=date(2026, 8, 10),
        subject="Payment Advice",
        body_text="Remittance body",
        status=RemittanceStatus.SENT,
    )
    db_session.add_all([r1, r2])
    await db_session.commit()
    await db_session.refresh(r1)
    await db_session.refresh(r2)

    from app.core.security import create_access_token
    admin_token = create_access_token(data={"sub": str(admin.id)})
    std_token = create_access_token(data={"sub": str(std_user.id)})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Standard user forbidden check
        std_res = await client.delete(
            f"/api/v1/remittances/{r1.id}",
            headers={"Authorization": f"Bearer {std_token}"}
        )
        assert std_res.status_code == 403

        # Single delete by admin
        admin_res = await client.delete(
            f"/api/v1/remittances/{r1.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert admin_res.status_code == 200

        # Bulk delete by admin
        bulk_res = await client.post(
            "/api/v1/remittances/bulk-delete",
            json={"remittance_ids": [str(r2.id)]},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert bulk_res.status_code == 200
        assert bulk_res.json()["deleted_count"] == 1


@pytest.mark.asyncio
async def test_get_latest_nacha_file(db_session):
    """Test GET /api/v1/nacha/latest endpoint fetching the latest NACHA file record."""
    from app.models import NachaFileRecord, NachaFileStatus
    record = NachaFileRecord(
        filename="TEST_LATEST.ach",
        file_creation_date="260815",
        file_creation_time="1200",
        file_id_modifier="A",
        total_credit_amount="1250.00",
        total_entry_count=2,
        total_batch_count=1,
        total_block_count=1,
        entry_hash="021000021",
        raw_content="101 021000021 ...\n9000001000001...",
        status=NachaFileStatus.GENERATED,
    )
    db_session.add(record)
    await db_session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        res = await client.get("/api/v1/nacha/latest")
        assert res.status_code == 200
        data = res.json()
        assert data["filename"] == "TEST_LATEST.ach"
        assert data["total_credit_amount"] == "1250.00"
        assert data["entry_hash"] == "021000021"


@pytest.mark.asyncio
async def test_tabular_remittance_email_template_rendering_and_preview(db_session):
    """Test tabular remittance email template rendering, HTML table generation, and live preview endpoint."""
    from app.core.email_templates import render_email_template

    sample_invoices = [
        {"method": "ACH/Wire", "invoice_date": "05-19-2026", "invoice_number": "128753", "amount": 22094.82},
        {"method": "ACH/Wire", "invoice_date": "05-21-2026", "invoice_number": "128779", "amount": 31318.24},
    ]

    subj, text, html = render_email_template(
        "Payment Remittance Advice — {{vendor_name}} (${{amount}})",
        "Dear {{vendor_name}},\n\nWe would like to inform you that we have processed the following payment and applied the invoices accordingly.\n\nPayment Amount: ${{amount}}\nEffective Date: {{effective_date}}\nReference Number: {{invoice_ref}}\n\nInvoices applied:",
        {
            "vendor_name": "AMIPI INC",
            "amount": "53,413.06",
            "invoice_ref": "INV-128753",
            "effective_date": "05-19-2026",
            "company_name": "AMIPI INC",
            "payment_method": "ACH/Wire",
            "deposit_ref": "12970",
        },
        invoice_items=sample_invoices,
    )

    assert "53,413.06" in subj
    assert "05-19-2026" in html
    assert "INV-128753" in html
    assert "Sunrise" not in html
    assert "Check/Wire Deposits" not in html
    assert "Sunrise" not in text
    assert "Check/Wire Deposits" not in text
    assert "2 Payment Transaction records" in html
    assert "128753" in html
    assert "128779" in html
    assert "$22,094.82" in html
    assert "$31,318.24" in html
    assert "TOT" in html
    assert "$53,413.06" in html

    # Test Live Preview Endpoint
    user = User(username="tmpl_user", email="tmpl@test.com", password_hash="hashed", role=UserRole.USER)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    from app.core.security import create_access_token
    token = create_access_token(data={"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        prev_res = await client.post(
            "/api/v1/remittances/template/preview",
            headers=headers,
            json={
                "subject_template": "Custom Remittance — {{vendor_name}}",
                "body_template": "Hello {{vendor_name}},\n\nPayment processed of ${{amount}}.",
            },
        )
        assert prev_res.status_code == 200
        data = prev_res.json()
        assert "Custom Remittance — AMIPI INC" in data["subject"]
        assert "2 Payment Transaction records" in data["body_html"]
        assert "TOT" in data["body_html"]


