"""
Derivation of the Entry Detail "Individual Identification Number" field.

Positions 40-54 of the type-6 record: 15 characters, left justified, space padded.

What the real Chase files actually contain
------------------------------------------
Across all 97 Entry Detail records in AMIPI's transmit files, this field contains
**only alphanumeric characters** -- no ``/``, ``-`` or ``+`` anywhere. Of the purely
numeric values, 26 are the last 5 digits of the receiving account, 12 are the last 4,
and 8 bear no relation to it. The remaining 51 are operator-entered references such as
``INVOICE547549DT`` or the literal ``EPAY``.

Two conclusions follow:

* The field is **operator-driven**, not deterministically derivable. Where no reference
  is supplied the house convention is the tail of the account number, most commonly the
  last 5 digits, which is what ``DEFAULT_ACCOUNT_TAIL_DIGITS`` reproduces.
* Anything non-alphanumeric must be stripped before it is written. The parser produces
  a human-readable multi-invoice reference like ``UDI261954/65/55`` for display, and an
  earlier revision of this code emitted an invented ``875886+2`` overflow marker. Both
  would have differed from Chase byte-for-byte. The readable form is retained for the
  UI and the audit trail; only this function's output reaches the file.

The v7 prototype behaves the same way: ``cleanId()`` strips to ``[A-Za-z0-9]`` and
truncates to 15. Its documented fallback (``acctId``: first 6 digits after removing
leading zeros) matches **none** of the 97 real records, so the account-tail convention
observed in the files is used instead.
"""
from __future__ import annotations

import re
from typing import Optional

# Field width, positions 40-54 of the Entry Detail record.
ID_FIELD_WIDTH = 15

# House convention when no invoice reference exists: the last N digits of the account.
DEFAULT_ACCOUNT_TAIL_DIGITS = 5

# Used when neither a reference nor an account tail is available. Appears verbatim in
# the production files.
FALLBACK_ID = "EPAY"

# Values that carry no payment meaning and must not be written as a reference.
_PLACEHOLDER_REFS = {
    "", "ACH", "CHECK", "EFT", "PMT", "PAYMENT", "BILL", "BILL PMT",
    "BILL PMT -CHECK", "NONE", "N/A", "NA", "EPAY",
}

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]")


def _strip_to_alphanumeric(value: str) -> str:
    return _NON_ALNUM.sub("", str(value or ""))


def account_tail_id(account_number: Optional[str],
                    digits: int = DEFAULT_ACCOUNT_TAIL_DIGITS) -> str:
    """
    The account-derived reference used when no invoice reference exists.

    Returns the last ``digits`` digits of the account number, matching the dominant
    pattern in AMIPI's transmit files.
    """
    numeric = re.sub(r"\D", "", str(account_number or ""))
    if not numeric:
        return FALLBACK_ID
    return numeric[-digits:]


def nacha_id_field(
    invoice_reference: Optional[str],
    account_number: Optional[str] = None,
    *,
    account_tail_digits: int = DEFAULT_ACCOUNT_TAIL_DIGITS,
) -> str:
    """
    Build the 15-character Individual Identification Number.

    An invoice reference wins when present; it is stripped to alphanumerics and
    truncated to 15 characters. Otherwise the account tail is used, and failing that
    the literal ``EPAY``.

    Padding to the field width is left to the record builder, which space-pads all
    left-justified fields.
    """
    reference = str(invoice_reference or "").strip()

    if reference.upper() not in _PLACEHOLDER_REFS:
        cleaned = _strip_to_alphanumeric(reference)[:ID_FIELD_WIDTH]
        if cleaned:
            return cleaned

    tail = account_tail_id(account_number, account_tail_digits)
    return tail[:ID_FIELD_WIDTH] if tail else FALLBACK_ID
