"""
Phase 6 Tests — Auth (User/Admin Roles) & Vendor Bank Detail Edit Approval Workflow.

Verifies:
1. User registration & JWT authentication.
2. Vendor bank change request creation by standard user (vendor details unchanged).
3. Standard user approval bypass attempt -> HTTP 403 Forbidden.
4. Admin approval applying bank updates & creating an AuditLog entry.
5. Admin rejection keeping vendor bank details unchanged & logging to AuditLog.
"""
import json
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import AuditLog, ChangeRequestStatus, User, UserRole, Vendor, VendorChangeRequest
from tests._helpers import create_admin_user


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_auth_registration_and_login(db_session):
    """Test user registration, role assignment, and JWT login."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Register Standard User
        res_u = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "user1@amipi.com",
                "username": "stduser1",
                "password": "SecretPassword123!",
            },
        )
        assert res_u.status_code == 201
        data_u = res_u.json()
        assert data_u["role"] == "user"

        # Self-registration must ALWAYS produce a standard user, never an admin.
        res_a = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin1@amipi.com",
                "username": "adminuser1",
                "password": "AdminPassword123!",
            },
        )
        assert res_a.status_code == 201
        data_a = res_a.json()
        assert data_a["role"] == "user"

        # Attempting to smuggle an elevated role must be rejected outright rather
        # than silently ignored (privilege-escalation regression guard).
        res_esc = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "escalate@amipi.com",
                "username": "escalate1",
                "password": "AdminPassword123!",
                "role": "admin",
            },
        )
        assert res_esc.status_code == 422, (
            f"Expected 422 for role smuggling, got {res_esc.status_code}: {res_esc.text}"
        )

        # Login Standard User
        res_l1 = await client.post(
            "/api/v1/auth/login",
            data={"username": "stduser1", "password": "SecretPassword123!"},
        )
        assert res_l1.status_code == 200
        token_u = res_l1.json()["access_token"]

        # Fetch profile
        res_me = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token_u}"},
        )
        assert res_me.status_code == 200
        assert res_me.json()["username"] == "stduser1"


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_standard_user_cannot_bypass_approval(db_session):
    """
    Test standard user submitting a vendor bank change request and attempting to approve it.
    - Vendor bank details MUST remain unchanged upon request creation.
    - Standard user approval attempt MUST be rejected with 403 Forbidden.
    """
    v = Vendor(name="SECURE VENDOR CORP", routing_number="021000021", account_number="10000001")
    db_session.add(v)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Register & Login Standard User
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "standard@amipi.com",
                "username": "std_actor",
                "password": "Password123!",
            },
        )
        res_l = await client.post(
            "/api/v1/auth/login",
            data={"username": "std_actor", "password": "Password123!"},
        )
        user_token = res_l.json()["access_token"]
        headers_user = {"Authorization": f"Bearer {user_token}"}

        # Submit change request
        res_req = await client.post(
            f"/api/v1/vendors/{v.id}/change-requests",
            headers=headers_user,
            json={
                "requested_routing_number": "026009768",
                "requested_account_number": "999888777",
                "requested_account_type": "savings",
                "reason": "Bank account migration",
            },
        )
        assert res_req.status_code == 201
        req_data = res_req.json()
        req_id = req_data["id"]
        assert req_data["status"] == "pending"

        # Verify Vendor bank details in DB are UNCHANGED
        res_v1 = await db_session.execute(select(Vendor).where(Vendor.id == v.id))
        v_db1 = res_v1.scalar_one()
        assert v_db1.routing_number == "021000021"
        assert v_db1.account_number == "10000001"

        # Standard user attempts approval -> 403 FORBIDDEN
        res_app = await client.post(
            f"/api/v1/vendors/change-requests/{req_id}/approve",
            headers=headers_user,
        )
        assert res_app.status_code == 403
        assert "Admin privileges required" in res_app.json()["detail"]

        # Verify request remains pending and vendor details remain unchanged
        await db_session.refresh(v_db1)
        assert v_db1.routing_number == "021000021"


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_admin_approval_updates_vendor_and_logs_audit(db_session):
    """
    Test Admin user approving a vendor bank change request:
    - Vendor bank details updated in PostgreSQL.
    - Change request status set to APPROVED.
    - AuditLog record created with admin user ID and bank detail diffs.
    """
    v = Vendor(name="AUDIT TEST VENDOR", routing_number="021000021", account_number="55555555")
    db_session.add(v)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Register User and Admin
        await client.post(
            "/api/v1/auth/register",
            json={"email": "requester@amipi.com", "username": "requester1", "password": "Pass123!"},
        )
        await create_admin_user(db_session, username="admin_boss", email="approver@amipi.com", password="Pass123!")

        # Login Requester & Admin
        res_lr = await client.post("/api/v1/auth/login", data={"username": "requester1", "password": "Pass123!"})
        res_la = await client.post("/api/v1/auth/login", data={"username": "admin_boss", "password": "Pass123!"})
        user_headers = {"Authorization": f"Bearer {res_lr.json()['access_token']}"}
        admin_headers = {"Authorization": f"Bearer {res_la.json()['access_token']}"}

        # Create change request as user
        res_req = await client.post(
            f"/api/v1/vendors/{v.id}/change-requests",
            headers=user_headers,
            json={
                "requested_routing_number": "026009768",
                "requested_account_number": "77778888",
                "requested_account_type": "savings",
                "reason": "Updated ACH details",
            },
        )
        req_id = res_req.json()["id"]

        # Admin approves
        res_app = await client.post(
            f"/api/v1/vendors/change-requests/{req_id}/approve",
            headers=admin_headers,
        )
        assert res_app.status_code == 200
        assert res_app.json()["status"] == "approved"

    # Verify Vendor bank details updated in PostgreSQL
    res_v = await db_session.execute(select(Vendor).where(Vendor.id == v.id))
    v_updated = res_v.scalar_one()
    assert v_updated.routing_number == "026009768"
    assert v_updated.account_number == "77778888"
    assert v_updated.account_type.value == "savings"

    # Verify AuditLog created
    res_audit = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "VENDOR_BANK_UPDATE_APPROVED")
    )
    audit = res_audit.scalar_one()
    assert str(audit.entity_id) == str(v.id)
    assert audit.entity_type == "Vendor"

    details = audit.details
    assert details["old_bank_details"]["account_number"] == "55555555"
    assert details["new_bank_details"]["account_number"] == "77778888"
    assert details["approved_by_admin"] == "admin_boss"


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_admin_rejection_workflow(db_session):
    """
    Test Admin user rejecting a vendor bank change request:
    - Vendor bank details remain unchanged.
    - Request status set to REJECTED.
    - AuditLog record created with action VENDOR_BANK_UPDATE_REJECTED.
    """
    v = Vendor(name="REJECT VENDOR INC", routing_number="021000021", account_number="11112222")
    db_session.add(v)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Register & Login Admin
        await create_admin_user(db_session, username="admin_rej", email="admin_rejector@amipi.com", password="Pass123!")
        res_la = await client.post("/api/v1/auth/login", data={"username": "admin_rej", "password": "Pass123!"})
        admin_headers = {"Authorization": f"Bearer {res_la.json()['access_token']}"}

        # Create change request
        res_req = await client.post(
            f"/api/v1/vendors/{v.id}/change-requests",
            headers=admin_headers,
            json={
                "requested_routing_number": "026009768",
                "requested_account_number": "99999999",
                "requested_account_type": "checking",
                "reason": "Suspicious request",
            },
        )
        req_id = res_req.json()["id"]

        # Reject request
        res_rej = await client.post(
            f"/api/v1/vendors/change-requests/{req_id}/reject",
            headers=admin_headers,
        )
        assert res_rej.status_code == 200
        assert res_rej.json()["status"] == "rejected"

    # Verify Vendor details unchanged
    res_v = await db_session.execute(select(Vendor).where(Vendor.id == v.id))
    v_db = res_v.scalar_one()
    assert v_db.account_number == "11112222"

    # Verify AuditLog for rejection
    res_audit = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "VENDOR_BANK_UPDATE_REJECTED")
    )
    audit = res_audit.scalar_one()
    assert str(audit.entity_id) == str(v.id)
    assert "rejected_by_admin" in audit.details
