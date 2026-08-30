"""
Vendor name identity.

A vendor's name is what a spreadsheet row is matched against, so it decides which bank
account a payment reaches. That makes "are these two names the same vendor?" a
money-correctness question, and it needs exactly one answer used everywhere.

Two separate defects made duplicate vendors possible despite a duplicate check:

1. Names were truncated to 22 characters ON WRITE, because the NACHA Entry Detail
   receiver name field is 22 characters wide. Storing the truncated form as the
   vendor's identity means two genuinely different companies whose names share a
   22-character prefix collapse into indistinguishable rows pointing at different bank
   accounts. `INTERNATIONAL DIAMOND ALPHA CORP` and `INTERNATIONAL DIAMOND BRAVO CORP`
   both became `'INTERNATIONAL DIAMOND '`.

   The 22-character limit belongs to the FILE, not to the record. Truncation now
   happens only when the NACHA line is written.

2. The comparison itself was `upper(trim(vendors.name)) = :name`, where the bind
   parameter had been truncated with `[:22]` AFTER whitespace normalisation. When
   character 22 landed on a space, the parameter kept a trailing space that SQL's
   `trim()` had already removed from the stored side, so the two never compared equal
   and the duplicate went in. Normalising both sides identically removes that class of
   bug entirely.

`normalize_vendor_name` is that shared normal form. It is deliberately aggressive --
case, punctuation and whitespace are all discarded -- because the observed real-world
duplicates are `KIRAN GEMS USA INC.` against `KIRAN GEMS USA INC`, and
`B. H. C. DIAMONDS` against `BHC DIAMONDS`.
"""
from __future__ import annotations

import re
import unicodedata

# NACHA Entry Detail positions 55-76: Individual/Receiver name.
NACHA_RECEIVER_NAME_WIDTH = 22

# Generous enough for real legal entity names, which routinely exceed 22 characters.
VENDOR_NAME_MAX_LENGTH = 120

_NON_ALPHANUMERIC = re.compile(r"[^0-9A-Z]+")


def clean_vendor_name(raw: str | None) -> str:
    """
    The form STORED in the database: original characters, tidy whitespace.

    Leading and trailing whitespace is removed and internal runs are collapsed to a
    single space, so 'DUPTEST  GEMS' and 'DUPTEST GEMS' are stored identically. Case and
    punctuation are preserved, because this is the name a human reads and the basis of
    the receiver name written into the file.
    """
    if not raw:
        return ""
    collapsed = " ".join(str(raw).split())
    # Truncate to the column width, then strip again: cutting mid-string can leave a
    # trailing space, which is exactly what defeated the old duplicate check.
    return collapsed[:VENDOR_NAME_MAX_LENGTH].strip()


def normalize_vendor_name(raw: str | None) -> str:
    """
    The form COMPARED for identity. Never stored, never displayed, never written to a file.

    Uppercased, stripped of everything that is not a letter or digit, and reduced to
    ASCII where a compatibility mapping exists. Two names with the same normal form are
    treated as the same vendor.

    Note the deliberate asymmetry with the fuzzy matcher used on spreadsheet rows: that
    matcher REFUSES a non-ASCII name unless it matches exactly, because a Cyrillic
    homograph could otherwise be steered onto a legitimate vendor. Here the normal form
    is only ever used to reject a duplicate, so folding is safe -- the failure mode is
    refusing to create a second record, not paying the wrong account.
    """
    if not raw:
        return ""
    # NFKD separates accents so they can be dropped, mapping e.g. 'É' onto 'E'.
    decomposed = unicodedata.normalize("NFKD", str(raw))
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALPHANUMERIC.sub("", without_marks.upper())


def nacha_receiver_name(raw: str | None) -> str:
    """
    The form WRITTEN to the file: cleaned, then cut to the 22-character field.

    This is the only place the 22-character limit is applied.
    """
    return clean_vendor_name(raw)[:NACHA_RECEIVER_NAME_WIDTH]


# SQL expression matching normalize_vendor_name, for use in queries and in the unique
# index that backs it at the database level. Kept beside the Python implementation so
# the two cannot drift: if one changes, the other is right here.
#
# upper() and regexp_replace() are both IMMUTABLE in PostgreSQL, which is required for
# an expression index. Accent folding is intentionally NOT included here -- unaccent()
# lives in a contrib extension that may not be installed -- so the SQL form is slightly
# more permissive than the Python form. That direction is safe: the database may allow a
# pair the application would reject, and the application check runs first.
SQL_NORMALIZED_NAME = "upper(regexp_replace(name, '[^0-9A-Za-z]+', '', 'g'))"
