"""Course end dates must reach dose switches and their state consumers."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from entity_test_support import Event, State, load_entities

SCHEDULES = [
    {"schedule_type": "weekdays"},
    {"schedule_type": "interval", "interval_days": 1},
    {"schedule_type": "cycle", "cycle_on": 3, "cycle_off": 1},
    {"schedule_type": "monthly", "month_days": [1, 2, 3]},
]


@pytest.fixture
def modules():
    with load_entities("switch", "number", "binary_sensor") as loaded:
        yield loaded


def make_dose(modules, schedule=None, **overrides):
    record = {
        "time": "08:00",
        "meds": "Test med",
        "anchor_date": "2026-06-01",
        "end_date": "2026-06-02",
        **(schedule or {}),
        **overrides,
    }
    if record.get("end_date") == "missing":
        del record["end_date"]
    entry = SimpleNamespace(entry_id="test_entry", options={"doses": [record]})
    dose = modules.switch.MedicationDoseSwitch(
        entry, "Test patient", "person", "", 30, 15, "24h", record, {}, AsyncMock()
    )
    return entry, dose


@pytest.mark.parametrize("schedule", SCHEDULES)
@pytest.mark.parametrize("day, expected", [(1, True), (2, True), (3, False)])
def test_switch_respects_inclusive_end_date(modules, schedule, day, expected):
    modules.clock.now = lambda: datetime(2026, 6, day, 14, tzinfo=timezone.utc)
    _, dose = make_dose(modules, schedule)
    assert dose.extra_state_attributes["scheduled_today"] is expected


def test_end_date_is_exposed_for_state_consumers(modules):
    _, dose = make_dose(modules)
    assert dose.extra_state_attributes["end_date"] == "2026-06-02"


@pytest.mark.parametrize("end_date", ["missing", None, ""])
def test_existing_doses_without_end_date_remain_scheduled(modules, end_date):
    modules.clock.now = lambda: datetime(2026, 6, 3, 14, tzinfo=timezone.utc)
    _, dose = make_dose(modules, end_date=end_date)
    assert dose.extra_state_attributes["scheduled_today"] is True


@pytest.mark.parametrize(
    "local_now, expected",
    [
        (datetime(2026, 6, 3, 0, 30, tzinfo=timezone(timedelta(hours=2))), False),
        (datetime(2026, 6, 2, 23, 30, tzinfo=timezone(timedelta(hours=-7))), True),
    ],
)
def test_end_date_uses_local_calendar_day(modules, local_now, expected):
    modules.clock.now = lambda: local_now
    _, dose = make_dose(modules)
    assert dose.extra_state_attributes["scheduled_today"] is expected


@pytest.mark.parametrize("schedule", SCHEDULES)
@pytest.mark.parametrize("day, active", [(2, True), (3, False)])
def test_status_and_supply_use_the_switch_end_date(modules, schedule, day, active):
    modules.clock.now = lambda: datetime(2026, 6, day, 14, tzinfo=timezone.utc)
    entry, dose = make_dose(modules, schedule)
    entity_id = "switch.test_dose"
    pending = State(entity_id, "off", dose.extra_state_attributes)
    hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda domain: [pending]))

    all_given = modules.binary_sensor.AllDosesGivenBinarySensor(
        entry, "Test patient", "person", "00:01:00"
    )
    all_given.hass = hass
    attention = modules.binary_sensor.NeedsAttentionBinarySensor(
        entry, "Test patient", "00:01:00"
    )
    attention.hass = hass
    assert all_given.extra_state_attributes["remaining"] == int(active)
    assert all_given.is_on is (False if active else None)
    assert attention.is_on is active

    supply = modules.number.MedicationSupplyNumber(
        entry,
        "Test patient",
        {"supply_med": "Test med", "supply_units": 12},
        "00:01:00",
    )
    supply.hass = hass
    supply.entity_id = "number.test_supply"
    marked = State(
        entity_id,
        "on",
        {
            **dose.extra_state_attributes,
            "given_at": modules.clock.now().isoformat(),
        },
    )
    supply._on_state_changed(
        Event(
            "state_changed",
            {
                "entity_id": entity_id,
                "old_state": pending,
                "new_state": marked,
            },
        )
    )
    assert supply.native_value == (11 if active else 12)
