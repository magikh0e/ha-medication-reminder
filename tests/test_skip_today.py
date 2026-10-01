"""Unit tests for the "skip a dose for the day" handled predicate (dose_handled).

Distinct from test_skipped.py: that covers skipping one med within a dose that is
still taken (partial dose); this covers skipping a whole dose for the day, a third
state the status sensors treat as handled. const.py is HA-free, so we load it in
isolation and test the shared predicate without needing Home Assistant.
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


def test_given_is_handled():
    assert const.dose_handled("on", False) is True


def test_skipped_is_handled():
    # Not given (switch off) but skipped for today still counts as handled.
    assert const.dose_handled("off", True) is True


def test_pending_is_not_handled():
    assert const.dose_handled("off", False) is False


def test_skipped_flag_coerced():
    assert const.dose_handled("off", None) is False
    assert const.dose_handled("off", 1) is True


def test_given_wins_even_if_skipped_flag_set():
    # A given dose is handled regardless of a stale skip flag.
    assert const.dose_handled("on", True) is True
