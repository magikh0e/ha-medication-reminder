"""Calendar platform: each patient's dose schedule as a read-only calendar.

`calendar.<patient>_medication` shows one event per due dose, which makes the
interval and on/off-cycle schedules easy to see laid out over the weeks.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta

import homeassistant.util.dt as dt_util
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_DOSES,
    CONF_MEDS,
    CONF_PATIENT,
    CONF_TIME,
    DOMAIN,
    is_due,
)

# Each dose event is shown as a short block.
_EVENT_LENGTH = timedelta(minutes=15)
# How far ahead to look when reporting the "next" event.
_NEXT_HORIZON = timedelta(days=366)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the medication calendar for this patient."""
    patient: str = entry.data[CONF_PATIENT]
    async_add_entities([MedicationCalendar(entry, patient)])


class MedicationCalendar(CalendarEntity):
    """A read-only calendar of a patient's scheduled doses."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, entry: ConfigEntry, patient: str) -> None:
        self._entry = entry
        self._patient = patient
        self._attr_name = "Medication"
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _build_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Dose events that overlap the [start, end) window."""
        events: list[CalendarEvent] = []
        for dose in self._entry.options.get(CONF_DOSES, []):
            try:
                hour, minute = (int(p) for p in str(dose.get(CONF_TIME)).split(":")[:2])
            except (ValueError, AttributeError, TypeError):
                continue
            summary = dose.get(CONF_MEDS) or "Dose"
            day = start.date()
            while day <= end.date():
                if is_due(dose, day):
                    ev_start = datetime.combine(
                        day, dtime(hour, minute), tzinfo=dt_util.DEFAULT_TIME_ZONE
                    )
                    ev_end = ev_start + _EVENT_LENGTH
                    if ev_end > start and ev_start < end:
                        events.append(
                            CalendarEvent(start=ev_start, end=ev_end, summary=summary)
                        )
                day += timedelta(days=1)
        events.sort(key=lambda e: e.start)
        return events

    @property
    def event(self) -> CalendarEvent | None:
        """The current or next scheduled dose."""
        now = dt_util.now()
        upcoming = self._build_events(now, now + _NEXT_HORIZON)
        return upcoming[0] if upcoming else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Events in the requested range (used by the calendar UI)."""
        return self._build_events(start_date, end_date)
