"""Binary sensors for the Medication Reminder integration.

- <patient> all doses given : on when every dose scheduled today is given.
- <patient> needs attention  : problem sensor, on (red) when a dose is overdue.

Both consider only doses scheduled for the current day (any schedule type).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify

from .const import (
    CONF_DOSES,
    CONF_MEDS,
    CONF_NOTIFY,
    CONF_PATIENT,
    CONF_PATIENT_TYPE,
    CONF_RESET_TIME,
    CONF_SCHEDULE_TYPE,
    CONF_SUPPLIES,
    CONF_TIME,
    DEFAULT_PATIENT_TYPE,
    DEFAULT_RESET_TIME,
    DOMAIN,
    EVENT_DOSE_LOGGED,
    PATIENT_ICONS,
    SCHEDULE_PRN,
    dose_max_per_day,
    dose_min_interval_hours,
    dose_over_cap,
    dose_too_soon,
    is_due,
    next_dose_allowed,
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
    entities = [
        AllDosesGivenBinarySensor(entry, patient, patient_type),
        NeedsAttentionBinarySensor(entry, patient),
    ]
    # Only expose the supply-low sensor when supplies are configured.
    if entry.options.get(CONF_SUPPLIES):
        notify_target = entry.options.get(CONF_NOTIFY, "")
        entities.append(SuppliesLowBinarySensor(entry, patient, notify_target))
    # Over-dose guard: one per as-needed (PRN) dose that sets a minimum interval
    # between doses or a daily cap.
    reset_time = entry.options.get(CONF_RESET_TIME, DEFAULT_RESET_TIME)
    for dose in entry.options.get(CONF_DOSES, []):
        if (dose.get(CONF_SCHEDULE_TYPE) or "") != SCHEDULE_PRN:
            continue
        min_interval = dose_min_interval_hours(dose)
        max_per_day = dose_max_per_day(dose)
        if not (min_interval or max_per_day):
            continue
        entities.append(
            DoseGuardBinarySensor(
                entry,
                patient,
                str(dose[CONF_TIME])[:5],
                str(dose[CONF_MEDS]),
                min_interval,
                max_per_day,
                reset_time,
            )
        )
    async_add_entities(entities)


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
        """This patient's doses scheduled for today (any schedule type)."""
        today = dt_util.now().date()
        return [s for s in self._doses() if is_due(s.attributes, today)]

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
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, patient: str, patient_type: str) -> None:
        self._patient = patient
        self._patient_type = patient_type
        self._attr_name = "All doses given"
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
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, patient: str) -> None:
        self._patient = patient
        self._attr_name = "Needs attention"
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
            async_track_time_interval(self.hass, self._handle_interval, _CHECK_INTERVAL)
        )

    @callback
    def _handle_interval(self, _now) -> None:
        self.async_write_ha_state()


class SuppliesLowBinarySensor(BinarySensorEntity):
    """Problem sensor: on (red) when any of this patient's supplies is low.

    Aggregates the per-medication supply numbers (created by the number
    platform). A supply is "low" when its value is at or below its threshold.
    """

    _attr_should_poll = False
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, patient: str, notify_target: str) -> None:
        self._patient = patient
        self._notify = notify_target
        self._attr_name = "Supplies low"
        self._attr_unique_id = f"{entry.entry_id}_supplies_low"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _supplies(self) -> list:
        """This patient's supply number entities."""
        return [
            s
            for s in self.hass.states.async_all("number")
            if s.attributes.get("patient") == self._patient
            and s.attributes.get("medication") is not None
        ]

    def _low(self) -> list:
        """Supplies at or below their threshold."""
        low = []
        for s in self._supplies():
            threshold = s.attributes.get("threshold")
            if threshold is None:
                continue
            try:
                if float(s.state) <= float(threshold):
                    low.append(s)
            except (ValueError, TypeError):
                continue
        return low

    @property
    def is_on(self) -> bool:
        return bool(self._low())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        low = self._low()

        def _left(state) -> str:
            try:
                return str(int(float(state.state)))
            except (ValueError, TypeError):
                return state.state

        return {
            "patient": self._patient,
            "notify_service": self._notify,
            "low_count": len(low),
            "low": [f"{s.attributes.get('medication')}: {_left(s)} left" for s in low],
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _on_state_changed(event: Event) -> None:
            if not event.data.get("entity_id", "").startswith("number."):
                return
            new = event.data.get("new_state")
            if new is None or (
                new.attributes.get("patient") == self._patient
                and new.attributes.get("medication") is not None
            ):
                self.async_write_ha_state()

        self.async_on_remove(
            self.hass.bus.async_listen("state_changed", _on_state_changed)
        )


class DoseGuardBinarySensor(RestoreEntity, BinarySensorEntity):
    """Over-dose guard for one as-needed (PRN) dose.

    A `problem` sensor that is on when taking another dose right now would be too
    soon (within the configured minimum interval since the last log) or would
    exceed the daily cap. It only warns; the Log dose button and the log_dose
    service never block. Restart-safe.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:timer-alert-outline"

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        time: str,
        meds: str,
        min_interval_hours: float,
        max_per_day: int,
        reset_time: str,
    ) -> None:
        self._patient = patient
        self._meds = meds
        self._min_interval = min_interval_hours
        self._max_per_day = max_per_day
        self._reset_time = reset_time
        self._last_taken: datetime | None = None
        self._count = 0
        self._period: str | None = None
        self._attr_name = f"{meds} dose guard"
        self._attr_unique_id = (
            f"{entry.entry_id}_doseguard_{slugify(time + '_' + meds)}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _reset_hms(self) -> tuple[int, int, int]:
        try:
            parts = [int(p) for p in str(self._reset_time).split(":")]
            h, m = parts[0], parts[1]
            s = parts[2] if len(parts) > 2 else 0
        except (ValueError, IndexError, TypeError):
            h, m, s = 0, 1, 0
        return h % 24, m % 60, s % 60

    def _period_key(self) -> str:
        now = dt_util.now()
        h, m, s = self._reset_hms()
        boundary = now.replace(hour=h, minute=m, second=s, microsecond=0)
        if now < boundary:
            boundary -= timedelta(days=1)
        return boundary.date().isoformat()

    def _roll(self) -> None:
        cur = self._period_key()
        if self._period != cur:
            self._period = cur
            self._count = 0

    @property
    def is_on(self) -> bool:
        now = dt_util.now()
        return dose_too_soon(
            self._last_taken, self._min_interval, now
        ) or dose_over_cap(self._count, self._max_per_day)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now = dt_util.now()
        allowed = next_dose_allowed(self._last_taken, self._min_interval)
        return {
            "patient": self._patient,
            "medications": self._meds,
            "too_soon": dose_too_soon(self._last_taken, self._min_interval, now),
            "over_cap": dose_over_cap(self._count, self._max_per_day),
            "min_interval_hours": self._min_interval,
            "max_per_day": self._max_per_day,
            "doses_today": self._count,
            "remaining_today": (
                max(self._max_per_day - self._count, 0) if self._max_per_day else None
            ),
            "next_allowed": allowed.isoformat() if allowed else None,
            "last_taken": self._last_taken.isoformat() if self._last_taken else None,
            "period": self._period,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        cur = self._period_key()
        last = await self.async_get_last_state()
        if last is not None:
            lt = last.attributes.get("last_taken")
            if lt:
                self._last_taken = dt_util.parse_datetime(lt)
            if last.attributes.get("period") == cur:
                try:
                    self._count = int(last.attributes.get("doses_today") or 0)
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
        # Re-check on a timer so "too soon" clears once the interval elapses.
        self.async_on_remove(
            async_track_time_interval(self.hass, self._tick, _CHECK_INTERVAL)
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
        when = dt_util.parse_datetime(data.get("logged_at") or "") or dt_util.now()
        self._last_taken = dt_util.as_local(when)
        self._count += 1
        self.async_write_ha_state()

    @callback
    def _on_reset(self, _now: datetime) -> None:
        self._period = self._period_key()
        self._count = 0
        self.async_write_ha_state()

    @callback
    def _tick(self, _now: datetime) -> None:
        self.async_write_ha_state()
