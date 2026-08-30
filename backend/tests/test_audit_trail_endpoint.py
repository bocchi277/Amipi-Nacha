import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.models import AuditLog
from tests._helpers import create_standard_user


@pytest.mark.asyncio
async def test_admin_can_fetch_audit_logs(db_session):
    # Create sample audit log
    log_entry = AuditLog(
        action="TEST_ACTION_LOGGED",
        entity_type="Vendor",
        entity_id="test-123",
        details={"key": "value"},
    )
    db_session.add(log_entry)
    await db_session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        # Register and login admin
        await create_standard_user(db_session, username="audit_admin", email="audit_admin@amipi.com", password="Password123!")
        res_login = await client.post(
            "/api/v1/auth/login",
            data={"username": "audit_admin", "password": "Password123!"},
        )
        token = res_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.get("/api/v1/audit-logs", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        actions = [item["action"] for item in data]
        assert "TEST_ACTION_LOGGED" in actions

