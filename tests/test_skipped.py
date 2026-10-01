"""Unit tests for partial-dose skip matching (normalize_skipped, med_skipped).

const.py has no Home Assistant imports, so we load it in isolation (like
test_supply.py) and test the pure helpers without needing HA. These back the
"mark a dose given but skip one of its meds" feature: a skipped med's supply
must not decrement, while the other meds in the dose still do.
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


def test_normalize_list_strips_and_drops_blanks():
    assert const.normalize_skipped(["Vitamin D", "  Apoquel  ", ""]) == [
        "Vitamin D",
        "Apoquel",
    ]


def test_normalize_string_splits_on_separators():
    assert const.normalize_skipped("Vitamin D, Apoquel") == ["Vitamin D", "Apoquel"]
    assert const.normalize_skipped("Keppra & Phenobarbital") == [
        "Keppra",
        "Phenobarbital",
    ]


def test_normalize_keeps_bare_slash_name_whole():
    # A bare slash is part of the name, not a separator (same rule as dose meds).
    assert const.normalize_skipped("TMP/SMX") == ["TMP/SMX"]


def test_normalize_empty_inputs():
    assert const.normalize_skipped(None) == []
    assert const.normalize_skipped("") == []
    assert const.normalize_skipped([]) == []


def test_med_skipped_matches_case_insensitively():
    assert const.med_skipped(["Vitamin D"], "vitamin d") is True
    assert const.med_skipped("Vitamin D, Apoquel", "Apoquel") is True


def test_med_skipped_false_when_not_in_list():
    # The other meds in the dose are not skipped, so they still decrement.
    assert const.med_skipped(["Vitamin D"], "Apoquel") is False


def test_med_skipped_empty_is_false():
    assert const.med_skipped(None, "Apoquel") is False
    assert const.med_skipped([], "Apoquel") is False
    assert const.med_skipped("", "Apoquel") is False


def test_med_skipped_handles_combo_skip_entry():
    # A single skipped entry that itself lists several meds matches each of them.
    assert const.med_skipped(["Keppra & Phenobarbital"], "Phenobarbital") is True


def test_partial_skip_meds_lists_each_med_of_a_grouped_dose():
    assert const.partial_skip_meds("Apoquel & Vitamin D", "weekdays") == [
        "Apoquel",
        "Vitamin D",
    ]


def test_partial_skip_meds_empty_for_single_med_dose():
    # Nothing to partially skip when the dose has only one med.
    assert const.partial_skip_meds("Apoquel", "weekdays") == []


def test_partial_skip_meds_empty_for_prn():
    # PRN doses are logged per med already; no skip buttons.
    assert const.partial_skip_meds("Apoquel & Vitamin D", "prn") == []


def test_partial_skip_meds_keeps_bare_slash_name_whole():
    # A combo name with a bare slash stays one med, so a two-name dose like this
    # is still eligible and not mis-split.
    assert const.partial_skip_meds("TMP/SMX & Vitamin D", "weekdays") == [
        "TMP/SMX",
        "Vitamin D",
    ]


def test_partial_skip_meds_handles_empty_and_none():
    assert const.partial_skip_meds("", "weekdays") == []
    assert const.partial_skip_meds(None, "weekdays") == []
