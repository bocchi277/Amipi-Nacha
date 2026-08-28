"""
Comprehensive Test Suite for Vendor Deduplication & Merge Engine:
1. POST /api/v1/vendors/deduplicate - Safely merges duplicate vendor records and re-links payments, remittances, and change requests.
2. POST /api/v1/vendors - Normalized name and bank detail collision detection.
3. POST /api/v1/vendors/bulk-confirm - Duplicate shield against re-uploading and intra-batch duplicates.
"""
import uuid
from decimal import Decimal
from datetime import date
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import (
    AccountType,
    AuditLog,
    ChangeRequestStatus,
    Payment,
    User,
    UserRole,
    Vendor,
    VendorChangeRequest,
    VendorRemittance,
)
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_vendor_deduplicate_merges_records_and_relinks_history(db_session):
    """
    Verify that when duplicate vendor records exist (e.g. 'Amanda Forzono' and 'AMANDA FORZONO '),
    the /deduplicate endpoint merges them into one primary record, re-links all payments, remittances,
    and change requests, and deletes the duplicate record.
    """
    run_id = uuid.uuid4().hex[:4]
    base_name = f"Amanda F {run_id}"

    # Create admin user
    admin_user = User(
        username=f"admin_{run_id}",
        email=f"admin_{run_id}@amipi.com",
        password_hash="fakehash123",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin_user)
    await db_session.commit()
    await db_session.refresh(admin_user)

    token = create_access_token(data={"sub": str(admin_user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    # Create Primary Vendor (created first, has email)
    v_primary = Vendor(
        name=base_name,
        routing_number="021000021",
        account_number="1122334455",
        account_type=AccountType.CHECKING,
        default_id_number="4455",
        email=f"amanda_{run_id}@amipi.com",
        is_active=True,
    )
    # Create Duplicate Vendor (created second, with extra spaces / upper case, no email)
    v_dup = Vendor(
        name=f" {base_name.upper()} ",
        routing_number="021000021",
        account_number="9988776655",
        account_type=AccountType.CHECKING,
        default_id_number="6655",
        email=None,
        is_active=True,
    )
    db_session.add_all([v_primary, v_dup])
    await db_session.flush()

    # Attach Payment to duplicate vendor
    payment_dup = Payment(
        vendor_id=v_dup.id,
        amount=Decimal("1500.00"),
        id_number="INV-DUP-01",
        effective_date=date(2026, 8, 30),
    )
    # Attach Remittance to duplicate vendor
    remittance_dup = VendorRemittance(
        vendor_id=v_dup.id,
        vendor_name=v_dup.name,
        recipient_email="old_amanda@vendor.com",
        subject="Remittance Advice",
        body_text="Your payment has been processed.",
        amount=Decimal("1500.00"),
        effective_date=date(2026, 8, 30),
        status="sent",
    )
    # Attach Change Request to duplicate vendor
    change_req_dup = VendorChangeRequest(
        vendor_id=v_dup.id,
        requested_routing_number="026013356",
        requested_account_number="5544332211",
        requested_account_type=AccountType.SAVINGS,
        status=ChangeRequestStatus.PENDING,
    )

    db_session.add_all([payment_dup, remittance_dup, change_req_dup])
    await db_session.commit()

    # Call /vendors/deduplicate endpoint
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.post("/api/v1/vendors/deduplicate", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["merged_count"] >= 1
    assert str(v_dup.id) in data["purged_duplicate_ids"]

    # Verify Database state
    res_v = await db_session.execute(select(Vendor).where(Vendor.id == v_primary.id))
    primary_after = res_v.scalar_one_or_none()
    assert primary_after is not None

    res_dup = await db_session.execute(select(Vendor).where(Vendor.id == v_dup.id))
    dup_after = res_dup.scalar_one_or_none()
    assert dup_after is None, "Duplicate vendor record must be purged from database"

    # Verify Payment was safely re-linked to primary vendor
    res_p_check = await db_session.execute(select(Payment).where(Payment.id == payment_dup.id))
    p_fresh = res_p_check.scalar_one()
    assert p_fresh.vendor_id == v_primary.id

    # Verify Remittance was safely re-linked to primary vendor
    res_r_check = await db_session.execute(select(VendorRemittance).where(VendorRemittance.id == remittance_dup.id))
    r_fresh = res_r_check.scalar_one()
    assert r_fresh.vendor_id == v_primary.id
    assert r_fresh.vendor_name == v_primary.name

    # Verify Change Request was safely re-linked
    res_cr_check = await db_session.execute(select(VendorChangeRequest).where(VendorChangeRequest.id == change_req_dup.id))
    cr_fresh = res_cr_check.scalar_one()
    assert cr_fresh.vendor_id == v_primary.id

    # Verify AuditLog was recorded
    res_audit = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "DEDUPLICATE_VENDORS")
    )
    audit = res_audit.scalars().first()
    assert audit is not None
    assert audit.user_id == admin_user.id


@pytest.mark.asyncio
async def test_bulk_confirm_duplicate_shield(db_session):
    """
    Verify that POST /api/v1/vendors/bulk-confirm does NOT insert duplicate vendors
    when the vendor already exists in the database or appears multiple times in new_vendors payload.
    """
    run_id = uuid.uuid4().hex[:4]
    admin_user = User(
        username=f"admin_b_{run_id}",
        email=f"admin_b_{run_id}@amipi.com",
        password_hash="fakehash123",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin_user)
    await db_session.commit()
    await db_session.refresh(admin_user)

    token = create_access_token(data={"sub": str(admin_user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    vendor_name = f"ShieldV {run_id}"
    brand_new_name = f"BrandNew {run_id}"

    # Initial Vendor in DB
    existing_v = Vendor(
        name=vendor_name,
        routing_number="021000021",
        account_number="123456789",
        account_type=AccountType.CHECKING,
        default_id_number="6789",
        email=f"existing_{run_id}@vendor.com",
        is_active=True,
    )
    db_session.add(existing_v)
    await db_session.commit()

    # Bulk confirm payload containing existing vendor + intra-batch duplicate
    payload = {
        "new_vendors": [
            {
                "name": f"  {vendor_name.upper()}  ",
                "routing_number": "021000021",
                "account_number": "123456789",
                "account_type": "checking",
                "email": f"updated_{run_id}@vendor.com",
                "default_id_number": "9999",
            },
            {
                "name": brand_new_name,
                "routing_number": "026013356",
                "account_number": "987654321",
                "account_type": "checking",
                "email": f"new_{run_id}@vendor.com",
                "default_id_number": "4321",
            },
            {
                "name": brand_new_name,  # Duplicate in same batch
                "routing_number": "026013356",
                "account_number": "987654321",
                "account_type": "checking",
                "email": f"new_{run_id}@vendor.com",
                "default_id_number": "4321",
            },
        ],
        "updated_vendors": [],
        "apply_updates": True,
        "allow_bank_updates": False,
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp = await client.post("/api/v1/vendors/bulk-confirm", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["inserted_count"] == 1  # Only 1 brand new vendor inserted!
    assert data["updated_count"] == 1   # Existing vendor updated with new email/ref without duplicate row

    # Verify DB has only 2 vendors total for this test (existing + new), not 4!
    res_all = await db_session.execute(
        select(Vendor).where(
            Vendor.name.in_([vendor_name, brand_new_name])
        )
    )
    vendors = res_all.scalars().all()
    assert len(vendors) == 2


@pytest.mark.asyncio
async def test_create_vendor_normalized_duplicate_rejection(db_session):
    """
    Verify that single vendor creation (POST /api/v1/vendors) rejects duplicate names
    even with case or surrounding whitespace variations.
    """
    run_id = uuid.uuid4().hex[:4]
    admin_user = User(
        username=f"admin_c_{run_id}",
        email=f"admin_c_{run_id}@amipi.com",
        password_hash="fakehash123",
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(admin_user)
    await db_session.commit()
    await db_session.refresh(admin_user)

    token = create_access_token(data={"sub": str(admin_user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    vendor_name = f"ExactTest {run_id}"

    # Create first vendor
    create_payload_1 = {
        "name": vendor_name,
        "routing_number": "021000021",
        "account_number": "111222333",
        "account_type": "checking",
        "email": f"test_{run_id}@vendor.com",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        resp1 = await client.post("/api/v1/vendors", json=create_payload_1, headers=headers)
        assert resp1.status_code == 201

        # Attempt to create second vendor with extra spacing & uppercase
        create_payload_2 = {
            "name": f"  {vendor_name.upper()}  ",
            "routing_number": "026013356",
            "account_number": "444555666",
            "account_type": "savings",
            "email": f"test2_{run_id}@vendor.com",
        }
        resp2 = await client.post("/api/v1/vendors", json=create_payload_2, headers=headers)
    assert resp2.status_code == 409
    data = resp2.json()
    assert data["detail"]["duplicate"] is True
