"""Sensor platform.

* `sensor.<patient>_next_dose` is a timestamp of the soonest dose still in the
  future, computed from each dose's schedule (any schedule type) via is_due.
* per as-needed (PRN) dose: a `sensor.<patient>_<med>_last_taken` timestamp of
  when that med was last logged, and a `sensor.<patient>_<med>_doses_today`
  count of how many times it was logged since the daily reset. Both survive
  restarts.
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
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import slugify

from .const import (
    CONF_DOSES,
    CONF_MEDS,
    CONF_PATIENT,
    CONF_RESET_TIME,
    CONF_SCHEDULE_TYPE,
    CONF_TIME,
    DEFAULT_RESET_TIME,
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
    """Create the next-dose sensor, plus last-taken and doses-today per PRN dose."""
    patient: str = entry.data[CONF_PATIENT]
    doses: list[dict[str, Any]] = entry.options.get(CONF_DOSES, [])
    reset_time: str = entry.options.get(CONF_RESET_TIME, DEFAULT_RESET_TIME)
    entities: list[SensorEntity] = [MedicationNextDoseSensor(entry, patient)]
    for dose in doses:
        if (dose.get(CONF_SCHEDULE_TYPE) or "") != SCHEDULE_PRN:
            continue
        time = str(dose[CONF_TIME])[:5]
        meds = str(dose[CONF_MEDS])
        entities.append(MedicationLastTakenSensor(entry, patient, time, meds))
        entities.append(
            MedicationDosesTodaySensor(entry, patient, time, meds, reset_time)
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


class MedicationDosesTodaySensor(RestoreSensor):
    """Count of PRN doses logged so far today (since the daily reset).

    Increments on each Log dose press or `log_dose` call for this med, and
    resets to 0 at the patient's daily reset time. Restart-safe, and it drops
    back to 0 on restore if the stored count is from an earlier day. Answers
    "how many doses of this have I taken today?" without changing the button.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "doses"

    def __init__(
        self, entry: ConfigEntry, patient: str, time: str, meds: str, reset_time: str
    ) -> None:
        self._patient = patient
        self._meds = meds
        self._reset_time = reset_time
        self._count = 0
        self._period: str | None = None
        self._attr_name = f"{meds} doses today"
        self._attr_unique_id = (
            f"{entry.entry_id}_dosestoday_{slugify(time + '_' + meds)}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _reset_hms(self) -> tuple[int, int, int]:
        """The daily reset time as (hour, minute, second); 00:01:00 on bad input."""
        try:
            parts = [int(p) for p in str(self._reset_time).split(":")]
            h, m = parts[0], parts[1]
            s = parts[2] if len(parts) > 2 else 0
        except (ValueError, IndexError, TypeError):
            h, m, s = 0, 1, 0
        return h % 24, m % 60, s % 60

    def _period_key(self) -> str:
        """The date of the counting period now belongs to (reset to reset)."""
        now = dt_util.now()
        h, m, s = self._reset_hms()
        boundary = now.replace(hour=h, minute=m, second=s, microsecond=0)
        if now < boundary:
            boundary -= timedelta(days=1)
        return boundary.date().isoformat()

    def _roll(self) -> None:
        """Zero the count if we have crossed into a new reset period."""
        cur = self._period_key()
        if self._period != cur:
            self._period = cur
            self._count = 0

    @property
    def native_value(self) -> int:
        return self._count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "patient": self._patient,
            "medications": self._meds,
            "period": self._period,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the count, but only if it is still from today's reset period.
        cur = self._period_key()
        last = await self.async_get_last_sensor_data()
        last_state = await self.async_get_last_state()
        prev_period = last_state.attributes.get("period") if last_state else None
        if last is not None and last.native_value is not None and prev_period == cur:
            try:
                self._count = int(last.native_value)
            except (ValueError, TypeError):
                self._count = 0
        self._period = cur
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_DOSE_LOGGED, self._on_dose_logged)
        )
        h, m, s = self._reset_hms()
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._on_reset, hour=h, minute=m, second=s
            )
        )

    @callback
    def _on_dose_logged(self, event: Event) -> None:
        data = event.data
        if (
            data.get("patient") != self._patient
            or data.get("medications") != self._meds
        ):
            return
        self._roll()
        self._count += 1
        self.async_write_ha_state()

    @callback
    def _on_reset(self, _now: datetime) -> None:
        self._period = self._period_key()
        self._count = 0
        self.async_write_ha_state()
