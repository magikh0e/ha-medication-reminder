"""The supply refreshes its state on the post-startup reconcile, so dose-derived
attributes (est_runout_date, doses-per-week, cost) recompute once the dose
switches are loaded.

Regression test for the bug where a supply's first state write at startup could
land before its dose switches existed, caching est_runout_date as None until the
supply next changed. A supply whose dose was not given or refilled after the
restart stayed None; the reconcile pass now always re-writes, so every supply
recomputes once the switches are available.
"""

from types import SimpleNamespace

import pytest

from entity_test_support import State, load_entities

WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@pytest.fixture
def modules():
    with load_entities("number") as loaded:
        yield loaded


def make_supply(modules, switches):
    supply = modules.number.MedicationSupplyNumber(
        SimpleNamespace(entry_id="e"),
        "Test patient",
        {"supply_med": "Test med", "supply_units": 30, "supply_per_dose": 1},
        "00:01:00",
    )
    supply.hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda _d: switches))
    supply.entity_id = "number.test_supply"
    writes = []
    # Capture the attributes at each state write, as Home Assistant would.
    supply.async_write_ha_state = lambda: writes.append(
        dict(supply.extra_state_attributes)
    )
    return supply, writes


def dose(state="off"):
    return State(
        "switch.test_dose",
        state,
        {
            "patient": "Test patient",
            "medications": "Test med",
            "schedule_type": "weekdays",
            "days": WEEK,
            "dose_units": 1,
            "given_at": "2026-06-01T08:00:00+00:00",
        },
    )


def test_reconcile_refreshes_state_when_nothing_is_caught(modules):
    # A daily dose that is not currently given: nothing to decrement, but the
    # run-out must still be published once the switch is present.
    supply, writes = make_supply(modules, [dose("off")])
    supply._reconcile()
    assert writes, "reconcile should write state even when it catches nothing"
    assert writes[-1]["est_runout_date"] is not None


def test_reconcile_with_no_matching_dose_publishes_none(modules):
    # No matching dose at all: a refresh still happens, and None is correct.
    supply, writes = make_supply(modules, [])
    supply._reconcile()
    assert writes
    assert writes[-1]["est_runout_date"] is None


def test_reconcile_still_catches_a_given_dose(modules):
    supply, writes = make_supply(modules, [dose("on")])
    supply._reconcile()
    assert supply.native_value == 29  # the given dose was decremented
    assert writes  # and state was written
