"""Sensor platform.

* `sensor.<patient>_next_dose` is a timestamp of the soonest dose still in the
  future, computed from each dose's schedule (any schedule type) via is_due.
* per as-needed (PRN) dose: a `sensor.<patient>_<med>_last_taken` timestamp of
  when that med was last logged, a `sensor.<patient>_<med>_doses_today` count of
  how many times it was logged since the daily reset, and a
  `sensor.<patient>_<med>_days_this_month` count of the distinct days it was
  logged in the rolling last 30 days (for meds with a days-per-month limit). All
  survive restarts.
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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import (
    CONF_DOSES,
    CONF_MEDICATIONS,
    CONF_MEDS,
    CONF_PATIENT,
    CONF_PLAN_VIEW,
    CONF_RESET_TIME,
    CONF_SCHEDULE_TYPE,
    CONF_STREAK,
    CONF_SUPPLIES,
    CONF_TIME,
    DEFAULT_RESET_TIME,
    DOMAIN,
    EVENT_DOSE_GIVEN,
    EVENT_DOSE_LOGGED,
    EVENT_DOSE_SKIPPED,
    EVENT_DOSE_UNDONE,
    SCHEDULE_PRN,
    STREAK_WINDOW_DAYS,
    build_day_plan,
    classify_day,
    current_medications,
    is_due,
    med_day,
    medication_summary_line,
    reset_hms,
    streak_stats,
)

# Re-evaluate this often so "next dose" rolls forward as time passes.
_SCAN = timedelta(seconds=60)
# Rolling window (days) for the PRN "days this month" usage sensor.
_WINDOW_DAYS = 30
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
    entities: list[SensorEntity] = [
        MedicationNextDoseSensor(entry, patient),
        MedicationsSensor(entry, patient),
    ]
    for dose in doses:
        if (dose.get(CONF_SCHEDULE_TYPE) or "") != SCHEDULE_PRN:
            continue
        time = str(dose[CONF_TIME])[:5]
        meds = str(dose[CONF_MEDS])
        entities.append(MedicationLastTakenSensor(entry, patient, time, meds))
        entities.append(
            MedicationDosesTodaySensor(entry, patient, time, meds, reset_time)
        )
        entities.append(MedicationDaysThisMonthSensor(entry, patient, time, meds))
    # Pill-box plan view (opt-in): the per-day plan the dashboard card renders.
    if entry.options.get(CONF_PLAN_VIEW):
        entities.append(MedicationPlanSensor(entry, patient))
    # Adherence streak (opt-in): consecutive days every scheduled dose was taken.
    if entry.options.get(CONF_STREAK):
        entities.append(MedicationStreakSensor(entry, patient, doses, reset_time))
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

    def _period_key(self) -> str:
        """The date of the counting period now belongs to (reset to reset)."""
        return med_day(dt_util.now(), self._reset_time).isoformat()

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
        h, m, s = reset_hms(self._reset_time)
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


class MedicationDaysThisMonthSensor(RestoreSensor):
    """Distinct days a PRN med was logged in the rolling last 30 days.

    Answers "how many days this month did I take this?" for as-needed meds with
    a days-per-month limit, e.g. acute pain or migraine medication that should
    stay under about 10 days a month to avoid medication overuse. The state is
    the count of distinct days; the `dates` attribute lists which days (an
    archive to keep). The window rolls forward each day, so days older than 30
    fall out on their own even without a new dose. Restart-safe.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-check"
    _attr_native_unit_of_measurement = "days"

    def __init__(self, entry: ConfigEntry, patient: str, time: str, meds: str) -> None:
        self._patient = patient
        self._meds = meds
        self._days: set[str] = set()
        self._attr_name = f"{meds} days this month"
        self._attr_unique_id = (
            f"{entry.entry_id}_daysmonth_{slugify(time + '_' + meds)}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _prune(self) -> None:
        """Drop any recorded day that has aged out of the rolling window."""
        cutoff = (dt_util.now().date() - timedelta(days=_WINDOW_DAYS - 1)).isoformat()
        self._days = {d for d in self._days if d >= cutoff}

    @property
    def native_value(self) -> int:
        return len(self._days)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "patient": self._patient,
            "medications": self._meds,
            "window_days": _WINDOW_DAYS,
            "dates": sorted(self._days),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Restore the recorded days (the archive) across restarts, then prune
        # anything that has since aged out of the window.
        last_state = await self.async_get_last_state()
        if last_state is not None:
            stored = last_state.attributes.get("dates")
            if isinstance(stored, (list, tuple)):
                self._days = {str(d) for d in stored}
        self._prune()
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_DOSE_LOGGED, self._on_dose_logged)
        )
        # Re-evaluate just after midnight so an aged-out day drops on its own.
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._on_new_day, hour=0, minute=0, second=30
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
        when = dt_util.parse_datetime(data.get("logged_at") or "") or dt_util.now()
        self._prune()
        self._days.add(dt_util.as_local(when).date().isoformat())
        self.async_write_ha_state()

    @callback
    def _on_new_day(self, _now: datetime) -> None:
        self._prune()
        self.async_write_ha_state()


class MedicationsSensor(SensorEntity):
    """A current-medications summary for one patient.

    Lists every medication the patient takes (gathered from their doses),
    enriched with any reference detail (full name, strength, brand,
    prescribed-for, dosage). The state is the count of distinct medications; the
    `medications` attribute holds the detail and `summary` is a ready-to-share
    text block for handing to a provider.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:clipboard-text-outline"

    def __init__(self, entry: ConfigEntry, patient: str) -> None:
        self._patient = patient
        self._meds = current_medications(
            entry.options.get(CONF_DOSES, []),
            entry.options.get(CONF_MEDICATIONS, []),
        )
        self._attr_name = "Medications"
        self._attr_unique_id = f"{entry.entry_id}_medications"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def native_value(self) -> int:
        return len(self._meds)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "patient": self._patient,
            "medications": self._meds,
            "summary": "\n".join(medication_summary_line(m) for m in self._meds),
        }


class MedicationPlanSensor(SensorEntity):
    """The pill-box plan for the selected day: rows = meds, columns = time slots.

    Reads the plan-offset number to choose the date (today + offset), then
    computes the plan from the stored doses, supplies, and medication details.
    The state is the plan date; the `times` and `rows` attributes are the table
    the dashboard card renders. Created only when the plan view is enabled.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-check"

    def __init__(self, entry: ConfigEntry, patient: str) -> None:
        self._entry = entry
        self._patient = patient
        self._doses = entry.options.get(CONF_DOSES, [])
        self._supplies = entry.options.get(CONF_SUPPLIES, [])
        self._details = entry.options.get(CONF_MEDICATIONS, [])
        self._offset_unique_id = f"{entry.entry_id}_planoffset"
        self._attr_name = "Pill-box plan"
        self._attr_unique_id = f"{entry.entry_id}_plan"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    def _offset(self) -> int:
        """Current value of this patient's plan-offset number (0 if unavailable)."""
        registry = er.async_get(self.hass)
        eid = registry.async_get_entity_id("number", DOMAIN, self._offset_unique_id)
        if eid and (state := self.hass.states.get(eid)) is not None:
            try:
                return int(float(state.state))
            except (TypeError, ValueError):
                return 0
        return 0

    def _plan_date(self):
        return dt_util.now().date() + timedelta(days=self._offset())

    @property
    def native_value(self) -> str:
        return self._plan_date().isoformat()

    def _paused_keys(self) -> set:
        """(time, meds) of this patient's doses currently paused (suspended)."""
        keys = set()
        for s in self.hass.states.async_all("switch"):
            if s.attributes.get("patient") != self._patient:
                continue
            if s.attributes.get("paused"):
                keys.add(
                    (
                        str(s.attributes.get("dose_time")),
                        str(s.attributes.get("medications")),
                    )
                )
        return keys

    def _active_doses(self) -> list:
        """The configured doses minus any that are paused, so a suspended med is
        left out of the pill-box plan."""
        paused = self._paused_keys()
        return [
            d
            for d in self._doses
            if (str(d.get(CONF_TIME))[:5], str(d.get(CONF_MEDS))) not in paused
        ]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        day = self._plan_date()
        plan = build_day_plan(self._active_doses(), self._supplies, self._details, day)
        long = f"{day.strftime('%A')} {day.day} {day.strftime('%B %Y')}"
        return {
            "patient": self._patient,
            "plan_date": day.isoformat(),
            "plan_date_long": long,
            "offset": self._offset(),
            "times": plan["times"],
            "rows": plan["rows"],
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Recompute when the offset number changes, and just after midnight so the
        # date rolls over even when the offset value itself does not change.
        self.async_on_remove(
            self.hass.bus.async_listen("state_changed", self._on_offset_changed)
        )
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._midnight, hour=0, minute=0, second=5
            )
        )

    @callback
    def _on_offset_changed(self, event: Event) -> None:
        entity_id = event.data.get("entity_id", "")
        registry = er.async_get(self.hass)
        mine = registry.async_get_entity_id("number", DOMAIN, self._offset_unique_id)
        if entity_id == mine:
            self.async_write_ha_state()
            return
        # Recompute when one of this patient's doses is paused or resumed, since a
        # paused med drops out of the plan.
        if entity_id.startswith("switch."):
            new = event.data.get("new_state")
            if new is None or new.attributes.get("patient") != self._patient:
                return
            old = event.data.get("old_state")
            old_paused = old.attributes.get("paused") if old is not None else None
            if new.attributes.get("paused") != old_paused:
                self.async_write_ha_state()

    @callback
    def _midnight(self, _now) -> None:
        self.async_write_ha_state()


class MedicationStreakSensor(SensorEntity):
    """Adherence streak: consecutive completed days on which every scheduled dose
    for this patient was taken.

    A per-day outcome log is persisted, since the integration otherwise forgets
    each day at the reset. At the daily reset the day that just ended is scored
    from the doses given or skipped during it: taken (all given), skipped (all
    handled, at least one skip-today), missed (a due dose neither given nor
    skipped), or none (nothing due). The streak counts back from yesterday over
    taken-or-skipped days; a skip keeps the streak but counts against the
    adherence percentage, a "none" day is neutral, and a missed day or a gap
    (Home Assistant was off) ends it. Created only when the option is on.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:fire"
    _attr_native_unit_of_measurement = "days"

    _STORAGE_VERSION = 1
    _LOG_CAP_DAYS = 120  # how much day history to keep

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        doses: list[dict[str, Any]],
        reset_time: str,
    ) -> None:
        self._entry_id = entry.entry_id
        self._patient = patient
        self._doses = doses
        self._reset_time = reset_time
        # Dose key -> "given" | "skipped" for the current medication day, rebuilt
        # from the dose switches at startup and kept current by dose events.
        self._handled: dict[str, str] = {}
        self._outcomes: dict[str, str] = {}  # date ISO -> outcome, persisted
        self._stats: dict[str, Any] = {}
        self._store: Store | None = None
        self._attr_name = "Adherence streak"
        self._attr_unique_id = f"{entry.entry_id}_streak"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @staticmethod
    def _dose_key(time: Any, meds: Any) -> str:
        return f"{str(time)[:5]}|{str(meds)}"

    def _today(self):
        """The current medication day (reset-time bounded, not midnight)."""
        return med_day(dt_util.now(), self._reset_time)

    def _paused_keys(self) -> set:
        """(time, meds) of this patient's doses currently paused (suspended)."""
        keys = set()
        for s in self.hass.states.async_all("switch"):
            if s.attributes.get("patient") != self._patient:
                continue
            if s.attributes.get("paused"):
                keys.add(
                    (
                        str(s.attributes.get("dose_time")),
                        str(s.attributes.get("medications")),
                    )
                )
        return keys

    def _scheduled_keys(self, day) -> set:
        """Keys of this patient's scheduled (non-PRN) doses due on `day`,
        excluding any currently paused (suspended) dose. A paused med is left
        out, same as the pill-box plan, so a day on which everything due was
        taken or paused stays a clean day instead of scoring as missed."""
        paused = self._paused_keys()
        keys = set()
        for dose in self._doses:
            if (dose.get(CONF_SCHEDULE_TYPE) or "") == SCHEDULE_PRN:
                continue
            if (str(dose.get(CONF_TIME))[:5], str(dose.get(CONF_MEDS))) in paused:
                continue
            if is_due(dose, day):
                keys.add(self._dose_key(dose.get(CONF_TIME), dose.get(CONF_MEDS)))
        return keys

    def _recompute(self) -> None:
        self._stats = streak_stats(self._outcomes, self._today())

    @property
    def native_value(self) -> int:
        return int(self._stats.get("current_streak", 0))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "patient": self._patient,
            "longest_streak": self._stats.get("longest_streak", 0),
            "last_missed": self._stats.get("last_missed"),
            "adherence_percent": self._stats.get("adherence"),
            "window_days": STREAK_WINDOW_DAYS,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._store = Store(
            self.hass, self._STORAGE_VERSION, f"{DOMAIN}.{self._entry_id}.streak"
        )
        data = await self._store.async_load() or {}
        outcomes = data.get("outcomes")
        if isinstance(outcomes, dict):
            self._outcomes = {str(k): str(v) for k, v in outcomes.items()}
        # Rebuild today's handled set from the dose switches, so a restart part
        # way through the day keeps what has already been given or skipped.
        self._seed_handled()
        self._recompute()
        # Dose events keep the handled set current through the day.
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_DOSE_GIVEN, self._make_handler("given"))
        )
        self.async_on_remove(
            self.hass.bus.async_listen(
                EVENT_DOSE_SKIPPED, self._make_handler("skipped")
            )
        )
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_DOSE_UNDONE, self._on_undone)
        )
        # Finalise the ending day at the daily reset.
        hour, minute, second = reset_hms(self._reset_time)
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._finalize, hour=hour, minute=minute, second=second
            )
        )

    @callback
    def _seed_handled(self) -> None:
        for state in self.hass.states.async_all("switch"):
            attrs = state.attributes
            if attrs.get("patient") != self._patient:
                continue
            if attrs.get("medications") is None:
                continue  # not a dose switch (e.g. a pause toggle)
            key = self._dose_key(attrs.get("dose_time"), attrs.get("medications"))
            if state.state == "on":
                self._handled[key] = "given"
            elif attrs.get("skipped_today"):
                self._handled[key] = "skipped"

    def _make_handler(self, result: str):
        @callback
        def _handler(event: Event) -> None:
            if event.data.get("patient") != self._patient:
                return
            key = self._dose_key(
                event.data.get("dose_time"), event.data.get("medications")
            )
            self._handled[key] = result

        return _handler

    @callback
    def _on_undone(self, event: Event) -> None:
        if event.data.get("patient") != self._patient:
            return
        key = self._dose_key(event.data.get("dose_time"), event.data.get("medications"))
        self._handled.pop(key, None)

    @callback
    def _finalize(self, _now) -> None:
        """At the daily reset, score the day that just ended and append it."""
        ending = self._today() - timedelta(days=1)
        outcome = classify_day(self._scheduled_keys(ending), self._handled)
        self._outcomes[ending.isoformat()] = outcome
        cutoff = (self._today() - timedelta(days=self._LOG_CAP_DAYS)).isoformat()
        self._outcomes = {d: o for d, o in self._outcomes.items() if d >= cutoff}
        self._handled = {}
        self._recompute()
        self.async_write_ha_state()
        if self._store is not None:
            self.hass.async_create_task(
                self._store.async_save({"outcomes": self._outcomes})
            )
