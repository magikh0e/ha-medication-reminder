"""Unit tests for the medication-day boundary (med_day / reset_hms).

const.py has no Home Assistant imports, so we load it in isolation (like
test_schedule.py) and test the pure helpers without needing HA. This covers the
fix for issue #28: the status sensors' "day" rolls over at the patient's daily
reset time, not midnight, so a dose left un-given late at night stays "today's"
(and keeps nagging) until the reset time passes.
"""

import importlib.util
from datetime import datetime
from pathlib import Path

_CONST = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "medication_reminder"
    / "const.py"
)
_spec = importlib.util.spec_from_file_location("med_const", _CONST)
const = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(const)


def d(y, mo, da, h=0, mi=0, s=0):
    return datetime(y, mo, da, h, mi, s)


# --- reset_hms parsing -------------------------------------------------------


def test_reset_hms_hh_mm_ss():
    assert const.reset_hms("06:30:15") == (6, 30, 15)


def test_reset_hms_hh_mm_defaults_seconds_to_zero():
    assert const.reset_hms("06:30") == (6, 30, 0)


def test_reset_hms_malformed_falls_back_to_default():
    for bad in ("", "nope", None, "1", "aa:bb"):
        assert const.reset_hms(bad) == (0, 1, 0)


def test_reset_hms_out_of_range_wraps():
    assert const.reset_hms("25:70:90") == (1, 10, 30)


# --- med_day with the default 00:01 reset ------------------------------------


def test_default_reset_after_boundary_is_today():
    # 00:02 is past the 00:01 reset, so we are on the new calendar day.
    assert const.med_day(d(2026, 8, 26, 0, 2), "00:01:00") == d(2026, 8, 26).date()


def test_default_reset_before_boundary_is_yesterday():
    # 00:00:30 is before the 00:01 reset, so still the previous day (to within
    # a minute of the old midnight behaviour).
    assert const.med_day(d(2026, 8, 26, 0, 0, 30), "00:01:00") == d(2026, 8, 25).date()


def test_default_reset_midday_is_today():
    assert const.med_day(d(2026, 8, 26, 13, 0), "00:01:00") == d(2026, 8, 26).date()


# --- med_day with a later reset (the issue #28 scenario) ---------------------


def test_late_dose_stays_todays_after_midnight_with_6am_reset():
    # Dose at 22:30 on the 25th, reset at 06:00. At 01:00 on the 26th we are
    # still before the reset, so the med-day is the 25th and the untaken dose
    # keeps "needs attention" red instead of clearing at midnight.
    assert const.med_day(d(2026, 8, 26, 1, 0), "06:00:00") == d(2026, 8, 25).date()


def test_same_evening_is_that_day_with_6am_reset():
    assert const.med_day(d(2026, 8, 25, 23, 0), "06:00:00") == d(2026, 8, 25).date()


def test_after_reset_rolls_to_new_day_with_6am_reset():
    # 07:00 on the 26th is past the 06:00 reset, so the day finally rolls over
    # and yesterday's late dose stops nagging.
    assert const.med_day(d(2026, 8, 26, 7, 0), "06:00:00") == d(2026, 8, 26).date()


def test_exactly_at_boundary_is_new_day():
    # now == boundary is not "before", so we are on the new day.
    assert const.med_day(d(2026, 8, 26, 6, 0, 0), "06:00:00") == d(2026, 8, 26).date()


def test_malformed_reset_time_behaves_like_default():
    # Falls back to 00:01, so 00:00:30 is still the previous day.
    assert const.med_day(d(2026, 8, 26, 0, 0, 30), "garbage") == d(2026, 8, 25).date()
