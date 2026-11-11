"""A paused dose must not count as missed in the adherence streak.

Regression test for the bug where a suspended med was still treated as due by
the streak sensor, so every day scored as missed and the streak stuck at 0 with
adherence 0%. The pill-box plan already excluded paused doses; the streak sensor
now does the same, so a day on which everything due was taken or paused stays a
clean day.
"""

from types import SimpleNamespace

import pytest

from entity_test_support import State, load_entities

WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@pytest.fixture
def modules():
    with load_entities("sensor") as loaded:
        yield loaded


def dose(time="08:00", meds="Test med"):
    return {"time": time, "meds": meds, "schedule_type": "weekdays", "days": WEEK}


def switch(paused, time="08:00", meds="Test med", state="off"):
    return State(
        "switch." + meds.lower().replace(" ", "_") + "_" + time.replace(":", ""),
        state,
        {
            "patient": "Test patient",
            "medications": meds,
            "dose_time": time,
            "paused": paused,
        },
    )


def make_streak(modules, doses, switches):
    entry = SimpleNamespace(entry_id="test_entry")
    s = modules.sensor.MedicationStreakSensor(entry, "Test patient", doses, "00:01:00")
    s.hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda _domain: switches))
    return s


def test_paused_dose_is_excluded_from_scheduled(modules):
    s = make_streak(modules, [dose()], [switch(paused=True)])
    assert s._scheduled_keys(s._today()) == set()


def test_active_dose_is_still_scheduled(modules):
    s = make_streak(modules, [dose()], [switch(paused=False)])
    assert s._scheduled_keys(s._today()) != set()


def test_paused_only_day_scores_none_not_missed(modules):
    s = make_streak(modules, [dose()], [switch(paused=True)])
    day = s._today()
    # Before the fix this scored "missed" (due dose, never handled) and broke
    # the streak; a wholly-paused day must be neutral.
    assert modules.sensor.classify_day(s._scheduled_keys(day), s._handled) == "none"


def test_active_unhandled_day_still_scores_missed(modules):
    # Guards the test itself: an active, untouched due dose is still a miss.
    s = make_streak(modules, [dose()], [switch(paused=False)])
    day = s._today()
    assert modules.sensor.classify_day(s._scheduled_keys(day), s._handled) == "missed"


def test_active_given_with_other_paused_scores_taken(modules):
    doses = [dose("08:00", "Morning med"), dose("20:00", "Evening med")]
    switches = [
        switch(paused=False, time="08:00", meds="Morning med"),
        switch(paused=True, time="20:00", meds="Evening med"),
    ]
    s = make_streak(modules, doses, switches)
    s._handled[s._dose_key("08:00", "Morning med")] = "given"
    day = s._today()
    # The paused evening med drops out; the taken morning med makes it a clean day.
    assert modules.sensor.classify_day(s._scheduled_keys(day), s._handled) == "taken"
