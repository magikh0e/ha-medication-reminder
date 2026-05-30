"""Switch platform: one toggle per medication dose (on = given today)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify

from .const import (
    CONF_DOSES,
    CONF_MEDS,
    CONF_NAG_INTERVAL,
    CONF_NAG_MINUTES,
    CONF_NOTIFY,
    CONF_PATIENT,
    CONF_PATIENT_TYPE,
    CONF_RESET_TIME,
    CONF_TIME,
    DEFAULT_NAG_INTERVAL,
    DEFAULT_NAG_MINUTES,
    DEFAULT_PATIENT_TYPE,
    DEFAULT_RESET_TIME,
    DOMAIN,
)


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
    doses: list[dict[str, Any]] = entry.options.get(CONF_DOSES, [])
    entities = [
        MedicationDoseSwitch(
            entry, patient, patient_type, notify_target, nag_minutes, nag_interval, dose
        )
        for dose in doses
    ]
    async_add_entities(entities)

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
    _attr_icon = "mdi:pill"  # doses keep the pill icon regardless of patient type

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        patient_type: str,
        notify_target: str,
        nag_minutes: int,
        nag_interval: int,
        dose: dict[str, Any],
    ) -> None:
        self._patient = patient
        self._patient_type = patient_type
        self._notify = notify_target
        self._nag_minutes = nag_minutes
        self._nag_interval = nag_interval
        self._time = str(dose[CONF_TIME])[:5]  # 24h "HH:MM" (used by automations)
        self._meds = dose[CONF_MEDS]
        # 12h display, with the medications inline: "Patient 2:00 PM (Meds)"
        self._attr_name = f"{patient} {self._format_time(self._time)} ({self._meds})"
        self._attr_unique_id = (
            f"{entry.entry_id}_{slugify(self._time + '_' + self._meds)}"
        )
        self._attr_is_on = False
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @staticmethod
    def _format_time(hhmm: str) -> str:
        """Convert 24h 'HH:MM' to 12h 'H:MM AM/PM' for the entity name."""
        try:
            hour_str, minute = hhmm.split(":")
            hour = int(hour_str)
            suffix = "AM" if hour < 12 else "PM"
            hour12 = hour % 12 or 12
            return f"{hour12}:{minute} {suffix}"
        except (ValueError, AttributeError):
            return hhmm

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Metadata the companion automations read to build reminders."""
        return {
            "patient": self._patient,
            "patient_type": self._patient_type,
            "dose_time": self._time,
            "medications": self._meds,
            "notify_service": self._notify,
            "nag_minutes": self._nag_minutes,
            "nag_interval": self._nag_interval,
        }

    async def async_added_to_hass(self) -> None:
        """Restore the given/not-given state across restarts."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mark this dose given."""
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Mark this dose not given."""
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def reset_given(self) -> None:
        """Daily reset: clear the given flag."""
        self._attr_is_on = False
        self.async_write_ha_state()
