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
