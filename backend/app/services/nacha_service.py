"""
NACHA File Generation Service.

Combines multiple upload/manual batches into a single Chase-compliant NACHA file
using the Phase 1 generation core, updating PostgreSQL payment links and control totals.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Optional
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, BatchStatus, NachaFileRecord, Payment, PaymentStatus, UploadBatch, Vendor
from app.nacha.generator import generate_nacha_file, GenerationResult
from app.nacha.models import Batch, EntryDetail, FileHeaderConfig, NachaFileInput


async def combine_batches_and_generate_nacha(
    db_session: AsyncSession,
    batch_ids: list[uuid.UUID],
    company_name: str = "AMIPI INC",
    company_account: str = "785957066",
    effective_entry_date: Optional[datetime.date | str] = None,
    file_id_modifier: str = "A",
    trace_sequence_start: int = 1,
    entry_description: str = "EPAYMNT",
    created_by_user_id: Optional[uuid.UUID] = None,
) -> tuple[NachaFileRecord, GenerationResult]:
    """
    Combine multiple payment batches (e.g. Batch 1 + Batch 2) into a single NACHA file.

    1. Fetches batches & linked payments from PostgreSQL.
    2. Maps DB Payments & Vendors -> Phase 1 EntryDetail objects.
    3. Invokes Phase 1 generate_nacha_file core.
    4. Persists NachaFileRecord in database with combined control totals.
    5. Links Payments to NachaFileRecord and updates statuses to PROCESSING.
    """
    if not batch_ids:
        raise ValueError("At least one batch_id must be provided for NACHA generation.")

    # 1. Fetch batches in specified order
    res_batches = await db_session.execute(
        select(UploadBatch).where(UploadBatch.id.in_(batch_ids))
    )
    fetched_batches = {b.id: b for b in res_batches.scalars().all()}

    missing_ids = [bid for bid in batch_ids if bid not in fetched_batches]
    if missing_ids:
        raise ValueError(f"Upload batch(es) not found: {missing_ids}")

    ordered_batches = [fetched_batches[bid] for bid in batch_ids]

    # Format dates
    now = datetime.datetime.now(datetime.timezone.utc)
    file_date_yymmdd = now.strftime("%y%m%d")
    file_time_hhmm = now.strftime("%H%M")

    if isinstance(effective_entry_date, str):
        # YYYY-MM-DD or YYMMDD
        eff_str = effective_entry_date.strip().replace("-", "")
        if len(eff_str) == 8:
            eff_yymmdd = eff_str[2:]
        elif len(eff_str) == 6:
            eff_yymmdd = eff_str
        else:
            eff_yymmdd = file_date_yymmdd
    elif isinstance(effective_entry_date, datetime.date):
        eff_yymmdd = effective_entry_date.strftime("%y%m%d")
    else:
        eff_yymmdd = file_date_yymmdd

    cfg = FileHeaderConfig(
        company_name=company_name,
        company_account=company_account,
        entry_description=entry_description,
        effective_entry_date=eff_yymmdd,
        file_creation_date=file_date_yymmdd,
        file_creation_time=file_time_hhmm,
        file_id_modifier=file_id_modifier.upper()[:1],
        trace_sequence_start=trace_sequence_start,
    )

    nacha_batches: list[Batch] = []
    payments_to_update: list[Payment] = []

    for b in ordered_batches:
        res_payments = await db_session.execute(
            select(Payment).where(Payment.batch_id == b.id)
        )
        batch_payments = res_payments.scalars().all()
        if not batch_payments:
            raise ValueError(f"Batch {b.batch_number} ({b.id}) contains no payments.")

        entries: list[EntryDetail] = []
        for p in batch_payments:
            # Fetch vendor
            res_v = await db_session.execute(select(Vendor).where(Vendor.id == p.vendor_id))
            vendor = res_v.scalar_one()

            # Transaction code: 22 = checking credit, 32 = savings credit
            txcode = "32" if vendor.account_type and vendor.account_type.value == "savings" else "22"

            entries.append(
                EntryDetail(
                    transaction_code=txcode,
                    routing_number=vendor.routing_number,
                    account_number=vendor.account_number,
                    amount=str(p.amount),
                    id_number=p.id_number or "EPAY",
                    receiver_name=vendor.name[:22],
                    discretionary_data="  ",
                    addenda_indicator="0",
                )
            )
            payments_to_update.append(p)

        nacha_batches.append(Batch(entries=entries))

    # Invoke Phase 1 Core NACHA generator
    input_spec = NachaFileInput(header=cfg, batches=nacha_batches)
    gen_result = generate_nacha_file(input_spec)

    if not gen_result.success:
        err_details = (
            "; ".join(e.message for e in gen_result.validation.errors)
            if gen_result.validation
            else "Unknown validation error"
        )
        raise ValueError(f"NACHA file generation failed: {err_details}")

    # Extract control record totals from generated file text
    lines = [l for l in gen_result.content.split("\r\n") if l]
    file_control_line = [l for l in lines if l.startswith("9") and l != "9" * 94][0]

    # File control fields:
    # 2-7: batch count (6)
    # 8-13: block count (6)
    # 14-21: entry count (8)
    # 22-31: entry hash (10)
    # 44-55: total credit amount (12) in cents
    b_count = int(file_control_line[1:7])
    blk_count = int(file_control_line[7:13])
    e_count = int(file_control_line[13:21])
    e_hash = int(file_control_line[21:31])
    credit_cents = int(file_control_line[43:55])
    total_credit_amt = Decimal(credit_cents) / Decimal("100")

    filename = f"AMIPIINC_transmit_{eff_yymmdd}_{cfg.file_id_modifier}.ach"

    # Create NachaFileRecord in database
    nacha_record = NachaFileRecord(
        filename=filename,
        file_id_modifier=cfg.file_id_modifier,
        file_creation_date=file_date_yymmdd,
        file_creation_time=file_time_hhmm,
        total_entry_count=e_count,
        total_batch_count=b_count,
        total_block_count=blk_count,
        total_credit_amount=total_credit_amt,
        entry_hash=str(e_hash),
        raw_content=gen_result.content,
        created_by_user_id=created_by_user_id,
    )
    db_session.add(nacha_record)
    await db_session.flush()  # Generate nacha_record.id

    # Update Payments & UploadBatches, and create VendorRemittance pending records
    from app.models import RemittanceStatus, VendorRemittance

    for p in payments_to_update:
        p.nacha_file_id = nacha_record.id
        p.status = PaymentStatus.PROCESSING

        # Fetch vendor email
        res_v = await db_session.execute(select(Vendor).where(Vendor.id == p.vendor_id))
        vendor_obj = res_v.scalar_one()

        v_email = vendor_obj.email or f"remittance@{vendor_obj.name.lower().replace(' ', '')[:15]}.com"

        remittance = VendorRemittance(
            vendor_id=vendor_obj.id,
            nacha_file_id=nacha_record.id,
            payment_id=p.id,
            recipient_email=v_email,
            vendor_name=vendor_obj.name,
            amount=p.amount,
            effective_date=p.effective_date,
            invoice_reference=p.id_number,
            subject=f"Payment Remittance Advice — {vendor_obj.name} (${p.amount:.2f})",
            body_text=(
                f"Dear {vendor_obj.name},\n\n"
                f"Please be advised that an ACH payment of ${p.amount:.2f} has been scheduled for "
                f"effective date {p.effective_date.isoformat()}.\n"
                f"Reference / Invoice: {p.id_number}\n\n"
                f"Thank you,\nAMIPI Inc Accounts Payable"
            ),
            status=RemittanceStatus.PENDING,
        )
        db_session.add(remittance)

    for b in ordered_batches:
        b.status = BatchStatus.PROCESSED

    # Audit Logging
    audit = AuditLog(
        user_id=created_by_user_id,
        action="NACHA_FILE_GENERATED",
        entity_type="NachaFileRecord",
        entity_id=str(nacha_record.id),
        details={
            "filename": nacha_record.filename,
            "total_entry_count": nacha_record.total_entry_count,
            "total_batch_count": nacha_record.total_batch_count,
            "total_credit_amount": str(nacha_record.total_credit_amount),
            "entry_hash": nacha_record.entry_hash,
        },
    )
    db_session.add(audit)

    await db_session.commit()
    await db_session.refresh(nacha_record)

    return nacha_record, gen_result
