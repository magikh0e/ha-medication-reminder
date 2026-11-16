"""Switch platform: one toggle per medication dose (on = given today)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import homeassistant.util.dt as dt_util
import voluptuous as vol
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    entity_platform,
    entity_registry as er,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import ExtraStoredData, RestoreEntity
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

from .const import (
    CONF_ANCHOR_DATE,
    CONF_ASK_UNITS,
    CONF_CYCLE_OFF,
    CONF_CYCLE_ON,
    CONF_DAYS,
    CONF_DOSES,
    CONF_DOSE_UNITS,
    CONF_END_DATE,
    CONF_INTERVAL_DAYS,
    CONF_MEDS,
    CONF_MONTH_DAYS,
    CONF_NAG_INTERVAL,
    CONF_NAG_MINUTES,
    CONF_NOTIFY,
    CONF_PATIENT,
    CONF_PATIENT_TYPE,
    CONF_PAUSE_SWITCHES,
    CONF_RELATIVE_POSITION,
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
    DEFAULT_PAUSE_SWITCHES,
    DEFAULT_RESET_TIME,
    DEFAULT_TIME_FORMAT,
    DOMAIN,
    EVENT_DOSE_GIVEN,
    EVENT_DOSE_SKIPPED,
    EVENT_DOSE_SNOOZED,
    EVENT_DOSE_UNDONE,
    SCHEDULE_PRN,
    SCHEDULE_RELATIVE,
    SCHEDULE_WEEKDAYS,
    SERVICE_MARK_GIVEN,
    SERVICE_SKIP_TODAY,
    SERVICE_SNOOZE,
    clamp_snooze_minutes,
    expand_doses,
    is_due,
    normalize_skipped,
    relative_count,
    relative_due_at,
    relative_offset_hours,
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


# Crash-safe store of each dose's give-time. RestoreEntity only flushes to disk
# every ~15 min and on a graceful shutdown, so an ungraceful stop (crash, OOM,
# power loss, hard reboot) shortly after marking a dose given would lose it and
# revert the dose to "not given", a double-dose risk. This store is written on
# every mark/un-mark/reset, so the given state survives those too.
_STORAGE_VERSION = 1


def _given_store(hass: HomeAssistant, entry_id: str) -> Store:
    """The per-entry store mapping a dose's unique_id to its give-time (or None)."""
    return Store(hass, _STORAGE_VERSION, f"{DOMAIN}.{entry_id}.doses")


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
    # Opt-in: add a pause toggle per scheduled dose (suspend a med until resumed).
    pause_enabled: bool = entry.options.get(CONF_PAUSE_SWITCHES, DEFAULT_PAUSE_SWITCHES)

    # Crash-safe given-state: load the saved map and a coroutine to persist it.
    store = _given_store(hass, entry.entry_id)
    given_state: dict[str, str | None] = await store.async_load() or {}

    async def _save_given() -> None:
        await store.async_save(given_state)

    dose_switches: list[MedicationDoseSwitch] = []
    entities: list[SwitchEntity] = []
    # A relative/interval dose expands into one switch per daily occurrence (the
    # fixed anchor plus its relative legs); every other dose yields one switch.
    for dose in expand_doses(doses):
        dose_switch = MedicationDoseSwitch(
            entry,
            patient,
            patient_type,
            notify_target,
            nag_minutes,
            nag_interval,
            time_format,
            dose,
            given_state,
            _save_given,
            pause_enabled,
        )
        dose_switches.append(dose_switch)
        entities.append(dose_switch)
        # Pause toggle only for scheduled (non-PRN) doses: a PRN dose has no
        # schedule to suspend. Added after its dose switch so the dose switch's
        # state restores first. It drives the dose switch's paused flag directly.
        # For a relative chain only the anchor (position 0) gets a toggle: pausing
        # it leaves the chain un-anchored, so the legs never come due either.
        is_relative = (dose.get(CONF_SCHEDULE_TYPE) or "") == SCHEDULE_RELATIVE
        is_leg = is_relative and int(dose.get(CONF_RELATIVE_POSITION) or 0) > 0
        if (
            pause_enabled
            and (dose.get(CONF_SCHEDULE_TYPE) or "") != SCHEDULE_PRN
            and not is_leg
        ):
            pause_switch = MedicationDosePauseSwitch(entry, patient, dose, dose_switch)
            dose_switch.register_pause_switch(pause_switch)
            entities.append(pause_switch)
    async_add_entities(entities)

    # mark_given service: the plain toggle is "Take Now"; this records a dose
    # taken at a specified time (e.g. log at 9:00 that it was taken at 8:00).
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_MARK_GIVEN,
        {
            vol.Optional("given_at"): cv.datetime,
            # Meds in this dose that were NOT taken (partial dose). Their supply
            # is not decremented. Accepts a list or a single/separated string.
            vol.Optional("skipped"): vol.Any(cv.string, [cv.string]),
            # The amount actually taken, for a dose whose quantity varies. The
            # matching supply decrements by this instead of the configured amount.
            vol.Optional("units"): vol.Coerce(float),
        },
        "async_mark_given_at",
    )
    # skip_today service: clear a dose for the day without taking it. It is a
    # third state, distinct from given and not-given: reminders stop, supply is
    # untouched, and the status sensors treat it as handled until the daily reset.
    platform.async_register_entity_service(
        SERVICE_SKIP_TODAY,
        {},
        "async_skip_today",
    )
    # snooze service: "remind me later". Defers this dose's reminder (and its
    # missed-dose escalation) by `minutes`, without marking it given or skipped.
    platform.async_register_entity_service(
        SERVICE_SNOOZE,
        {vol.Optional("minutes"): vol.Coerce(int)},
        "async_snooze",
    )

    # Parse the configured daily-reset time (defaults to 00:01).
    reset_time = entry.options.get(CONF_RESET_TIME, DEFAULT_RESET_TIME)
    try:
        reset_hour, reset_minute = (int(p) for p in reset_time.split(":")[:2])
    except (ValueError, AttributeError):
        reset_hour, reset_minute = 0, 1

    @callback
    def _reset_all(_now) -> None:
        for entity in dose_switches:
            entity.reset_given()
        # One disk write for the whole reset, not one per dose.
        hass.async_create_task(_save_given())

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
        given_state: dict[str, str | None],
        save_given: Callable[[], Awaitable[None]],
        pause_enabled: bool = False,
    ) -> None:
        # Shared crash-safe given-state map (unique_id -> give-time) and its saver.
        self._given_state = given_state
        self._save_given = save_given
        # Pause (suspend): honoured only when the pause-switches option is on, so
        # turning the option off resumes everything. Set by the sibling pause
        # switch; unlike the given/skip state it is NOT cleared by the daily reset,
        # so a med stays paused across days until the toggle is switched back.
        self._pause_enabled = pause_enabled
        self._paused: bool = False
        self._pause_switch: SwitchEntity | None = None
        self._patient = patient
        self._patient_type = patient_type
        self._notify = notify_target
        self._nag_minutes = nag_minutes
        self._nag_interval = nag_interval
        self._time_format = time_format
        self._time = str(dose[CONF_TIME])[:5]  # 24h "HH:MM" (used by automations)
        self._meds = dose[CONF_MEDS]
        # Optional per-dose consumption override (0 = use the supply default).
        self._dose_units = float(dose.get(CONF_DOSE_UNITS) or 0)
        # Opt-in: honour an amount chosen at mark time (for a varying-dose med).
        self._ask_units = bool(dose.get(CONF_ASK_UNITS, False))
        # The amount used on today's mark (None = the configured amount).
        self._marked_units: float | None = None
        # Days of the week this dose applies to (default: every day).
        self._days = dose.get(CONF_DAYS) or list(DEFAULT_DAYS)
        # Schedule type: weekdays (default) or every-N-days from an anchor date.
        self._schedule_type = dose.get(CONF_SCHEDULE_TYPE) or SCHEDULE_WEEKDAYS
        self._interval_days = int(dose.get(CONF_INTERVAL_DAYS) or DEFAULT_INTERVAL_DAYS)
        self._cycle_on = int(dose.get(CONF_CYCLE_ON) or DEFAULT_CYCLE_ON)
        _off = dose.get(CONF_CYCLE_OFF)
        self._cycle_off = int(_off if _off is not None else DEFAULT_CYCLE_OFF)
        self._anchor_date = dose.get(CONF_ANCHOR_DATE) or ""
        self._end_date = dose.get(CONF_END_DATE) or ""
        # The patient's daily reset time, echoed so a dashboard can place a bare
        # dose_time ("HH:MM") on the right medication day when the reset is not
        # midnight (a dose before the reset belongs to the previous day).
        self._reset_time = str(entry.options.get(CONF_RESET_TIME, DEFAULT_RESET_TIME))
        self._month_days = dose.get(CONF_MONTH_DAYS) or list(DEFAULT_MONTH_DAYS)
        # Relative / interval chain (one switch per daily occurrence): position 0
        # is the fixed anchor, positions 1.. are legs timed from the previous
        # dose's actual give time. A leg's reminder fires off its computed
        # `due_at` instead of a fixed clock time; see _relative_due_at.
        self._relative = self._schedule_type == SCHEDULE_RELATIVE
        self._position = int(dose.get(CONF_RELATIVE_POSITION) or 0)
        self._chain_count = relative_count(dose) if self._relative else 1
        self._offset_hours = relative_offset_hours(dose) if self._relative else 0.0
        # When the dose was last marked given (ISO), persisted across restarts.
        self._given_at: str | None = None
        # Meds in this dose skipped on today's mark (partial dose). Empty unless
        # the dose was marked given with a `skipped` list; cleared on un-mark and
        # the daily reset.
        self._skipped: list[str] = []
        # Whole-dose "skipped for today": a third state, neither given nor
        # not-given. Reminders stop and supply is untouched; cleared on mark-given
        # and the daily reset.
        self._skipped_today: bool = False
        # "Remind me later": an ISO time until which the reminder (and its missed
        # escalation) is deferred. Cleared on mark-given, skip, un-mark, and reset.
        self._snooze_until: str | None = None
        # A relative chain's switches share the same time+meds, so each occurrence
        # gets a position suffix to stay a distinct entity, and a leg records the
        # id of the dose before it to read that dose's give time for its own due.
        id_base = slugify(self._time + "_" + self._meds)
        if self._relative:
            id_base_rel = f"{id_base}_r{self._position}"
        else:
            id_base_rel = id_base
        self._pred_unique_id = (
            f"{entry.entry_id}_{slugify(self._time + '_' + self._meds)}_r"
            f"{self._position - 1}"
            if self._relative and self._position > 0
            else None
        )
        # Name: as-needed (PRN) doses have no meaningful time, so name them by
        # the medication; scheduled doses lead with their display time. A relative
        # chain numbers its occurrences; only the anchor has a fixed clock time.
        if self._schedule_type == SCHEDULE_PRN:
            self._attr_name = f"{self._meds} (as needed)"
        elif self._relative and self._position == 0:
            self._attr_name = (
                f"{self._format_time(self._time)} ({self._meds}) 1/{self._chain_count}"
            )
        elif self._relative:
            self._attr_name = f"({self._meds}) {self._position + 1}/{self._chain_count}"
        else:
            self._attr_name = f"{self._format_time(self._time)} ({self._meds})"
        self._attr_unique_id = f"{entry.entry_id}_{id_base_rel}"
        # The sibling amount-input number (created only for ask_units doses), read
        # at mark time so the normal mark-given honours the chosen amount.
        self._amount_unique_id = f"{entry.entry_id}_amount_{id_base_rel}"
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
            CONF_END_DATE: self._end_date,
            CONF_CYCLE_ON: self._cycle_on,
            CONF_CYCLE_OFF: self._cycle_off,
            CONF_MONTH_DAYS: self._month_days,
        }

    def _scheduled_today(self) -> bool:
        """Whether this dose is due today, honouring its schedule type."""
        return is_due(self._schedule_attrs(), dt_util.now().date())

    def _relative_due_at(self) -> str | None:
        """When this relative leg is due: the previous dose in the chain's actual
        give time plus the offset, as an ISO string. None for the anchor (it is a
        normal fixed-time dose) and for a leg whose predecessor is not yet given
        (the chain has not reached it, so it must not remind). The reminder
        blueprint times a leg off this instead of a fixed clock time."""
        if not self._relative or self._position == 0 or self._pred_unique_id is None:
            return None
        return relative_due_at(
            self._given_state.get(self._pred_unique_id), self._offset_hours
        )

    def _read_amount(self) -> float | None:
        """The current value of this dose's amount-input number, if it has one.

        Returns None when the dose is not an adjustable-quantity one or the
        number is unavailable, so the mark falls back to the configured amount.
        """
        if not self._ask_units:
            return None
        registry = er.async_get(self.hass)
        amount_eid = registry.async_get_entity_id(
            "number", DOMAIN, self._amount_unique_id
        )
        if not amount_eid:
            return None
        state = self.hass.states.get(amount_eid)
        if state is None:
            return None
        try:
            return max(0.0, float(state.state))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Metadata the companion automations read to build reminders."""
        return {
            "patient": self._patient,
            "patient_type": self._patient_type,
            "dose_time": self._time,
            "medications": self._meds,
            "dose_units": self._dose_units,
            "days": self._days,
            "schedule_type": self._schedule_type,
            "interval_days": self._interval_days,
            "anchor_date": self._anchor_date,
            "end_date": self._end_date,
            "cycle_on": self._cycle_on,
            "cycle_off": self._cycle_off,
            "month_days": self._month_days,
            # Relative / interval chain: a leg reminds off `due_at` (previous
            # dose's give time + offset), not its anchor clock time. `due_at` is
            # None for the anchor and for a leg not yet reached by the chain.
            "relative": self._relative,
            "chain_position": self._position,
            "chain_count": self._chain_count,
            "relative_offset_hours": self._offset_hours,
            "due_at": self._relative_due_at(),
            "scheduled_today": self._scheduled_today(),
            "skipped": self._skipped,
            "skipped_today": self._skipped_today,
            "snooze_until": self._snooze_until,
            "ask_units": self._ask_units,
            "marked_units": self._marked_units,
            "notify_service": self._notify,
            "nag_minutes": self._nag_minutes,
            "nag_interval": self._nag_interval,
            "time_format": self._time_format,
            "reset_time": self._reset_time,
            "given_at": self._given_at,
            # Suspended until resumed: no reminders, not overdue, left out of the
            # day summary and the pill-box plan. Persists across the daily reset.
            "paused": self._paused,
        }

    @property
    def paused(self) -> bool:
        """Whether this dose is suspended (the pause toggle is on)."""
        return self._paused

    def register_pause_switch(self, pause_switch: SwitchEntity) -> None:
        """Link the sibling pause toggle so a change refreshes its display."""
        self._pause_switch = pause_switch

    async def async_pause(self) -> None:
        """Suspend this dose until resumed (no effect unless the option is on)."""
        if not self._pause_enabled or self._paused:
            return
        self._paused = True
        self.async_write_ha_state()
        if self._pause_switch is not None:
            self._pause_switch.async_write_ha_state()

    async def async_resume(self) -> None:
        """Resume a suspended dose."""
        if not self._paused:
            return
        self._paused = False
        self.async_write_ha_state()
        if self._pause_switch is not None:
            self._pause_switch.async_write_ha_state()

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
        # The crash-safe store is authoritative when it has a record for this
        # dose: it is written on every change, so it survives an ungraceful
        # shutdown that RestoreEntity's periodic dump would miss.
        if self._attr_unique_id in self._given_state:
            self._given_at = self._given_state[self._attr_unique_id]
            self._attr_is_on = self._given_at is not None
        # Restore today's skipped-meds list while the dose is still marked given,
        # so a reload/restart does not lose which meds were skipped (and a later
        # re-toggle would not then decrement a skipped med's supply).
        if self._attr_is_on and last_state is not None:
            self._skipped = normalize_skipped(last_state.attributes.get("skipped"))
            # Restore the amount this mark used, so the display and a later
            # un-mark stay consistent (the supply was already decremented by it).
            restored_units = last_state.attributes.get("marked_units")
            if restored_units is not None:
                try:
                    self._marked_units = float(restored_units)
                except (TypeError, ValueError):
                    self._marked_units = None
        # Restore a "skipped today" across a reload/restart. Only meaningful while
        # the dose is not given; marking given clears it and the daily reset does
        # too, so a restored skip never outlives its day.
        if not self._attr_is_on and last_state is not None:
            self._skipped_today = bool(last_state.attributes.get("skipped_today"))
            # Restore a pending snooze; a stale (past) value is harmless, as the
            # reminder logic only defers while now is before it, and the daily
            # reset clears it.
            self._snooze_until = last_state.attributes.get("snooze_until")
        if not self._attr_is_on:
            self._given_at = None
        elif not self._given_at and last_state is not None:
            # Dose marked given before given_at was tracked (or otherwise
            # missing): freeze its last known change time so the displayed
            # give-time stops drifting to the startup time on each restart.
            self._given_at = last_state.last_changed.isoformat()
        # Restore the pause (suspend) state, independent of the given/skip state
        # and not tied to the day. Honoured only while the option is on, so
        # turning the option off (the entity is recreated without pause enabled)
        # resumes every dose rather than stranding one paused with no toggle.
        if self._pause_enabled and last_state is not None:
            self._paused = bool(last_state.attributes.get("paused"))
        # Migration: a dose marked given under a pre-store version is not in the
        # store yet. Seed it now so it is crash-safe without waiting for a re-mark.
        if self._attr_is_on and self._attr_unique_id not in self._given_state:
            self._given_state[self._attr_unique_id] = self._given_at
            await self._save_given()
        # A relative leg's `due_at` depends on the dose before it in the chain, so
        # refresh this entity's state whenever a chain-mate is given, un-done,
        # skipped, or reset. That re-publishes due_at (which the reminder
        # blueprint reads) the moment the previous dose is taken, arming this
        # leg's reminder, and clears it again if that dose is undone.
        if self._relative and self._position > 0:
            for event_type in (
                EVENT_DOSE_GIVEN,
                EVENT_DOSE_UNDONE,
                EVENT_DOSE_SKIPPED,
            ):
                self.async_on_remove(
                    self.hass.bus.async_listen(event_type, self._on_chain_event)
                )

    @callback
    def _on_chain_event(self, event: Event) -> None:
        """Re-publish state (and so `due_at`) when another dose in this chain
        changes. Scoped to this chain by patient, medications, and anchor time,
        which every occurrence of the chain shares."""
        data = event.data
        if (
            data.get("patient") == self._patient
            and data.get("medications") == self._meds
            and data.get("dose_time") == self._time
        ):
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Mark this dose given now ("Take Now")."""
        await self.async_mark_given_at()

    async def async_mark_given_at(
        self,
        given_at: datetime | None = None,
        skipped: Any = None,
        units: float | None = None,
    ) -> None:
        """Mark this dose given, optionally at a specified time.

        Backs the ``mark_given`` service. With no time it behaves like the
        toggle (records "now"); a ``given_at`` lets you log that the dose was
        taken at a different time than when you are tapping. Correcting the time
        on a dose already marked given just updates the timestamp; it does not
        re-fire the given event, so it will not re-warn or re-decrement supply.

        ``skipped`` names meds in this dose that were not actually taken (a
        partial dose); their supply is left alone. It is only applied on a fresh
        mark (off -> on), so it must be given when the dose is first marked, not
        on a later time-correction, and it is set before the state write so the
        supply numbers see it as they decide whether to decrement.
        """
        was_on = self._attr_is_on
        self._attr_is_on = True
        # Marking given overrides a "skipped today": the dose was taken after all.
        self._skipped_today = False
        self._snooze_until = None
        if given_at is not None:
            self._given_at = dt_util.as_local(given_at).isoformat()
        elif not was_on:
            self._given_at = dt_util.now().isoformat()
        if not was_on:
            self._skipped = normalize_skipped(skipped)
            # The amount this mark used: an explicit units value wins, else the
            # dose's amount-input number (for an adjustable-quantity dose), else
            # None, meaning the configured per-dose/supply amount.
            if units is not None:
                try:
                    self._marked_units = max(0.0, float(units))
                except (TypeError, ValueError):
                    self._marked_units = None
            else:
                self._marked_units = self._read_amount()
        self._given_state[self._attr_unique_id] = self._given_at
        await self._save_given()
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
        # A relative leg has no fixed clock time (its due shifts with the previous
        # dose), so an early/late figure against the anchor would be meaningless.
        if not (self._relative and self._position > 0):
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
                "skipped": self._skipped,
                "units": self._marked_units,
            },
        )

    async def async_skip_today(self) -> None:
        """Skip this dose for the day: not taken, supply untouched, reminders off.

        A third state distinct from given and not-given. The switch stays off but
        carries ``skipped_today``, which the status sensors and reminder blueprint
        treat as handled. If the dose had already been marked given, the give is
        undone first (firing the undone event, which restores its supply) so a
        skip never leaves a phantom decrement behind. Cleared at the daily reset,
        or by marking the dose given.
        """
        was_on = self._attr_is_on
        self._attr_is_on = False
        self._given_at = None
        self._skipped = []
        self._skipped_today = True
        self._snooze_until = None
        self._marked_units = None
        self._given_state[self._attr_unique_id] = None
        await self._save_given()
        self.async_write_ha_state()
        if was_on:
            # Undo the earlier give so its supply is put back before the skip.
            self.hass.bus.async_fire(
                EVENT_DOSE_UNDONE,
                {
                    "entity_id": self.entity_id,
                    "patient": self._patient,
                    "dose_time": self._time,
                    "medications": self._meds,
                },
            )
        self.hass.bus.async_fire(
            EVENT_DOSE_SKIPPED,
            {
                "entity_id": self.entity_id,
                "patient": self._patient,
                "dose_time": self._time,
                "medications": self._meds,
                "notify_service": self._notify,
            },
        )

    async def async_snooze(self, minutes: int | None = None) -> None:
        """Defer this dose's reminder for a delay ("remind me later").

        Records a ``snooze_until`` time; the reminder automation pushes this
        dose's nag window and its missed-dose escalation out to that time, so the
        reminder goes quiet and comes back once, later, if the dose is still not
        given or skipped. It does not mark the dose given or skipped. A snooze on
        an already-given dose is a no-op in effect, since a given dose is not
        reminded; the daily reset and marking given both clear it.
        """
        until = dt_util.now() + timedelta(minutes=clamp_snooze_minutes(minutes))
        self._snooze_until = until.isoformat()
        self.async_write_ha_state()
        self.hass.bus.async_fire(
            EVENT_DOSE_SNOOZED,
            {
                "entity_id": self.entity_id,
                "patient": self._patient,
                "dose_time": self._time,
                "medications": self._meds,
                "snooze_until": self._snooze_until,
                "notify_service": self._notify,
            },
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Mark this dose not given (un-mark). The daily reset uses reset_given,
        not this, so only a deliberate un-mark fires the undone event."""
        was_on = self._attr_is_on
        self._attr_is_on = False
        self._given_at = None
        self._skipped = []
        self._skipped_today = False
        self._snooze_until = None
        self._marked_units = None
        self._given_state[self._attr_unique_id] = None
        await self._save_given()
        self.async_write_ha_state()
        if was_on:
            self.hass.bus.async_fire(
                EVENT_DOSE_UNDONE,
                {
                    "entity_id": self.entity_id,
                    "patient": self._patient,
                    "dose_time": self._time,
                    "medications": self._meds,
                },
            )

    @callback
    def reset_given(self) -> None:
        """Daily reset: clear the given flag and give-time. The shared store is
        saved once by the reset loop, not per dose. The pause (suspend) state is
        deliberately left untouched, so a paused med stays paused across days."""
        self._attr_is_on = False
        self._given_at = None
        self._skipped = []
        self._skipped_today = False
        self._snooze_until = None
        self._marked_units = None
        self._given_state[self._attr_unique_id] = None
        self.async_write_ha_state()


class MedicationDosePauseSwitch(SwitchEntity):
    """The panel toggle to suspend a scheduled dose until resumed.

    A thin control over its dose switch's pause flag (the single source of
    truth, persisted there), created only for scheduled doses when the
    pause-switches option is on. On suspends the dose: no reminders, not flagged
    overdue, left out of the day summary and the pill-box plan, and no supply
    counted down, until it is switched back off. The suspend survives the daily
    reset and restarts; it is cleared only by resuming or by turning the option
    off.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:pause-circle-outline"

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        dose: dict[str, Any],
        dose_switch: MedicationDoseSwitch,
    ) -> None:
        self._dose = dose_switch
        self._patient = patient
        self._time = str(dose[CONF_TIME])[:5]
        meds = str(dose[CONF_MEDS])
        self._attr_name = f"Pause {self._time} {meds}"
        self._attr_unique_id = (
            f"{entry.entry_id}_pause_{slugify(self._time + '_' + meds)}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def is_on(self) -> bool:
        return self._dose.paused

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # A pause-control marker and the dose's patient/time, for the dashboards
        # to find and sort these toggles. Deliberately NO "medications" key: the
        # status sensors and reminder blueprint identify dose switches by that
        # attribute, and a pause switch must never be mistaken for a dose.
        return {
            "pause_control": True,
            "patient": self._patient,
            "dose_time": self._time,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Suspend the dose."""
        await self._dose.async_pause()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Resume the dose."""
        await self._dose.async_resume()
