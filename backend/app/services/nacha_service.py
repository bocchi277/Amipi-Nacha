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

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.business_dates import (
    default_effective_date,
    file_creation_stamp,
    today_bank_time,
    validate_effective_date,
)
from app.models import AuditLog, BatchStatus, NachaFileRecord, Payment, PaymentStatus, UploadBatch, Vendor
from app.nacha.generator import generate_nacha_file, GenerationResult
from app.core.vendor_identity import nacha_receiver_name
from app.nacha.id_field import nacha_id_field
from app.nacha.models import Batch, EntryDetail, FileHeaderConfig, NachaFileInput


class BatchAlreadyProcessedError(Exception):
    """Raised when a batch already committed to a NACHA file is submitted again."""


async def get_next_trace_sequence(db_session: AsyncSession) -> int:
    """
    Peek at the next trace sequence WITHOUT consuming it (for display only).

    Uses ``last_value``/``is_called`` rather than ``nextval`` so calling this to show
    the operator a preview does not burn a trace number.
    """
    row = (await db_session.execute(
        text("SELECT last_value, is_called FROM nacha_trace_sequence")
    )).first()
    if row is None:
        return 1
    last_value, is_called = row[0], row[1]
    return int(last_value) + 1 if is_called else int(last_value)


async def allocate_trace_sequence(db_session: AsyncSession, count: int) -> int:
    """
    Atomically reserve ``count`` consecutive trace numbers and return the first.

    Replaces re-parsing the previous file's text, which collided when two generations
    ran concurrently and silently restarted at 1 whenever the last file was missing or
    unparseable -- re-issuing trace numbers the bank had already seen.

    ``nextval`` is transaction-safe and never hands the same value to two callers, so
    no explicit locking is required.
    """
    if count <= 0:
        raise ValueError("Cannot allocate a non-positive number of trace numbers.")

    rows = (await db_session.execute(
        text("SELECT nextval('nacha_trace_sequence') FROM generate_series(1, :n)"),
        {"n": count},
    )).scalars().all()

    allocated = [int(v) for v in rows]
    first, last = allocated[0], allocated[-1]

    # The trace field is 7 digits (positions 88-94).
    if last > 9_999_999:
        raise ValueError(
            f"Trace sequence {last} exceeds the 7-digit NACHA field. The sequence "
            f"must be reset in coordination with Chase before further files are sent."
        )
    if last - first != count - 1:
        raise ValueError(
            f"Trace number allocation was not contiguous ({first}..{last} for "
            f"{count} entries); refusing to build a file with non-sequential traces."
        )
    return first


async def combine_batches_and_generate_nacha(
    db_session: AsyncSession,
    batch_ids: list[uuid.UUID],
    company_name: str = "AMIPI INC",
    company_account: str = "785957066",
    effective_entry_date: Optional[datetime.date | str] = None,
    file_id_modifier: str = "A",
    trace_sequence_start: Optional[int] = None,
    entry_description: str = "EPAYMNT",
    created_by_user_id: Optional[uuid.UUID] = None,
) -> tuple[NachaFileRecord, GenerationResult]:
    """
    Combine multiple payment batches (e.g. Batch 1 + Batch 2) into a single NACHA file.
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

    # Guard against paying the same batch twice. Once a batch has been written into a
    # NACHA file it is marked PROCESSED; regenerating it would produce a second set of
    # credits for the same invoices.
    already_processed = [
        f"Batch {b.batch_number} ({b.id})"
        for b in ordered_batches
        if b.status == BatchStatus.PROCESSED
    ]
    if already_processed:
        raise BatchAlreadyProcessedError(
            "The following batch(es) have already been included in a generated NACHA "
            "file and cannot be reused: "
            + "; ".join(already_processed)
            + ". Create a new batch instead."
        )

    # Reject duplicate batch ids in a single request for the same reason.
    if len(set(batch_ids)) != len(batch_ids):
        raise ValueError("The same batch was supplied more than once in batch_ids.")

    # File creation date/time in the BANK's timezone (Eastern), not UTC. UTC runs 4-5
    # hours ahead, so it both wrote the wrong clock time and, after ~20:00 ET, stamped
    # the following day's date. AMIPI's real Chase files carry Eastern times.
    file_date_yymmdd, file_time_hhmm = file_creation_stamp()
    today_et = today_bank_time()

    # ---- Effective entry date -------------------------------------------------
    # Resolve to a real date first so it can be validated as a banking day. Nothing
    # previously checked this, and an effective date in the past or on a weekend or
    # Federal Reserve holiday will not settle.
    resolved_effective: Optional[datetime.date] = None
    if isinstance(effective_entry_date, str) and effective_entry_date.strip():
        raw = effective_entry_date.strip().replace("-", "").replace("/", "")
        try:
            if len(raw) == 8:        # YYYYMMDD
                resolved_effective = datetime.datetime.strptime(raw, "%Y%m%d").date()
            elif len(raw) == 6:      # YYMMDD
                resolved_effective = datetime.datetime.strptime(raw, "%y%m%d").date()
            else:
                raise ValueError
        except ValueError:
            raise ValueError(
                f"Effective entry date '{effective_entry_date}' is not a valid date. "
                f"Use YYYY-MM-DD or YYMMDD."
            )
    elif isinstance(effective_entry_date, datetime.date):
        resolved_effective = effective_entry_date

    if resolved_effective is None:
        # Default to the next banking day rather than today. The real transmit files
        # show creation 07/30 -> effective 07/31, i.e. one banking day ahead.
        resolved_effective = default_effective_date(today_et)

    validate_effective_date(resolved_effective, reference=today_et)
    eff_yymmdd = resolved_effective.strftime("%y%m%d")

    nacha_batches: list[Batch] = []
    payments_to_update: list[Payment] = []

    # Resolve every vendor needed by this file in ONE query instead of one query per
    # payment (previously two per payment: once for the entry, once for the remittance).
    all_payments_by_batch: dict[uuid.UUID, list[Payment]] = {}
    needed_vendor_ids: set[uuid.UUID] = set()
    for b in ordered_batches:
        res_payments = await db_session.execute(
            select(Payment).where(Payment.batch_id == b.id).order_by(Payment.created_at.asc())
        )
        bp = list(res_payments.scalars().all())
        if not bp:
            raise ValueError(f"Batch {b.batch_number} ({b.id}) contains no payments.")
        all_payments_by_batch[b.id] = bp
        needed_vendor_ids.update(p.vendor_id for p in bp if p.vendor_id)

    vendor_by_id: dict[uuid.UUID, Vendor] = {}
    if needed_vendor_ids:
        res_v = await db_session.execute(select(Vendor).where(Vendor.id.in_(needed_vendor_ids)))
        vendor_by_id = {v.id: v for v in res_v.scalars().all()}

    for b in ordered_batches:
        batch_payments = all_payments_by_batch[b.id]

        entries: list[EntryDetail] = []
        for p in batch_payments:
            # Previously `scalar_one()`, which raised (HTTP 500) for a payment whose
            # vendor row was missing or whose vendor_id was NULL. Fail with a clear,
            # actionable message instead.
            if not p.vendor_id:
                raise ValueError(
                    f"Payment {p.id} in batch {b.batch_number} has no vendor assigned "
                    f"and cannot be included in a NACHA file."
                )
            vendor = vendor_by_id.get(p.vendor_id)
            if vendor is None:
                raise ValueError(
                    f"Payment {p.id} in batch {b.batch_number} references vendor "
                    f"{p.vendor_id}, which no longer exists."
                )

            # Transaction code: 22 = checking credit, 32 = savings credit
            txcode = "32" if vendor.account_type and vendor.account_type.value == "savings" else "22"

            entries.append(
                EntryDetail(
                    transaction_code=txcode,
                    routing_number=vendor.routing_number,
                    account_number=vendor.account_number,
                    amount=str(p.amount),
                    # The stored id_number is the human-readable reference (it may
                    # contain '/' separators for multi-invoice payments). Chase files
                    # contain ONLY alphanumerics in this field, so derive the written
                    # value here rather than passing the display form through.
                    id_number=nacha_id_field(p.id_number, vendor.account_number),
                    # The 22-character limit belongs to this field, not to the stored vendor name.
                    receiver_name=nacha_receiver_name(vendor.name),
                    discretionary_data="  ",
                    addenda_indicator="0",
                )
            )
            payments_to_update.append(p)

        nacha_batches.append(Batch(entries=entries))

    # ---- Trace numbers --------------------------------------------------------
    # Allocated only now that the exact entry count is known, and reserved atomically
    # from a database sequence so two concurrent generations cannot receive the same
    # numbers. An explicit trace_sequence_start is still honoured for the rare case of
    # deliberately regenerating a file to match one already sent to the bank.
    total_entries = sum(len(b.entries) for b in nacha_batches)
    if trace_sequence_start is None or trace_sequence_start <= 0:
        trace_sequence_start = await allocate_trace_sequence(db_session, total_entries)

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

    # Extract entry detail trace numbers from generated file
    entry_lines = [l for l in lines if l.startswith("6")]

    # Vendors with no email on file get no remittance advice; we record who was skipped
    # rather than inventing an address for them.
    skipped_remittances: list[str] = []

    for idx, p in enumerate(payments_to_update):
        trace_str = entry_lines[idx][79:94] if idx < len(entry_lines) else None
        p.nacha_file_id = nacha_record.id
        p.status = PaymentStatus.PROCESSING
        p.trace_number = trace_str

        vendor_obj = vendor_by_id[p.vendor_id]

        # Only create a remittance when we have a REAL vendor email. The previous
        # fallback invented an address like remittance@<vendorname>.com, which points
        # at a third-party domain AMIPI does not control — sending payment details
        # there would leak data to an unrelated party.
        v_email = (vendor_obj.email or "").strip()
        if not v_email:
            skipped_remittances.append(vendor_obj.name)
            continue

        from app.core.email_templates import ACTIVE_TEMPLATE, render_email_template

        subj, body_text, body_html = render_email_template(
            ACTIVE_TEMPLATE["subject"],
            ACTIVE_TEMPLATE["body"],
            {
                "vendor_name": vendor_obj.name,
                "amount": f"{p.amount:,.2f}",
                "invoice_ref": p.id_number or "N/A",
                "effective_date": p.effective_date.strftime("%m-%d-%Y") if hasattr(p.effective_date, "strftime") else str(p.effective_date),
                "company_name": company_name,
                "payment_method": "ACH/Wire",
                "deposit_ref": trace_str or str(nacha_record.id)[:8],
            },
            invoice_items=p.invoice_breakdown,
        )

        remittance = VendorRemittance(
            vendor_id=vendor_obj.id,
            nacha_file_id=nacha_record.id,
            payment_id=p.id,
            recipient_email=v_email,
            vendor_name=vendor_obj.name,
            amount=p.amount,
            effective_date=p.effective_date,
            invoice_reference=p.id_number,
            trace_number=trace_str,
            subject=subj,
            body_text=body_text,
            body_html=body_html,
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
            "remittances_skipped_no_email": skipped_remittances,
        },
    )
    db_session.add(audit)

    await db_session.commit()
    await db_session.refresh(nacha_record)

    return nacha_record, gen_result
