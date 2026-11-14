"""The dose switch echoes the patient's daily reset time, so a dashboard can
place a bare dose_time on the correct medication day when the reset is custom (#64)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from entity_test_support import load_entities


@pytest.fixture
def modules():
    with load_entities("switch") as loaded:
        yield loaded


def make_dose(modules, reset_time=None):
    options = {"doses": [{"time": "08:00", "meds": "Test med"}]}
    if reset_time is not None:
        options["reset_time"] = reset_time
    entry = SimpleNamespace(entry_id="e", options=options)
    record = {"time": "08:00", "meds": "Test med"}
    return modules.switch.MedicationDoseSwitch(
        entry, "Test patient", "person", "", 30, 15, "24h", record, {}, AsyncMock()
    )


def test_reset_time_reflects_configured_value(modules):
    dose = make_dose(modules, reset_time="04:00:00")
    assert dose.extra_state_attributes["reset_time"] == "04:00:00"


def test_reset_time_defaults_when_unset(modules):
    dose = make_dose(modules)
    assert dose.extra_state_attributes["reset_time"] == "00:01:00"
