"""SolarEdge Monitoring API v2 (OAuth Site Access) for Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import SolarEdgeV2Client
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_SITE_ID,
    CONF_TOKEN,
    DOMAIN,
    NOISE_SUFFIXES,
    TIMESTAMP_SUFFIX,
)
from .coordinator import SolarEdgeCoordinator
from .http_view import async_register_view

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]

type SolarEdgeConfigEntry = ConfigEntry[SolarEdgeCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the OAuth callback view (needed before any entry exists)."""
    async_register_view(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SolarEdgeConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    async def _persist_token(token: dict[str, Any]) -> None:
        # Refresh tokens rotate on every use: store the new one right away.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_TOKEN: token}
        )

    coordinator: SolarEdgeCoordinator

    client = SolarEdgeV2Client(
        session,
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
        entry.data[CONF_SITE_ID],
        entry.data[CONF_TOKEN],
        _persist_token,
        on_request=lambda: coordinator.count_request(),
    )
    coordinator = SolarEdgeCoordinator(hass, entry, client)
    await coordinator.async_load()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    _purge_obsolete_entities(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_options_updated))
    return True


async def _options_updated(hass: HomeAssistant, entry: SolarEdgeConfigEntry) -> None:
    """Reload only when options changed (token updates also fire this listener)."""
    if dict(entry.options) != entry.runtime_data.options_snapshot:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SolarEdgeConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _purge_obsolete_entities(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entities of version 0.1.x that only carried request-window noise."""
    registry = er.async_get(hass)
    obsolete = NOISE_SUFFIXES + (TIMESTAMP_SUFFIX, "_energy_values")
    for ent in er.async_entries_for_config_entry(registry, entry.entry_id):
        if ent.unique_id.endswith(obsolete):
            registry.async_remove(ent.entity_id)
