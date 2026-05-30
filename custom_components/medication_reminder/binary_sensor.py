"""Binary sensors for the Medication Reminder integration.

- <patient> all doses given : on when every dose scheduled today is given.
- <patient> needs attention  : problem sensor, on (red) when a dose is overdue.

Both consider only doses scheduled for the current day of the week.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_PATIENT,
    CONF_PATIENT_TYPE,
    DEFAULT_PATIENT_TYPE,
    DOMAIN,
    PATIENT_ICONS,
    WEEKDAYS,
)

# Re-check the overdue status this often, so it trips on time alone.
_CHECK_INTERVAL = timedelta(seconds=60)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the per-patient status sensors."""
    patient = entry.data[CONF_PATIENT]
    patient_type = entry.options.get(CONF_PATIENT_TYPE, DEFAULT_PATIENT_TYPE)
    async_add_entities(
        [
            AllDosesGivenBinarySensor(entry, patient, patient_type),
            NeedsAttentionBinarySensor(entry, patient),
        ]
    )


class _DoseLookupMixin:
    """Shared helpers to find a patient's dose switches and track changes."""

    _patient: str
    hass: HomeAssistant

    def _doses(self) -> list:
        """This patient's dose switches (matched by attributes)."""
        return [
            s
            for s in self.hass.states.async_all("switch")
            if s.attributes.get("medications") is not None
            and s.attributes.get("patient") == self._patient
        ]

    def _todays_doses(self) -> list:
        """This patient's doses scheduled for the current weekday."""
        today = WEEKDAYS[dt_util.now().weekday()]
        return [
            s
            for s in self._doses()
            if today in (s.attributes.get("days") or WEEKDAYS)
        ]

    @callback
    def _track_dose_changes(self) -> None:
        """Re-evaluate when one of this patient's dose switches changes."""

        @callback
        def _on_state_changed(event: Event) -> None:
            if not event.data.get("entity_id", "").startswith("switch."):
                return
            new = event.data.get("new_state")
            if new is None or (
                new.attributes.get("patient") == self._patient
                and new.attributes.get("medications") is not None
            ):
                self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen("state_changed", _on_state_changed)
        )


class AllDosesGivenBinarySensor(_DoseLookupMixin, BinarySensorEntity):
    """On when every dose scheduled today for this patient is marked given."""

    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, patient: str, patient_type: str) -> None:
        self._patient = patient
        self._patient_type = patient_type
        self._attr_name = f"{patient} all doses given"
        self._attr_unique_id = f"{entry.entry_id}_all_doses_given"
        self._attr_icon = PATIENT_ICONS.get(patient_type, "mdi:check-all")
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def is_on(self) -> bool | None:
        doses = self._todays_doses()
        if not doses:
            return None
        return all(s.state == "on" for s in doses)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        doses = self._todays_doses()
        total = len(doses)
        given = sum(1 for s in doses if s.state == "on")
        return {
            "patient": self._patient,
            "patient_type": self._patient_type,
            "total": total,
            "given": given,
            "remaining": total - given,
            "pending": [s.name for s in doses if s.state != "on"],
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_dose_changes()


class NeedsAttentionBinarySensor(_DoseLookupMixin, BinarySensorEntity):
    """Problem sensor: on (red) when a dose scheduled today is overdue.

    Re-evaluates every minute (not just on changes), so a dose crossing into
    "overdue" trips it red with no interaction. Fails safe toward "problem"
    rather than a false "all OK".
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, entry: ConfigEntry, patient: str) -> None:
        self._patient = patient
        self._attr_name = f"{patient} needs attention"
        self._attr_unique_id = f"{entry.entry_id}_needs_attention"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _overdue(self) -> list:
        """Today's doses past their time + nag window and still not given."""
        from .const import DEFAULT_NAG_MINUTES

        now = dt_util.now()
        overdue: list = []
        for s in self._todays_doses():
            if s.state == "on":
                continue  # given -> fine
            dose_time = s.attributes.get("dose_time")
            nag = s.attributes.get("nag_minutes", DEFAULT_NAG_MINUTES)
            try:
                hour, minute = (int(p) for p in str(dose_time).split(":")[:2])
                due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if now >= due + timedelta(minutes=int(nag)):
                    overdue.append(s)
            except (ValueError, TypeError, AttributeError):
                # Fail safe: a dose we cannot evaluate is treated as a problem.
                overdue.append(s)
        return overdue

    @property
    def is_on(self) -> bool:
        return bool(self._overdue())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        overdue = self._overdue()
        return {
            "patient": self._patient,
            "overdue_count": len(overdue),
            "overdue": [s.name for s in overdue],
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._track_dose_changes()
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._handle_interval, _CHECK_INTERVAL
            )
        )

    @callback
    def _handle_interval(self, _now) -> None:
        self.async_write_ha_state()
