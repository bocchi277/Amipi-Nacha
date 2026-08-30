"""
Regression guards for the pre-production hardening pass (items 3-8).

Each test names the concrete risk it protects against. Several assert *parity with
AMIPI's real Chase transmit files*, because the acceptance criterion for this tool is
producing the same output as the Chase subscription it replaces.
"""
from datetime import date, datetime

import pytest

from app.core.business_dates import (
    EffectiveDateError,
    default_effective_date,
    federal_reserve_holidays,
    file_creation_stamp,
    is_banking_day,
    next_banking_day,
    validate_effective_date,
)
from app.nacha.generator import NachaRecordLengthError, _require_record_length
from app.nacha.id_field import account_tail_id, nacha_id_field
from app.services.spreadsheet_parser import _compress_invoices, _is_account_number_bleed


# ---------------------------------------------------------------------------
# Item 3: record-length invariants must survive python -O
# ---------------------------------------------------------------------------

def test_record_length_violation_raises_rather_than_asserting():
    """
    Risk: the 94-character guarantee was enforced with `assert`, which python -O strips
    entirely. Running the server optimised would have silently removed the only check
    that the file is well formed.
    """
    with pytest.raises(NachaRecordLengthError) as exc:
        _require_record_length("too short", "Probe record")
    assert "94" in str(exc.value)

    # A correct record passes through unchanged.
    ok = "6" * 94
    assert _require_record_length(ok, "Probe record") == ok


def test_generator_module_contains_no_assert_statements():
    """asserts in the money path are removed at runtime under -O, so none may remain."""
    import ast
    import inspect

    import app.nacha.generator as generator

    tree = ast.parse(inspect.getsource(generator))
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    assert not asserts, (
        f"{len(asserts)} assert statement(s) remain in the NACHA generator; "
        f"python -O would delete them"
    )


# ---------------------------------------------------------------------------
# Item 4: Eastern time, not UTC
# ---------------------------------------------------------------------------

def test_file_creation_stamp_uses_eastern_time_not_utc():
    """
    Risk: creation date/time came from UTC. AMIPI's real 07.30.2026 file carries
    `2607301328` (13:28 ET). UTC runs 4-5 hours ahead, so besides the wrong clock time
    any file produced after ~20:00 ET was stamped with the FOLLOWING day's date.
    """
    # 21:30 ET on 30 Aug is already 01:30 UTC on 31 Aug.
    from zoneinfo import ZoneInfo

    evening_et = datetime(2026, 8, 30, 21, 30, tzinfo=ZoneInfo("America/New_York"))
    stamp_date, stamp_time = file_creation_stamp(evening_et)
    assert stamp_date == "260830", f"date must stay on the ET day, got {stamp_date}"
    assert stamp_time == "2130", stamp_time

    # And the UTC rendering of the same instant would have been wrong.
    assert evening_et.astimezone(ZoneInfo("UTC")).strftime("%y%m%d") == "260831"


def test_file_creation_stamp_is_dst_aware():
    from zoneinfo import ZoneInfo

    winter = datetime(2026, 1, 15, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    summer = datetime(2026, 7, 15, 12, 0, tzinfo=ZoneInfo("America/New_York"))
    assert file_creation_stamp(winter) == ("260115", "1200")
    assert file_creation_stamp(summer) == ("260715", "1200")


# ---------------------------------------------------------------------------
# Item 5: the 15-character ID field must match Chase byte-for-byte
# ---------------------------------------------------------------------------

def test_nacha_id_field_is_always_alphanumeric_and_within_15_chars():
    """
    Risk: all 97 ID fields in AMIPI's real transmit files are purely alphanumeric. The
    parser produces a readable multi-invoice reference containing '/', and an earlier
    revision of this code emitted an invented '875886+2' overflow marker. Either would
    have broken byte parity with the tool being replaced.
    """
    readable_forms = [
        "UDI261954/65/55",
        "875886/2425708/876153",
        "SI-5872/919/871",
        "INV-7788",
        "INVOICE 1139 DTD 07/30",
    ]
    for ref in readable_forms:
        written = nacha_id_field(ref, "918025393")
        assert written.isalnum(), f"{ref!r} produced non-alphanumeric {written!r}"
        assert len(written) <= 15, f"{ref!r} produced {len(written)} chars: {written!r}"
        assert "/" not in written and "+" not in written and "-" not in written


def test_nacha_id_field_falls_back_to_account_tail_matching_real_files():
    """
    With no invoice reference the house convention is the tail of the account number.
    These three pairs are read directly out of the real transmit files.
    """
    # (account number, ID field actually present in the Chase file)
    from_real_files = [
        ("731138338", "38338"),
        ("385016029033", "29033"),
        ("706312066", "12066"),
    ]
    for account, expected in from_real_files:
        assert account_tail_id(account) == expected
        assert nacha_id_field(None, account) == expected
        assert nacha_id_field("", account) == expected
        # "EPAY" is a placeholder, not a reference, so it must not be written verbatim
        # when a real account tail is available.
        assert nacha_id_field("EPAY", account) == expected


def test_nacha_id_field_prefers_an_explicit_invoice_reference():
    assert nacha_id_field("INVOICE1139DTD0", "918025393") == "INVOICE1139DTD0"
    # Truncation happens at the field width, after separators are removed.
    assert nacha_id_field("INVOICE-2026-000123456789", "918025393") == "INVOICE20260001"


def test_nacha_id_field_uses_epay_when_nothing_is_available():
    assert nacha_id_field(None, None) == "EPAY"
    assert nacha_id_field("", "") == "EPAY"
    assert nacha_id_field("N/A", None) == "EPAY"


# ---------------------------------------------------------------------------
# Item 6: prototype parser behaviours
# ---------------------------------------------------------------------------

def test_account_number_in_the_reference_column_is_not_written_to_the_file():
    """
    Risk: QuickBooks exports sometimes carry the bank account in the reference column.
    Writing it into the ID field tells the vendor nothing about which invoice was paid
    and duplicates the account number into a second field of the file.
    """
    account = "385016029033"
    assert _is_account_number_bleed("385016029033", account) is True
    assert _is_account_number_bleed("385016", account) is True

    # Must NOT reject legitimate values:
    assert _is_account_number_bleed("29033", account) is False       # account tail
    assert _is_account_number_bleed("38501", account) is False       # under 6 digits
    assert _is_account_number_bleed("1139", "918025393") is False    # short invoice no.
    assert _is_account_number_bleed("INVOICE1139", "918025393") is False
    assert _is_account_number_bleed("2425708", account) is False     # unrelated invoice


def test_compressed_reference_no_longer_invents_an_overflow_marker():
    """The '+N' marker was this codebase's invention and appears in no Chase file."""
    got = _compress_invoices(["875886", "2425708", "876153"])
    assert "+" not in got, f"overflow marker must be gone, got {got!r}"
    # Every invoice stays present in the readable reference.
    for invoice in ("875886", "2425708", "876153"):
        assert invoice in got, f"{invoice} lost from {got!r}"


def test_common_prefix_compression_still_keeps_every_invoice_identifiable():
    assert _compress_invoices(["UDI261954", "UDI261965", "UDI261955"]) == "UDI261954/65/55"


# ---------------------------------------------------------------------------
# Item 8: banking calendar
# ---------------------------------------------------------------------------

def test_2026_federal_reserve_holidays_are_correct():
    """Verified against the published Federal Reserve Bank holiday schedule."""
    expected = {
        date(2026, 1, 1),    # New Year's Day
        date(2026, 1, 19),   # Martin Luther King Jr. Day
        date(2026, 2, 16),   # Washington's Birthday
        date(2026, 5, 25),   # Memorial Day
        date(2026, 6, 19),   # Juneteenth
        date(2026, 9, 7),    # Labor Day
        date(2026, 10, 12),  # Columbus Day
        date(2026, 11, 11),  # Veterans Day
        date(2026, 11, 26),  # Thanksgiving
        date(2026, 12, 25),  # Christmas
    }
    assert federal_reserve_holidays(2026) == frozenset(expected)


def test_saturday_holiday_is_not_shifted_but_sunday_is():
    """
    The Reserve Banks differ from other federal agencies: a Saturday holiday leaves them
    open the preceding Friday, while a Sunday holiday closes them the following Monday.
    """
    # 4 July 2026 falls on a Saturday -> no weekday closure.
    assert date(2026, 7, 4).weekday() == 5
    assert date(2026, 7, 3) not in federal_reserve_holidays(2026)

    # 4 July 2027 falls on a Sunday -> observed Monday 5 July.
    assert date(2027, 7, 4).weekday() == 6
    assert date(2027, 7, 5) in federal_reserve_holidays(2027)


def test_effective_date_defaults_to_next_banking_day_like_the_real_files():
    """The real files show creation 07/30/2026 -> effective 07/31/2026."""
    assert default_effective_date(date(2026, 7, 30)) == date(2026, 7, 31)
    # Friday rolls past the weekend.
    assert default_effective_date(date(2026, 7, 31)) == date(2026, 8, 3)
    # And skips holidays: Wed 25 Nov -> Fri 27 Nov, stepping over Thanksgiving.
    assert default_effective_date(date(2026, 11, 25)) == date(2026, 11, 27)


def test_effective_date_validation_rejects_unusable_dates():
    """
    Risk: nothing validated the effective entry date, and the parser used the
    QuickBooks bill date -- frequently in the past -- as the ACH effective date. Chase
    rejects stale effective dates and ACH does not settle at weekends or on holidays.
    """
    reference = date(2026, 11, 20)

    for bad, reason in [
        (date(2026, 11, 19), "past"),
        (date(2026, 11, 28), "Saturday"),
        (date(2026, 11, 29), "Sunday"),
        (date(2026, 11, 26), "Thanksgiving"),
        (date(2030, 1, 1), "absurdly far ahead"),
    ]:
        with pytest.raises(EffectiveDateError):
            validate_effective_date(bad, reference=reference)

    # Ordinary banking days pass, including today.
    validate_effective_date(date(2026, 11, 20), reference=reference)
    validate_effective_date(date(2026, 11, 23), reference=reference)


def test_is_banking_day_excludes_weekends_and_holidays():
    assert is_banking_day(date(2026, 7, 31)) is True     # Friday
    assert is_banking_day(date(2026, 8, 1)) is False     # Saturday
    assert is_banking_day(date(2026, 8, 2)) is False     # Sunday
    assert is_banking_day(date(2026, 11, 26)) is False   # Thanksgiving
    assert next_banking_day(date(2026, 8, 1), 0) == date(2026, 8, 3)
