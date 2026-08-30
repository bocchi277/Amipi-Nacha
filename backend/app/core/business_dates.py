"""
Banking calendar and time-of-day helpers.

Two separate problems live here because they are both "what date does the bank think
it is" questions:

1. **File creation timestamp.** The File Header's creation date (positions 24-29) and
   time (30-33) were generated from ``datetime.now(timezone.utc)``. AMIPI operates in
   Eastern time and the real Chase transmit files reflect that -- the 07.30.2026 file
   carries ``2607301328``, i.e. 13:28 ET. UTC runs 4-5 hours ahead, so besides the
   wrong clock time, any file produced after ~20:00 ET was stamped with the FOLLOWING
   day's date. The prototype used the operator's local browser time, which in practice
   was Eastern; this module makes that explicit and DST-correct rather than incidental.

2. **Effective entry date.** ACH credits settle on a banking day. Nothing previously
   validated the effective entry date, and the spreadsheet parser used the QuickBooks
   *bill* date -- frequently in the past -- as the ACH effective date. Chase rejects
   stale effective dates, so this module supplies the next valid banking day and a
   validator.

Holiday rules follow the Federal Reserve Bank schedule, which differs from the general
federal holiday schedule: when a fixed-date holiday falls on a **Sunday** the Reserve
Banks close the following Monday, but when it falls on a **Saturday** they remain open
the preceding Friday.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

# AMIPI's operating timezone, and the timezone Chase files are stamped in.
BANK_TIMEZONE = ZoneInfo("America/New_York")

# ACH files must be dated at least this many banking days ahead.
DEFAULT_LEAD_BANKING_DAYS = 1

# Refuse absurd future dates; NACHA effective dates are near-term by nature.
MAX_EFFECTIVE_DATE_DAYS_AHEAD = 60


class EffectiveDateError(ValueError):
    """Raised when an effective entry date is not a usable banking day."""


# ---------------------------------------------------------------------------
# Current time in the bank's timezone
# ---------------------------------------------------------------------------

def now_bank_time() -> datetime:
    """Current time in the bank's timezone (Eastern, DST-aware)."""
    return datetime.now(BANK_TIMEZONE)


def today_bank_time() -> date:
    """Today's date as the bank sees it, not as UTC sees it."""
    return now_bank_time().date()


def file_creation_stamp(moment: datetime | None = None) -> tuple[str, str]:
    """
    Return ``(YYMMDD, HHMM)`` for the File Header creation fields, in Eastern time.

    Passing ``moment`` allows deterministic tests.
    """
    if moment is None:
        moment = now_bank_time()
    elif moment.tzinfo is None:
        moment = moment.replace(tzinfo=BANK_TIMEZONE)
    else:
        moment = moment.astimezone(BANK_TIMEZONE)
    return moment.strftime("%y%m%d"), moment.strftime("%H%M")


# ---------------------------------------------------------------------------
# Federal Reserve holiday calendar
# ---------------------------------------------------------------------------

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth given weekday of a month (weekday: Monday=0)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


@lru_cache(maxsize=64)
def federal_reserve_holidays(year: int) -> frozenset[date]:
    """
    Dates on which the Federal Reserve Banks are closed, so ACH does not settle.

    Fixed-date holidays falling on a Sunday are observed the following Monday. Ones
    falling on a Saturday are NOT shifted, because the Reserve Banks stay open the
    preceding Friday.
    """
    fixed = [
        date(year, 1, 1),    # New Year's Day
        date(year, 6, 19),   # Juneteenth National Independence Day
        date(year, 7, 4),    # Independence Day
        date(year, 11, 11),  # Veterans Day
        date(year, 12, 25),  # Christmas Day
    ]

    observed: set[date] = set()
    for holiday in fixed:
        if holiday.weekday() == 6:      # Sunday -> observed Monday
            observed.add(holiday + timedelta(days=1))
        elif holiday.weekday() == 5:    # Saturday -> Reserve Banks open Friday
            continue
        else:
            observed.add(holiday)

    # Floating holidays always land on a weekday.
    observed.update({
        _nth_weekday(year, 1, 0, 3),    # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),    # Washington's Birthday
        _last_weekday(year, 5, 0),      # Memorial Day
        _nth_weekday(year, 9, 0, 1),    # Labor Day
        _nth_weekday(year, 10, 0, 2),   # Columbus Day
        _nth_weekday(year, 11, 3, 4),   # Thanksgiving Day
    })

    return frozenset(observed)


def is_banking_day(value: date) -> bool:
    """True when ACH settles on this date (weekday and not a Reserve Bank holiday)."""
    if value.weekday() >= 5:
        return False
    return value not in federal_reserve_holidays(value.year)


def next_banking_day(start: date, lead_days: int = DEFAULT_LEAD_BANKING_DAYS) -> date:
    """
    The banking day ``lead_days`` banking days after ``start``.

    ``lead_days=0`` returns ``start`` itself when it is already a banking day,
    otherwise the next one.
    """
    result = start
    if lead_days <= 0:
        while not is_banking_day(result):
            result += timedelta(days=1)
        return result

    remaining = lead_days
    while remaining > 0:
        result += timedelta(days=1)
        if is_banking_day(result):
            remaining -= 1
    return result


def default_effective_date(reference: date | None = None) -> date:
    """The effective entry date to use when the caller did not supply one."""
    return next_banking_day(reference or today_bank_time(), DEFAULT_LEAD_BANKING_DAYS)


def validate_effective_date(value: date, reference: date | None = None) -> None:
    """
    Raise :class:`EffectiveDateError` when ``value`` is not a usable effective date.

    Rejects dates in the past, weekends, Reserve Bank holidays, and dates absurdly far
    in the future. Today is permitted (same-day origination depends on the customer's
    cut-off with Chase, so this is a business decision rather than a hard rule) but
    anything earlier is not.
    """
    today = reference or today_bank_time()

    if value < today:
        raise EffectiveDateError(
            f"Effective entry date {value.isoformat()} is in the past "
            f"(today is {today.isoformat()}). ACH credits cannot settle retroactively; "
            f"the next available banking day is "
            f"{next_banking_day(today, DEFAULT_LEAD_BANKING_DAYS).isoformat()}."
        )

    if (value - today).days > MAX_EFFECTIVE_DATE_DAYS_AHEAD:
        raise EffectiveDateError(
            f"Effective entry date {value.isoformat()} is more than "
            f"{MAX_EFFECTIVE_DATE_DAYS_AHEAD} days ahead, which is almost certainly a "
            f"typo in the year or month."
        )

    if value.weekday() >= 5:
        raise EffectiveDateError(
            f"Effective entry date {value.isoformat()} falls on a "
            f"{value.strftime('%A')}. ACH settles only on banking days; the next one "
            f"is {next_banking_day(value, 0).isoformat()}."
        )

    if value in federal_reserve_holidays(value.year):
        raise EffectiveDateError(
            f"Effective entry date {value.isoformat()} is a Federal Reserve holiday, "
            f"so ACH will not settle. The next banking day is "
            f"{next_banking_day(value, 0).isoformat()}."
        )
