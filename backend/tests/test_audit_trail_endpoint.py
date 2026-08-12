"""
Tests for Admin Security Audit Trail endpoint.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, User, UserRole


@pytest.mark.asyncio
async def test_admin_can_fetch_audit_logs(
    client: AsyncClient,
    admin_token_headers: dict[str, str],
    db_session: AsyncSession,
):
    # Create sample audit log
    log_entry = AuditLog(
        action="TEST_ACTION_LOGGED",
        entity_type="Vendor",
        entity_id="test-123",
        details={"key": "value"},
    )
    db_session.add(log_entry)
    await db_session.commit()

    response = await client.get("/api/v1/audit-logs", headers=admin_token_headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    actions = [item["action"] for item in data]
    assert "TEST_ACTION_LOGGED" in actions
