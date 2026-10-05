"""Unit tests for the pill-box plan builder (build_day_plan, schedule_cadence).

const.py is HA-free, so we load it in isolation and test the per-date plan
computation (rows = meds, columns = time slots, cell = quantity) that the
integration hands to the dashboard plan card.
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

WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MON = date(2026, 10, 6)  # a Monday
TUE = date(2026, 10, 7)

DOSES = [
    {"time": "08:00", "meds": "Keppra", "schedule_type": "weekdays", "days": WEEK, "dose_units": 0},
    {"time": "08:00", "meds": "Marcoumar", "schedule_type": "weekdays", "days": WEEK, "dose_units": 0.5},
    {"time": "20:00", "meds": "Marcoumar", "schedule_type": "weekdays", "days": WEEK, "dose_units": 1},
    {"time": "09:00", "meds": "Atozet", "schedule_type": "interval", "interval_days": 2, "anchor_date": "2026-10-06", "days": WEEK, "dose_units": 1},
    {"time": "12:00", "meds": "Tramadol", "schedule_type": "prn", "days": WEEK},
]
SUPPLIES = [{"supply_med": "Keppra", "supply_per_dose": 1}]
DETAILS = [{"med_name": "Keppra", "prescribed_for": "seizures"}]


def _rows_by_med(plan):
    return {r["med"]: r for r in plan["rows"]}


def test_times_are_the_distinct_sorted_slots():
    plan = const.build_day_plan(DOSES, SUPPLIES, DETAILS, MON)
    assert plan["times"] == ["08:00", "09:00", "20:00"]


def test_one_row_per_med():
    plan = const.build_day_plan(DOSES, SUPPLIES, DETAILS, MON)
    # Keppra, Marcoumar, Atozet (PRN Tramadol excluded).
    assert sorted(r["med"] for r in plan["rows"]) == ["Atozet", "Keppra", "Marcoumar"]


def test_quantity_per_time_slot():
    rows = _rows_by_med(const.build_day_plan(DOSES, SUPPLIES, DETAILS, MON))
    # Marcoumar: half in the morning, one at night -> two columns in one row.
    assert rows["Marcoumar"]["amounts"] == {"08:00": 0.5, "20:00": 1}


def test_amount_falls_back_to_supply_per_dose():
    rows = _rows_by_med(const.build_day_plan(DOSES, SUPPLIES, DETAILS, MON))
    # Keppra has no per-dose amount, so it uses the supply's per-dose (1).
    assert rows["Keppra"]["amounts"] == {"08:00": 1}


def test_prn_doses_are_excluded():
    plan = const.build_day_plan(DOSES, SUPPLIES, DETAILS, MON)
    assert all(r["med"] != "Tramadol" for r in plan["rows"])


def test_prescribed_for_and_schedule_columns():
    rows = _rows_by_med(const.build_day_plan(DOSES, SUPPLIES, DETAILS, MON))
    assert rows["Keppra"]["prescribed_for"] == "seizures"
    assert rows["Keppra"]["schedule"] == "daily"
    assert rows["Atozet"]["schedule"] == "every 2 days"


def test_computed_per_actual_date_not_weekday():
    # Atozet is every 2 days from Mon, so it is due Mon but not Tue.
    mon = _rows_by_med(const.build_day_plan(DOSES, SUPPLIES, DETAILS, MON))
    tue = _rows_by_med(const.build_day_plan(DOSES, SUPPLIES, DETAILS, TUE))
    assert "Atozet" in mon
    assert "Atozet" not in tue
    # The daily meds still appear on Tuesday.
    assert "Keppra" in tue


def test_empty_when_nothing_scheduled():
    plan = const.build_day_plan([], [], [], MON)
    assert plan == {"times": [], "rows": []}


def test_schedule_cadence_variants():
    assert const.schedule_cadence({"schedule_type": "weekdays", "days": WEEK}) == "daily"
    assert (
        const.schedule_cadence({"schedule_type": "weekdays", "days": ["mon", "wed", "fri"]})
        == "Mon, Wed, Fri"
    )
    assert const.schedule_cadence({"schedule_type": "interval", "interval_days": 2}) == "every 2 days"
    assert const.schedule_cadence({"schedule_type": "interval", "interval_days": 1}) == "daily"
    assert const.schedule_cadence({"schedule_type": "cycle", "cycle_on": 21, "cycle_off": 7}) == "21 on / 7 off"
    assert const.schedule_cadence({"schedule_type": "monthly", "month_days": [1, 15]}) == "monthly on 1, 15"
    assert const.schedule_cadence({"schedule_type": "prn"}) == "as needed"
