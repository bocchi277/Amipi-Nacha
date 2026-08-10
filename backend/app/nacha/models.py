"""
Data models for NACHA file generation.

These are pure Python dataclasses — no ORM, no DB dependency.
They define the structured input the NACHA generator expects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FileHeaderConfig:
    """
    Configuration for the NACHA File Header record (type 1) and
    values that propagate into Batch Header records (type 5).

    Chase-specific fixed values are NOT stored here — they live as
    constants in the generator module itself.
    """

    # Company name — appears in both the File Header (pos 64-86)
    # and the Batch Header (pos 5-20, truncated to 16 chars).
    company_name: str = "AMIPI INC"

    # Chase funding ("pay-from") account number.
    # Becomes the Company Discretionary Data (pos 21-40 in Batch Header),
    # right-justified and zero-filled to 20 characters.
    company_account: str = "785957066"

    # Entry description — e.g. "EPAYMNT".  Placed in Batch Header pos 54-63.
    # Must NOT be "PAYROLL" or "REVERSAL" for CCD batches.
    entry_description: str = "EPAYMNT"

    # Effective entry date in YYMMDD format.
    # Goes into Batch Header pos 70-75 AND pos 64-69 (Company Descriptive Date).
    effective_entry_date: str = ""

    # File creation date in YYMMDD format.
    # Goes into File Header pos 24-29.
    file_creation_date: str = ""

    # File creation time in HHMM format.
    # Goes into File Header pos 30-33.
    file_creation_time: str = ""

    # Single uppercase letter, defaults to 'A'.
    # Goes into File Header pos 34.
    file_id_modifier: str = "A"

    # The starting 7-digit trace sequence number.
    # Entries are assigned incrementing trace numbers starting from this value.
    trace_sequence_start: int = 1


@dataclass
class EntryDetail:
    """
    A single ACH entry (a payment to one vendor).

    All fields are strings exactly as they should appear in the file,
    with the exception of `amount` which is a Decimal-friendly string
    (e.g. "1234.56") that the generator converts to cents.
    """

    # Transaction code: "22" = checking credit, "32" = savings credit.
    transaction_code: str = "22"

    # 9-digit ABA routing number (including check digit).
    routing_number: str = ""

    # Vendor's bank account number (up to 17 chars, left-justified).
    account_number: str = ""

    # Dollar amount as a string like "1234.56".
    amount: str = "0.00"

    # Identification number — up to 15 characters, left-justified, space-padded.
    # This is whatever the caller provides (invoice ref, account-derived ID, "EPAY", etc.).
    id_number: str = "EPAY"

    # Receiver (vendor) name — up to 22 characters, left-justified.
    receiver_name: str = ""

    # Discretionary data — 2 characters, usually blank.
    discretionary_data: str = "  "

    # Addenda record indicator: "0" = no addenda, "1" = has addenda.
    addenda_indicator: str = "0"


@dataclass
class Batch:
    """A batch of entry detail records that share one Batch Header/Control."""

    entries: list[EntryDetail] = field(default_factory=list)


@dataclass
class NachaFileInput:
    """
    Complete input for generating a NACHA file.

    Contains the file/batch header configuration and one or more batches,
    each containing one or more entry details.
    """

    header: FileHeaderConfig = field(default_factory=FileHeaderConfig)
    batches: list[Batch] = field(default_factory=list)
