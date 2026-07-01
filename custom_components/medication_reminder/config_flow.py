"""Config and options flow for the Medication Reminder integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    selector,
)
from homeassistant.util import dt as dt_util, slugify

from .const import (
    CONF_ANCHOR_DATE,
    CONF_CYCLE_OFF,
    CONF_CYCLE_ON,
    CONF_DAYS,
    CONF_DOSES,
    CONF_INTERVAL_DAYS,
    CONF_MAX_PER_DAY,
    CONF_MED_BRAND,
    CONF_MED_DOSAGE,
    CONF_MED_FULL_NAME,
    CONF_MED_NAME,
    CONF_MED_PRESCRIBED_FOR,
    CONF_MED_STRENGTH,
    CONF_MEDICATIONS,
    CONF_MEDS,
    CONF_MIN_INTERVAL_HOURS,
    CONF_MONTH_DAYS,
    CONF_NAG_INTERVAL,
    CONF_NAG_MINUTES,
    CONF_NOTIFY,
    CONF_PATIENT,
    CONF_PATIENT_TYPE,
    CONF_RESET_TIME,
    CONF_SCHEDULE_TYPE,
    CONF_SUPPLIES,
    CONF_SUPPLY_MED,
    CONF_SUPPLY_PER_DOSE,
    CONF_SUPPLY_REFILL_ADD,
    CONF_SUPPLY_REFILL_TO,
    CONF_SUPPLY_THRESHOLD,
    CONF_SUPPLY_UNITS,
    CONF_TIME,
    CONF_TIME_FORMAT,
    DEFAULT_CYCLE_OFF,
    DEFAULT_CYCLE_ON,
    DEFAULT_DAYS,
    DEFAULT_INTERVAL_DAYS,
    DEFAULT_MAX_PER_DAY,
    DEFAULT_MIN_INTERVAL_HOURS,
    DEFAULT_MONTH_DAYS,
    DEFAULT_NAG_INTERVAL,
    DEFAULT_NAG_MINUTES,
    DEFAULT_PATIENT_TYPE,
    DEFAULT_RESET_TIME,
    DEFAULT_SCHEDULE_TYPE,
    DEFAULT_SUPPLY_PER_DOSE,
    DEFAULT_SUPPLY_REFILL_ADD,
    DEFAULT_SUPPLY_REFILL_TO,
    DEFAULT_SUPPLY_THRESHOLD,
    DEFAULT_SUPPLY_UNITS,
    DEFAULT_TIME_FORMAT,
    DOMAIN,
    SCHEDULE_CYCLE,
    SCHEDULE_INTERVAL,
    SCHEDULE_MONTHLY,
    SCHEDULE_PRN,
    split_medications,
)


def _notify_selector(hass: HomeAssistant) -> selector.SelectSelector:
    """Dropdown of available notify services (groups + per-device)."""
    services = sorted(hass.services.async_services().get("notify", {}))
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=services,
            mode=selector.SelectSelectorMode.DROPDOWN,
            custom_value=True,
        )
    )


def _type_selector() -> selector.SelectSelector:
    """Dropdown of patient types (drives the patient icon)."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": "person", "label": "Person"},
                {"value": "dog", "label": "Dog"},
                {"value": "cat", "label": "Cat"},
                {"value": "bird", "label": "Bird"},
                {"value": "rabbit", "label": "Rabbit"},
                {"value": "other", "label": "Other"},
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _time_format_selector() -> selector.SelectSelector:
    """12-hour vs 24-hour display for dose times in entity names."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": "12h", "label": "12-hour (2:00 PM)"},
                {"value": "24h", "label": "24-hour (14:00)"},
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _days_selector() -> selector.SelectSelector:
    """Multi-select of the days of the week a dose applies to."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": "mon", "label": "Monday"},
                {"value": "tue", "label": "Tuesday"},
                {"value": "wed", "label": "Wednesday"},
                {"value": "thu", "label": "Thursday"},
                {"value": "fri", "label": "Friday"},
                {"value": "sat", "label": "Saturday"},
                {"value": "sun", "label": "Sunday"},
            ],
            multiple=True,
            mode=selector.SelectSelectorMode.LIST,
        )
    )


def _schedule_type_selector() -> selector.SelectSelector:
    """Dropdown: day-of-week schedule vs every-N-days."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                {"value": "weekdays", "label": "On chosen days of the week"},
                {"value": "interval", "label": "Every N days"},
                {"value": "cycle", "label": "On/off cycle (X days on, Y days off)"},
                {"value": "monthly", "label": "Monthly (on chosen days of the month)"},
                {
                    "value": "prn",
                    "label": "As needed (PRN) - no schedule, no reminders",
                },
            ],
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _month_days_selector() -> selector.SelectSelector:
    """Multi-select of days of the month (1-31) for a monthly schedule.

    A day past a given month's length (e.g. 31 in February) is clamped to the
    last day at scheduling time, so a monthly dose is never skipped.
    """
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[{"value": str(d), "label": str(d)} for d in range(1, 32)],
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
        )
    )


def _interval_selector() -> selector.NumberSelector:
    """Whole-number box for the every-N-days interval."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=1,
            max=365,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="days",
        )
    )


def _cycle_selector(low: int) -> selector.NumberSelector:
    """Whole-number box for an on/off cycle's day counts."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=low,
            max=365,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="days",
        )
    )


def _min_interval_selector() -> selector.NumberSelector:
    """Hours between as-needed doses for the over-dose guard (0 = no limit)."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=48,
            step=0.5,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="hours",
        )
    )


def _max_per_day_selector() -> selector.NumberSelector:
    """Daily cap on as-needed doses for the over-dose guard (0 = no limit)."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=24,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="doses",
        )
    )


def _minutes_selector(low: int, high: int) -> selector.NumberSelector:
    """A minutes number box in steps of 5."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=low,
            max=high,
            step=5,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement="min",
        )
    )


def _count_selector() -> selector.NumberSelector:
    """A whole-number box for supply counts (pills/doses on hand)."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=0,
            max=9999,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
        )
    )


class MedicationReminderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial flow: one config entry per patient (pet or person)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for the patient's name, type, and who to notify."""
        errors: dict[str, str] = {}
        if user_input is not None:
            patient = user_input[CONF_PATIENT].strip()
            await self.async_set_unique_id(patient.lower())
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=patient,
                data={CONF_PATIENT: patient},
                options={
                    CONF_DOSES: [],
                    CONF_PATIENT_TYPE: user_input[CONF_PATIENT_TYPE],
                    CONF_NOTIFY: str(user_input[CONF_NOTIFY]).removeprefix("notify."),
                    CONF_RESET_TIME: DEFAULT_RESET_TIME,
                    CONF_NAG_MINUTES: DEFAULT_NAG_MINUTES,
                    CONF_NAG_INTERVAL: DEFAULT_NAG_INTERVAL,
                    CONF_TIME_FORMAT: DEFAULT_TIME_FORMAT,
                },
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_PATIENT): str,
                vol.Required(
                    CONF_PATIENT_TYPE, default=DEFAULT_PATIENT_TYPE
                ): _type_selector(),
                vol.Required(CONF_NOTIFY): _notify_selector(self.hass),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> "MedicationReminderOptionsFlow":
        return MedicationReminderOptionsFlow(config_entry)


class MedicationReminderOptionsFlow(config_entries.OptionsFlow):
    """Add or remove doses, and change reminder settings."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry
        self._edit_index: int | None = None
        self._edit_med_name: str | None = None
        self._edit_supply_med: str | None = None

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Top menu, grouped into submenus to keep it short."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["doses", "supplies", "med_details", "settings"],
        )

    async def async_step_doses(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="doses",
            menu_options=["add_dose", "edit_dose", "remove_dose"],
        )

    async def async_step_supplies(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="supplies",
            menu_options=["add_supply", "edit_supply", "remove_supply"],
        )

    async def async_step_med_details(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="med_details",
            menu_options=["medication_detail", "edit_medication", "remove_medication"],
        )

    async def async_step_add_dose(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add one dose: a time, the medications, and how it repeats.

        Schedule type "weekdays" uses the days picker (the default, unchanged
        behaviour); "interval" uses every-N-days from a start date; "cycle"
        uses X days on / Y days off from a start date; "prn" is as-needed with
        no schedule (never reminds, logged manually); "monthly" fires on chosen
        days of the month. The fields for the other types are ignored on save.
        """
        if user_input is not None:
            new_dose = self._dose_from_input(user_input)
            if self._dose_key_exists(new_dose):
                return self.async_show_form(
                    step_id="add_dose",
                    data_schema=self._dose_schema(user_input),
                    errors={"base": "duplicate_dose"},
                )
            options = dict(self._entry.options)
            doses = list(options.get(CONF_DOSES, []))
            doses.append(new_dose)
            options[CONF_DOSES] = doses
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="add_dose", data_schema=self._dose_schema({})
        )

    def _dose_key_exists(
        self, dose: dict[str, Any], skip_index: int | None = None
    ) -> bool:
        """Whether another dose already has this dose's time + medications (which
        would collide on the same switch entity id). skip_index ignores the dose
        being edited."""

        def key(d: dict[str, Any]) -> str:
            return slugify(
                str(d.get(CONF_TIME, ""))[:5] + "_" + str(d.get(CONF_MEDS, ""))
            )

        target = key(dose)
        for i, d in enumerate(self._entry.options.get(CONF_DOSES, [])):
            if i != skip_index and key(d) == target:
                return True
        return False

    @staticmethod
    def _dose_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
        """Build a dose record from the add/edit form input. Fields for schedule
        types other than the chosen one are ignored."""
        stype = user_input.get(CONF_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TYPE)
        dose = {
            CONF_TIME: str(user_input[CONF_TIME])[:5],
            CONF_MEDS: user_input[CONF_MEDS],
            CONF_SCHEDULE_TYPE: stype,
        }
        if stype == SCHEDULE_INTERVAL:
            dose[CONF_INTERVAL_DAYS] = int(
                user_input.get(CONF_INTERVAL_DAYS, DEFAULT_INTERVAL_DAYS)
            )
            dose[CONF_ANCHOR_DATE] = str(
                user_input.get(CONF_ANCHOR_DATE) or dt_util.now().date().isoformat()
            )[:10]
            dose[CONF_DAYS] = list(DEFAULT_DAYS)
        elif stype == SCHEDULE_CYCLE:
            dose[CONF_CYCLE_ON] = int(user_input.get(CONF_CYCLE_ON, DEFAULT_CYCLE_ON))
            dose[CONF_CYCLE_OFF] = int(
                user_input.get(CONF_CYCLE_OFF, DEFAULT_CYCLE_OFF)
            )
            dose[CONF_ANCHOR_DATE] = str(
                user_input.get(CONF_ANCHOR_DATE) or dt_util.now().date().isoformat()
            )[:10]
            dose[CONF_DAYS] = list(DEFAULT_DAYS)
        elif stype == SCHEDULE_MONTHLY:
            dose[CONF_MONTH_DAYS] = [
                int(d) for d in (user_input.get(CONF_MONTH_DAYS) or DEFAULT_MONTH_DAYS)
            ]
            dose[CONF_DAYS] = list(DEFAULT_DAYS)
        elif stype == SCHEDULE_PRN:
            # As needed: no schedule fields. days are ignored by is_due() for PRN,
            # but keep the key present for a uniform dose shape. The over-dose
            # guard (min interval / max per day) applies here.
            dose[CONF_DAYS] = list(DEFAULT_DAYS)
            dose[CONF_MIN_INTERVAL_HOURS] = float(
                user_input.get(CONF_MIN_INTERVAL_HOURS, DEFAULT_MIN_INTERVAL_HOURS)
            )
            dose[CONF_MAX_PER_DAY] = int(
                user_input.get(CONF_MAX_PER_DAY, DEFAULT_MAX_PER_DAY)
            )
        else:
            dose[CONF_DAYS] = user_input.get(CONF_DAYS) or list(DEFAULT_DAYS)
        return dose

    def _dose_schema(self, d: dict[str, Any]) -> vol.Schema:
        """The add/edit dose form, pre-filled from dose d (empty d = defaults)."""

        def _val(key: str, fallback: Any) -> Any:
            v = d.get(key)
            return fallback if v is None else v

        time_marker = (
            vol.Required(CONF_TIME, default=str(d[CONF_TIME])[:5])
            if d.get(CONF_TIME)
            else vol.Required(CONF_TIME)
        )
        meds_marker = (
            vol.Required(CONF_MEDS, default=d[CONF_MEDS])
            if d.get(CONF_MEDS)
            else vol.Required(CONF_MEDS)
        )
        return vol.Schema(
            {
                time_marker: selector.TimeSelector(),
                meds_marker: selector.TextSelector(),
                vol.Required(
                    CONF_SCHEDULE_TYPE,
                    default=_val(CONF_SCHEDULE_TYPE, DEFAULT_SCHEDULE_TYPE),
                ): _schedule_type_selector(),
                vol.Required(
                    CONF_DAYS, default=list(_val(CONF_DAYS, DEFAULT_DAYS))
                ): _days_selector(),
                vol.Optional(
                    CONF_INTERVAL_DAYS,
                    default=int(_val(CONF_INTERVAL_DAYS, DEFAULT_INTERVAL_DAYS)),
                ): _interval_selector(),
                vol.Optional(
                    CONF_CYCLE_ON, default=int(_val(CONF_CYCLE_ON, DEFAULT_CYCLE_ON))
                ): _cycle_selector(1),
                vol.Optional(
                    CONF_CYCLE_OFF, default=int(_val(CONF_CYCLE_OFF, DEFAULT_CYCLE_OFF))
                ): _cycle_selector(0),
                vol.Optional(
                    CONF_ANCHOR_DATE,
                    default=d.get(CONF_ANCHOR_DATE) or dt_util.now().date().isoformat(),
                ): selector.DateSelector(),
                vol.Optional(
                    CONF_MONTH_DAYS,
                    default=[str(x) for x in _val(CONF_MONTH_DAYS, DEFAULT_MONTH_DAYS)],
                ): _month_days_selector(),
                vol.Optional(
                    CONF_MIN_INTERVAL_HOURS,
                    default=float(
                        _val(CONF_MIN_INTERVAL_HOURS, DEFAULT_MIN_INTERVAL_HOURS)
                    ),
                ): _min_interval_selector(),
                vol.Optional(
                    CONF_MAX_PER_DAY,
                    default=int(_val(CONF_MAX_PER_DAY, DEFAULT_MAX_PER_DAY)),
                ): _max_per_day_selector(),
            }
        )

    async def async_step_remove_dose(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pick existing doses to remove."""
        doses = list(self._entry.options.get(CONF_DOSES, []))
        if user_input is not None:
            remove = set(user_input.get("remove", []))
            options = dict(self._entry.options)
            options[CONF_DOSES] = [
                d for i, d in enumerate(doses) if str(i) not in remove
            ]
            return self.async_create_entry(title="", data=options)
        choices = {
            str(i): f"{d[CONF_TIME]} - {d[CONF_MEDS]}" for i, d in enumerate(doses)
        }
        schema = vol.Schema(
            {vol.Optional("remove", default=[]): cv.multi_select(choices)}
        )
        return self.async_show_form(step_id="remove_dose", data_schema=schema)

    async def async_step_edit_dose(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pick a dose to edit; its current values pre-fill the next step."""
        doses = list(self._entry.options.get(CONF_DOSES, []))
        if not doses:
            return self.async_abort(reason="no_doses")
        if user_input is not None:
            self._edit_index = int(user_input["dose"])
            return await self.async_step_edit_dose_details()
        options = [
            {"value": str(i), "label": f"{d[CONF_TIME]} - {d[CONF_MEDS]}"}
            for i, d in enumerate(doses)
        ]
        schema = vol.Schema(
            {
                vol.Required("dose"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_dose", data_schema=schema)

    async def async_step_edit_dose_details(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """The pre-filled dose form; saving replaces the selected dose in place.

        Editing only the schedule keeps the same entity (its id is the time plus
        medications). Changing the time or medications is a new entity, so the
        old one is pruned to avoid leaving it unavailable.
        """
        doses = list(self._entry.options.get(CONF_DOSES, []))
        idx = self._edit_index
        if idx is None or idx >= len(doses):
            return self.async_abort(reason="no_doses")
        current = doses[idx]
        if user_input is not None:
            new_dose = self._dose_from_input(user_input)
            if self._dose_key_exists(new_dose, skip_index=idx):
                return self.async_show_form(
                    step_id="edit_dose_details",
                    data_schema=self._dose_schema(user_input),
                    errors={"base": "duplicate_dose"},
                )
            if new_dose[CONF_TIME] != str(current.get(CONF_TIME, ""))[:5] or new_dose[
                CONF_MEDS
            ] != current.get(CONF_MEDS):
                self._prune_dose_entity(current)
            doses[idx] = new_dose
            options = dict(self._entry.options)
            options[CONF_DOSES] = doses
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="edit_dose_details", data_schema=self._dose_schema(current)
        )

    def _prune_dose_entity(self, dose: dict[str, Any]) -> None:
        """Remove a dose's switch entity from the registry (used when an edit
        changes the time/medications, so the old entity does not linger)."""
        time = str(dose.get(CONF_TIME, ""))[:5]
        meds = str(dose.get(CONF_MEDS, ""))
        unique_id = f"{self._entry.entry_id}_{slugify(time + '_' + meds)}"
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id("switch", DOMAIN, unique_id)
        if entity_id:
            registry.async_remove(entity_id)

    def _dose_medications(self) -> list[str]:
        """Distinct medications used across this patient's doses, sorted."""
        seen: dict[str, str] = {}
        for dose in self._entry.options.get(CONF_DOSES, []):
            for med in split_medications(dose.get(CONF_MEDS)):
                seen.setdefault(med.lower(), med)
        return [seen[k] for k in sorted(seen)]

    async def async_step_add_supply(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Track supply for one medication: units on hand, per-dose, threshold.

        The medication is chosen from the doses, so the supply always matches a
        dose and decrements. Adding one for a medication that is already tracked
        is rejected (use Edit a supply) because two would collide on the same
        supply entity.
        """
        med_names = self._dose_medications()
        if not med_names:
            return self.async_abort(reason="no_medications")
        if user_input is not None:
            med = str(user_input[CONF_SUPPLY_MED]).strip()
            if med.lower() in {m.lower() for m in self._supply_meds()}:
                return self.async_show_form(
                    step_id="add_supply",
                    data_schema=self._add_supply_schema(med_names, user_input),
                    errors={"base": "supply_exists"},
                )
            return self._save_supply(med, self._supply_record(med, user_input))
        return self.async_show_form(
            step_id="add_supply", data_schema=self._add_supply_schema(med_names, {})
        )

    async def async_step_edit_supply(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pick a tracked medication; its supply pre-fills the next step."""
        meds = self._supply_meds()
        if not meds:
            return self.async_abort(reason="no_supplies")
        if user_input is not None:
            self._edit_supply_med = str(user_input[CONF_SUPPLY_MED])
            return await self.async_step_edit_supply_details()
        schema = vol.Schema(
            {
                vol.Required(CONF_SUPPLY_MED): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sorted(set(meds)),
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_supply", data_schema=schema)

    async def async_step_edit_supply_details(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """The pre-filled supply form for the chosen medication; saving updates it."""
        med = self._edit_supply_med
        record = (
            next(
                (
                    s
                    for s in self._entry.options.get(CONF_SUPPLIES, [])
                    if str(s.get(CONF_SUPPLY_MED, "")).strip().lower()
                    == str(med).strip().lower()
                ),
                None,
            )
            if med
            else None
        )
        if record is None:
            return self.async_abort(reason="no_supplies")
        if user_input is not None:
            return self._save_supply(
                str(med).strip(), self._supply_record(str(med).strip(), user_input)
            )
        return self.async_show_form(
            step_id="edit_supply_details",
            data_schema=vol.Schema(self._supply_fields(record)),
            description_placeholders={"medication": str(med)},
        )

    def _supply_meds(self) -> list[str]:
        """Medications that currently have a tracked supply."""
        return [
            str(s.get(CONF_SUPPLY_MED, "")).strip()
            for s in self._entry.options.get(CONF_SUPPLIES, [])
            if str(s.get(CONF_SUPPLY_MED, "")).strip()
        ]

    @staticmethod
    def _supply_record(med: str, user_input: dict[str, Any]) -> dict[str, Any]:
        """A supply record from form input, keyed by medication."""
        return {
            CONF_SUPPLY_MED: med,
            CONF_SUPPLY_UNITS: int(user_input[CONF_SUPPLY_UNITS]),
            CONF_SUPPLY_PER_DOSE: int(user_input[CONF_SUPPLY_PER_DOSE]),
            CONF_SUPPLY_THRESHOLD: int(user_input[CONF_SUPPLY_THRESHOLD]),
            CONF_SUPPLY_REFILL_TO: int(user_input[CONF_SUPPLY_REFILL_TO]),
            CONF_SUPPLY_REFILL_ADD: bool(user_input.get(CONF_SUPPLY_REFILL_ADD, False)),
        }

    def _save_supply(
        self, med: str, record: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Upsert a supply record (replace any with the same medication)."""
        options = dict(self._entry.options)
        supplies = [
            s
            for s in options.get(CONF_SUPPLIES, [])
            if str(s.get(CONF_SUPPLY_MED, "")).strip().lower() != med.lower()
        ]
        supplies.append(record)
        options[CONF_SUPPLIES] = supplies
        return self.async_create_entry(title="", data=options)

    def _supply_fields(self, s: dict[str, Any]) -> dict[Any, Any]:
        """The supply count fields, pre-filled from record s (empty s = defaults)."""
        return {
            vol.Required(
                CONF_SUPPLY_UNITS,
                default=int(s.get(CONF_SUPPLY_UNITS, DEFAULT_SUPPLY_UNITS)),
            ): _count_selector(),
            vol.Required(
                CONF_SUPPLY_PER_DOSE,
                default=int(s.get(CONF_SUPPLY_PER_DOSE, DEFAULT_SUPPLY_PER_DOSE)),
            ): _count_selector(),
            vol.Required(
                CONF_SUPPLY_THRESHOLD,
                default=int(s.get(CONF_SUPPLY_THRESHOLD, DEFAULT_SUPPLY_THRESHOLD)),
            ): _count_selector(),
            vol.Required(
                CONF_SUPPLY_REFILL_TO,
                default=int(s.get(CONF_SUPPLY_REFILL_TO, DEFAULT_SUPPLY_REFILL_TO)),
            ): _count_selector(),
            vol.Required(
                CONF_SUPPLY_REFILL_ADD,
                default=bool(s.get(CONF_SUPPLY_REFILL_ADD, DEFAULT_SUPPLY_REFILL_ADD)),
            ): selector.BooleanSelector(),
        }

    def _add_supply_schema(self, med_names: list[str], d: dict[str, Any]) -> vol.Schema:
        """The Track-a-supply form: a medication dropdown plus the count fields."""
        med_marker = (
            vol.Required(CONF_SUPPLY_MED, default=d[CONF_SUPPLY_MED])
            if d.get(CONF_SUPPLY_MED)
            else vol.Required(CONF_SUPPLY_MED)
        )
        return vol.Schema(
            {
                med_marker: selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=med_names,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                **self._supply_fields(d),
            }
        )

    async def async_step_remove_supply(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pick tracked medications to stop tracking supply for."""
        supplies = list(self._entry.options.get(CONF_SUPPLIES, []))
        if user_input is not None:
            remove = set(user_input.get("remove", []))
            options = dict(self._entry.options)
            options[CONF_SUPPLIES] = [
                s for i, s in enumerate(supplies) if str(i) not in remove
            ]
            return self.async_create_entry(title="", data=options)
        choices = {
            str(i): f"{s[CONF_SUPPLY_MED]} ({s.get(CONF_SUPPLY_UNITS, 0)} on hand)"
            for i, s in enumerate(supplies)
        }
        schema = vol.Schema(
            {vol.Optional("remove", default=[]): cv.multi_select(choices)}
        )
        return self.async_show_form(step_id="remove_supply", data_schema=schema)

    async def async_step_medication_detail(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add or update reference detail for one medication.

        Optional fields (full name, strength, brand, prescribed-for, dosage) are
        kept separate from the short dose name. The medication is chosen from the
        ones already used in this patient's doses (not free text), so detail
        can only attach to a real medication and cannot be misspelled into a
        duplicate. Records are keyed by name; saving one again replaces it.
        """
        med_names = self._dose_medications()
        if not med_names:
            return self.async_abort(reason="no_medications")
        if user_input is not None:
            name = str(user_input[CONF_MED_NAME]).strip()
            return self._save_medication(
                name, self._medication_record(name, user_input)
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_MED_NAME): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=med_names,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                **self._medication_detail_fields({}),
            }
        )
        return self.async_show_form(step_id="medication_detail", data_schema=schema)

    async def async_step_edit_medication(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pick a medication that has detail; its values pre-fill the next step."""
        names = [
            str(m.get(CONF_MED_NAME, "")).strip()
            for m in self._entry.options.get(CONF_MEDICATIONS, [])
            if str(m.get(CONF_MED_NAME, "")).strip()
        ]
        if not names:
            return self.async_abort(reason="no_medication_detail")
        if user_input is not None:
            self._edit_med_name = str(user_input[CONF_MED_NAME])
            return await self.async_step_edit_medication_details()
        schema = vol.Schema(
            {
                vol.Required(CONF_MED_NAME): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sorted(names),
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )
        return self.async_show_form(step_id="edit_medication", data_schema=schema)

    async def async_step_edit_medication_details(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """The pre-filled detail form for the chosen medication; saving updates it."""
        name = self._edit_med_name
        record = (
            next(
                (
                    m
                    for m in self._entry.options.get(CONF_MEDICATIONS, [])
                    if str(m.get(CONF_MED_NAME, "")).strip().lower()
                    == str(name).strip().lower()
                ),
                None,
            )
            if name
            else None
        )
        if record is None:
            return self.async_abort(reason="no_medication_detail")
        if user_input is not None:
            return self._save_medication(
                str(name).strip(),
                self._medication_record(str(name).strip(), user_input),
            )
        return self.async_show_form(
            step_id="edit_medication_details",
            data_schema=vol.Schema(self._medication_detail_fields(record)),
            description_placeholders={"medication": str(name)},
        )

    @staticmethod
    def _medication_record(name: str, user_input: dict[str, Any]) -> dict[str, Any]:
        """A medication-detail record from form input, keyed by name."""
        return {
            CONF_MED_NAME: name,
            CONF_MED_FULL_NAME: str(user_input.get(CONF_MED_FULL_NAME, "")).strip(),
            CONF_MED_STRENGTH: str(user_input.get(CONF_MED_STRENGTH, "")).strip(),
            CONF_MED_BRAND: str(user_input.get(CONF_MED_BRAND, "")).strip(),
            CONF_MED_PRESCRIBED_FOR: str(
                user_input.get(CONF_MED_PRESCRIBED_FOR, "")
            ).strip(),
            CONF_MED_DOSAGE: str(user_input.get(CONF_MED_DOSAGE, "")).strip(),
        }

    def _save_medication(
        self, name: str, record: dict[str, Any]
    ) -> config_entries.ConfigFlowResult:
        """Upsert a medication-detail record (replace any with the same name)."""
        options = dict(self._entry.options)
        meds = [
            m
            for m in options.get(CONF_MEDICATIONS, [])
            if str(m.get(CONF_MED_NAME, "")).strip().lower() != name.lower()
        ]
        meds.append(record)
        options[CONF_MEDICATIONS] = meds
        return self.async_create_entry(title="", data=options)

    @staticmethod
    def _medication_detail_fields(d: dict[str, Any]) -> dict[Any, Any]:
        """The optional detail fields (full name, strength, brand, prescribed-for,
        dosage), pre-filled from record d (empty d = blank)."""

        def opt(key: str) -> vol.Optional:
            v = str(d.get(key, "")).strip()
            return vol.Optional(key, default=v) if v else vol.Optional(key)

        return {
            opt(CONF_MED_FULL_NAME): selector.TextSelector(),
            opt(CONF_MED_STRENGTH): selector.TextSelector(),
            opt(CONF_MED_BRAND): selector.TextSelector(),
            opt(CONF_MED_PRESCRIBED_FOR): selector.TextSelector(),
            opt(CONF_MED_DOSAGE): selector.TextSelector(),
        }

    async def async_step_remove_medication(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Pick medications to clear the reference detail for."""
        meds = list(self._entry.options.get(CONF_MEDICATIONS, []))
        if user_input is not None:
            remove = set(user_input.get("remove", []))
            options = dict(self._entry.options)
            options[CONF_MEDICATIONS] = [
                m for i, m in enumerate(meds) if str(i) not in remove
            ]
            return self.async_create_entry(title="", data=options)
        choices = {str(i): str(m.get(CONF_MED_NAME, "")) for i, m in enumerate(meds)}
        schema = vol.Schema(
            {vol.Optional("remove", default=[]): cv.multi_select(choices)}
        )
        return self.async_show_form(step_id="remove_medication", data_schema=schema)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Patient type, notify target, reset time, nag window, and time format."""
        if user_input is not None:
            options = dict(self._entry.options)
            options[CONF_PATIENT_TYPE] = user_input[CONF_PATIENT_TYPE]
            options[CONF_NOTIFY] = str(user_input[CONF_NOTIFY]).removeprefix("notify.")
            options[CONF_RESET_TIME] = str(user_input[CONF_RESET_TIME])
            options[CONF_NAG_MINUTES] = int(user_input[CONF_NAG_MINUTES])
            options[CONF_NAG_INTERVAL] = int(user_input[CONF_NAG_INTERVAL])
            options[CONF_TIME_FORMAT] = user_input[CONF_TIME_FORMAT]
            return self.async_create_entry(title="", data=options)
        opts = self._entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PATIENT_TYPE,
                    default=opts.get(CONF_PATIENT_TYPE, DEFAULT_PATIENT_TYPE),
                ): _type_selector(),
                vol.Required(
                    CONF_NOTIFY, default=opts.get(CONF_NOTIFY, "")
                ): _notify_selector(self.hass),
                vol.Required(
                    CONF_TIME_FORMAT,
                    default=opts.get(CONF_TIME_FORMAT, DEFAULT_TIME_FORMAT),
                ): _time_format_selector(),
                vol.Required(
                    CONF_RESET_TIME,
                    default=opts.get(CONF_RESET_TIME, DEFAULT_RESET_TIME),
                ): selector.TimeSelector(),
                vol.Required(
                    CONF_NAG_MINUTES,
                    default=opts.get(CONF_NAG_MINUTES, DEFAULT_NAG_MINUTES),
                ): _minutes_selector(5, 240),
                vol.Required(
                    CONF_NAG_INTERVAL,
                    default=opts.get(CONF_NAG_INTERVAL, DEFAULT_NAG_INTERVAL),
                ): _minutes_selector(5, 120),
            }
        )
        return self.async_show_form(step_id="settings", data_schema=schema)
