"""
Payment Batch & Spreadsheet Upload FastAPI Endpoints.
"""
import os
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional


from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_current_user
from app.db.session import get_async_db
from app.models import AuditLog, BatchStatus, Payment, PaymentStatus, UploadBatch, User, Vendor
from app.services.duplicate_detector import compute_payment_fingerprint, detect_payment_duplicates
from app.services.spreadsheet_parser import parse_payment_spreadsheet

router = APIRouter(prefix="/payments", tags=["Payments"])


class ParsedRowErrorSchema(BaseModel):
    row_number: int
    raw_data: dict
    errors: list[str]


class ParsedPaymentSchema(BaseModel):
    payment_id: Optional[str] = None
    vendor_name: str
    amount: str
    id_number: str
    effective_date: str
    routing_number: Optional[str] = None
    account_number: Optional[str] = None
    fingerprint: Optional[str] = None
    is_duplicate_override: bool = False
    invoice_breakdown: Optional[list[dict[str, Any]]] = None



class BatchSummarySchema(BaseModel):
    total_rows: int
    valid_rows: int
    error_rows: int
    total_amount: str


class ManualPaymentItemSchema(BaseModel):
    vendor_id: uuid.UUID
    amount: Decimal
    id_number: str
    effective_date: date


class ManualBatchRequest(BaseModel):
    batch_number: int = 2
    filename: str = "Manual Batch 2"
    allow_override: bool = False
    payments: list[ManualPaymentItemSchema]


class UploadBatchResponse(BaseModel):
    batch_id: str
    batch_number: int
    filename: str
    status: str
    summary: BatchSummarySchema
    valid_payments: list[ParsedPaymentSchema]
    errors: list[ParsedRowErrorSchema]


@router.post("/upload", response_model=UploadBatchResponse, status_code=status.HTTP_201_CREATED)
async def upload_payment_spreadsheet(
    file: UploadFile = File(...),
    batch_number: int = Form(1),
    effective_date: Optional[str] = Form(None),
    allow_override: bool = Form(False),
    db: AsyncSession = Depends(get_async_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """
    Upload a payment spreadsheet (.xlsx, .xls, .csv).

    Parses payment rows, detects duplicate transactions using SHA-256 fingerprints,
    and supports an explicit override flag (`allow_override=True`).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename missing.")

    # Sanitize filename (prevent path traversal / directory injection)
    sanitized_filename = os.path.basename(file.filename).strip()

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # File size limit (10 MB max)
    MAX_FILE_SIZE = 10 * 1024 * 1024
    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeds maximum limit of {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )

    parsed_eff_date = None
    if effective_date:
        try:
            parsed_eff_date = datetime.strptime(effective_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid effective_date format. Expected YYYY-MM-DD.",
            )

    parse_result = await parse_payment_spreadsheet(
        file_bytes=file_bytes,
        filename=sanitized_filename,
        db_session=db,
        default_effective_date=parsed_eff_date,
    )

    # Phase 4: Duplicate Detection using Fingerprint Logic
    valid_payments, dup_errors = await detect_payment_duplicates(
        parse_result.valid_payments,
        db_session=db,
        allow_override=allow_override,
    )

    all_errors = parse_result.errors + dup_errors

    # Compute batch status
    if not valid_payments and all_errors:
        batch_status = BatchStatus.FAILED
    elif all_errors:
        batch_status = BatchStatus.PARTIALLY_FAILED
    else:
        batch_status = BatchStatus.PARSED

    total_amt = sum((p.amount for p in valid_payments), Decimal("0.00"))

    # Create new UploadBatch record
    batch = UploadBatch(
        batch_number=batch_number,
        filename=sanitized_filename,
        file_type=sanitized_filename.split(".")[-1].lower(),
        total_rows=parse_result.total_rows_parsed,
        valid_rows_count=len(valid_payments),
        error_rows_count=len(all_errors),
        total_amount=total_amt,
        status=batch_status,
    )
    db.add(batch)
    await db.flush()  # Generate batch.id

    # Create Payment records for all valid payments
    created_payments = []
    for vp in valid_payments:
        vendor_id = vp.vendor_id
        if not vendor_id and vp.routing_number and vp.account_number:
            # Auto-create vendor if not already in database
            res_v = await db.execute(select(Vendor).where(Vendor.name == vp.vendor_name.strip().upper()))
            existing_v = res_v.scalar_one_or_none()
            if not existing_v:
                acc_type = (vp.account_type.lower() if vp.account_type else "checking")
                existing_v = Vendor(
                    name=vp.vendor_name.strip().upper()[:22],
                    routing_number=vp.routing_number,
                    account_number=vp.account_number,
                    account_type=acc_type,
                    is_active=True,
                )
                db.add(existing_v)
                await db.flush()
            vendor_id = existing_v.id

        is_override = bool(vp.notes and vp.notes.startswith("OVERRIDE_DUP:"))
        fp = (
            compute_payment_fingerprint(vendor_id, vp.amount, vp.id_number, vp.effective_date)
            if vendor_id
            else None
        )

        payment = Payment(
            vendor_id=vendor_id,
            batch_id=batch.id,
            amount=vp.amount,
            id_number=vp.id_number,
            effective_date=vp.effective_date,
            invoice_breakdown=getattr(vp, 'invoice_breakdown', None),
            status=PaymentStatus.PENDING,
            fingerprint=fp,
            is_duplicate_override=is_override,
            created_by_user_id=current_user.id if current_user else None,
        )
        db.add(payment)
        await db.flush()
        created_payments.append(
            ParsedPaymentSchema(
                payment_id=str(payment.id),
                vendor_name=vp.vendor_name,
                amount=str(vp.amount),
                id_number=vp.id_number,
                effective_date=vp.effective_date.isoformat(),
                routing_number=vp.routing_number,
                account_number=vp.account_number,
                fingerprint=fp,
                is_duplicate_override=is_override,
                invoice_breakdown=getattr(vp, 'invoice_breakdown', None),
            )
        )


    # Audit Logging
    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        action="UPLOAD_BATCH_CREATED",
        entity_type="UploadBatch",
        entity_id=str(batch.id),
        details={
            "batch_number": batch.batch_number,
            "filename": batch.filename,
            "valid_rows": batch.valid_rows_count,
            "error_rows": batch.error_rows_count,
            "total_amount": str(batch.total_amount),
        },
    )
    db.add(audit)

    await db.commit()
    await db.refresh(batch)

    err_schemas = [
        ParsedRowErrorSchema(
            row_number=e.row_number,
            raw_data=e.raw_data,
            errors=e.errors,
        )
        for e in all_errors
    ]

    return UploadBatchResponse(
        batch_id=str(batch.id),
        batch_number=batch.batch_number,
        filename=batch.filename,
        status=batch.status.value,
        summary=BatchSummarySchema(
            total_rows=batch.total_rows,
            valid_rows=batch.valid_rows_count,
            error_rows=batch.error_rows_count,
            total_amount=str(batch.total_amount),
        ),
        valid_payments=created_payments,
        errors=err_schemas,
    )


@router.post("/manual-batch", response_model=UploadBatchResponse, status_code=status.HTTP_201_CREATED)
async def create_manual_payment_batch(
    payload: ManualBatchRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """
    Create a manual payment batch (Batch 2).

    Validates vendor IDs, checks for duplicates, and creates Payment records in PostgreSQL.
    """
    if not payload.payments:
        raise HTTPException(status_code=400, detail="At least one payment must be provided.")

    from app.services.spreadsheet_parser import ParsedPayment, ParsedRowError

    parsed_payments: list[ParsedPayment] = []
    errors: list[ParsedRowError] = []

    for idx, p_item in enumerate(payload.payments, 1):
        res_v = await db.execute(select(Vendor).where(Vendor.id == p_item.vendor_id))
        vendor = res_v.scalar_one_or_none()
        if not vendor:
            errors.append(
                ParsedRowError(
                    row_number=idx,
                    raw_data={"vendor_id": str(p_item.vendor_id)},
                    errors=[f"Vendor ID {p_item.vendor_id} not found in database."],
                )
            )
            continue

        id_val = p_item.id_number.strip() if p_item.id_number and p_item.id_number.strip() else (
            vendor.default_id_number or (vendor.account_number[-5:] if vendor.account_number and len(vendor.account_number) >= 5 else "EPAY")
        )
        parsed_payments.append(
            ParsedPayment(
                vendor_name=vendor.name,
                amount=p_item.amount,
                id_number=id_val,
                effective_date=p_item.effective_date,
                vendor_id=vendor.id,
                routing_number=vendor.routing_number,
                account_number=vendor.account_number,
            )
        )

    # Phase 4 Duplicate Detection
    valid_payments, dup_errors = await detect_payment_duplicates(
        parsed_payments,
        db_session=db,
        allow_override=payload.allow_override,
    )
    all_errors = errors + dup_errors

    # Compute batch status
    if not valid_payments and all_errors:
        batch_status = BatchStatus.FAILED
    elif all_errors:
        batch_status = BatchStatus.PARTIALLY_FAILED
    else:
        batch_status = BatchStatus.PARSED

    total_amt = sum((p.amount for p in valid_payments), Decimal("0.00"))

    batch = UploadBatch(
        batch_number=payload.batch_number,
        filename=payload.filename,
        file_type="manual",
        total_rows=len(payload.payments),
        valid_rows_count=len(valid_payments),
        error_rows_count=len(all_errors),
        total_amount=total_amt,
        status=batch_status,
    )
    db.add(batch)
    await db.flush()

    created_payments = []
    for vp in valid_payments:
        is_override = bool(vp.notes and vp.notes.startswith("OVERRIDE_DUP:"))
        fp = (
            compute_payment_fingerprint(vp.vendor_id, vp.amount, vp.id_number, vp.effective_date)
            if vp.vendor_id
            else None
        )

        payment = Payment(
            vendor_id=vp.vendor_id,
            batch_id=batch.id,
            amount=vp.amount,
            id_number=vp.id_number,
            effective_date=vp.effective_date,
            status=PaymentStatus.PENDING,
            fingerprint=fp,
            is_duplicate_override=is_override,
        )
        db.add(payment)
        await db.flush()
        created_payments.append(
            ParsedPaymentSchema(
                payment_id=str(payment.id),
                vendor_name=vp.vendor_name,
                amount=str(vp.amount),
                id_number=vp.id_number,
                effective_date=vp.effective_date.isoformat(),
                routing_number=vp.routing_number,
                account_number=vp.account_number,
                fingerprint=fp,
                is_duplicate_override=is_override,
            )
        )

    # Audit Logging
    audit = AuditLog(
        user_id=current_user.id if current_user else None,
        action="MANUAL_BATCH_CREATED",
        entity_type="UploadBatch",
        entity_id=str(batch.id),
        details={
            "batch_number": batch.batch_number,
            "filename": batch.filename,
            "valid_rows": batch.valid_rows_count,
            "error_rows": batch.error_rows_count,
            "total_amount": str(batch.total_amount),
        },
    )
    db.add(audit)

    await db.commit()
    await db.refresh(batch)

    err_schemas = [
        ParsedRowErrorSchema(
            row_number=e.row_number,
            raw_data=e.raw_data,
            errors=e.errors,
        )
        for e in all_errors
    ]

    return UploadBatchResponse(
        batch_id=str(batch.id),
        batch_number=batch.batch_number,
        filename=batch.filename,
        status=batch.status.value,
        summary=BatchSummarySchema(
            total_rows=batch.total_rows,
            valid_rows=batch.valid_rows_count,
            error_rows=batch.error_rows_count,
            total_amount=str(batch.total_amount),
        ),
        valid_payments=created_payments,
        errors=err_schemas,
    )


@router.get("/batches/{batch_id}", status_code=status.HTTP_200_OK)
async def get_upload_batch(batch_id: str, db: AsyncSession = Depends(get_async_db)):
    """Fetch an upload batch by ID along with its payments."""
    try:
        valid_uuid = uuid.UUID(batch_id.strip())
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid batch_id format '{batch_id}'. Must be a valid UUID.",
        )

    res = await db.execute(select(UploadBatch).where(UploadBatch.id == valid_uuid))
    batch = res.scalar_one_or_none()
    if not batch:
        raise HTTPException(status_code=404, detail="Upload batch not found.")

    res_payments = await db.execute(
        select(Payment).options(selectinload(Payment.vendor)).where(Payment.batch_id == batch.id)
    )
    payments = res_payments.scalars().all()

    return {
        "batch_id": str(batch.id),
        "batch_number": batch.batch_number,
        "filename": batch.filename,
        "status": batch.status.value,
        "summary": {
            "total_rows": batch.total_rows,
            "valid_rows": batch.valid_rows_count,
            "error_rows": batch.error_rows_count,
            "total_amount": str(batch.total_amount),
        },
        "payments": [
            {
                "payment_id": str(p.id),
                "vendor_id": str(p.vendor_id),
                "vendor_name": p.vendor.name if p.vendor else "Unknown",
                "amount": str(p.amount),
                "id_number": p.id_number,
                "effective_date": p.effective_date.isoformat(),
                "status": p.status.value,
                "fingerprint": p.fingerprint,
                "is_duplicate_override": p.is_duplicate_override,
                "invoice_breakdown": p.invoice_breakdown,
            }
            for p in payments
        ],
    }



class UpdatePaymentRequest(BaseModel):
    amount: Optional[Decimal] = None
    id_number: Optional[str] = None
    effective_date: Optional[date] = None


@router.put("/{payment_id}", status_code=status.HTTP_200_OK)
async def update_payment_item(
    payment_id: uuid.UUID,
    payload: UpdatePaymentRequest,
    db: AsyncSession = Depends(get_async_db),
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """
    Update details of a parsed payment item before NACHA file generation.
    Recalculates batch total amount and updates payment fields in PostgreSQL.
    """
    res = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = res.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment record not found.")

    if payload.amount is not None:
        payment.amount = payload.amount
    if payload.id_number is not None:
        payment.id_number = payload.id_number.strip()
    if payload.effective_date is not None:
        payment.effective_date = payload.effective_date

    # Recalculate fingerprint if needed
    if payment.vendor_id:
        payment.fingerprint = compute_payment_fingerprint(
            payment.vendor_id, payment.amount, payment.id_number, payment.effective_date
        )

    # Recalculate batch total
    res_all = await db.execute(select(Payment).where(Payment.batch_id == payment.batch_id))
    all_batch_payments = res_all.scalars().all()
    new_total = sum((p.amount for p in all_batch_payments), Decimal("0.00"))

    res_b = await db.execute(select(UploadBatch).where(UploadBatch.id == payment.batch_id))
    batch = res_b.scalar_one_or_none()
    if batch:
        batch.total_amount = new_total

    await db.commit()

    return {
        "payment_id": str(payment.id),
        "amount": str(payment.amount),
        "id_number": payment.id_number,
        "effective_date": payment.effective_date.isoformat(),
        "batch_total_amount": str(new_total),
    }

