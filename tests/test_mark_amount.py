"""Unit tests for the mark-time amount resolution (resolve_mark_amount).

const.py is HA-free, so we load it in isolation and test the helper that decides
how much a mark decrements: the amount chosen at mark time if given, else the
dose's own amount, else the supply default.
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


def test_explicit_amount_wins():
    # marked_units overrides both the dose amount and the supply default.
    assert const.resolve_mark_amount(0.5, 1, 2) == 0.5


def test_explicit_zero_is_respected():
    # Marking "took nothing" is a valid explicit amount, not a fall-through.
    assert const.resolve_mark_amount(0, 1, 2) == 0.0


def test_none_falls_back_to_dose_amount():
    assert const.resolve_mark_amount(None, 1.5, 2) == 1.5


def test_none_and_no_dose_amount_uses_supply_default():
    assert const.resolve_mark_amount(None, 0, 2) == 2.0


def test_negative_explicit_is_clamped():
    assert const.resolve_mark_amount(-3, 1, 2) == 0.0


def test_bad_explicit_falls_back():
    assert const.resolve_mark_amount("lots", 1, 2) == 1.0
