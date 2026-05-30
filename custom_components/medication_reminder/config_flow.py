"""Config and options flow for the Medication Reminder integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, selector

from .const import (
    CONF_DOSES,
    CONF_MEDS,
    CONF_NAG_INTERVAL,
    CONF_NAG_MINUTES,
    CONF_NOTIFY,
    CONF_PATIENT,
    CONF_RESET_TIME,
    CONF_TIME,
    DEFAULT_NAG_INTERVAL,
    DEFAULT_NAG_MINUTES,
    DEFAULT_RESET_TIME,
    DOMAIN,
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


class MedicationReminderConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial flow: one config entry per patient (pet or person)."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for the patient's name and who to notify."""
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
                    CONF_NOTIFY: user_input[CONF_NOTIFY],
                    CONF_RESET_TIME: DEFAULT_RESET_TIME,
                    CONF_NAG_MINUTES: DEFAULT_NAG_MINUTES,
                    CONF_NAG_INTERVAL: DEFAULT_NAG_INTERVAL,
                },
            )
        schema = vol.Schema(
            {
                vol.Required(CONF_PATIENT): str,
                vol.Required(CONF_NOTIFY): _notify_selector(self.hass),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_dose", "remove_dose", "settings"],
        )

    async def async_step_add_dose(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Add one dose: a time and the medications given at it."""
        if user_input is not None:
            options = dict(self._entry.options)
            doses = list(options.get(CONF_DOSES, []))
            doses.append(
                {
                    CONF_TIME: str(user_input[CONF_TIME])[:5],
                    CONF_MEDS: user_input[CONF_MEDS],
                }
            )
            options[CONF_DOSES] = doses
            return self.async_create_entry(title="", data=options)
        schema = vol.Schema(
            {
                vol.Required(CONF_TIME): selector.TimeSelector(),
                vol.Required(CONF_MEDS): selector.TextSelector(),
            }
        )
        return self.async_show_form(step_id="add_dose", data_schema=schema)

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

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Notify target, daily reset time, and the nag window/interval."""
        if user_input is not None:
            options = dict(self._entry.options)
            options[CONF_NOTIFY] = user_input[CONF_NOTIFY]
            options[CONF_RESET_TIME] = str(user_input[CONF_RESET_TIME])
            options[CONF_NAG_MINUTES] = int(user_input[CONF_NAG_MINUTES])
            options[CONF_NAG_INTERVAL] = int(user_input[CONF_NAG_INTERVAL])
            return self.async_create_entry(title="", data=options)
        opts = self._entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_NOTIFY, default=opts.get(CONF_NOTIFY, "")
                ): _notify_selector(self.hass),
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
