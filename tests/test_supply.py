"""Unit tests for supply consumption arithmetic (apply_consumption).

const.py has no Home Assistant imports, so we load it in isolation (like
test_schedule.py) and test the pure decrement helper without needing HA. This
covers the "near-empty over-restore" fix: a mark records only what actually came
off, so a later un-mark cannot add back more than was removed.
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


def test_full_amount_removed_when_plenty_on_hand():
    assert const.apply_consumption(30, 1) == (29.0, 1.0)


def test_fractional_amount():
    assert const.apply_consumption(10, 0.5) == (9.5, 0.5)


def test_clamps_at_zero_and_reports_actual_removed():
    # 0.5 on hand, a whole-pill dose: only 0.5 can come off, and that is what is
    # reported, so the matching un-mark restores 0.5 and not 1 (the bug that
    # inflated near-empty supplies on a mark-then-unmark).
    new, removed = const.apply_consumption(0.5, 1)
    assert new == 0.0
    assert removed == 0.5


def test_empty_supply_removes_nothing():
    assert const.apply_consumption(0, 1) == (0.0, 0.0)


def test_mark_then_unmark_is_a_no_op_even_near_empty():
    # Simulate mark (record `removed`) then un-mark (add `removed` back): the
    # count must return to exactly where it started, at any level.
    for value, amount in [(30, 1), (0.5, 1), (10, 0.5), (0, 1), (1, 0.25)]:
        after_mark, removed = const.apply_consumption(value, amount)
        after_unmark = min(9999, after_mark + removed)
        assert after_unmark == float(value)


def test_bad_input_is_safe():
    assert const.apply_consumption(None, 1) == (0.0, 0.0)
    assert const.apply_consumption(5, None) == (5.0, 0.0)
    assert const.apply_consumption(5, -3) == (5.0, 0.0)  # negative amount ignored
