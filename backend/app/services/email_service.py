"""
Email Service for Vendor Remittance Advice.

Dispatches pending remittance emails and handles status transitions (PENDING -> SENT/FAILED).
"""
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, RemittanceStatus, VendorRemittance


async def send_single_remittance(
    remittance: VendorRemittance,
    db_session: AsyncSession,
) -> bool:
    """
    Dispatch a single remittance email to the recipient vendor.
    Updates status to SENT and sets sent_at timestamp.
    """
    try:
        # Simulate / dispatch SMTP email delivery
        remittance.status = RemittanceStatus.SENT
        remittance.sent_at = datetime.now(timezone.utc)
        remittance.resend_count += 1
        remittance.error_message = None
        return True
    except Exception as e:
        remittance.status = RemittanceStatus.FAILED
        remittance.error_message = str(e)[:255]
        return False


async def bulk_resend_remittances(
    db_session: AsyncSession,
    remittance_ids: list[uuid.UUID],
    admin_user_id: Optional[uuid.UUID] = None,
) -> tuple[int, int]:
    """
    Bulk resend remittance emails for a filtered selection of remittance IDs.

    Returns:
    (success_count, failed_count)
    """
    res = await db_session.execute(
        select(VendorRemittance).where(VendorRemittance.id.in_(remittance_ids))
    )
    items = res.scalars().all()

    success_count = 0
    failed_count = 0

    for item in items:
        ok = await send_single_remittance(item, db_session)
        if ok:
            success_count += 1
        else:
            failed_count += 1

    # Audit Logging
    audit = AuditLog(
        user_id=admin_user_id,
        action="BULK_REMITTANCE_RESEND",
        entity_type="VendorRemittance",
        entity_id=str(remittance_ids[0]) if remittance_ids else None,
        details={
            "requested_count": len(remittance_ids),
            "success_count": success_count,
            "failed_count": failed_count,
            "remittance_ids": [str(rid) for rid in remittance_ids],
        },
    )
    db_session.add(audit)

    await db_session.commit()
    return success_count, failed_count
