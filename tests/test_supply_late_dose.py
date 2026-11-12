"""Supply must deduct for a scheduled dose marked given a day late or early.

Regression test for the bug where the supply only came down if the dose was due
on the current medication day, so a weekly med taken the day after (or before)
its scheduled day left the stock untouched. Consumption now follows the mark
itself; the daily switch reset and the per-dose ledger keep it from counting
twice, and as-needed (PRN) doses are still excluded (they come down through
their own log-dose button, not the switch).
"""

from types import SimpleNamespace

import pytest

from entity_test_support import Event, State, load_entities

WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@pytest.fixture
def modules():
    with load_entities("number") as loaded:
        yield loaded


def make_supply(modules, units=12):
    entry = SimpleNamespace(entry_id="test_entry")
    supply = modules.number.MedicationSupplyNumber(
        entry,
        "Test patient",
        {"supply_med": "Test med", "supply_units": units, "supply_per_dose": 1},
        "00:01:00",
    )
    supply.hass = SimpleNamespace(
        state=modules.core_state.running,
        states=SimpleNamespace(async_all=lambda _domain: []),
        bus=SimpleNamespace(async_listen=lambda *_a: lambda: None),
    )
    supply.entity_id = "number.test_supply"
    return supply


def _weekday_name(modules, offset):
    """A weekday name `offset` days from today (per the test clock)."""
    return WEEK[(modules.clock.now().weekday() + offset) % 7]


def dose_state(modules, days, schedule_type="weekdays", meds="Test med", **extra):
    attrs = {
        "patient": "Test patient",
        "medications": meds,
        "schedule_type": schedule_type,
        "days": list(days),
        "dose_units": 1,
        "given_at": modules.clock.now().isoformat(),
        **extra,
    }
    return State("switch.test_dose", "on", attrs)


def mark(supply, given_state):
    off = State(given_state.entity_id, "off", given_state.attributes)
    supply._on_state_changed(
        Event(
            "state_changed",
            {
                "entity_id": given_state.entity_id,
                "old_state": off,
                "new_state": given_state,
            },
        )
    )


def test_weekly_dose_marked_a_day_late_deducts(modules):
    # Dose scheduled for yesterday's weekday, marked given today (a day late).
    supply = make_supply(modules)
    mark(supply, dose_state(modules, [_weekday_name(modules, -1)]))
    assert supply.native_value == 11


def test_dose_marked_a_day_early_deducts(modules):
    # Dose scheduled for tomorrow's weekday, marked given today (a day early).
    supply = make_supply(modules)
    mark(supply, dose_state(modules, [_weekday_name(modules, +1)]))
    assert supply.native_value == 11


def test_on_schedule_dose_still_deducts_once(modules):
    supply = make_supply(modules)
    given = dose_state(modules, [_weekday_name(modules, 0)])
    mark(supply, given)
    mark(supply, given)  # a second mark the same day must not double-count
    assert supply.native_value == 11


def test_prn_switch_does_not_deduct_via_the_switch_path(modules):
    # PRN doses decrement through their log-dose button; the switch must not.
    supply = make_supply(modules)
    mark(supply, dose_state(modules, [], schedule_type="prn"))
    assert supply.native_value == 12


def test_skipped_med_is_not_deducted_even_when_late(modules):
    supply = make_supply(modules)
    mark(
        supply,
        dose_state(modules, [_weekday_name(modules, -1)], skipped=["Test med"]),
    )
    assert supply.native_value == 12


def test_dose_after_its_end_date_does_not_deduct(modules):
    # Outside the course window (the clock is 2026-06-01): an ended course must
    # not consume supply, even when its switch is marked given.
    supply = make_supply(modules)
    mark(
        supply,
        dose_state(modules, [_weekday_name(modules, -1)], end_date="2026-05-01"),
    )
    assert supply.native_value == 12


def test_dose_before_its_start_date_does_not_deduct(modules):
    supply = make_supply(modules)
    mark(
        supply,
        dose_state(modules, [_weekday_name(modules, -1)], anchor_date="2027-01-01"),
    )
    assert supply.native_value == 12
