"""
Duplicate Detection Service for Payment Transactions.

Uses SHA-256 financial fingerprints (vendor_id + amount + id_number + effective_date)
to detect existing or intra-batch duplicate payments, supporting an explicit override.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.services.spreadsheet_parser import ParsedPayment, ParsedRowError


def compute_payment_fingerprint(
    vendor_id: uuid.UUID | str,
    amount: Decimal,
    id_number: str,
    effective_date: date,
) -> str:
    """
    Compute a deterministic SHA-256 fingerprint for a payment transaction.

    Fingerprint components:
    - vendor_id (str)
    - amount (formatted to 2 decimal places)
    - id_number (uppercase, stripped)
    - effective_date (ISO format YYYY-MM-DD)
    """
    v_str = str(vendor_id).strip().lower()
    amt_str = f"{Decimal(str(amount)):.2f}"
    id_str = str(id_number or "").strip().upper()
    eff_str = effective_date.isoformat() if isinstance(effective_date, date) else str(effective_date)

    raw_fingerprint = f"{v_str}|{amt_str}|{id_str}|{eff_str}"
    return hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()


async def detect_payment_duplicates(
    parsed_payments: list[ParsedPayment],
    db_session: AsyncSession,
    allow_override: bool = False,
) -> tuple[list[ParsedPayment], list[Any]]:
    """
    Check parsed payments for duplicates against PostgreSQL database and intra-batch rows.

    If allow_override is False:
        - Duplicate rows are separated into errors list.
    If allow_override is True:
        - Duplicate rows are retained in valid_payments, but marked with is_duplicate_override=True.
    """
    from app.models import Payment
    from app.services.spreadsheet_parser import ParsedRowError

    valid_results: list[ParsedPayment] = []
    duplicate_errors: list[ParsedRowError] = []

    # Compute fingerprints for all incoming parsed payments that have a vendor_id
    incoming_fingerprints = []
    for idx, p in enumerate(parsed_payments):
        if p.vendor_id:
            fp = compute_payment_fingerprint(p.vendor_id, p.amount, p.id_number, p.effective_date)
            p.notes = fp  # Temporarily attach fingerprint
            incoming_fingerprints.append(fp)

    # Query DB for matching existing fingerprints
    existing_fps: set[str] = set()
    if incoming_fingerprints:
        res = await db_session.execute(
            select(Payment.fingerprint).where(
                Payment.fingerprint.in_(incoming_fingerprints)
            )
        )
        existing_fps = set(res.scalars().all())

    # Intra-batch duplicate tracking
    seen_batch_fps: set[str] = set()

    for idx, p in enumerate(parsed_payments, 1):
        if not p.vendor_id:
            # Unmatched vendor payments handled earlier in parser validation
            valid_results.append(p)
            continue

        fp = compute_payment_fingerprint(p.vendor_id, p.amount, p.id_number, p.effective_date)
        is_db_dup = fp in existing_fps
        is_batch_dup = fp in seen_batch_fps

        if is_db_dup or is_batch_dup:
            dup_source = "database" if is_db_dup else "current batch upload"
            msg = (
                f"Duplicate payment detected (matches {dup_source}): "
                f"Vendor '{p.vendor_name}', Amount '${p.amount:.2f}', Invoice '{p.id_number}', Date '{p.effective_date}'."
            )

            if allow_override:
                # Explicit override: keep payment, flag override
                p.notes = f"OVERRIDE_DUP:{fp}"
                valid_results.append(p)
            else:
                # Flag as duplicate error
                duplicate_errors.append(
                    ParsedRowError(
                        row_number=idx,
                        raw_data={
                            "vendor": p.vendor_name,
                            "amount": str(p.amount),
                            "invoice": p.id_number,
                            "date": p.effective_date.isoformat(),
                            "fingerprint": fp,
                        },
                        errors=[msg],
                    )
                )
        else:
            seen_batch_fps.add(fp)
            valid_results.append(p)

    return valid_results, duplicate_errors
