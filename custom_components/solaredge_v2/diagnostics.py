"""Diagnostics with secrets redacted."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

TO_REDACT = {"client_id", "client_secret", "token", "access_token", "refresh_token", "site_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "credits": {
            "used": coordinator.credits_used,
            "remaining": coordinator.credits_remaining,
            "budget": coordinator.budget,
            "live_interval_minutes": coordinator.live_interval_minutes(),
        },
        "skipped_endpoints": coordinator._state["skip"],  # noqa: SLF001
        "values": coordinator.data,
    }
