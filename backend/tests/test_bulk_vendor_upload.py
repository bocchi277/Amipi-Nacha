"""
Tests for Bulk Vendor Upload, Template Download, and Single/Bulk Vendor Deletion API Endpoints.
"""
import io
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.models import User, UserRole, Vendor
from app.core.security import create_access_token


@pytest.mark.asyncio
async def test_bulk_vendor_upload_csv(db_session):
    user = User(
        username="vendor_admin",
        email="vadmin@test.com",
        password_hash="hashed",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(data={"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    csv_content = (
        "Vendor Name,Routing Number,Account Number,Account Type,Invoice Ref,Email\n"
        "BULK VENDOR ONE,021000021,11111111,checking,REF-1,v1@test.com\n"
        "BULK VENDOR TWO,021000322,22222222,savings,REF-2,v2@test.com\n"
        "INVALID ABA VENDOR,123456789,33333333,checking,REF-3,v3@test.com\n"
    )

    files = {
        "file": ("test_vendors.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.post("/api/v1/vendors/bulk-upload", headers=headers, files=files)

    assert response.status_code == 201
    data = response.json()
    assert data["total_rows"] == 3
    assert data["imported_count"] == 2
    assert len(data["errors"]) == 1
    assert "Invalid 9-digit ABA routing number" in data["errors"][0]["error"]


@pytest.mark.asyncio
async def test_download_vendor_sample_template():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/v1/vendors/sample-template")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "Vendor Name,Routing Number" in response.text


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_single_and_bulk_vendor_deletion(db_session):
    # Setup admin user
    admin = User(
        username="del_admin",
        email="deladmin@test.com",
        password_hash="hashed",
        role=UserRole.ADMIN,
    )
    # Setup standard user (should be denied deletion)
    std_user = User(
        username="std_user",
        email="stduser@test.com",
        password_hash="hashed",
        role=UserRole.USER,
    )
    v1 = Vendor(name="DEL VENDOR ONE", routing_number="021000021", account_number="999111")
    v2 = Vendor(name="DEL VENDOR TWO", routing_number="021000322", account_number="999222")
    db_session.add_all([admin, std_user, v1, v2])
    await db_session.commit()
    await db_session.refresh(v1)
    await db_session.refresh(v2)

    admin_token = create_access_token(data={"sub": str(admin.id)})
    std_token = create_access_token(data={"sub": str(std_user.id)})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Standard user forbidden check
        std_res = await client.delete(
            f"/api/v1/vendors/{v1.id}",
            headers={"Authorization": f"Bearer {std_token}"}
        )
        assert std_res.status_code == 403

        # Single vendor delete by admin
        admin_res = await client.delete(
            f"/api/v1/vendors/{v1.id}",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert admin_res.status_code == 200

        # Bulk vendor delete by admin
        bulk_res = await client.post(
            "/api/v1/vendors/bulk-delete",
            json={"vendor_ids": [str(v2.id)]},
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert bulk_res.status_code == 200
        assert bulk_res.json()["deleted_count"] == 1


@pytest.mark.asyncio
async def test_single_vendor_duplicate_detection_and_update(db_session):
    admin = User(
        username="dup_admin",
        email="dupadmin@test.com",
        password_hash="hashed",
        role=UserRole.ADMIN,
    )
    v_orig = Vendor(
        name="TEST DUP VENDOR",
        routing_number="021000021",
        account_number="123456",
        email="old@test.com",
    )
    db_session.add_all([admin, v_orig])
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(v_orig)

    token = create_access_token(data={"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. Exact duplicate -> 409 Conflict with exact_match=True
        exact_res = await client.post(
            "/api/v1/vendors",
            json={
                "name": "TEST DUP VENDOR",
                "routing_number": "021000021",
                "account_number": "123456",
                "email": "old@test.com",
            },
            headers=headers,
        )
        assert exact_res.status_code == 409
        exact_data = exact_res.json()
        assert exact_data["detail"]["exact_match"] is True

        # 2. Duplicate with modified email -> 409 Conflict with diff details
        diff_res = await client.post(
            "/api/v1/vendors",
            json={
                "name": "TEST DUP VENDOR",
                "routing_number": "021000021",
                "account_number": "123456",
                "email": "new_email@test.com",
            },
            headers=headers,
        )
        assert diff_res.status_code == 409
        diff_data = diff_res.json()
        assert diff_data["detail"]["duplicate"] is True
        assert diff_data["detail"]["exact_match"] is False
        assert "email" in diff_data["detail"]["changes"]

        # 3. Allow update with confirmation -> 201 Created/Updated
        confirm_res = await client.post(
            "/api/v1/vendors",
            json={
                "name": "TEST DUP VENDOR",
                "routing_number": "021000021",
                "account_number": "123456",
                "email": "new_email@test.com",
                "allow_update": True,
            },
            headers=headers,
        )
        assert confirm_res.status_code == 201
        assert confirm_res.json()["email"] == "new_email@test.com"


@pytest.mark.asyncio
async def test_bulk_vendor_preview_and_confirm_workflow(db_session):
    admin = User(
        username="bulk_flow_admin",
        email="bulkflow@test.com",
        password_hash="hashed",
        role=UserRole.ADMIN,
    )
    v_existing = Vendor(
        name="EXISTING BULK VENDOR",
        routing_number="021000021",
        account_number="555555",
        email="old_ap@test.com",
    )
    db_session.add_all([admin, v_existing])
    await db_session.commit()
    await db_session.refresh(admin)

    token = create_access_token(data={"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    csv_content = (
        "Vendor Name,Routing Number,Account Number,Account Type,Invoice Ref,Email\n"
        "EXISTING BULK VENDOR,021000021,555555,checking,REF-UPDATED,new_ap@test.com\n"
        "BRAND NEW VENDOR,021000322,777777,checking,REF-NEW,brandnew@test.com\n"
    )

    files = {
        "file": ("bulk_preview.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Step 1: Bulk Preview (dry run)
        preview_res = await client.post("/api/v1/vendors/bulk-preview", headers=headers, files=files)
        assert preview_res.status_code == 200
        preview_data = preview_res.json()
        assert preview_data["new_count"] == 1
        assert preview_data["update_count"] == 1
        assert preview_data["error_count"] == 0

        # Step 2: Bulk Confirm (apply changes)
        confirm_res = await client.post(
            "/api/v1/vendors/bulk-confirm",
            json={
                "new_vendors": preview_data["new_vendors"],
                "updated_vendors": preview_data["updated_vendors"],
                "apply_updates": True,
                "allow_bank_updates": True,
            },
            headers=headers,
        )
        assert confirm_res.status_code == 200
        confirm_data = confirm_res.json()
        assert confirm_data["inserted_count"] == 1
        assert confirm_data["updated_count"] == 1


@pytest.mark.asyncio
async def test_delete_vendor_with_payments_returns_clean_400_error(db_session):
    """Deleting a vendor succeeds and preserves payment history records (vendor_id becomes NULL)."""
    from datetime import date
    from decimal import Decimal
    from sqlalchemy import select
    from app.models import Payment

    admin = User(username="del_admin", email="del_admin@test.com", password_hash="hashed", role=UserRole.ADMIN)
    v_with_payment = Vendor(name="VENDOR WITH PAYMENT", routing_number="021000021", account_number="111222")
    v_without_payment = Vendor(name="VENDOR WITHOUT PAYMENT", routing_number="021000021", account_number="333444")
    db_session.add_all([admin, v_with_payment, v_without_payment])
    await db_session.commit()
    await db_session.refresh(admin)
    await db_session.refresh(v_with_payment)
    await db_session.refresh(v_without_payment)

    pmt = Payment(
        vendor_id=v_with_payment.id,
        amount=Decimal("12.00"),
        id_number="INV-12",
        effective_date=date(2026, 7, 20),
    )
    db_session.add(pmt)
    await db_session.commit()
    await db_session.refresh(pmt)

    token = create_access_token(data={"sub": str(admin.id)})
    headers = {"Authorization": f"Bearer {token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Single delete of vendor with payments -> 200 OK and safely preserves payment history
        res_single = await client.delete(f"/api/v1/vendors/{v_with_payment.id}", headers=headers)
        assert res_single.status_code == 200
        assert "successfully deleted" in res_single.json()["message"]

        # Verify vendor is deleted from Vendor table
        v_check = (await db_session.execute(select(Vendor).where(Vendor.id == v_with_payment.id))).scalar_one_or_none()
        assert v_check is None

        # Verify payment still exists in DB with vendor_id set to None
        await db_session.refresh(pmt)
        assert pmt.vendor_id is None
        assert pmt.amount == Decimal("12.00")

        # Bulk delete deletes remaining vendor
        res_bulk = await client.post(
            "/api/v1/vendors/bulk-delete",
            json={"vendor_ids": [str(v_without_payment.id)]},
            headers=headers,
        )
        assert res_bulk.status_code == 200
        data_bulk = res_bulk.json()
        assert data_bulk["deleted_count"] == 1
        assert "Successfully deleted 1 vendor(s)" in data_bulk["message"]


