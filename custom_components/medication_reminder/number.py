"""Number platform: per-medication supply (doses/pills remaining).

Each supply decrements when a dose that includes its medication is marked given
today, exposes how many doses are left and an estimated run-out date from the
schedule, and is user-settable for manual corrections and refills.

Decrement rules (deliberately simple and safe):
- Only on a dose switch going off -> on (an actual "mark given"), so the restore
  write on restart (old state is None) never counts.
- Only for doses scheduled today that include this medication.
- Once per dose per calendar day, so toggling a dose off and on again does not
  double-count. Un-marking a given dose (turning the switch off) restores the
  per-dose amount via the dose-undone event, including the early-dose "undo"
  button; the daily reset does not restore, since the dose was actually given.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import homeassistant.util.dt as dt_util
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify

from .const import (
    CONF_PATIENT,
    CONF_SUPPLIES,
    CONF_SUPPLY_MED,
    CONF_SUPPLY_PER_DOSE,
    CONF_SUPPLY_REFILL_ADD,
    CONF_SUPPLY_REFILL_TO,
    CONF_SUPPLY_THRESHOLD,
    CONF_SUPPLY_UNITS,
    DEFAULT_SUPPLY_PER_DOSE,
    DEFAULT_SUPPLY_REFILL_ADD,
    DEFAULT_SUPPLY_REFILL_TO,
    DEFAULT_SUPPLY_THRESHOLD,
    DEFAULT_SUPPLY_UNITS,
    DOMAIN,
    EVENT_DOSE_LOGGED,
    EVENT_DOSE_UNDONE,
    EVENT_SUPPLY_REFILL,
    doses_per_week,
    is_due,
    meds_contains,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a supply number per configured medication."""
    patient: str = entry.data[CONF_PATIENT]
    supplies: list[dict[str, Any]] = entry.options.get(CONF_SUPPLIES, [])
    async_add_entities(
        MedicationSupplyNumber(entry, patient, supply) for supply in supplies
    )


class MedicationSupplyNumber(NumberEntity, RestoreEntity):
    """Units on hand for one medication. Decrements as doses are given."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:pill-multiple"
    _attr_native_min_value = 0
    _attr_native_max_value = 9999
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self, entry: ConfigEntry, patient: str, supply: dict[str, Any]
    ) -> None:
        self._patient = patient
        self._med = str(supply[CONF_SUPPLY_MED]).strip()
        self._per_dose = int(supply.get(CONF_SUPPLY_PER_DOSE, DEFAULT_SUPPLY_PER_DOSE))
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
        # dose entity_id -> calendar date already counted, to avoid double-count.
        self._consumed: dict[str, str] = {}
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
        return {
            "patient": self._patient,
            "medication": self._med,
            "per_dose": self._per_dose,
            "threshold": self._threshold,
            "refill_to": self._refill_to,
            "refill_add": self._refill_add,
            "doses_left": self._doses_left(),
            "est_runout_date": self._est_runout_date(),
            "low": self._value <= self._threshold,
        }

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
        self._value = max(0.0, self._value - self._per_dose)
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
            self.async_write_ha_state()

    @callback
    def _on_dose_undone(self, event: Event) -> None:
        """Restore the per-dose amount when a dose this supply counted today is
        un-marked. Only restores if this supply actually decremented for that
        dose today; the daily reset does not fire this event."""
        entity_id = event.data.get("entity_id")
        date_str = dt_util.now().date().isoformat()
        if self._consumed.get(entity_id) == date_str:
            del self._consumed[entity_id]
            self._value = min(self._attr_native_max_value, self._value + self._per_dose)
            self.async_write_ha_state()

    @callback
    def _on_state_changed(self, event: Event) -> None:
        """Decrement when a matching dose is marked given today."""
        entity_id = event.data.get("entity_id", "")
        if not entity_id.startswith("switch."):
            return
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        # Only a real off -> on transition (restore writes have old_state None).
        if old is None or new is None or old.state != "off" or new.state != "on":
            return
        if new.attributes.get("patient") != self._patient:
            return
        meds = new.attributes.get("medications")
        if meds is None or not meds_contains(meds, self._med):
            return
        if not is_due(new.attributes, dt_util.now().date()):
            return
        date_str = dt_util.now().date().isoformat()
        if self._consumed.get(entity_id) == date_str:
            return  # already counted this dose today
        self._consumed[entity_id] = date_str
        self._value = max(0.0, self._value - self._per_dose)
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Manual adjust / refill (e.g. set back to a full bottle)."""
        self._value = max(0.0, float(value))
        self.async_write_ha_state()
