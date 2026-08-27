"""
Vendor Remittance Emails FastAPI Router.

Provides filterable table query, pending dispatch, and bulk resend endpoints.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_admin
from app.db.session import get_async_db
from app.models import AuditLog, NachaFileRecord, Payment, RemittanceStatus, UploadBatch, User, VendorRemittance
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
    body_html: Optional[str] = None
    status: str
    sent_at: Optional[str] = None
    resend_count: int
    created_at: str
    created_by_username: Optional[str] = "admin"
    invoice_breakdown: Optional[list[dict[str, Any]]] = None
    sequence_id: Optional[str] = None



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
    preview_html: Optional[str] = None


class UpdateEmailTemplateRequest(BaseModel):
    subject_template: str
    body_template: str


class EmailTemplatePreviewRequest(BaseModel):
    subject_template: Optional[str] = None
    body_template: Optional[str] = None


class EmailTemplatePreviewResponse(BaseModel):
    subject: str
    body_text: str
    body_html: str


class UpdateRemittanceEmailRequest(BaseModel):
    recipient_email: str
    update_vendor_default: Optional[bool] = False


@router.get("/template", response_model=EmailTemplateSchema)
async def get_email_template(current_user: User = Depends(get_current_user)):
    """Fetch the active remittance email template and available dynamic placeholders."""
    from app.core.email_templates import ACTIVE_TEMPLATE, AVAILABLE_PLACEHOLDERS, render_email_template
    subj, txt, html = render_email_template(
        ACTIVE_TEMPLATE["subject"],
        ACTIVE_TEMPLATE["body"],
        {
            "vendor_name": "AMIPI INC",
            "amount": "53,413.06",
            "invoice_ref": "INV-128753",
            "effective_date": "05-19-2026",
            "company_name": "AMIPI INC",
            "payment_method": "ACH/Wire",
            "deposit_ref": "12970",
        },
        invoice_items=[
            {"method": "ACH/Wire", "invoice_date": "05-19-2026", "invoice_number": "128753", "amount": 22094.82},
            {"method": "ACH/Wire", "invoice_date": "05-21-2026", "invoice_number": "128779", "amount": 31318.24},
        ],
    )
    return EmailTemplateSchema(
        subject_template=ACTIVE_TEMPLATE["subject"],
        body_template=ACTIVE_TEMPLATE["body"],
        available_placeholders=AVAILABLE_PLACEHOLDERS,
        preview_html=html,
    )


@router.post("/template/preview", response_model=EmailTemplatePreviewResponse)
async def preview_email_template(
    payload: EmailTemplatePreviewRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate a live HTML preview of the customized email template with sample sub-invoices."""
    from app.core.email_templates import ACTIVE_TEMPLATE, render_email_template
    subj_tmpl = payload.subject_template or ACTIVE_TEMPLATE["subject"]
    body_tmpl = payload.body_template or ACTIVE_TEMPLATE["body"]

    subj, txt, html = render_email_template(
        subj_tmpl,
        body_tmpl,
        {
            "vendor_name": "AMIPI INC",
            "amount": "53,413.06",
            "invoice_ref": "INV-128753",
            "effective_date": "05-19-2026",
            "company_name": "AMIPI INC",
            "payment_method": "ACH/Wire",
            "deposit_ref": "12970",
        },
        invoice_items=[
            {"method": "ACH/Wire", "invoice_date": "05-19-2026", "invoice_number": "128753", "amount": 22094.82},
            {"method": "ACH/Wire", "invoice_date": "05-21-2026", "invoice_number": "128779", "amount": 31318.24},
        ],
    )
    return EmailTemplatePreviewResponse(
        subject=subj,
        body_text=txt,
        body_html=html,
    )


@router.put("/template", response_model=EmailTemplateSchema)
async def update_email_template(
    payload: UpdateEmailTemplateRequest,
    current_user: User = Depends(get_current_user),
):
    """Update active remittance email template."""
    from app.core.email_templates import ACTIVE_TEMPLATE, AVAILABLE_PLACEHOLDERS, render_email_template
    if payload.subject_template and payload.subject_template.strip():
        ACTIVE_TEMPLATE["subject"] = payload.subject_template.strip()
    if payload.body_template and payload.body_template.strip():
        ACTIVE_TEMPLATE["body"] = payload.body_template.strip()

    subj, txt, html = render_email_template(
        ACTIVE_TEMPLATE["subject"],
        ACTIVE_TEMPLATE["body"],
        {
            "vendor_name": "AMIPI INC",
            "amount": "53,413.06",
            "invoice_ref": "INV-128753",
            "effective_date": "05-19-2026",
            "company_name": "AMIPI INC",
            "payment_method": "ACH/Wire",
            "deposit_ref": "12970",
        },
        invoice_items=[
            {"method": "ACH/Wire", "invoice_date": "05-19-2026", "invoice_number": "128753", "amount": 22094.82},
            {"method": "ACH/Wire", "invoice_date": "05-21-2026", "invoice_number": "128779", "amount": 31318.24},
        ],
    )

    return EmailTemplateSchema(
        subject_template=ACTIVE_TEMPLATE["subject"],
        body_template=ACTIVE_TEMPLATE["body"],
        available_placeholders=AVAILABLE_PLACEHOLDERS,
        preview_html=html,
    )


def _build_remittance_response(r: VendorRemittance) -> RemittanceResponseSchema:
    from app.core.email_templates import ACTIVE_TEMPLATE, render_email_template
    from sqlalchemy.inspection import inspect

    insp = inspect(r)
    breakdown = None
    created_by_user = "admin"

    if "payment" in insp.dict and r.payment is not None:
        breakdown = getattr(r.payment, "invoice_breakdown", None)

    if "nacha_file" in insp.dict and r.nacha_file is not None:
        nf_insp = inspect(r.nacha_file)
        if "created_by_user" in nf_insp.dict and r.nacha_file.created_by_user is not None:
            created_by_user = r.nacha_file.created_by_user.username

    seq_id = getattr(r, "trace_number", None)
    if not seq_id and "payment" in insp.dict and r.payment is not None:
        seq_id = getattr(r.payment, "trace_number", None)
    if not seq_id and "nacha_file" in insp.dict and r.nacha_file is not None and getattr(r.nacha_file, "raw_content", None):
        try:
            lines = [l for l in r.nacha_file.raw_content.split("\r\n") if l.startswith("6")]
            for eline in lines:
                if (r.invoice_reference and r.invoice_reference[:15] in eline) or (r.vendor_name and r.vendor_name[:15].upper() in eline.upper()):
                    seq_id = eline[79:94]
                    break
            if not seq_id and lines:
                seq_id = lines[0][79:94]
        except Exception:
            pass

    eff_str = r.effective_date.strftime("%m-%d-%Y") if hasattr(r.effective_date, "strftime") else str(r.effective_date)
    subject_rendered, body_text_rendered, html_content = render_email_template(
        ACTIVE_TEMPLATE["subject"],
        ACTIVE_TEMPLATE["body"],
        {
            "vendor_name": r.vendor_name,
            "amount": f"{float(r.amount):,.2f}",
            "invoice_ref": r.invoice_reference or "N/A",
            "effective_date": eff_str,
            "company_name": ACTIVE_TEMPLATE.get("company_name", "AMIPI INC"),
            "payment_method": "ACH/Wire",
            "deposit_ref": seq_id or (str(r.nacha_file_id)[:8] if r.nacha_file_id else "12970"),
        },
        invoice_items=breakdown,
    )

    return RemittanceResponseSchema(
        id=str(r.id),
        vendor_id=str(r.vendor_id),
        vendor_name=r.vendor_name,
        recipient_email=r.recipient_email,
        amount=str(r.amount),
        effective_date=r.effective_date.isoformat(),
        invoice_reference=r.invoice_reference,
        subject=subject_rendered,
        body_text=body_text_rendered,
        body_html=html_content,
        status=r.status.value,
        sent_at=r.sent_at.isoformat() if r.sent_at else None,
        resend_count=r.resend_count,
        created_at=r.created_at.isoformat(),
        created_by_username=created_by_user,
        invoice_breakdown=breakdown,
        sequence_id=seq_id,
    )


@router.get("", response_model=list[RemittanceResponseSchema])
async def list_remittances(
    remittance_status: Optional[RemittanceStatus] = Query(None, alias="status"),
    vendor_id: Optional[uuid.UUID] = Query(None),
    nacha_file_id: Optional[uuid.UUID] = Query(None),
    search: Optional[str] = Query(None, description="Search by vendor name, email, or invoice ref"),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    min_amount: Optional[Decimal] = Query(None, description="Minimum remittance dollar amount"),
    max_amount: Optional[Decimal] = Query(None, description="Maximum remittance dollar amount"),
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a filterable table of vendor remittance emails.

    Supports filtering by status, vendor_id, nacha_file_id, date range, amount range, and text search.
    """
    stmt = select(VendorRemittance).options(
        selectinload(VendorRemittance.payment),
        selectinload(VendorRemittance.nacha_file).selectinload(NachaFileRecord.created_by_user)
    )

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
    if min_amount is not None:
        stmt = stmt.where(VendorRemittance.amount >= min_amount)
    if max_amount is not None:
        stmt = stmt.where(VendorRemittance.amount <= max_amount)

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

    return [_build_remittance_response(r) for r in remittances]


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
    stmt = select(VendorRemittance).options(
        selectinload(VendorRemittance.payment),
        selectinload(VendorRemittance.nacha_file).selectinload(NachaFileRecord.created_by_user)
    ).where(VendorRemittance.status == RemittanceStatus.PENDING)
    if nacha_file_id:
        stmt = stmt.where(VendorRemittance.nacha_file_id == nacha_file_id)

    res = await db.execute(stmt)
    pending_remittances = res.scalars().all()

    dispatched = []
    for r in pending_remittances:
        await send_single_remittance(r, db)
        dispatched.append(r)

    await db.commit()

    return [_build_remittance_response(r) for r in dispatched]


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


@router.patch("/{remittance_id}/email", response_model=RemittanceResponseSchema)
@router.put("/{remittance_id}/email", response_model=RemittanceResponseSchema)
async def update_remittance_email(
    remittance_id: uuid.UUID,
    payload: UpdateRemittanceEmailRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update recipient email address for a specific remittance record.
    Optionally update vendor's primary email address if update_vendor_default is true.
    """
    new_email = payload.recipient_email.strip()
    if not new_email or "@" not in new_email or "." not in new_email:
        raise HTTPException(status_code=400, detail="Invalid email address format.")

    stmt = (
        select(VendorRemittance)
        .where(VendorRemittance.id == remittance_id)
        .options(
            selectinload(VendorRemittance.payment),
            selectinload(VendorRemittance.nacha_file).selectinload(NachaFileRecord.created_by_user),
            selectinload(VendorRemittance.vendor),
        )
    )
    res = await db.execute(stmt)
    remittance = res.scalar_one_or_none()
    if not remittance:
        raise HTTPException(status_code=404, detail="Remittance record not found")

    old_email = remittance.recipient_email
    remittance.recipient_email = new_email

    if payload.update_vendor_default and remittance.vendor:
        remittance.vendor.email = new_email

    audit_entry = AuditLog(
        user_id=current_user.id,
        action="UPDATE_REMITTANCE_EMAIL",
        entity_type="VendorRemittance",
        entity_id=str(remittance_id),
        details={
            "remittance_id": str(remittance_id),
            "old_email": old_email,
            "new_email": new_email,
            "vendor_name": remittance.vendor_name,
            "updated_by": current_user.username,
        },
    )
    db.add(audit_entry)
    await db.commit()
    await db.refresh(remittance)

    return _build_remittance_response(remittance)


class BulkDeleteRemittancesRequest(BaseModel):
    remittance_ids: list[uuid.UUID]


class BulkDeleteRemittancesResponseSchema(BaseModel):
    deleted_count: int
    message: str


@router.delete("/{remittance_id}")
async def delete_single_remittance(
    remittance_id: uuid.UUID,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """
    Delete a single remittance transaction record from the database (Admin only).
    """
    stmt = select(VendorRemittance).where(VendorRemittance.id == remittance_id)
    res = await db.execute(stmt)
    remittance = res.scalar_one_or_none()
    if not remittance:
        raise HTTPException(status_code=404, detail="Remittance record not found")

    vendor_name = remittance.vendor_name
    await db.delete(remittance)

    audit_entry = AuditLog(
        user_id=admin_user.id,
        action="DELETE_REMITTANCE",
        entity_type="VendorRemittance",
        entity_id=str(remittance_id),
        details={
            "remittance_id": str(remittance_id),
            "vendor_name": vendor_name,
            "admin_user_id": str(admin_user.id),
            "username": admin_user.username,
        },
    )
    db.add(audit_entry)
    await db.commit()

    return {"message": f"Remittance record for {vendor_name} deleted successfully"}


@router.post("/bulk-delete", response_model=BulkDeleteRemittancesResponseSchema)
async def bulk_delete_remittances(
    payload: BulkDeleteRemittancesRequest,
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """
    Bulk delete remittance transaction records from the database (Admin only).
    """
    if not payload.remittance_ids:
        raise HTTPException(status_code=400, detail="At least one remittance_id must be provided.")

    stmt = select(VendorRemittance).where(VendorRemittance.id.in_(payload.remittance_ids))
    res = await db.execute(stmt)
    remittances = res.scalars().all()

    deleted_count = len(remittances)
    if deleted_count == 0:
        return BulkDeleteRemittancesResponseSchema(
            deleted_count=0,
            message="No matching remittance records found to delete."
        )

    for r in remittances:
        await db.delete(r)

    audit_entry = AuditLog(
        user_id=admin_user.id,
        action="BULK_DELETE_REMITTANCES",
        entity_type="VendorRemittance",
        details={
            "deleted_count": deleted_count,
            "remittance_ids": [str(rid) for rid in payload.remittance_ids],
            "admin_user_id": str(admin_user.id),
            "username": admin_user.username,
        },
    )
    db.add(audit_entry)
    await db.commit()

    return BulkDeleteRemittancesResponseSchema(
        deleted_count=deleted_count,
        message=f"Successfully deleted {deleted_count} remittance transaction record(s)."
    )


@router.post("/clear-all", response_model=BulkDeleteRemittancesResponseSchema)
async def clear_all_payment_history(
    db: AsyncSession = Depends(get_async_db),
    admin_user: User = Depends(require_admin),
):
    """
    Clear all payment history, remittances, batch staging records, and generated files (Admin only).
    """
    res = await db.execute(select(VendorRemittance))
    remittances = res.scalars().all()
    rem_count = len(remittances)

    await db.execute(delete(VendorRemittance))
    await db.execute(delete(Payment))
    await db.execute(delete(NachaFileRecord))
    await db.execute(delete(UploadBatch))

    audit_entry = AuditLog(
        user_id=admin_user.id,
        action="CLEAR_ALL_PAYMENT_HISTORY",
        entity_type="VendorRemittance",
        details={
            "deleted_remittances_count": rem_count,
            "admin_user_id": str(admin_user.id),
            "username": admin_user.username,
        },
    )
    db.add(audit_entry)
    await db.commit()

    return BulkDeleteRemittancesResponseSchema(
        deleted_count=rem_count,
        message=f"All payment history and records successfully cleared ({rem_count} remittances deleted)."
    )
