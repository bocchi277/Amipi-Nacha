"""
NACHA file generator — pure logic, no DB / UI / auth.

Produces a Chase-compliant NACHA flat file from structured input.
All records are 94 characters, separated by CRLF (\\r\\n).
The file is block-padded to a multiple of 10 records using "9" filler lines.

Chase-specific constants
------------------------
    Immediate Destination:    " 021000021"   (leading space + 9 digits)
    Immediate Origin:         "0000000000"   (10 zeros)
    Destination Name:         "JPMORGAN CHASE"
    Company Identification:   "0000000000"
    Originating DFI ID:       "02100002"     (first 8 of Chase routing)
    SEC Code:                 "CCD"
    Record Size:              "094"
    Blocking Factor:          "10"
    Format Code:              "1"

Reference: Chase "cbo_nacha_filespecs May 2020.pdf"
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .models import Batch, EntryDetail, FileHeaderConfig, NachaFileInput
from .validation import ValidationResult, validate_nacha_input


# ---------------------------------------------------------------------------
# Chase-mandated constants
# ---------------------------------------------------------------------------
IMM_DEST = " 021000021"        # pos 4-13  (leading space + routing)
IMM_ORIG = "0000000000"        # pos 14-23
DEST_NAME = "JPMORGAN CHASE"   # pos 41-63 (left-justified, 23 chars)
CO_ID = "0000000000"           # Batch Header pos 41-50
ODFI = "02100002"              # First 8 digits of Chase routing
SEC_CODE = "CCD"               # Standard Entry Class
RECORD_SIZE = "094"
BLOCKING_FACTOR = "10"
FORMAT_CODE = "1"
RECORD_LEN = 94
BLOCK_SIZE = 10
LINE_ENDING = "\r\n"


from decimal import Decimal, InvalidOperation


def _clean_str(value: str) -> str:
    """Sanitize string fields by stripping CRLF, control chars, and non-ASCII chars."""
    if not value:
        return ""
    # Strip carriage returns and line feeds to prevent line injection vulnerabilities
    cleaned = value.replace("\r", "").replace("\n", "").replace("\t", " ")
    # Keep printable ASCII characters only (0x20 to 0x7E)
    cleaned = "".join(c for c in cleaned if 32 <= ord(c) <= 126)
    return cleaned


def _pad_left(value: str, width: int, fill: str = "0") -> str:
    """Right-justify `value` in a field of `width`, padding with `fill` on the left."""
    s = _clean_str(str(value))
    if len(s) >= width:
        return s[-width:]  # truncate from the left if too long
    return fill * (width - len(s)) + s


def _pad_right(value: str, width: int, fill: str = " ") -> str:
    """Left-justify `value` in a field of `width`, padding with `fill` on the right."""
    s = _clean_str(str(value))
    if len(s) >= width:
        return s[:width]  # truncate from the right if too long
    return s + fill * (width - len(s))


def _amount_to_cents(amount_str: str) -> int:
    """Convert a dollar string like '1234.56' to integer cents using Decimal for precision."""
    try:
        d = Decimal(str(amount_str).strip())
        return int((d * Decimal("100")).quantize(Decimal("1")))
    except (InvalidOperation, TypeError, ValueError):
        return 0



# ---------------------------------------------------------------------------
# Record builders
# ---------------------------------------------------------------------------

def _build_file_header(cfg: FileHeaderConfig) -> str:
    """
    Build the File Header Record (type 1).

    Layout (94 chars total):
        1       Record type "1"
        2-3     Priority code "01"
        4-13    Immediate destination (b021000021)
        14-23   Immediate origin (0000000000)
        24-29   File creation date (YYMMDD)
        30-33   File creation time (HHMM)
        34      File ID modifier
        35-37   Record size "094"
        38-39   Blocking factor "10"
        40      Format code "1"
        41-63   Immediate destination name (23 chars, left-justified)
        64-86   Immediate origin name (23 chars, left-justified)
        87-94   Reference code (8 blanks)
    """
    rec = (
        "1"                                                # 1       Record type
        + "01"                                             # 2-3     Priority code
        + IMM_DEST                                         # 4-13    Immediate dest
        + IMM_ORIG                                         # 14-23   Immediate origin
        + cfg.file_creation_date                           # 24-29   File creation date
        + cfg.file_creation_time                           # 30-33   File creation time
        + cfg.file_id_modifier                             # 34      File ID modifier
        + RECORD_SIZE                                      # 35-37   Record size
        + BLOCKING_FACTOR                                  # 38-39   Blocking factor
        + FORMAT_CODE                                      # 40      Format code
        + _pad_right(DEST_NAME, 23)                        # 41-63   Dest name
        + _pad_right(cfg.company_name, 23)                 # 64-86   Origin name
        + " " * 8                                          # 87-94   Reference code
    )
    assert len(rec) == RECORD_LEN, f"File header is {len(rec)} chars, expected {RECORD_LEN}"
    return rec


def _build_batch_header(cfg: FileHeaderConfig, batch_number: int) -> str:
    """
    Build a Batch Header Record (type 5).

    Layout (94 chars total):
        1       Record type "5"
        2-4     Service class code "220" (all credits)
        5-20    Company name (16 chars, left-justified)
        21-40   Company discretionary data (20 chars, right-justified zero-filled acct)
        41-50   Company identification "0000000000"
        51-53   SEC code "CCD"
        54-63   Company entry description (10 chars, left-justified)
        64-69   Company descriptive date (= effective date in AMIPI's usage)
        70-75   Effective entry date (YYMMDD)
        76-78   Settlement date (3 blanks — filled by ACH operator)
        79      Originator status code "1"
        80-87   Originating DFI identification "02100002"
        88-94   Batch number (7 digits, zero-padded)
    """
    disc_data = _pad_left(cfg.company_account.replace(" ", ""), 20, "0")
    entry_desc = _pad_right((cfg.entry_description or "EPAYMNT").upper(), 10)

    rec = (
        "5"                                                # 1       Record type
        + "220"                                            # 2-4     Service class (credits)
        + _pad_right(cfg.company_name, 16)                 # 5-20    Company name
        + disc_data                                        # 21-40   Discretionary data
        + CO_ID                                            # 41-50   Company ID
        + SEC_CODE                                         # 51-53   SEC code
        + entry_desc                                       # 54-63   Entry description
        + cfg.effective_entry_date                         # 64-69   Descriptive date
        + cfg.effective_entry_date                         # 70-75   Effective entry date
        + "   "                                            # 76-78   Settlement date (blank)
        + "1"                                              # 79      Originator status
        + ODFI                                             # 80-87   ODFI
        + _pad_left(str(batch_number), 7)                  # 88-94   Batch number
    )
    assert len(rec) == RECORD_LEN, f"Batch header is {len(rec)} chars, expected {RECORD_LEN}"
    return rec


def _build_entry_detail(entry: EntryDetail, trace_number: int) -> str:
    """
    Build an Entry Detail Record (type 6).

    Layout (94 chars total):
        1       Record type "6"
        2-3     Transaction code
        4-11    Receiving DFI ID (first 8 digits of routing)
        12      Check digit (9th digit of routing)
        13-29   DFI account number (17 chars, left-justified)
        30-39   Amount (10 digits, right-justified zero-filled, in cents)
        40-54   Individual ID number (15 chars, left-justified)
        55-76   Individual name (22 chars, left-justified)
        77-78   Discretionary data (2 chars)
        79      Addenda record indicator
        80-94   Trace number (ODFI 8 digits + 7-digit sequence)
    """
    routing = entry.routing_number.replace(" ", "")
    routing_dfi = routing[:8]      # First 8 digits → Receiving DFI
    check_digit = routing[8]       # 9th digit → Check digit
    amt_cents = _amount_to_cents(entry.amount)

    rec = (
        "6"                                                # 1       Record type
        + entry.transaction_code                           # 2-3     Transaction code
        + routing_dfi                                      # 4-11    Receiving DFI
        + check_digit                                      # 12      Check digit
        + _pad_right(entry.account_number, 17)             # 13-29   Account number
        + _pad_left(str(amt_cents), 10)                    # 30-39   Amount (cents)
        + _pad_right(entry.id_number or "EPAY", 15)       # 40-54   ID number
        + _pad_right(entry.receiver_name, 22)              # 55-76   Receiver name
        + entry.discretionary_data                         # 77-78   Discretionary data
        + entry.addenda_indicator                          # 79      Addenda indicator
        + ODFI                                             # 80-87   Trace: ODFI
        + _pad_left(str(trace_number), 7)                  # 88-94   Trace: sequence
    )
    assert len(rec) == RECORD_LEN, f"Entry detail is {len(rec)} chars, expected {RECORD_LEN}"
    return rec


def _build_batch_control(
    service_class: str,
    entry_count: int,
    entry_hash: int,
    total_debit: int,
    total_credit: int,
    batch_number: int,
) -> str:
    """
    Build a Batch Control Record (type 8).

    Layout (94 chars total):
        1       Record type "8"
        2-4     Service class code
        5-10    Entry/addenda count (6 digits)
        11-20   Entry hash (10 digits, right-most 10 of sum)
        21-32   Total debit dollar amount (12 digits, in cents)
        33-44   Total credit dollar amount (12 digits, in cents)
        45-54   Company identification "0000000000"
        55-73   Message authentication code (19 blanks)
        74-79   Reserved (6 blanks)
        80-87   Originating DFI identification
        88-94   Batch number (7 digits)
    """
    # Hash truncated to rightmost 10 digits
    hash_str = _pad_left(str(entry_hash % 10_000_000_000), 10)

    rec = (
        "8"                                                # 1       Record type
        + service_class                                    # 2-4     Service class
        + _pad_left(str(entry_count), 6)                   # 5-10    Entry count
        + hash_str                                         # 11-20   Entry hash
        + _pad_left(str(total_debit), 12)                  # 21-32   Total debit
        + _pad_left(str(total_credit), 12)                 # 33-44   Total credit
        + CO_ID                                            # 45-54   Company ID
        + " " * 19                                         # 55-73   MAC (blank)
        + " " * 6                                          # 74-79   Reserved (blank)
        + ODFI                                             # 80-87   ODFI
        + _pad_left(str(batch_number), 7)                  # 88-94   Batch number
    )
    assert len(rec) == RECORD_LEN, f"Batch control is {len(rec)} chars, expected {RECORD_LEN}"
    return rec


def _build_file_control(
    batch_count: int,
    block_count: int,
    entry_addenda_count: int,
    entry_hash: int,
    total_debit: int,
    total_credit: int,
) -> str:
    """
    Build the File Control Record (type 9).

    Layout (94 chars total):
        1       Record type "9"
        2-7     Batch count (6 digits)
        8-13    Block count (6 digits)
        14-21   Entry/addenda count (8 digits)
        22-31   Entry hash (10 digits)
        32-43   Total debit dollar amount (12 digits)
        44-55   Total credit dollar amount (12 digits)
        56-94   Reserved (39 blanks)
    """
    hash_str = _pad_left(str(entry_hash % 10_000_000_000), 10)

    rec = (
        "9"                                                # 1       Record type
        + _pad_left(str(batch_count), 6)                   # 2-7     Batch count
        + _pad_left(str(block_count), 6)                   # 8-13    Block count
        + _pad_left(str(entry_addenda_count), 8)           # 14-21   Entry/addenda count
        + hash_str                                         # 22-31   Entry hash
        + _pad_left(str(total_debit), 12)                  # 32-43   Total debit
        + _pad_left(str(total_credit), 12)                 # 44-55   Total credit
        + " " * 39                                         # 56-94   Reserved
    )
    assert len(rec) == RECORD_LEN, f"File control is {len(rec)} chars, expected {RECORD_LEN}"
    return rec


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class GenerationResult:
    """Result of a NACHA file generation attempt."""
    success: bool
    content: str = ""            # The full NACHA file content (only when success=True)
    validation: Optional[ValidationResult] = None  # Populated when validation fails
    record_count: int = 0        # Number of records (excluding filler)
    final_trace_number: int = 0  # The last trace sequence number used


def generate_nacha_file(
    inp: NachaFileInput,
    *,
    skip_validation: bool = False,
) -> GenerationResult:
    """
    Generate a complete NACHA file from structured input.

    Parameters
    ----------
    inp : NachaFileInput
        The complete file specification.
    skip_validation : bool
        If True, skip input validation. Use only when you've already validated.

    Returns
    -------
    GenerationResult
        On success, .content contains the full NACHA file text.
        On failure, .validation contains the error details.
    """
    # ── Validate ──────────────────────────────────────────────────────────
    if not skip_validation:
        vr = validate_nacha_input(inp)
        if not vr.is_valid:
            return GenerationResult(success=False, validation=vr)

    cfg = inp.header
    records: list[str] = []
    trace_seq = cfg.trace_sequence_start

    # ── File Header ───────────────────────────────────────────────────────
    records.append(_build_file_header(cfg))

    # ── Batches ───────────────────────────────────────────────────────────
    file_hash = 0
    file_credit = 0
    file_debit = 0
    file_entry_count = 0

    for bi, batch in enumerate(inp.batches, start=1):
        # Batch Header
        records.append(_build_batch_header(cfg, bi))

        batch_hash = 0
        batch_credit = 0
        batch_debit = 0
        batch_entry_count = 0

        for entry in batch.entries:
            routing = entry.routing_number.replace(" ", "")
            routing_dfi_int = int(routing[:8])
            amt_cents = _amount_to_cents(entry.amount)

            records.append(_build_entry_detail(entry, trace_seq))

            batch_hash += routing_dfi_int
            # CCD credits: amount goes to credit total; debit total stays 0
            # (transaction codes 22 and 32 are both credits)
            batch_credit += amt_cents
            batch_entry_count += 1
            trace_seq += 1

        # Batch Control
        records.append(_build_batch_control(
            service_class="220",
            entry_count=batch_entry_count,
            entry_hash=batch_hash,
            total_debit=batch_debit,
            total_credit=batch_credit,
            batch_number=bi,
        ))

        file_hash += batch_hash
        file_credit += batch_credit
        file_debit += batch_debit
        file_entry_count += batch_entry_count

    # ── File Control ──────────────────────────────────────────────────────
    batch_count = len(inp.batches)
    # Block count: ceiling of (total records including file control) / 10
    total_records_before_padding = len(records) + 1  # +1 for file control itself
    block_count = math.ceil(total_records_before_padding / BLOCK_SIZE)

    records.append(_build_file_control(
        batch_count=batch_count,
        block_count=block_count,
        entry_addenda_count=file_entry_count,
        entry_hash=file_hash,
        total_debit=file_debit,
        total_credit=file_credit,
    ))

    # ── Blocking / padding ────────────────────────────────────────────────
    # Pad to a multiple of BLOCK_SIZE (10) records with "9"-filled lines.
    records_needed = block_count * BLOCK_SIZE
    filler_count = records_needed - len(records)
    for _ in range(filler_count):
        records.append("9" * RECORD_LEN)

    # ── Assemble ──────────────────────────────────────────────────────────
    # Sanity: every record must be exactly 94 characters
    for i, rec in enumerate(records):
        assert len(rec) == RECORD_LEN, (
            f"Record {i} has {len(rec)} chars (expected {RECORD_LEN}): {rec!r}"
        )

    content = LINE_ENDING.join(records) + LINE_ENDING

    return GenerationResult(
        success=True,
        content=content,
        record_count=len(records),
        final_trace_number=trace_seq - 1,
    )
