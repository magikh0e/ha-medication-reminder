"""Refills and authoritative counts must survive reconciliation and restoration."""

import asyncio
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from entity_test_support import Event, State, load_entities


class SupplyHarness:
    def __init__(self, modules, value=12, add=True, amount=30, reset="00:01:00"):
        self.modules = modules
        self.states = {}
        self.reset = reset
        self.record = {
            "supply_med": "Test med",
            "supply_units": value,
            "supply_per_dose": 1,
            "supply_refill_to": amount,
            "supply_refill_add": add,
        }
        self.entry = SimpleNamespace(entry_id="test_entry")
        self.hass = SimpleNamespace(
            state=modules.core_state.running,
            states=SimpleNamespace(async_all=lambda domain: list(self.states.values())),
            bus=SimpleNamespace(async_listen=lambda *args: lambda: None),
        )
        self.supply = self.new_supply()

    def new_supply(self):
        supply = self.modules.number.MedicationSupplyNumber(
            self.entry, "Test patient", self.record, self.reset
        )
        supply.hass = self.hass
        supply.entity_id = "number.test_supply"
        return supply

    def state(self, state="on", entity="switch.test_dose", **attributes):
        return State(
            entity,
            state,
            {
                "patient": "Test patient",
                "medications": "Test med",
                "schedule_type": "weekdays",
                "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
                "dose_units": 1,
                "given_at": self.modules.clock.now().isoformat(),
                **attributes,
            },
        )

    def mark(self, entity="switch.test_dose", **attributes):
        new = self.state(entity=entity, **attributes)
        self.states[entity] = new
        self.supply._on_state_changed(
            Event(
                "state_changed",
                {
                    "entity_id": entity,
                    "old_state": self.state("off", entity),
                    "new_state": new,
                },
            )
        )

    def undo(self, entity="switch.test_dose"):
        self.states[entity] = self.state("off", entity)
        self.supply._on_dose_undone(
            Event("medication_reminder_dose_undone", {"entity_id": entity})
        )

    def refill(self):
        self.supply._on_refill(
            Event(
                "medication_reminder_supply_refill",
                {
                    "patient": "Test patient",
                    "medication": "Test med",
                },
            )
        )

    def set_count(self, value):
        asyncio.run(self.supply.async_set_native_value(value))

    def restore(self):
        previous = State(
            self.supply.entity_id,
            str(self.supply.native_value),
            copy.deepcopy(self.supply.extra_state_attributes),
        )
        self.supply = self.new_supply()
        self.supply.async_get_last_state = AsyncMock(return_value=previous)
        asyncio.run(self.supply.async_added_to_hass())
        self.supply._reconcile()


@pytest.fixture
def harness():
    with load_entities("number") as modules:
        yield lambda **kwargs: SupplyHarness(modules, **kwargs)


@pytest.mark.parametrize("dose_units", [0.5, 1, 2.5])
@pytest.mark.parametrize("restore", [False, True])
def test_additive_refill_preserves_consumption_and_exact_undo(
    harness, dose_units, restore
):
    h = harness()
    h.mark(marked_units=dose_units)
    assert h.supply.native_value == 12 - dose_units
    h.refill()
    if restore:
        h.restore()
    else:
        h.supply._reconcile()
    assert h.supply.native_value == 42 - dose_units
    h.undo()
    assert h.supply.native_value == 42
    h.undo()
    assert h.supply.native_value == 42


@pytest.mark.parametrize("mode", ["manual", "set_to"])
@pytest.mark.parametrize("restore", [False, True])
def test_authoritative_count_is_not_reconsumed_or_refunded(harness, mode, restore):
    h = harness(add=False, amount=50)
    h.mark()
    if mode == "manual":
        h.set_count(50)
    else:
        h.refill()
    if restore:
        h.restore()
    else:
        h.supply._reconcile()
    assert h.supply.native_value == 50
    h.undo()
    assert h.supply.native_value == 50
    h.mark()
    assert h.supply.native_value == 49


def test_near_empty_refill_restores_only_actual_consumption(harness):
    h = harness(value=0.5)
    h.mark()
    h.refill()
    h.restore()
    h.undo()
    assert h.supply.native_value == 30.5


@pytest.mark.parametrize("authoritative", [False, True])
def test_missing_live_event_respects_refill_semantics(harness, authoritative):
    h = harness()
    h.states["switch.test_dose"] = h.state()  # Marked while listener was absent.
    if authoritative:
        h.set_count(50)
    else:
        h.refill()
    h.restore()
    assert h.supply.native_value == (50 if authoritative else 41)


def test_multiple_doses_and_repeated_refills_keep_separate_refunds(harness):
    h = harness()
    h.mark(entity="switch.morning")
    h.mark(entity="switch.evening", dose_units=0.5)
    h.refill()
    h.refill()
    h.restore()
    assert h.supply.native_value == 70.5
    h.undo("switch.evening")
    assert h.supply.native_value == 71
    h.undo("switch.morning")
    assert h.supply.native_value == 72


def test_pending_dose_after_manual_count_is_still_consumed_once(harness):
    h = harness()
    h.states["switch.test_dose"] = h.state("off")
    h.set_count(50)
    h.mark()
    h.mark()
    h.restore()
    assert h.supply.native_value == 49


@pytest.mark.parametrize(
    "attributes",
    [
        {"skipped": ["Test med"]},
        {"patient": "Other patient"},
        {"medications": "Other med"},
        {"given_at": "2026-05-31T14:00:00+00:00"},
        {"schedule_type": "monthly", "month_days": [2]},
    ],
)
def test_authoritative_count_does_not_track_ineligible_doses(harness, attributes):
    h = harness()
    h.states["switch.test_dose"] = h.state(**attributes)
    h.set_count(50)
    h.restore()
    assert h.supply.native_value == 50
    assert h.supply.extra_state_attributes["consumed"] == {}


def test_next_day_confirmation_after_refill_is_counted(harness):
    h = harness()
    h.mark()
    h.refill()
    tomorrow = h.modules.clock.now() + timedelta(days=1)
    h.modules.clock.now = lambda: tomorrow
    h.mark()
    h.supply._reconcile()
    assert h.supply.native_value == 40


def test_refill_and_restore_honor_custom_day_boundary(harness):
    h = harness(reset="03:00:00")
    h.modules.clock.now = lambda: datetime(2026, 6, 2, 0, 30, tzinfo=timezone.utc)
    h.mark()
    h.refill()
    h.restore()
    assert h.supply.native_value == 41
    h.undo()
    assert h.supply.native_value == 42
