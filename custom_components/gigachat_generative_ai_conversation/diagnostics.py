"""Diagnostics support for Sber GigaChat AI."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_AUTH_KEY, CONF_CLOUD_RU_API_KEY, CONF_SPEECH_AUTH_KEY

TO_REDACT = {
    CONF_CLOUD_RU_API_KEY,
    CONF_AUTH_KEY,
    CONF_SPEECH_AUTH_KEY,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return {
        "data": async_redact_data(entry.data, TO_REDACT),
        "options": async_redact_data(entry.options, TO_REDACT),
        "subentries": {
            subentry.subentry_id: {
                "subentry_type": subentry.subentry_type,
                "title": subentry.title,
                "data": dict(subentry.data),
            }
            for subentry in entry.subentries.values()
        },
    }
