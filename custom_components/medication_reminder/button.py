"""Button platform.

Two button types:
  * a one-tap "refill to full" per tracked medication supply (fires
    EVENT_SUPPLY_REFILL; the matching supply number restocks to its
    configured refill-to amount), and
  * a "Log dose" button per as-needed (PRN) dose (fires EVENT_DOSE_LOGGED;
    the matching supply decrements by its per-dose amount on every press).
    PRN doses have no schedule, so the daily on/off switch never counts them;
    this button records a dose each time it is pressed, which also supports
    meds taken several times a day.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import homeassistant.util.dt as dt_util
import voluptuous as vol
from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    config_validation as cv,
    entity_platform,
    entity_registry as er,
)
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import (
    CONF_DOSES,
    CONF_DOSE_UNITS,
    CONF_MEDS,
    CONF_PATIENT,
    CONF_SCHEDULE_TYPE,
    CONF_SKIP_BUTTONS,
    CONF_SUPPLIES,
    CONF_SUPPLY_MED,
    CONF_SUPPLY_REFILL_ADD,
    CONF_SUPPLY_REFILL_TO,
    CONF_TIME,
    DEFAULT_SUPPLY_REFILL_ADD,
    DEFAULT_SUPPLY_REFILL_TO,
    DOMAIN,
    EVENT_DOSE_LOGGED,
    EVENT_SUPPLY_REFILL,
    SCHEDULE_PRN,
    SERVICE_LOG_DOSE,
    SERVICE_MARK_GIVEN,
    partial_skip_meds,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a refill button per supply, plus a log-dose button per PRN dose."""
    patient: str = entry.data[CONF_PATIENT]
    supplies: list[dict[str, Any]] = entry.options.get(CONF_SUPPLIES, [])
    doses: list[dict[str, Any]] = entry.options.get(CONF_DOSES, [])

    entities: list[ButtonEntity] = [
        MedicationRefillButton(
            entry,
            patient,
            str(supply[CONF_SUPPLY_MED]).strip(),
            refill_add=bool(
                supply.get(CONF_SUPPLY_REFILL_ADD, DEFAULT_SUPPLY_REFILL_ADD)
            ),
            refill_to=supply.get(CONF_SUPPLY_REFILL_TO, DEFAULT_SUPPLY_REFILL_TO),
        )
        for supply in supplies
    ]
    entities.extend(
        MedicationLogDoseButton(
            entry,
            patient,
            str(dose[CONF_TIME])[:5],
            str(dose[CONF_MEDS]),
            dose.get(CONF_DOSE_UNITS),
        )
        for dose in doses
        if (dose.get(CONF_SCHEDULE_TYPE) or "") == SCHEDULE_PRN
    )
    # Opt-in partial-dose skip buttons: one "mark given, skip <med>" button per
    # med on each scheduled dose that groups two or more meds. Off by default so
    # patients who never partially dose do not get extra entities.
    if entry.options.get(CONF_SKIP_BUTTONS):
        for dose in doses:
            time = str(dose[CONF_TIME])[:5]
            meds = str(dose[CONF_MEDS])
            for med in partial_skip_meds(meds, dose.get(CONF_SCHEDULE_TYPE)):
                entities.append(
                    MedicationDoseSkipButton(entry, patient, time, meds, med)
                )
    async_add_entities(entities)

    # Service to log a PRN dose at a specified time (the "Specify Time" counterpart
    # to tapping the Log dose button, which records "now"). Target a Log dose button.
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_LOG_DOSE,
        {vol.Optional("taken_at"): cv.datetime},
        "async_log_dose",
    )


class MedicationRefillButton(ButtonEntity):
    """One-tap restock of a medication supply.

    Reflects the supply's refill mode so it is discoverable at a glance: an
    "add" (package) button carries a distinct icon, and both modes expose
    `refill_mode` / `refill_amount` attributes. The name (and therefore the
    entity id) stays `<med> refill` in either mode, so automations targeting the
    button keep working when the mode is changed.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        med: str,
        refill_add: bool = DEFAULT_SUPPLY_REFILL_ADD,
        refill_to: float = DEFAULT_SUPPLY_REFILL_TO,
    ) -> None:
        self._patient = patient
        self._med = med
        self._refill_add = refill_add
        self._refill_to = refill_to
        self._attr_name = f"{med} refill"
        self._attr_icon = "mdi:package-variant-plus" if refill_add else "mdi:refresh"
        self._attr_unique_id = f"{entry.entry_id}_refill_{slugify(med)}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the patient/med (for dashboard filtering) and the refill mode."""
        return {
            "patient": self._patient,
            "medication": self._med,
            "refill_mode": "add" if self._refill_add else "set",
            "refill_amount": self._refill_to,
        }

    async def async_press(self) -> None:
        """Tell the matching supply to restock (set-to or add, per its config)."""
        self.hass.bus.async_fire(
            EVENT_SUPPLY_REFILL,
            {"patient": self._patient, "medication": self._med},
        )


class MedicationLogDoseButton(ButtonEntity):
    """Record one as-needed (PRN) dose; decrements supply on every press."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:pill"

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        time: str,
        meds: str,
        dose_units: float = 0,
    ) -> None:
        self._patient = patient
        self._meds = meds
        self._dose_units = float(dose_units or 0)
        self._attr_name = f"Log {meds} dose"
        self._attr_unique_id = f"{entry.entry_id}_logdose_{slugify(time + '_' + meds)}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    async def async_press(self) -> None:
        """Log one dose taken now (button tap); records the current time."""
        await self.async_log_dose(taken_at=None)

    async def async_log_dose(self, taken_at: datetime | None = None) -> None:
        """Log one dose taken, optionally at a specified time.

        `taken_at` lets you record a dose that was taken earlier than now (the
        "Specify Time" counterpart to a plain button tap). Matching supplies
        decrement by their per-dose amount on every call. The recorded time is
        carried on the event as `logged_at` (ISO), which the "last taken" sensor
        reads.
        """
        when = dt_util.as_local(taken_at) if taken_at else dt_util.now()
        self.hass.bus.async_fire(
            EVENT_DOSE_LOGGED,
            {
                "patient": self._patient,
                "medications": self._meds,
                "dose_units": self._dose_units,
                "logged_at": when.isoformat(),
            },
        )


class MedicationDoseSkipButton(ButtonEntity):
    """One-tap "mark this grouped dose given, but skip one med".

    Created only for scheduled doses that list two or more meds, and only when
    the entry's partial-dose option is on. Pressing it marks the parent dose
    given with this one med in the ``skipped`` list, so the dose counts as taken
    while this med's supply is left alone, the common "one pill was missing"
    case, without splitting the med into its own dose. Skipping more than one med
    at once still needs the ``mark_given`` service with a full ``skipped`` list.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_icon = "mdi:pill-off"

    def __init__(
        self,
        entry: ConfigEntry,
        patient: str,
        time: str,
        meds: str,
        skip_med: str,
    ) -> None:
        self._patient = patient
        self._time = time
        self._meds = meds
        self._skip_med = skip_med
        # The parent dose switch shares this unique_id; resolve its entity_id at
        # press time so a user rename of the switch does not break the button.
        self._parent_unique_id = f"{entry.entry_id}_{slugify(time + '_' + meds)}"
        self._attr_name = f"Mark given, skip {skip_med}"
        self._attr_unique_id = (
            f"{entry.entry_id}_skipbtn_{slugify(time + '_' + meds)}_{slugify(skip_med)}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": patient,
            "manufacturer": "Medication Reminder",
        }

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Patient/dose/med, so the dashboard can group these under their dose."""
        return {
            "patient": self._patient,
            "dose_time": self._time,
            "medications": self._meds,
            "skip_med": self._skip_med,
        }

    async def async_press(self) -> None:
        """Mark the parent dose given with this med skipped."""
        registry = er.async_get(self.hass)
        parent_eid = registry.async_get_entity_id(
            "switch", DOMAIN, self._parent_unique_id
        )
        if not parent_eid:
            return
        await self.hass.services.async_call(
            DOMAIN,
            SERVICE_MARK_GIVEN,
            {"entity_id": parent_eid, "skipped": [self._skip_med]},
            blocking=True,
        )
