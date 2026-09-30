"""Unit tests for prescription refill arithmetic (next_refills_remaining,
restore_refills).

const.py has no Home Assistant imports, so we load it in isolation (like
test_supply.py) and test the pure refill helpers without needing HA. These cover
the decrement-on-refill count and the restore logic that keeps a live count
across the entry reloads the options flow does on every edit, while still
resetting when the configured prescription count changes.
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


def test_decrements_by_one():
    assert const.next_refills_remaining(3) == 2


def test_never_goes_below_zero():
    assert const.next_refills_remaining(0) == 0
    assert const.next_refills_remaining(-5) == 0


def test_counts_down_to_zero_over_repeated_refills():
    remaining = 2
    remaining = const.next_refills_remaining(remaining)
    assert remaining == 1
    remaining = const.next_refills_remaining(remaining)
    assert remaining == 0
    remaining = const.next_refills_remaining(remaining)
    assert remaining == 0  # stays out, does not wrap negative


def test_bad_input_is_safe():
    assert const.next_refills_remaining(None) == 0
    assert const.next_refills_remaining("x") == 0


def test_restore_keeps_live_count_when_configured_unchanged():
    # Prescription configured for 3, one refill already used (2 left). A reload
    # with the same configured count must keep the decremented 2, not reset to 3.
    assert const.restore_refills(3, 3, 2) == 2


def test_restore_resets_when_configured_count_changes():
    # A new prescription: the configured count went from 3 to 5, so the counter
    # starts over at the new configured value regardless of the restored count.
    assert const.restore_refills(5, 3, 0) == 5


def test_restore_resets_to_zero_when_tracking_turned_off():
    assert const.restore_refills(0, 3, 2) == 0


def test_restore_falls_back_to_configured_without_prior_state():
    # First load (nothing restored) starts at the configured count.
    assert const.restore_refills(4, None, None) == 4


def test_restore_clamps_negative_restored_remaining():
    assert const.restore_refills(3, 3, -1) == 0


def test_restore_bad_input_is_safe():
    assert const.restore_refills(None, None, None) == 0
    assert const.restore_refills("x", "y", "z") == 0
