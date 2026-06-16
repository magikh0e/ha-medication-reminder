"""Unit tests for the dose schedule logic (is_due / doses_per_week).

const.py has no Home Assistant imports, so we load it in isolation (without
triggering the integration package __init__, which does import HA). That keeps
these tests fast and dependency-free, needing only pytest.
"""
import importlib.util
from datetime import date, datetime
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

is_due = const.is_due
doses_per_week = const.doses_per_week
WEEKDAYS = const.WEEKDAYS
split_medications = const.split_medications
meds_contains = const.meds_contains
dose_min_interval_hours = const.dose_min_interval_hours
dose_max_per_day = const.dose_max_per_day
next_dose_allowed = const.next_dose_allowed
dose_too_soon = const.dose_too_soon
dose_over_cap = const.dose_over_cap

# A known Monday, for weekday tests that don't hardcode the mapping.
MON = date(2026, 6, 1)


# --- Weekday schedule (default, backward compatible) -----------------------

def test_weekday_due_when_listed():
    wd = WEEKDAYS[MON.weekday()]
    assert is_due({"days": [wd]}, MON) is True


def test_weekday_not_due_when_only_other_day():
    other = WEEKDAYS[(MON.weekday() + 3) % 7]
    assert is_due({"days": [other]}, MON) is False


def test_weekday_missing_days_is_daily():
    assert is_due({}, MON) is True


def test_weekday_full_week_is_daily():
    assert is_due({"days": WEEKDAYS}, MON) is True


# --- Interval (every N days) -----------------------------------------------

INTERVAL = {"schedule_type": "interval", "interval_days": 2, "anchor_date": "2026-06-01"}


def test_interval_due_on_anchor():
    assert is_due(INTERVAL, date(2026, 6, 1)) is True


def test_interval_not_due_anchor_plus_1():
    assert is_due(INTERVAL, date(2026, 6, 2)) is False


def test_interval_due_anchor_plus_2():
    assert is_due(INTERVAL, date(2026, 6, 3)) is True


def test_interval_due_anchor_plus_4():
    assert is_due(INTERVAL, date(2026, 6, 5)) is True


def test_interval_not_due_before_anchor():
    assert is_due(INTERVAL, date(2026, 5, 31)) is False


def test_interval_n1_is_daily():
    one = {"schedule_type": "interval", "interval_days": 1, "anchor_date": "2026-06-01"}
    assert is_due(one, date(2026, 6, 9)) is True


def test_interval_no_anchor_is_deterministic():
    na = {"schedule_type": "interval", "interval_days": 3}
    d = MON
    while d.toordinal() % 3 != 0:
        d = date.fromordinal(d.toordinal() + 1)
    assert is_due(na, d) is True
    assert is_due(na, date.fromordinal(d.toordinal() + 1)) is False


def test_interval_zero_is_safe():
    # invalid 0 falls back to the default interval, never divides by zero
    z = {"schedule_type": "interval", "interval_days": 0, "anchor_date": "2026-06-01"}
    assert is_due(z, date(2026, 6, 1)) is True


# --- On/off cycle (e.g. 21 on / 7 off) -------------------------------------

CYCLE = {
    "schedule_type": "cycle",
    "cycle_on": 21,
    "cycle_off": 7,
    "anchor_date": "2026-06-01",
}


def test_cycle_due_on_anchor():
    assert is_due(CYCLE, date(2026, 6, 1)) is True


def test_cycle_due_last_on_day():
    assert is_due(CYCLE, date(2026, 6, 21)) is True  # offset 20, still in the 21 on


def test_cycle_not_due_first_off_day():
    assert is_due(CYCLE, date(2026, 6, 22)) is False  # offset 21, into the 7 off


def test_cycle_not_due_last_off_day():
    assert is_due(CYCLE, date(2026, 6, 28)) is False  # offset 27


def test_cycle_due_next_cycle_start():
    assert is_due(CYCLE, date(2026, 6, 29)) is True  # offset 28, wraps to on


def test_cycle_not_due_before_anchor():
    assert is_due(CYCLE, date(2026, 5, 31)) is False


def test_cycle_short_2on_1off():
    c = {"schedule_type": "cycle", "cycle_on": 2, "cycle_off": 1, "anchor_date": "2026-06-01"}
    assert is_due(c, date(2026, 6, 1)) is True   # offset 0
    assert is_due(c, date(2026, 6, 2)) is True   # offset 1
    assert is_due(c, date(2026, 6, 3)) is False  # offset 2 (off)
    assert is_due(c, date(2026, 6, 4)) is True   # offset 3 wraps to on


def test_dpw_cycle_21_7():
    assert abs(doses_per_week(CYCLE) - (7.0 * 21 / 28)) < 1e-9  # 5.25


# --- As needed (PRN) -------------------------------------------------------

PRN = {"schedule_type": "prn"}


def test_prn_never_due():
    # As-needed meds are never on a schedule, so never "due" (no reminders).
    for d in (date(2026, 6, 1), date(2026, 6, 2), date(2026, 12, 25), MON):
        assert is_due(PRN, d) is False


def test_prn_ignores_days():
    # Even with day fields present, a PRN dose stays off-schedule.
    assert is_due({"schedule_type": "prn", "days": WEEKDAYS}, MON) is False


def test_dpw_prn_is_zero():
    # No cadence, so no schedule-based run-out (number.py guards per_week <= 0).
    assert doses_per_week(PRN) == 0.0


# --- Monthly (day-of-month) ------------------------------------------------

def test_monthly_due_on_chosen_days():
    m = {"schedule_type": "monthly", "month_days": [1, 15]}
    assert is_due(m, date(2026, 6, 1)) is True
    assert is_due(m, date(2026, 6, 15)) is True


def test_monthly_not_due_other_days():
    m = {"schedule_type": "monthly", "month_days": [1, 15]}
    assert is_due(m, date(2026, 6, 2)) is False
    assert is_due(m, date(2026, 6, 16)) is False


def test_monthly_default_is_first():
    m = {"schedule_type": "monthly"}
    assert is_due(m, date(2026, 6, 1)) is True
    assert is_due(m, date(2026, 6, 2)) is False


def test_monthly_clamps_to_last_day_in_short_month():
    # 31st requested; Feb 2026 has 28 days, so it fires on the 28th instead.
    m = {"schedule_type": "monthly", "month_days": [31]}
    assert is_due(m, date(2026, 2, 28)) is True
    assert is_due(m, date(2026, 2, 27)) is False


def test_monthly_not_clamped_in_long_month():
    # In a 31-day month the 31st stays the 31st.
    m = {"schedule_type": "monthly", "month_days": [31]}
    assert is_due(m, date(2026, 1, 31)) is True
    assert is_due(m, date(2026, 1, 28)) is False


def test_dpw_monthly():
    m = {"schedule_type": "monthly", "month_days": [1, 15]}
    assert abs(doses_per_week(m) - (2 * 12.0 / 52.0)) < 1e-9


# --- doses_per_week (run-out estimate cadence) -----------------------------

def test_dpw_weekdays_is_len_days():
    assert doses_per_week({"days": ["mon", "wed", "fri"]}) == 3.0


def test_dpw_daily_is_seven():
    assert doses_per_week({}) == 7.0


def test_dpw_interval_every_two():
    assert abs(doses_per_week({"schedule_type": "interval", "interval_days": 2}) - 3.5) < 1e-9


def test_dpw_interval_every_seven():
    assert abs(doses_per_week({"schedule_type": "interval", "interval_days": 7}) - 1.0) < 1e-9


# --- Medication matching (supply decrement, refill, repairs) ----------------

def test_split_medications_separators():
    assert split_medications("Med A & Med B") == ["Med A", "Med B"]
    assert split_medications("Med A, Med B + Med C / Med D") == ["Med A", "Med B", "Med C", "Med D"]


def test_split_medications_slash_in_name_is_kept_whole():
    # A bare slash is part of the name (combo drugs, fractional doses), not a
    # separator, so the medication is tracked as one.
    assert split_medications("Carbimazol 5mg (1/2)") == ["Carbimazol 5mg (1/2)"]
    assert split_medications("TMP/SMX") == ["TMP/SMX"]
    assert split_medications("Lisinopril/HCTZ") == ["Lisinopril/HCTZ"]
    # A slash with spaces around it still separates two meds.
    assert split_medications("Aspirin / Warfarin") == ["Aspirin", "Warfarin"]


def test_meds_contains_slash_in_name_matches_supply():
    # The reported bug: a supply named with a slash now matches its dose.
    assert meds_contains("Carbimazol 5mg (1/2)", "Carbimazol 5mg (1/2)") is True


def test_split_medications_empty():
    assert split_medications("") == []
    assert split_medications(None) == []


def test_meds_contains_match():
    assert meds_contains("Med A & Med B", "Med B") is True
    assert meds_contains("Med A", "Med A") is True


def test_meds_contains_no_match():
    assert meds_contains("Med A & Med B", "Med C") is False


def test_meds_contains_case_insensitive():
    assert meds_contains("med a", "Med A") is True


def test_meds_contains_empty_is_false():
    assert meds_contains("Med A", "") is False
    assert meds_contains("", "Med A") is False


def test_dose_min_interval_hours():
    assert dose_min_interval_hours({"min_interval_hours": 4}) == 4.0
    assert dose_min_interval_hours({}) == 0.0
    assert dose_min_interval_hours({"min_interval_hours": "bad"}) == 0.0
    assert dose_min_interval_hours({"min_interval_hours": -2}) == 0.0


def test_dose_max_per_day():
    assert dose_max_per_day({"max_per_day": 3}) == 3
    assert dose_max_per_day({}) == 0
    assert dose_max_per_day({"max_per_day": "x"}) == 0


def test_next_dose_allowed():
    last = datetime(2026, 6, 1, 8, 0)
    assert next_dose_allowed(last, 4) == datetime(2026, 6, 1, 12, 0)
    assert next_dose_allowed(last, 0) is None
    assert next_dose_allowed(None, 4) is None


def test_dose_too_soon():
    last = datetime(2026, 6, 1, 8, 0)
    # 2 hours in, 4-hour minimum -> too soon
    assert dose_too_soon(last, 4, datetime(2026, 6, 1, 10, 0)) is True
    # exactly at the boundary -> allowed
    assert dose_too_soon(last, 4, datetime(2026, 6, 1, 12, 0)) is False
    assert dose_too_soon(last, 4, datetime(2026, 6, 1, 14, 0)) is False
    # no interval / no last dose -> never too soon
    assert dose_too_soon(last, 0, datetime(2026, 6, 1, 8, 30)) is False
    assert dose_too_soon(None, 4, datetime(2026, 6, 1, 8, 30)) is False


def test_dose_over_cap():
    assert dose_over_cap(3, 3) is True
    assert dose_over_cap(4, 3) is True
    assert dose_over_cap(2, 3) is False
    assert dose_over_cap(5, 0) is False  # 0 = no cap
