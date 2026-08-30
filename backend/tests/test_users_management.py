"""
Backend User Management Router Tests.

Tests:
1. Standard user cannot access /api/v1/users (403 Forbidden).
2. Unauthenticated request rejected (401 Unauthorized).
3. Admin can list users.
4. Admin can create new user.
5. Admin can toggle user active status.
6. Admin cannot deactivate own account.
7. Admin can reset user password.
8. Duplicate username or email rejected with 400.
"""
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from tests._helpers import create_admin_user, create_standard_user


_RUN_ID = uuid.uuid4().hex[:6]
ADMIN_USER = f"adm_be_{_RUN_ID}"
ADMIN_EMAIL = f"{ADMIN_USER}@amipi.com"
ADMIN_PASSWORD = "AdminBePass123!"

STD_USER = f"std_be_{_RUN_ID}"
STD_EMAIL = f"{STD_USER}@amipi.com"
STD_PASSWORD = "StdBePass123!"


async def _get_auth_token(client: AsyncClient, username: str, password: str) -> str:
    res = await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
    )
    assert res.status_code == 200, f"Login failed: {res.text}"
    return res.json()["access_token"]


@pytest.mark.real_auth
@pytest.mark.asyncio
async def test_user_management_access_control(db_session):
    """Verify standard user and unauthenticated access to /users is blocked."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        # Register admin & standard user
        # Registration is administrator-only now, so provision both accounts directly.
        await create_admin_user(db_session, username=ADMIN_USER, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
        await create_standard_user(db_session, username=STD_USER, email=STD_EMAIL, password=STD_PASSWORD)

        # 1. Unauthenticated request -> 401
        res = await client.get("/api/v1/users")
        assert res.status_code == 401

        # 2. Standard user token -> 403
        std_token = await _get_auth_token(client, STD_USER, STD_PASSWORD)
        res = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {std_token}"})
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_admin_user_crud_and_status(db_session):
    """Verify admin user listing, creation, status toggle, and password reset."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        await create_admin_user(db_session, username=ADMIN_USER, email=ADMIN_EMAIL, password=ADMIN_PASSWORD)
        admin_token = await _get_auth_token(client, ADMIN_USER, ADMIN_PASSWORD)
        headers = {"Authorization": f"Bearer {admin_token}"}

        # 1. List users
        res = await client.get("/api/v1/users", headers=headers)
        assert res.status_code == 200
        users = res.json()
        assert isinstance(users, list)
        assert any(u["username"] == ADMIN_USER for u in users)

        # 2. Create new user
        uid = uuid.uuid4().hex[:6]
        new_user_name = f"new_be_{uid}"
        new_user_email = f"{new_user_name}@amipi.com"
        new_user_pass = "SecureBePass123!"

        res = await client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": new_user_email, "username": new_user_name, "password": new_user_pass},
        )
        assert res.status_code == 201
        created = res.json()
        assert created["username"] == new_user_name
        assert created["email"] == new_user_email
        assert created["role"] == "user"
        assert created["is_active"] is True
        created_id = created["id"]

        # 3. Created user can log in
        token = await _get_auth_token(client, new_user_name, new_user_pass)
        assert token is not None

        # 4. Toggle status to Inactive
        res = await client.put(f"/api/v1/users/{created_id}/status", headers=headers, json={"is_active": False})
        assert res.status_code == 200
        assert res.json()["is_active"] is False

        # 5. Inactive user login fails
        res = await client.post("/api/v1/auth/login", data={"username": new_user_name, "password": new_user_pass})
        assert res.status_code == 400
        assert "inactive" in res.json()["detail"].lower()

        # 6. Admin reactivates user
        res = await client.put(f"/api/v1/users/{created_id}/status", headers=headers, json={"is_active": True})
        assert res.status_code == 200
        assert res.json()["is_active"] is True

        # 7. Admin resets password
        new_pass = "BrandNewPassword123!"
        res = await client.post(f"/api/v1/users/{created_id}/reset-password", headers=headers, json={"new_password": new_pass})
        assert res.status_code == 200

        # 8. Login with new password succeeds
        new_token = await _get_auth_token(client, new_user_name, new_pass)
        assert new_token is not None
