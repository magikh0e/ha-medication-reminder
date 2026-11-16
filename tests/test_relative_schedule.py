"""Unit tests for the relative / interval dosing helpers (#40).

const.py has no Home Assistant imports, so we load it in isolation (like
test_schedule.py) and test the pure helpers without needing HA.

Relative dosing is N doses a day, the first at a fixed anchor time and each later
one due a set number of hours after the previous one was actually taken. These
cover the chain expansion (one stored dose -> N occurrence switches), the
due-time math (previous give time + offset), and that is_due still gates the
chain by day and by course start/end dates.
"""

import importlib.util
from datetime import date
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

relative_count = const.relative_count
relative_offset_hours = const.relative_offset_hours
relative_due_at = const.relative_due_at
expand_doses = const.expand_doses
is_due = const.is_due
doses_per_week = const.doses_per_week
schedule_cadence = const.schedule_cadence
SCHEDULE_RELATIVE = const.SCHEDULE_RELATIVE
CONF_RELATIVE_POSITION = const.CONF_RELATIVE_POSITION
WEEKDAYS = const.WEEKDAYS


def rel(**overrides):
    dose = {
        "time": "07:00",
        "meds": "Amox",
        "schedule_type": SCHEDULE_RELATIVE,
        "relative_count": 3,
        "relative_offset_hours": 5,
        "days": list(WEEKDAYS),
    }
    dose.update(overrides)
    return dose


# --- count / offset parsing -------------------------------------------------


def test_count_defaults_and_floor():
    assert relative_count({}) == const.DEFAULT_RELATIVE_COUNT
    assert relative_count({"relative_count": 4}) == 4
    # A chain must have at least two doses (a one-dose chain is just a fixed dose).
    assert relative_count({"relative_count": 1}) == 2
    assert relative_count({"relative_count": "oops"}) == const.DEFAULT_RELATIVE_COUNT


def test_offset_defaults_and_floor():
    assert relative_offset_hours({}) == const.DEFAULT_RELATIVE_OFFSET_HOURS
    assert relative_offset_hours({"relative_offset_hours": 6}) == 6.0
    assert relative_offset_hours({"relative_offset_hours": 4.5}) == 4.5
    assert relative_offset_hours({"relative_offset_hours": -3}) == 0.0
    assert (
        relative_offset_hours({"relative_offset_hours": "x"})
        == const.DEFAULT_RELATIVE_OFFSET_HOURS
    )


# --- due-time math ----------------------------------------------------------


def test_due_at_is_previous_give_plus_offset():
    # Taken at 07:00, 5h offset -> next due 12:00.
    assert relative_due_at("2026-06-01T07:00:00", 5) == "2026-06-01T12:00:00"


def test_due_at_shifts_with_a_late_dose():
    # The chain is anchored to the ACTUAL time, so a late dose pushes the next.
    assert relative_due_at("2026-06-01T10:00:00", 6) == "2026-06-01T16:00:00"


def test_due_at_fractional_offset():
    assert relative_due_at("2026-06-01T08:00:00", 1.5) == "2026-06-01T09:30:00"


def test_due_at_crosses_midnight():
    assert relative_due_at("2026-06-01T22:00:00", 6) == "2026-06-02T04:00:00"


def test_due_at_keeps_timezone_offset():
    assert (
        relative_due_at("2026-06-01T07:00:00-04:00", 5) == "2026-06-01T12:00:00-04:00"
    )


def test_due_at_none_when_predecessor_not_given():
    # No give time yet -> the chain has not reached this leg, so it is not due.
    assert relative_due_at(None, 5) is None
    assert relative_due_at("", 5) is None


def test_due_at_none_on_bad_input():
    assert relative_due_at("not-a-time", 5) is None


# --- expansion --------------------------------------------------------------


def test_non_relative_dose_passes_through_unchanged():
    doses = [{"time": "08:00", "meds": "A", "schedule_type": "weekdays"}]
    assert expand_doses(doses) == doses


def test_relative_dose_expands_into_n_occurrences():
    out = expand_doses([rel(relative_count=3)])
    assert len(out) == 3
    assert [o[CONF_RELATIVE_POSITION] for o in out] == [0, 1, 2]
    # Every occurrence keeps the chain's shared fields.
    for o in out:
        assert o["meds"] == "Amox"
        assert o["time"] == "07:00"
        assert o["relative_offset_hours"] == 5
        assert o["schedule_type"] == SCHEDULE_RELATIVE


def test_expansion_floors_at_two():
    out = expand_doses([rel(relative_count=1)])
    assert len(out) == 2


def test_expansion_does_not_mutate_the_stored_dose():
    stored = rel()
    expand_doses([stored])
    assert CONF_RELATIVE_POSITION not in stored


def test_mixed_list_expands_only_the_relative_ones():
    fixed = {"time": "09:00", "meds": "B", "schedule_type": "weekdays"}
    out = expand_doses([fixed, rel(relative_count=2)])
    assert len(out) == 3
    assert out[0] == fixed
    assert [o.get(CONF_RELATIVE_POSITION) for o in out] == [None, 0, 1]


# --- is_due gating (day + course dates) ------------------------------------


def test_relative_is_due_on_its_days():
    # 2026-06-01 is a Monday.
    mon = date(2026, 6, 1)
    assert is_due(rel(days=["mon"]), mon) is True
    assert is_due(rel(days=["tue"]), mon) is False


def test_relative_respects_start_and_end_dates():
    dose = rel(anchor_date="2026-06-02", end_date="2026-06-10")
    assert is_due(dose, date(2026, 6, 1)) is False  # before start
    assert is_due(dose, date(2026, 6, 2)) is True
    assert is_due(dose, date(2026, 6, 10)) is True
    assert is_due(dose, date(2026, 6, 11)) is False  # after end


def test_each_expanded_occurrence_counts_as_one_dose_per_week():
    # Each occurrence is its own switch (one dose a day), so the supply run-out
    # sums them: doses_per_week per leg = number of active days.
    occ = expand_doses([rel(days=["mon", "wed", "fri"])])[0]
    assert doses_per_week(occ) == 3.0


# --- cadence string ---------------------------------------------------------


def test_cadence_string():
    assert schedule_cadence(rel(relative_count=3, relative_offset_hours=5)) == (
        "3x/day, 5h apart"
    )
    assert schedule_cadence(rel(relative_count=2, relative_offset_hours=4.5)) == (
        "2x/day, 4.5h apart"
    )
