"""Switch platform: one toggle per medication dose (on = given today)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import homeassistant.util.dt as dt_util
import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.util import slugify

from .const import (
    CONF_ANCHOR_DATE,
    CONF_CYCLE_OFF,
    CONF_CYCLE_ON,
    CONF_DAYS,
    CONF_DOSES,
    CONF_INTERVAL_DAYS,
    CONF_MEDS,
    CONF_MONTH_DAYS,
    CONF_NAG_INTERVAL,
    CONF_NAG_MINUTES,
    CONF_NOTIFY,
    CONF_PATIENT,
    CONF_PATIENT_TYPE,
    CONF_RESET_TIME,
    CONF_SCHEDULE_TYPE,
    CONF_TIME,
    CONF_TIME_FORMAT,
    DEFAULT_CYCLE_OFF,
    DEFAULT_CYCLE_ON,
    DEFAULT_DAYS,
    DEFAULT_INTERVAL_DAYS,
    DEFAULT_MONTH_DAYS,
    DEFAULT_NAG_INTERVAL,
    DEFAULT_NAG_MINUTES,
    DEFAULT_PATIENT_TYPE,
    DEFAULT_RESET_TIME,
    DEFAULT_TIME_FORMAT,
    DOMAIN,
    EVENT_DOSE_GIVEN,
    EVENT_DOSE_UNDONE,
    SCHEDULE_PRN,
    SCHEDULE_WEEKDAYS,
    SERVICE_MARK_GIVEN,
    is_due,
)


@dataclass
class _DoseExtraData(ExtraStoredData):
    """Restore-state payload: when the dose was actually marked given.

    The on/off state restores on its own, but a restart resets the entity's
    last_changed, so we persist the real give-time separately to keep the
    dashboard's "Already given at ..." accurate across restarts.
    """

    given_at: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"given_at": self.given_at}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a switch per dose and wire up the daily reset."""
    patient: str = entry.data[CONF_PATIENT]
    patient_type: str = entry.options.get(CONF_PATIENT_TYPE, DEFAULT_PATIENT_TYPE)
    notify_target: str = entry.options.get(CONF_NOTIFY, "")
    nag_minutes: int = entry.options.get(CONF_NAG_MINUTES, DEFAULT_NAG_MINUTES)
    nag_interval: int = entry.options.get(CONF_NAG_INTERVAL, DEFAULT_NAG_INTERVAL)
    time_format: str = entry.options.get(CONF_TIME_FORMAT, DEFAULT_TIME_FORMAT)
    doses: list[dict[str, Any]] = entry.options.get(CONF_DOSES, [])
    entities = [
        MedicationDoseSwitch(
            entry,
            patient,
            patient_type,
            notify_target,
            nag_minutes,
            nag_interval,
            time_format,
            dose,
        )
        for dose in doses
    ]
    async_add_entities(entities)

    # mark_given service: the plain toggle is "Take Now"; this records a dose
    # taken at a specified time (e.g. log at 9:00 that it was taken at 8:00).
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_MARK_GIVEN,
        {vol.Optional("given_at"): cv.datetime},
        "async_mark_given_at",
    )

    # Parse the configured daily-reset time (defaults to 00:01).
    reset_time = entry.options.get(CONF_RESET_TIME, DEFAULT_RESET_TIME)
    try:
        reset_hour, reset_minute = (int(p) for p in reset_time.split(":")[:2])
    except (ValueError, AttributeError):
        reset_hour, reset_minute = 0, 1

    @callback
    def _reset_all(_now) -> None:
        for entity in entities:
            entity.reset_given()

    entry.async_on_unload(
        async_track_time_change(
            hass, _reset_all, hour=reset_hour, minute=reset_minute, second=0
        )
    )


class MedicationDoseSwitch(SwitchEntity, RestoreEntity):
    """A single scheduled dose. on = given today, off = not yet given."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:pill"  # doses keep the pill icon regardless of patient type

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        patient_type: str,
        notify_target: str,
        nag_minutes: int,
        nag_interval: int,
        time_format: str,
        dose: dict[str, Any],
    ) -> None:
        self._patient = patient
        self._patient_type = patient_type
        self._notify = notify_target
        self._nag_minutes = nag_minutes
        self._nag_interval = nag_interval
        self._time_format = time_format
        self._time = str(dose[CONF_TIME])[:5]  # 24h "HH:MM" (used by automations)
        self._meds = dose[CONF_MEDS]
        # Days of the week this dose applies to (default: every day).
        self._days = dose.get(CONF_DAYS) or list(DEFAULT_DAYS)
        # Schedule type: weekdays (default) or every-N-days from an anchor date.
        self._schedule_type = dose.get(CONF_SCHEDULE_TYPE) or SCHEDULE_WEEKDAYS
        self._interval_days = int(dose.get(CONF_INTERVAL_DAYS) or DEFAULT_INTERVAL_DAYS)
        self._cycle_on = int(dose.get(CONF_CYCLE_ON) or DEFAULT_CYCLE_ON)
        _off = dose.get(CONF_CYCLE_OFF)
        self._cycle_off = int(_off if _off is not None else DEFAULT_CYCLE_OFF)
        self._anchor_date = dose.get(CONF_ANCHOR_DATE) or ""
        self._month_days = dose.get(CONF_MONTH_DAYS) or list(DEFAULT_MONTH_DAYS)
        # When the dose was last marked given (ISO), persisted across restarts.
        self._given_at: str | None = None
        # Name: as-needed (PRN) doses have no meaningful time, so name them by
        # the medication; scheduled doses lead with their display time.
        if self._schedule_type == SCHEDULE_PRN:
            self._attr_name = f"{self._meds} (as needed)"
        else:
            self._attr_name = f"{self._format_time(self._time)} ({self._meds})"
        self._attr_unique_id = (
            f"{entry.entry_id}_{slugify(self._time + '_' + self._meds)}"
        )
        self._attr_is_on = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _format_time(self, hhmm: str) -> str:
        """Format 24h 'HH:MM' per the patient's time_format setting."""
        if self._time_format == "24h":
            return hhmm
        try:
            hour_str, minute = hhmm.split(":")
            hour = int(hour_str)
            suffix = "AM" if hour < 12 else "PM"
            hour12 = hour % 12 or 12
            return f"{hour12}:{minute} {suffix}"
        except (ValueError, AttributeError):
            return hhmm

    def _schedule_attrs(self) -> dict[str, Any]:
        """The schedule fields shaped for is_due()."""
        return {
            CONF_SCHEDULE_TYPE: self._schedule_type,
            CONF_DAYS: self._days,
            CONF_INTERVAL_DAYS: self._interval_days,
            CONF_ANCHOR_DATE: self._anchor_date,
            CONF_CYCLE_ON: self._cycle_on,
            CONF_CYCLE_OFF: self._cycle_off,
            CONF_MONTH_DAYS: self._month_days,
        }

    def _scheduled_today(self) -> bool:
        """Whether this dose is due today, honouring its schedule type."""
        return is_due(self._schedule_attrs(), dt_util.now().date())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Metadata the companion automations read to build reminders."""
        return {
            "patient": self._patient,
            "patient_type": self._patient_type,
            "dose_time": self._time,
            "medications": self._meds,
            "days": self._days,
            "schedule_type": self._schedule_type,
            "interval_days": self._interval_days,
            "anchor_date": self._anchor_date,
            "cycle_on": self._cycle_on,
            "cycle_off": self._cycle_off,
            "month_days": self._month_days,
            "scheduled_today": self._scheduled_today(),
            "notify_service": self._notify,
            "nag_minutes": self._nag_minutes,
            "nag_interval": self._nag_interval,
            "time_format": self._time_format,
            "given_at": self._given_at,
        }

    @property
    def extra_restore_state_data(self) -> _DoseExtraData:
        """Persist the give-time so it survives restarts."""
        return _DoseExtraData(self._given_at)

    async def async_added_to_hass(self) -> None:
        """Restore the given/not-given state and give-time across restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
        restored = await self.async_get_last_extra_data()
        if restored is not None:
            self._given_at = restored.as_dict().get("given_at")
        if not self._attr_is_on:
            self._given_at = None
        elif not self._given_at and last_state is not None:
            # Dose marked given before given_at was tracked (or otherwise
            # missing): freeze its last known change time so the displayed
            # give-time stops drifting to the startup time on each restart.
            self._given_at = last_state.last_changed.isoformat()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mark this dose given now ("Take Now")."""
        await self.async_mark_given_at()

    async def async_mark_given_at(self, given_at: datetime | None = None) -> None:
        """Mark this dose given, optionally at a specified time.

        Backs the ``mark_given`` service. With no time it behaves like the
        toggle (records "now"); a ``given_at`` lets you log that the dose was
        taken at a different time than when you are tapping. Correcting the time
        on a dose already marked given just updates the timestamp; it does not
        re-fire the given event, so it will not re-warn or re-decrement supply.
        """
        was_on = self._attr_is_on
        self._attr_is_on = True
        if given_at is not None:
            self._given_at = dt_util.as_local(given_at).isoformat()
        elif not was_on:
            self._given_at = dt_util.now().isoformat()
        self.async_write_ha_state()
        if not was_on:
            self._fire_dose_given_event()

    @callback
    def _fire_dose_given_event(self) -> None:
        """Announce a dose was marked given, for companion automations."""
        # Use the give-time (now for a plain tap, or the specified time) so the
        # early-dose warning and scheduled-today flag reflect when it was taken.
        when = dt_util.parse_datetime(self._given_at or "") or dt_util.now()
        minutes_early: int | None = None
        try:
            hour, minute = (int(p) for p in self._time.split(":")[:2])
            due = when.replace(hour=hour, minute=minute, second=0, microsecond=0)
            minutes_early = round((due - when).total_seconds() / 60)
        except (ValueError, AttributeError):
            minutes_early = None
        self.hass.bus.async_fire(
            EVENT_DOSE_GIVEN,
            {
                "entity_id": self.entity_id,
                "patient": self._patient,
                "dose_time": self._time,
                "medications": self._meds,
                "days": self._days,
                "notify_service": self._notify,
                "scheduled_today": is_due(self._schedule_attrs(), when.date()),
                "minutes_early": minutes_early,
            },
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Mark this dose not given (un-mark). The daily reset uses reset_given,
        not this, so only a deliberate un-mark fires the undone event."""
        was_on = self._attr_is_on
        self._attr_is_on = False
        self._given_at = None
        self.async_write_ha_state()
        if was_on:
            self.hass.bus.async_fire(
                EVENT_DOSE_UNDONE,
                {
                    "entity_id": self.entity_id,
                    "patient": self._patient,
                    "medications": self._meds,
                },
            )

    @callback
    def reset_given(self) -> None:
        """Daily reset: clear the given flag and give-time."""
        self._attr_is_on = False
        self._given_at = None
        self.async_write_ha_state()
