"""Unit tests for the snooze delay validation (clamp_snooze_minutes).

const.py is HA-free, so we load it in isolation and test the pure helper that
turns a snooze service input into a safe delay in minutes.
"""

import importlib.util
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


def test_default_when_none():
    assert const.clamp_snooze_minutes(None) == const.DEFAULT_SNOOZE_MINUTES


def test_passes_through_a_normal_value():
    assert const.clamp_snooze_minutes(45) == 45


def test_coerces_numeric_string():
    assert const.clamp_snooze_minutes("15") == 15


def test_floor_is_one_minute():
    assert const.clamp_snooze_minutes(0) == 1
    assert const.clamp_snooze_minutes(-10) == 1


def test_capped_at_a_day():
    assert const.clamp_snooze_minutes(99999) == 1440


def test_bad_input_falls_back_to_default():
    assert const.clamp_snooze_minutes("soon") == const.DEFAULT_SNOOZE_MINUTES
    assert const.clamp_snooze_minutes([30]) == const.DEFAULT_SNOOZE_MINUTES
