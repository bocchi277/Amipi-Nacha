"""
Vendor Remittance Emails FastAPI Router.

Provides filterable table query, pending dispatch, and bulk resend endpoints.
"""
import uuid
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_async_db
from app.models import RemittanceStatus, User, VendorRemittance
from app.services.email_service import bulk_resend_remittances, send_single_remittance

router = APIRouter(prefix="/remittances", tags=["Vendor Remittances"])


class RemittanceResponseSchema(BaseModel):
    id: str
    vendor_id: str
    vendor_name: str
    recipient_email: str
    amount: str
    effective_date: str
    invoice_reference: Optional[str] = None
    subject: str
    body_text: str
    status: str
    sent_at: Optional[str] = None
    resend_count: int
    created_at: str
    invoice_breakdown: Optional[list[dict[str, Any]]] = None



class BulkResendRequest(BaseModel):
    remittance_ids: list[uuid.UUID]


class BulkResendResponseSchema(BaseModel):
    total_requested: int
    success_count: int
    failed_count: int
    message: str


class EmailTemplateSchema(BaseModel):
    subject_template: str
    body_template: str
    available_placeholders: list[dict[str, str]]


class UpdateEmailTemplateRequest(BaseModel):
    subject_template: str
    body_template: str


@router.get("/template", response_model=EmailTemplateSchema)
async def get_email_template(current_user: User = Depends(get_current_user)):
    """Fetch the active remittance email template and available dynamic placeholders."""
    from app.core.email_templates import ACTIVE_TEMPLATE, AVAILABLE_PLACEHOLDERS
    return EmailTemplateSchema(
        subject_template=ACTIVE_TEMPLATE["subject"],
        body_template=ACTIVE_TEMPLATE["body"],
        available_placeholders=AVAILABLE_PLACEHOLDERS,
    )


@router.put("/template", response_model=EmailTemplateSchema)
async def update_email_template(
    payload: UpdateEmailTemplateRequest,
    current_user: User = Depends(get_current_user),
):
    """Update active remittance email template."""
    from app.core.email_templates import ACTIVE_TEMPLATE, AVAILABLE_PLACEHOLDERS
    if payload.subject_template and payload.subject_template.strip():
        ACTIVE_TEMPLATE["subject"] = payload.subject_template.strip()
    if payload.body_template and payload.body_template.strip():
        ACTIVE_TEMPLATE["body"] = payload.body_template.strip()

    return EmailTemplateSchema(
        subject_template=ACTIVE_TEMPLATE["subject"],
        body_template=ACTIVE_TEMPLATE["body"],
        available_placeholders=AVAILABLE_PLACEHOLDERS,
    )


@router.get("", response_model=list[RemittanceResponseSchema])

async def list_remittances(
    remittance_status: Optional[RemittanceStatus] = Query(None, alias="status"),
    vendor_id: Optional[uuid.UUID] = Query(None),
    nacha_file_id: Optional[uuid.UUID] = Query(None),
    search: Optional[str] = Query(None, description="Search by vendor name, email, or invoice ref"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a filterable table of vendor remittance emails.

    Supports filtering by status, vendor_id, nacha_file_id, date range, and text search.
    """
    stmt = select(VendorRemittance).options(selectinload(VendorRemittance.payment))

    if remittance_status:
        stmt = stmt.where(VendorRemittance.status == remittance_status)
    if vendor_id:
        stmt = stmt.where(VendorRemittance.vendor_id == vendor_id)
    if nacha_file_id:
        stmt = stmt.where(VendorRemittance.nacha_file_id == nacha_file_id)
    if start_date:
        stmt = stmt.where(VendorRemittance.effective_date >= start_date)
    if end_date:
        stmt = stmt.where(VendorRemittance.effective_date <= end_date)

    if search and search.strip():
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                VendorRemittance.vendor_name.ilike(term),
                VendorRemittance.recipient_email.ilike(term),
                VendorRemittance.invoice_reference.ilike(term),
            )
        )

    stmt = stmt.order_by(VendorRemittance.created_at.desc())

    res = await db.execute(stmt)
    remittances = res.scalars().all()

    return [
        RemittanceResponseSchema(
            id=str(r.id),
            vendor_id=str(r.vendor_id),
            vendor_name=r.vendor_name,
            recipient_email=r.recipient_email,
            amount=str(r.amount),
            effective_date=r.effective_date.isoformat(),
            invoice_reference=r.invoice_reference,
            subject=r.subject,
            body_text=r.body_text,
            status=r.status.value,
            sent_at=r.sent_at.isoformat() if r.sent_at else None,
            resend_count=r.resend_count,
            created_at=r.created_at.isoformat(),
            invoice_breakdown=r.payment.invoice_breakdown if (r.payment and r.payment.invoice_breakdown) else None,
        )
        for r in remittances
    ]



@router.post("/send", response_model=list[RemittanceResponseSchema])
async def dispatch_pending_remittances(
    nacha_file_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Dispatch pending vendor remittance emails.

    Updates status from PENDING to SENT and populates sent_at timestamps.
    """
    stmt = select(VendorRemittance).where(VendorRemittance.status == RemittanceStatus.PENDING)
    if nacha_file_id:
        stmt = stmt.where(VendorRemittance.nacha_file_id == nacha_file_id)

    res = await db.execute(stmt)
    pending_remittances = res.scalars().all()

    dispatched = []
    for r in pending_remittances:
        await send_single_remittance(r, db)
        dispatched.append(r)

    await db.commit()

    return [
        RemittanceResponseSchema(
            id=str(r.id),
            vendor_id=str(r.vendor_id),
            vendor_name=r.vendor_name,
            recipient_email=r.recipient_email,
            amount=str(r.amount),
            effective_date=r.effective_date.isoformat(),
            invoice_reference=r.invoice_reference,
            subject=r.subject,
            body_text=r.body_text,
            status=r.status.value,
            sent_at=r.sent_at.isoformat() if r.sent_at else None,
            resend_count=r.resend_count,
            created_at=r.created_at.isoformat(),
        )
        for r in dispatched
    ]


@router.post("/bulk-resend", response_model=BulkResendResponseSchema)
async def bulk_resend_remittance_emails(
    payload: BulkResendRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Bulk resend remittance emails for a filtered selection of remittance IDs.

    Resends selected emails, updates status to SENT, updates sent_at timestamps,
    and logs the action to AuditLog.
    """
    if not payload.remittance_ids:
        raise HTTPException(status_code=400, detail="At least one remittance_id must be specified.")

    success_cnt, fail_cnt = await bulk_resend_remittances(
        db_session=db,
        remittance_ids=payload.remittance_ids,
        admin_user_id=current_user.id,
    )

    return BulkResendResponseSchema(
        total_requested=len(payload.remittance_ids),
        success_count=success_cnt,
        failed_count=fail_cnt,
        message=f"Successfully resent {success_cnt} of {len(payload.remittance_ids)} remittance email(s).",
    )
