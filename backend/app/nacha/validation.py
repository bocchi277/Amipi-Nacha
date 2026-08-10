"""
NACHA validation helpers.

Provides field-level validation against the Chase NACHA File Specification
(May 2020).  Used by the generator to fail loudly before producing output.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import EntryDetail, FileHeaderConfig, NachaFileInput


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    """A single validation failure."""
    location: str  # e.g. "File Header", "Batch 1 Entry 3"
    field: str  # e.g. "routing_number"
    message: str  # human-readable explanation


@dataclass
class ValidationResult:
    errors: list[ValidationError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add(self, location: str, field_name: str, message: str) -> None:
        self.errors.append(ValidationError(location, field_name, message))

    def __str__(self) -> str:
        if self.is_valid:
            return "Validation passed."
        lines = [f"Validation failed with {len(self.errors)} error(s):"]
        for e in self.errors:
            lines.append(f"  [{e.location}] {e.field}: {e.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# ABA routing-number check-digit validation
# ---------------------------------------------------------------------------

def validate_routing_checksum(routing: str) -> bool:
    """
    Validate the 9-digit ABA routing number check digit.

    The check digit (9th digit) is computed as:
        (3*(d1+d4+d7) + 7*(d2+d5+d8) + (d3+d6+d9)) mod 10 == 0
    """
    if len(routing) != 9 or not routing.isdigit():
        return False
    d = [int(c) for c in routing]
    checksum = (
        3 * (d[0] + d[3] + d[6])
        + 7 * (d[1] + d[4] + d[7])
        + 1 * (d[2] + d[5] + d[8])
    )
    return checksum % 10 == 0


# ---------------------------------------------------------------------------
# Main validator
# ---------------------------------------------------------------------------

def validate_nacha_input(inp: NachaFileInput) -> ValidationResult:
    """
    Validate all fields of a NachaFileInput against the Chase NACHA spec.

    Returns a ValidationResult — check .is_valid before proceeding.
    """
    result = ValidationResult()
    h = inp.header

    # -- File Header fields --------------------------------------------------
    if not h.company_name or not h.company_name.strip():
        result.add("File Header", "company_name", "Company name is required.")

    if not h.company_account or not h.company_account.strip():
        result.add("File Header", "company_account", "Chase pay-from account number is required.")

    eff = h.effective_entry_date
    if not eff or len(eff) != 6 or not eff.isdigit():
        result.add("File Header", "effective_entry_date",
                    "Effective entry date must be exactly 6 digits in YYMMDD format.")

    fcd = h.file_creation_date
    if not fcd or len(fcd) != 6 or not fcd.isdigit():
        result.add("File Header", "file_creation_date",
                    "File creation date must be exactly 6 digits in YYMMDD format.")

    fct = h.file_creation_time
    if not fct or len(fct) != 4 or not fct.isdigit():
        result.add("File Header", "file_creation_time",
                    "File creation time must be exactly 4 digits in HHMM format.")

    fid = h.file_id_modifier
    if not fid or len(fid) != 1 or not fid.isalnum():
        result.add("File Header", "file_id_modifier",
                    "File ID modifier must be a single alphanumeric character.")

    desc = (h.entry_description or "").upper()
    if desc in ("PAYROLL", "REVERSAL"):
        result.add("File Header", "entry_description",
                    f'Entry description cannot be "{desc}" for CCD batches.')
    # Additional Chase-rejected descriptions
    if desc in ("NONSETTLED", "RECLAIM", "RETRY PMT", "RETURN FEE"):
        result.add("File Header", "entry_description",
                    f'Entry description "{desc}" is not supported by Chase.')

    if h.trace_sequence_start < 1:
        result.add("File Header", "trace_sequence_start",
                    "Trace sequence start must be >= 1.")

    # -- Batches -------------------------------------------------------------
    if not inp.batches:
        result.add("File", "batches", "At least one batch is required.")

    for bi, batch in enumerate(inp.batches, start=1):
        bloc = f"Batch {bi}"
        if not batch.entries:
            result.add(bloc, "entries", "Batch must contain at least one entry.")

        for ei, entry in enumerate(batch.entries, start=1):
            eloc = f"Batch {bi} Entry {ei}"
            _validate_entry(entry, eloc, result)

    return result


def _validate_entry(entry: EntryDetail, location: str, result: ValidationResult) -> None:
    """Validate a single EntryDetail record."""

    # Transaction code
    if entry.transaction_code not in ("22", "32"):
        result.add(location, "transaction_code",
                    f'Transaction code must be "22" (checking) or "32" (savings), '
                    f'got "{entry.transaction_code}".')

    # Routing number — must be 9 digits and pass checksum
    rt = entry.routing_number.replace(" ", "")
    if len(rt) != 9 or not rt.isdigit():
        result.add(location, "routing_number",
                    f"Routing number must be exactly 9 digits, got \"{rt}\".")
    elif not validate_routing_checksum(rt):
        result.add(location, "routing_number",
                    f"Routing number \"{rt}\" fails ABA check-digit validation.")

    # Account number — must not be empty, max 17 chars
    acct = entry.account_number.strip()
    if not acct:
        result.add(location, "account_number", "Account number is required.")
    elif len(acct) > 17:
        result.add(location, "account_number",
                    f"Account number must be ≤ 17 characters, got {len(acct)}.")

    # Control char check
    if "\r" in entry.receiver_name or "\n" in entry.receiver_name:
        result.add(location, "receiver_name", "Receiver name contains invalid newline/control characters.")
    if "\r" in entry.account_number or "\n" in entry.account_number:
        result.add(location, "account_number", "Account number contains invalid newline/control characters.")
    if "\r" in entry.id_number or "\n" in entry.id_number:
        result.add(location, "id_number", "ID number contains invalid newline/control characters.")

    # Amount — must be a positive number
    try:
        from decimal import Decimal, InvalidOperation
        d_amt = Decimal(str(entry.amount).strip())
        amt_cents = int((d_amt * Decimal("100")).quantize(Decimal("1")))
        if amt_cents <= 0:
            result.add(location, "amount",
                        f"Amount must be > 0, got {entry.amount}.")
        if amt_cents > 9_999_999_999:  # 10 digits max in the amount field
            result.add(location, "amount",
                        f"Amount exceeds maximum (99,999,999.99), got {entry.amount}.")
    except (InvalidOperation, ValueError, TypeError):
        result.add(location, "amount",
                    f'Amount is not a valid decimal number: "{entry.amount}".')

    # ID number — max 15 chars
    id_num = entry.id_number or ""
    if len(id_num) > 15:
        result.add(location, "id_number",
                    f"ID number must be ≤ 15 characters, got {len(id_num)}.")

    # Receiver name — must not be empty, max 22 chars
    name = entry.receiver_name.strip()
    if not name:
        result.add(location, "receiver_name", "Receiver name is required.")
    elif len(name) > 22:
        result.add(location, "receiver_name",
                    f"Receiver name must be ≤ 22 characters, got {len(name)}.")
