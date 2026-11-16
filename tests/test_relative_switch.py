"""Entity-level tests for relative / interval dose switches (#40).

A relative dose expands into one switch per daily occurrence: a fixed anchor
(position 0) and its legs (positions 1..N-1). A leg has no fixed clock time; it
exposes a ``due_at`` computed from the previous dose's actual give time plus the
offset, which the reminder blueprint times off. These cover the expansion, the
due-time wiring between occurrences, the chain-event refresh, and that each
occurrence decrements supply on its own (N pills a day from one bottle).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from entity_test_support import Event, State, load_entities


@pytest.fixture
def modules():
    with load_entities("switch", "number", "binary_sensor") as loaded:
        yield loaded


def build_chain(modules, given_state=None, **overrides):
    """Expand a relative dose and construct a switch per occurrence, all sharing
    one crash-safe give-state map (as the platform does)."""
    record = {
        "time": "07:00",
        "meds": "Amox",
        "schedule_type": "relative",
        "relative_count": 3,
        "relative_offset_hours": 5,
        "days": list(modules.switch.DEFAULT_DAYS),
        **overrides,
    }
    entry = SimpleNamespace(entry_id="e", options={"doses": [record]})
    store = {} if given_state is None else given_state
    switches = []
    for occ in modules.switch.expand_doses([record]):
        switches.append(
            modules.switch.MedicationDoseSwitch(
                entry, "Pat", "person", "", 30, 15, "24h", occ, store, AsyncMock()
            )
        )
    return entry, switches, store


def test_expands_into_n_distinct_switches(modules):
    _, sw, _ = build_chain(modules, relative_count=3)
    assert len(sw) == 3
    assert [s._position for s in sw] == [0, 1, 2]
    # Distinct entities, so three switches really are created.
    assert len({s._attr_unique_id for s in sw}) == 3


def test_occurrence_names(modules):
    _, sw, _ = build_chain(modules, relative_count=3)
    # Anchor leads with its clock time; legs are numbered, no fixed time.
    assert sw[0]._attr_name == "07:00 (Amox) 1/3"
    assert sw[1]._attr_name == "(Amox) 2/3"
    assert sw[2]._attr_name == "(Amox) 3/3"


def test_anchor_has_no_due_at(modules):
    _, sw, _ = build_chain(modules)
    attrs = sw[0].extra_state_attributes
    assert attrs["relative"] is True
    assert attrs["chain_position"] == 0
    assert attrs["due_at"] is None  # the anchor is a normal fixed-time dose


def test_leg_due_at_none_until_predecessor_given(modules):
    _, sw, _ = build_chain(modules)
    # Nothing given yet: the chain has not reached leg 1, so it must not remind.
    assert sw[1].extra_state_attributes["due_at"] is None
    assert sw[2].extra_state_attributes["due_at"] is None


def test_leg_due_at_is_predecessor_give_plus_offset(modules):
    _, sw, store = build_chain(modules, relative_offset_hours=5)
    # Anchor taken at 07:00 -> leg 1 due at 12:00.
    store[sw[0]._attr_unique_id] = "2026-06-01T07:00:00"
    assert sw[1].extra_state_attributes["due_at"] == "2026-06-01T12:00:00"
    # Leg 2 only comes due once leg 1 is taken (at, say, 12:30 -> 17:30).
    assert sw[2].extra_state_attributes["due_at"] is None
    store[sw[1]._attr_unique_id] = "2026-06-01T12:30:00"
    assert sw[2].extra_state_attributes["due_at"] == "2026-06-01T17:30:00"


def test_late_dose_pushes_the_next_leg(modules):
    _, sw, store = build_chain(modules, relative_offset_hours=6)
    store[sw[0]._attr_unique_id] = "2026-06-01T10:00:00"  # anchor taken 3h late
    assert sw[1].extra_state_attributes["due_at"] == "2026-06-01T16:00:00"


def test_chain_event_refreshes_only_its_own_chain(modules):
    _, sw, _ = build_chain(modules)
    leg = sw[1]
    writes = []
    leg.async_write_ha_state = lambda: writes.append(1)
    EVENT_GIVEN = modules.switch.EVENT_DOSE_GIVEN
    # A given event for this chain (same patient, meds, anchor time) refreshes it.
    leg._on_chain_event(
        Event(
            EVENT_GIVEN, {"patient": "Pat", "medications": "Amox", "dose_time": "07:00"}
        )
    )
    # A different med, or a different patient, or another time must not.
    leg._on_chain_event(
        Event(
            EVENT_GIVEN,
            {"patient": "Pat", "medications": "Other", "dose_time": "07:00"},
        )
    )
    leg._on_chain_event(
        Event(
            EVENT_GIVEN,
            {"patient": "Someone", "medications": "Amox", "dose_time": "07:00"},
        )
    )
    leg._on_chain_event(
        Event(
            EVENT_GIVEN, {"patient": "Pat", "medications": "Amox", "dose_time": "21:00"}
        )
    )
    assert writes == [1]


def test_chain_refreshes_on_undo_and_skip_too(modules):
    # Un-marking or skipping the previous dose must also re-publish the leg, so
    # its due_at clears back to None (the chain stall) the moment that happens.
    _, sw, _ = build_chain(modules)
    leg = sw[1]
    writes = []
    leg.async_write_ha_state = lambda: writes.append(1)
    chain = {"patient": "Pat", "medications": "Amox", "dose_time": "07:00"}
    leg._on_chain_event(Event(modules.switch.EVENT_DOSE_UNDONE, dict(chain)))
    leg._on_chain_event(Event(modules.switch.EVENT_DOSE_SKIPPED, dict(chain)))
    assert writes == [1, 1]


# --- chain transitions: unmark, skip, daily reset ---------------------------


def test_unmarking_the_anchor_blanks_the_leg_due_at(modules):
    _, sw, store = build_chain(modules, relative_offset_hours=5)
    # Anchor given -> leg 1 is due. Then the anchor is un-marked (its give-time
    # cleared from the shared store): leg 1 goes pending (due_at None) again.
    store[sw[0]._attr_unique_id] = "2026-06-01T07:00:00"
    assert sw[1].extra_state_attributes["due_at"] == "2026-06-01T12:00:00"
    store[sw[0]._attr_unique_id] = None  # un-mark clears the predecessor's time
    assert sw[1].extra_state_attributes["due_at"] is None


def test_skipping_a_leg_stalls_the_rest_of_the_chain(modules):
    _, sw, store = build_chain(modules, relative_count=3, relative_offset_hours=5)
    # Anchor taken -> leg 1 due. Leg 1 is skipped (never given, no give-time), so
    # leg 2, which times off leg 1, never comes due: the chain stops there.
    store[sw[0]._attr_unique_id] = "2026-06-01T07:00:00"
    assert sw[1].extra_state_attributes["due_at"] == "2026-06-01T12:00:00"
    # Leg 1 skipped -> its store entry stays None -> leg 2 is pending.
    assert sw[2].extra_state_attributes["due_at"] is None


def test_daily_reset_clears_the_chain(modules):
    _, sw, store = build_chain(modules, relative_count=3, relative_offset_hours=5)
    # A full day's chain taken: anchor 07:00, leg 1 at 12:00; leg 2 is due 17:00.
    store[sw[0]._attr_unique_id] = "2026-06-01T07:00:00"
    store[sw[1]._attr_unique_id] = "2026-06-01T12:00:00"
    assert sw[2].extra_state_attributes["due_at"] == "2026-06-01T17:00:00"
    # The daily reset clears every occurrence, anchor first (occurrence order), so
    # each leg re-reads a cleared predecessor and goes pending for the new day.
    for s in sw:
        s.reset_given()
    assert all(s._attr_is_on is False for s in sw)
    assert sw[1].extra_state_attributes["due_at"] is None
    assert sw[2].extra_state_attributes["due_at"] is None


# --- supply: each occurrence decrements on its own --------------------------


def make_supply(modules, switches):
    supply = modules.number.MedicationSupplyNumber(
        SimpleNamespace(entry_id="e"),
        "Pat",
        {"supply_med": "Amox", "supply_units": 30, "supply_per_dose": 1},
        "00:01:00",
    )
    supply.hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda _d: switches))
    supply.entity_id = "number.amox_supply"
    supply.async_write_ha_state = lambda: None
    return supply


def occ_state(entity_id):
    return State(
        entity_id,
        "on",
        {
            "patient": "Pat",
            "medications": "Amox",
            "schedule_type": "relative",
            "days": list(modules_days()),
            "dose_units": 1,
            "given_at": "2026-06-01T07:00:00+00:00",
        },
    )


def modules_days():
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def test_each_occurrence_decrements_supply_once(modules):
    modules.clock.now = lambda: datetime(2026, 6, 1, 14, tzinfo=timezone.utc)
    # Three given occurrence switches for one med -> three pills off one bottle.
    states = [occ_state(f"switch.amox_{i}") for i in range(3)]
    supply = make_supply(modules, states)
    supply._reconcile()
    assert supply.native_value == 27


# --- overdue sensor must not flag a not-yet-due leg -------------------------


def leg_state(entity_id, due_at, position=1):
    return State(
        entity_id,
        "off",
        {
            "patient": "Pat",
            "medications": "Amox",
            "schedule_type": "relative",
            "days": list(modules_days()),
            "relative": True,
            "chain_position": position,
            "due_at": due_at,
            "dose_time": "07:00",
            "nag_minutes": 45,
        },
    )


def make_needs_attention(modules, states):
    sensor = modules.binary_sensor.NeedsAttentionBinarySensor(
        SimpleNamespace(entry_id="e"), "Pat", "00:01:00"
    )
    sensor.hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda _d: states))
    return sensor


def test_pending_leg_is_not_overdue(modules):
    # It is 14:00 and the previous dose has not been taken, so leg 1 has no
    # due_at yet. It is pending, not overdue, so the panel stays calm.
    modules.clock.now = lambda: datetime(2026, 6, 1, 14, tzinfo=timezone.utc)
    sensor = make_needs_attention(modules, [leg_state("switch.amox_1", None)])
    assert sensor.is_on is False


def test_due_leg_past_its_window_is_overdue(modules):
    # Leg 1 came due at 12:00 (previous dose taken at, say, 07:00 + 5h) and it is
    # now 14:00, past the 45-minute window, still not given -> overdue.
    modules.clock.now = lambda: datetime(2026, 6, 1, 14, tzinfo=timezone.utc)
    sensor = make_needs_attention(
        modules, [leg_state("switch.amox_1", "2026-06-01T12:00:00+00:00")]
    )
    assert sensor.is_on is True


def test_leg_not_yet_at_its_window_is_not_overdue(modules):
    # Leg 1 is due at 16:00; at 14:00 it is not overdue yet.
    modules.clock.now = lambda: datetime(2026, 6, 1, 14, tzinfo=timezone.utc)
    sensor = make_needs_attention(
        modules, [leg_state("switch.amox_1", "2026-06-01T16:00:00+00:00")]
    )
    assert sensor.is_on is False
