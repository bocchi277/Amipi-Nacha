"""
System Audit Log FastAPI Router.

Provides filterable audit history querying for Admin users.
"""
from typing import Any, Optional
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.db.session import get_async_db
from app.models import AuditLog, User

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


class AuditLogResponseSchema(BaseModel):
    id: str
    user_id: Optional[str] = None
    username: str
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    timestamp: str


@router.get("", response_model=list[AuditLogResponseSchema])
async def list_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action type"),
    user_id: Optional[uuid.UUID] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),  # ADMIN ONLY!
):
    """
    Fetch system audit trail logs (Admin Only).
    """
    stmt = select(AuditLog)

    if action and action.strip():
        stmt = stmt.where(AuditLog.action.ilike(f"%{action.strip()}%"))
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if start_date:
        stmt = stmt.where(AuditLog.created_at >= start_date)
    if end_date:
        # created_at is a timestamp; comparing it to a bare date pins the boundary at
        # 00:00 and silently excluded every entry recorded ON end_date. Advance to the
        # start of the following day so the range is inclusive as users expect.
        stmt = stmt.where(AuditLog.created_at < end_date + timedelta(days=1))

    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit)

    res = await db.execute(stmt)
    logs = res.scalars().all()

    # Pre-fetch users for usernames
    user_ids = {l.user_id for l in logs if l.user_id}
    users_map = {}
    if user_ids:
        res_u = await db.execute(select(User).where(User.id.in_(user_ids)))
        users_map = {u.id: u.username for u in res_u.scalars().all()}

    return [
        AuditLogResponseSchema(
            id=str(l.id),
            user_id=str(l.user_id) if l.user_id else None,
            username=users_map.get(l.user_id, "System / Admin"),
            action=l.action,
            entity_type=l.entity_type,
            entity_id=l.entity_id,
            details=l.details,
            timestamp=l.created_at.isoformat() if l.created_at else "",
        )
        for l in logs
    ]

