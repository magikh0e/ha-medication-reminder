"""Sensor platform.

* `sensor.<patient>_next_dose` is a timestamp of the soonest dose still in the
  future, computed from each dose's schedule (any schedule type) via is_due.
* one `sensor.<patient>_<med>_last_taken` per as-needed (PRN) dose, a timestamp
  of when that med was last logged (button tap or the log_dose service), which
  survives restarts.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import slugify

from .const import (
    CONF_DOSES,
    CONF_MEDS,
    CONF_PATIENT,
    CONF_SCHEDULE_TYPE,
    CONF_TIME,
    DOMAIN,
    EVENT_DOSE_LOGGED,
    SCHEDULE_PRN,
    is_due,
)

# Re-evaluate this often so "next dose" rolls forward as time passes.
_SCAN = timedelta(seconds=60)
# How far ahead to look for the next due day (covers monthly/long cycles).
_HORIZON_DAYS = 366


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the next-dose sensor, plus a last-taken sensor per PRN dose."""
    patient: str = entry.data[CONF_PATIENT]
    doses: list[dict[str, Any]] = entry.options.get(CONF_DOSES, [])
    entities: list[SensorEntity] = [MedicationNextDoseSensor(entry, patient)]
    entities.extend(
        MedicationLastTakenSensor(
            entry, patient, str(dose[CONF_TIME])[:5], str(dose[CONF_MEDS])
        )
        for dose in doses
        if (dose.get(CONF_SCHEDULE_TYPE) or "") == SCHEDULE_PRN
    )
    async_add_entities(entities)


class MedicationNextDoseSensor(SensorEntity):
    """Timestamp of the patient's next upcoming dose."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-time-four-outline"

    def __init__(self, entry: ConfigEntry, patient: str) -> None:
        self._doses: list[dict[str, Any]] = entry.options.get(CONF_DOSES, [])
        self._patient = patient
        self._value: datetime | None = None
        self._meds: str | None = None
        self._attr_name = "Next dose"
        self._attr_unique_id = f"{entry.entry_id}_next_dose"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _compute(self) -> None:
        """Find the soonest dose datetime strictly after now."""
        now = dt_util.now()
        best: datetime | None = None
        best_meds: str | None = None
        for dose in self._doses:
            try:
                hour, minute = (int(p) for p in str(dose.get(CONF_TIME)).split(":")[:2])
            except (ValueError, AttributeError, TypeError):
                continue
            for offset in range(_HORIZON_DAYS):
                day = (now + timedelta(days=offset)).date()
                if not is_due(dose, day):
                    continue
                cand = datetime.combine(day, dtime(hour, minute), tzinfo=now.tzinfo)
                if cand > now:
                    if best is None or cand < best:
                        best, best_meds = cand, dose.get(CONF_MEDS)
                    break
        self._value, self._meds = best, best_meds

    @property
    def native_value(self) -> datetime | None:
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"patient": self._patient, "medications": self._meds}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._compute()
        self.async_on_remove(async_track_time_interval(self.hass, self._tick, _SCAN))

    @callback
    def _tick(self, _now: datetime) -> None:
        self._compute()
        self.async_write_ha_state()


class MedicationLastTakenSensor(RestoreSensor):
    """Timestamp of when a PRN dose was last logged; restart-safe.

    Updates whenever its medication is logged, by a Log dose button tap or the
    `log_dose` service (which can record an earlier taken-time). Pairs with the
    over-dose guard, so an automation can warn when a dose is logged too soon
    after the last one.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:history"

    def __init__(self, entry: ConfigEntry, patient: str, time: str, meds: str) -> None:
        self._patient = patient
        self._meds = meds
        self._value: datetime | None = None
        self._attr_name = f"{meds} last taken"
        self._attr_unique_id = (
            f"{entry.entry_id}_lasttaken_{slugify(time + '_' + meds)}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def native_value(self) -> datetime | None:
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"patient": self._patient, "medications": self._meds}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the last logged time across restarts.
        last = await self.async_get_last_sensor_data()
        if last is not None and isinstance(last.native_value, datetime):
            self._value = last.native_value
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_DOSE_LOGGED, self._on_dose_logged)
        )

    @callback
    def _on_dose_logged(self, event: Event) -> None:
        data = event.data
        if (
            data.get("patient") != self._patient
            or data.get("medications") != self._meds
        ):
            return
        when = dt_util.parse_datetime(data.get("logged_at") or "") or dt_util.now()
        self._value = dt_util.as_local(when)
        self.async_write_ha_state()
