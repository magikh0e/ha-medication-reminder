"""The Medication Reminder integration.

One config entry per patient. Each entry creates a switch per dose (on = given
today) and a binary sensor that is on when all of that patient's doses are
given. Reminders/notifications are handled by companion automations that read
the dose switches (see companion-automations.yaml).
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import slugify

from .const import (
    CONF_DOSES,
    CONF_MEDS,
    CONF_PATIENT,
    CONF_SUPPLIES,
    CONF_SUPPLY_MED,
    DOMAIN,
    meds_contains,
)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.CALENDAR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a patient entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    _check_supply_issues(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a patient entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when doses are added/removed in the options flow."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clear this patient's repair issues and crash-safe dose store on removal."""
    from .switch import _given_store

    await _given_store(hass, entry.entry_id).async_remove()
    registry = ir.async_get(hass)
    prefix = f"supply_no_dose_{entry.entry_id}_"
    for dom, issue_id in list(registry.issues):
        if dom == DOMAIN and issue_id.startswith(prefix):
            ir.async_delete_issue(hass, DOMAIN, issue_id)


@callback
def _check_supply_issues(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Warn (in Repairs) about a tracked supply whose medication matches no
    dose, since it would then never decrement. Reconciles against the issue
    registry on every reload, so cleared/renamed supplies drop their warning."""
    patient = entry.data[CONF_PATIENT]
    meds_strings = [d.get(CONF_MEDS, "") for d in entry.options.get(CONF_DOSES, [])]
    prefix = f"supply_no_dose_{entry.entry_id}_"
    current: set[str] = set()
    for supply in entry.options.get(CONF_SUPPLIES, []):
        med = str(supply.get(CONF_SUPPLY_MED, "")).strip()
        if not med or any(meds_contains(ms, med) for ms in meds_strings):
            continue
        issue_id = f"{prefix}{slugify(med)}"
        current.add(issue_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="supply_no_matching_dose",
            translation_placeholders={"medication": med, "patient": patient},
        )
    registry = ir.async_get(hass)
    for dom, issue_id in list(registry.issues):
        if dom == DOMAIN and issue_id.startswith(prefix) and issue_id not in current:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
