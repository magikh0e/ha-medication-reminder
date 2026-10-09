"""Number platform: per-medication supply (doses/pills remaining).

Each supply decrements when a dose that includes its medication is marked given
today, exposes how many doses are left and an estimated run-out date from the
schedule, and is user-settable for manual corrections and refills.

Decrement rules (deliberately simple and safe):
- Only on a dose switch going off -> on (an actual "mark given"), so the restore
  write on restart (old state is None) never counts.
- Only for doses scheduled on this medication day that include this medication.
- Once per dose per medication day (the day boundary is the patient reset time,
  not midnight), so toggling a dose off and on again does not double-count, and
  a dose taken late, after midnight but before the reset, files under the day it
  belongs to instead of colliding with the next day's dose. Un-marking a given
  dose (turning the switch off) restores the exact amount that was removed via
  the dose-undone event, including the early-dose "undo" button; the daily reset
  does not restore, since the dose was actually given.
- The per-dose tracking (which doses were counted today and by how much) is
  persisted in the entity attributes and restored on startup, so a reload (the
  options flow reloads the entry on every change) or a restart between a mark
  and an un-mark does not lose it, which would otherwise drop the restore or
  double-count a re-toggle. A manual set or a refill is a fresh baseline and
  clears the tracking.
- On startup the supply also catches up: a decrement can be lost if a mark lands
  while this entity is not listening (a reload, or a restart between the mark
  and now), since the switch restores as given but the live off -> on event
  never fires again. A catch-up pass re-derives any such missed decrement from
  the dose switches' restored (crash-safe) given state, deduped by the per-dose
  tracking so it can only add a missed decrement, never double-count.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later, async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify

from .const import (
    CONF_ASK_UNITS,
    CONF_PLAN_VIEW,
    CONF_DOSES,
    CONF_DOSE_UNITS,
    CONF_MEDS,
    CONF_PATIENT,
    CONF_RESET_TIME,
    CONF_SCHEDULE_TYPE,
    CONF_SUPPLIES,
    CONF_SUPPLY_COST,
    CONF_SUPPLY_MED,
    CONF_SUPPLY_PER_DOSE,
    CONF_SUPPLY_REFILLS,
    CONF_SUPPLY_REFILL_ADD,
    CONF_SUPPLY_REFILL_TO,
    CONF_SUPPLY_THRESHOLD,
    CONF_SUPPLY_UNITS,
    CONF_TIME,
    DEFAULT_RESET_TIME,
    DEFAULT_SUPPLY_COST,
    DEFAULT_SUPPLY_PER_DOSE,
    DEFAULT_SUPPLY_REFILLS,
    DEFAULT_SUPPLY_REFILL_ADD,
    DEFAULT_SUPPLY_REFILL_TO,
    DEFAULT_SUPPLY_THRESHOLD,
    DEFAULT_SUPPLY_UNITS,
    DOMAIN,
    EVENT_DOSE_LOGGED,
    EVENT_DOSE_UNDONE,
    EVENT_SUPPLY_REFILL,
    SCHEDULE_PRN,
    apply_consumption,
    dose_consumption,
    doses_per_week,
    is_due,
    med_day,
    med_skipped,
    meds_contains,
    next_refills_remaining,
    resolve_mark_amount,
    restore_refills,
    supply_cost_breakdown,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a supply number per medication, plus an amount number per
    adjustable-quantity dose."""
    patient: str = entry.data[CONF_PATIENT]
    reset_time: str = entry.options.get(CONF_RESET_TIME, DEFAULT_RESET_TIME)
    supplies: list[dict[str, Any]] = entry.options.get(CONF_SUPPLIES, [])
    entities: list[NumberEntity] = [
        MedicationSupplyNumber(entry, patient, supply, reset_time)
        for supply in supplies
    ]
    # Amount-input number for each scheduled dose that opted into "ask for amount
    # when marking"; the mark reads it to decrement by the amount actually taken.
    for dose in entry.options.get(CONF_DOSES, []):
        if not dose.get(CONF_ASK_UNITS):
            continue
        if (dose.get(CONF_SCHEDULE_TYPE) or "") == SCHEDULE_PRN:
            continue
        entities.append(MedicationDoseAmountNumber(entry, patient, dose))
    # Pill-box plan view (opt-in): the day-offset the plan sensor shows.
    if entry.options.get(CONF_PLAN_VIEW):
        entities.append(MedicationPlanOffsetNumber(entry, patient))
    async_add_entities(entities)


class MedicationSupplyNumber(NumberEntity, RestoreEntity):
    """Units on hand for one medication. Decrements as doses are given."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:pill-multiple"
    _attr_native_min_value = 0
    _attr_native_max_value = 9999
    _attr_native_step = 0.25
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        supply: dict[str, Any],
        reset_time: str,
    ) -> None:
        self._patient = patient
        self._reset_time = reset_time
        self._med = str(supply[CONF_SUPPLY_MED]).strip()
        self._per_dose = float(
            supply.get(CONF_SUPPLY_PER_DOSE, DEFAULT_SUPPLY_PER_DOSE)
        )
        self._threshold = int(
            supply.get(CONF_SUPPLY_THRESHOLD, DEFAULT_SUPPLY_THRESHOLD)
        )
        self._refill_to = int(
            supply.get(CONF_SUPPLY_REFILL_TO, DEFAULT_SUPPLY_REFILL_TO)
        )
        # Refill either sets the count to refill_to (default) or adds it
        # (a "package refill" that keeps what is left).
        self._refill_add = bool(
            supply.get(CONF_SUPPLY_REFILL_ADD, DEFAULT_SUPPLY_REFILL_ADD)
        )
        self._value = float(supply.get(CONF_SUPPLY_UNITS, DEFAULT_SUPPLY_UNITS))
        # Per-unit cost (0 = untracked); drives the optional cost attributes.
        self._cost = float(supply.get(CONF_SUPPLY_COST, DEFAULT_SUPPLY_COST) or 0)
        # Prescription refills remaining (0 = untracked). The configured value is
        # the baseline a new prescription resets to; the live count decrements on
        # each refill and is persisted across reloads (see async_added_to_hass).
        self._refills_cfg = int(
            supply.get(CONF_SUPPLY_REFILLS, DEFAULT_SUPPLY_REFILLS) or 0
        )
        self._refills_remaining = self._refills_cfg
        # dose entity_id -> medication-day already counted, to avoid double-count.
        self._consumed: dict[str, str] = {}
        # dose entity_id -> amount decremented today, so an un-mark restores exactly.
        self._consumed_amount: dict[str, float] = {}
        self._attr_name = f"{self._med} supply"
        self._attr_unique_id = f"{entry.entry_id}_supply_{slugify(self._med)}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "patient": self._patient,
            "medication": self._med,
            "per_dose": self._per_dose,
            "threshold": self._threshold,
            "refill_to": self._refill_to,
            "refill_add": self._refill_add,
            "doses_left": self._doses_left(),
            "est_runout_date": self._est_runout_date(),
            "low": self._value <= self._threshold,
            # Persisted so per-dose decrement tracking survives an entry reload
            # or restart (see the class docstring).
            "consumed": dict(self._consumed),
            "consumed_amount": dict(self._consumed_amount),
        }
        if self._cost > 0:
            # Same weekly cadence as the run-out estimate powers est_monthly_cost.
            attrs.update(
                supply_cost_breakdown(
                    self._value, self._per_dose, self._cost, self._doses_per_week()
                )
            )
        if self._refills_cfg > 0:
            # Prescription refills: how many are left, the configured baseline (so
            # a reload can tell an edit from a decrement), and whether they are out
            # (0 left -> the current fill is the last, time for a new prescription).
            attrs["refills_remaining"] = self._refills_remaining
            attrs["refills_configured"] = self._refills_cfg
            attrs["refills_out"] = self._refills_remaining <= 0
        return attrs

    def _doses_left(self) -> int | None:
        if self._per_dose <= 0:
            return None
        return int(self._value // self._per_dose)

    def _matching_dose_states(self) -> list:
        """This patient's dose switches that include this medication."""
        result = []
        for s in self.hass.states.async_all("switch"):
            if s.attributes.get("patient") != self._patient:
                continue
            meds = s.attributes.get("medications")
            if meds is None or not meds_contains(meds, self._med):
                continue
            result.append(s)
        return result

    def _doses_per_week(self) -> float:
        """How many times per week this medication is scheduled (any type)."""
        total = 0.0
        for s in self._matching_dose_states():
            total += doses_per_week(s.attributes)
        return total

    def _est_runout_date(self) -> str | None:
        """Estimated run-out date (ISO) from doses left and weekly cadence."""
        left = self._doses_left()
        if not left:
            return None
        per_week = self._doses_per_week()
        if per_week <= 0:
            return None
        per_day = per_week / 7.0
        days_left = left / per_day
        runout = dt_util.now() + timedelta(days=days_left)
        return runout.date().isoformat()

    async def async_added_to_hass(self) -> None:
        """Restore the count, then watch dose switches for "given"."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self._value = float(last.state)
            except (ValueError, TypeError):
                pass
            # Restore the per-dose decrement tracking so an un-mark or re-toggle
            # after a reload/restart still balances. Without this it resets to
            # empty on every entry reload (which the options flow triggers on any
            # change), dropping the restore or double-counting a re-toggle.
            consumed = last.attributes.get("consumed")
            if isinstance(consumed, dict):
                self._consumed = {str(k): str(v) for k, v in consumed.items()}
            amounts = last.attributes.get("consumed_amount")
            if isinstance(amounts, dict):
                for key, val in amounts.items():
                    try:
                        self._consumed_amount[str(key)] = float(val)
                    except (TypeError, ValueError):
                        pass
            # Keep the live refills count across reloads, but reset to the new
            # configured value when the prescription's refill count was edited.
            self._refills_remaining = restore_refills(
                self._refills_cfg,
                last.attributes.get("refills_configured"),
                last.attributes.get("refills_remaining"),
            )
        self.async_on_remove(
            self.hass.bus.async_listen("state_changed", self._on_state_changed)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_DOSE_UNDONE, self._on_dose_undone)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_SUPPLY_REFILL, self._on_refill)
        )
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT_DOSE_LOGGED, self._on_dose_logged)
        )
        # Catch up any dose marked given for the current medication day that was
        # not counted live, e.g. a decrement lost when a mark landed during an
        # entry reload or a restart before this entity was listening. The ledger
        # keeps this idempotent, so it can only add a missed decrement, never
        # double-count. Run it once the dose switches are available: at HA start,
        # or shortly after a reload while HA is already running.
        if self.hass.state is CoreState.running:
            self.async_on_remove(async_call_later(self.hass, 5, self._reconcile))
        else:
            self.async_on_remove(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, self._reconcile
                )
            )

    @callback
    def _on_dose_logged(self, event: Event) -> None:
        """Decrement once for an as-needed (PRN) dose logged via its button.

        Unlike the switch-driven decrement this has no is_due gate and no
        once-per-day guard, so a PRN med taken several times a day is counted
        on every press. There is no automatic undo; adjust the supply number
        directly if a press was a mistake."""
        if event.data.get("patient") != self._patient:
            return
        meds = event.data.get("medications")
        if meds is None or not meds_contains(meds, self._med):
            return
        amount = dose_consumption(event.data.get("dose_units"), self._per_dose)
        self._value, _ = apply_consumption(self._value, amount)
        self.async_write_ha_state()

    @callback
    def _on_refill(self, event: Event) -> None:
        """Restock when this supply's button is pressed. By default the count is
        set to the refill amount; in add mode the refill amount is added to
        what is left (a package refill), capped at the max."""
        if (
            event.data.get("patient") == self._patient
            and event.data.get("medication") == self._med
        ):
            if self._refill_add:
                self._value = min(
                    self._attr_native_max_value, self._value + self._refill_to
                )
            else:
                self._value = float(self._refill_to)
            # A refill is a fresh baseline; drop today's decrement tracking so a
            # later un-mark cannot add a dose back on top of the refilled count.
            self._consumed.clear()
            self._consumed_amount.clear()
            # Using a refill spends one of the prescription's refills.
            if self._refills_cfg > 0:
                self._refills_remaining = next_refills_remaining(
                    self._refills_remaining
                )
            self.async_write_ha_state()

    @callback
    def _on_dose_undone(self, event: Event) -> None:
        """Restore the per-dose amount when a dose this supply counted today is
        un-marked. Only restores if this supply actually decremented for that
        dose today; the daily reset does not fire this event."""
        entity_id = event.data.get("entity_id")
        date_str = med_day(dt_util.now(), self._reset_time).isoformat()
        if self._consumed.get(entity_id) == date_str:
            del self._consumed[entity_id]
            # Restore exactly what was removed; default 0 (never guess an amount)
            # so a lost/absent record can only under-restore, never inflate.
            amount = self._consumed_amount.pop(entity_id, 0.0)
            self._value = min(self._attr_native_max_value, self._value + amount)
            self.async_write_ha_state()

    @callback
    def _on_state_changed(self, event: Event) -> None:
        """Decrement when a matching dose is marked given (a real off -> on)."""
        entity_id = event.data.get("entity_id", "")
        if not entity_id.startswith("switch."):
            return
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        # Only a real off -> on transition (restore writes have old_state None).
        if old is None or new is None or old.state != "off" or new.state != "on":
            return
        self._consume_for_state(new, source="mark")

    @callback
    def _reconcile(self, _now: Any = None) -> None:
        """Count any dose marked given for the current medication day that this
        supply has not already recorded.

        A decrement is normally applied by catching the dose switch's live
        off -> on event. If that event lands while this entity is not listening
        (an entry reload, or a restart between the mark and now), the switch
        still restores as given, but the live event never fires again, so the
        pill would go uncounted and the supply would read high. This catch-up
        re-derives the decrement from the dose switches' restored given state,
        which is itself saved crash-safely on every mark. The per-dose ledger
        makes it idempotent: a dose already counted is skipped, so this can only
        add a missed decrement, never double-count.
        """
        caught = 0
        for state in self._matching_dose_states():
            if self._consume_for_state(state, source="reconcile", check_given_day=True):
                caught += 1
        if caught:
            _LOGGER.debug(
                "Supply '%s' caught up %s uncounted dose(s) at load",
                self._med,
                caught,
            )

    @callback
    def _consume_for_state(
        self, state: Any, *, source: str, check_given_day: bool = False
    ) -> bool:
        """Decrement this supply for one dose switch currently marked given.

        Shared by the live off -> on handler and the startup catch-up, so both
        apply the same rules: right patient and medication, not a partial skip
        of this med, scheduled for the medication day, and not already counted
        for that day. The day boundary is the patient reset time, not midnight,
        so a late dose files under the day it belongs to. ``check_given_day``
        also requires the give-time itself to fall in the current medication
        day, so the catch-up never counts a stale "given" switch left from an
        earlier day. Returns True if it decremented.
        """
        if state.state != "on":
            return False
        attrs = state.attributes
        if attrs.get("patient") != self._patient:
            return False
        meds = attrs.get("medications")
        if meds is None or not meds_contains(meds, self._med):
            return False
        # Partial dose: this med was marked skipped on this dose, so the dose is
        # "given" but this supply should not come down.
        if med_skipped(attrs.get("skipped"), self._med):
            return False
        day = med_day(dt_util.now(), self._reset_time)
        day_str = day.isoformat()
        if check_given_day:
            given_at = dt_util.parse_datetime(attrs.get("given_at") or "")
            if (
                given_at is not None
                and med_day(dt_util.as_local(given_at), self._reset_time) != day
            ):
                return False
        if not is_due(attrs, day):
            return False
        if self._consumed.get(state.entity_id) == day_str:
            return False  # already counted this dose for this medication day
        # Honour an amount chosen at mark time (adjustable-quantity dose); else
        # fall back to the dose's own amount or the supply default.
        amount = resolve_mark_amount(
            attrs.get("marked_units"), attrs.get("dose_units"), self._per_dose
        )
        self._value, removed = apply_consumption(self._value, amount)
        self._consumed[state.entity_id] = day_str
        # Record what actually came off (clamped at 0), so an un-mark gives back
        # exactly that, never the full requested amount on a near-empty supply.
        self._consumed_amount[state.entity_id] = removed
        _LOGGER.debug(
            "Supply '%s' -%s via %s for %s (%s); now %s",
            self._med,
            removed,
            source,
            state.entity_id,
            day_str,
            self._value,
        )
        self.async_write_ha_state()
        return True

    async def async_set_native_value(self, value: float) -> None:
        """Manual adjust / refill (e.g. set back to a full bottle)."""
        self._value = max(0.0, float(value))
        # A manual correction is authoritative; drop today's decrement tracking
        # so a later un-mark does not add a dose back on top of the new value.
        self._consumed.clear()
        self._consumed_amount.clear()
        self.async_write_ha_state()


class MedicationDoseAmountNumber(RestoreEntity, NumberEntity):
    """The amount to log when marking an adjustable-quantity dose given.

    A settable input: set it to what you are about to take (e.g. 0.5 of a pill),
    then mark the dose given by any means, and the matching supply decrements by
    this instead of the dose's configured amount. Created only for doses with
    "Ask for amount when marking" turned on; remembers its value across restarts.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:numeric"
    _attr_native_min_value = 0
    _attr_native_max_value = 99
    _attr_native_step = 0.25
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry, patient: str, dose: dict[str, Any]) -> None:
        self._patient = patient
        self._time = str(dose[CONF_TIME])[:5]
        self._meds = str(dose[CONF_MEDS])
        # Start at the dose's configured amount if it has one, else one unit.
        self._value = float(dose.get(CONF_DOSE_UNITS) or 0) or 1.0
        self._attr_name = f"{self._meds} amount ({self._time})"
        self._attr_unique_id = (
            f"{entry.entry_id}_amount_{slugify(self._time + '_' + self._meds)}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "patient": self._patient,
            "dose_time": self._time,
            "medications": self._meds,
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self._value = float(last.state)
            except (ValueError, TypeError):
                pass

    async def async_set_native_value(self, value: float) -> None:
        self._value = max(0.0, float(value))
        self.async_write_ha_state()


class MedicationPlanOffsetNumber(RestoreEntity, NumberEntity):
    """Day offset for the pill-box plan view: 0 = today, 1 = tomorrow, -1 = yesterday.

    The plan sensor reads this to choose the date it shows. Resets to 0 (today) at
    midnight so the default is always today; step it to prep another day's box.
    Created only when the plan view is enabled for the patient.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:calendar-arrow-right"
    _attr_native_min_value = -14
    _attr_native_max_value = 60
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(self, entry: ConfigEntry, patient: str) -> None:
        self._patient = patient
        self._value = 0.0
        self._attr_name = "Plan day (offset from today)"
        self._attr_unique_id = f"{entry.entry_id}_planoffset"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def native_value(self) -> float:
        return self._value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # `plan_offset` lets the dashboard find this control among the numbers.
        return {"patient": self._patient, "plan_offset": True}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None:
            try:
                self._value = float(last.state)
            except (ValueError, TypeError):
                pass
        # Back to today (offset 0) at midnight, so the default is always today.
        self.async_on_remove(
            async_track_time_change(
                self.hass, self._reset_to_today, hour=0, minute=0, second=0
            )
        )

    @callback
    def _reset_to_today(self, _now) -> None:
        self._value = 0.0
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        self._value = float(value)
        self.async_write_ha_state()
