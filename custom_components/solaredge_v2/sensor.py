"""Dynamic sensors: one entity per value found in the V2 responses."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, NOISE_SUFFIXES, TIMESTAMP_SUFFIX
from .coordinator import SolarEdgeCoordinator
from .parse import humanize

_UNIT_ALIASES = {
    "w": "W", "kw": "kW", "mw": "MW", "wh": "Wh", "kwh": "kWh", "mwh": "MWh",
    "v": "V", "a": "A", "hz": "Hz", "va": "VA", "var": "var",
    "c": "°C", "°c": "°C", "%": "%",
}
_ENERGY = ("Wh", "kWh", "MWh")
_POWER = ("W", "kW", "MW")
_CLASS_BY_UNIT: dict[str, tuple[SensorDeviceClass, SensorStateClass]] = {
    **{u: (SensorDeviceClass.POWER, SensorStateClass.MEASUREMENT) for u in _POWER},
    **{u: (SensorDeviceClass.ENERGY, SensorStateClass.TOTAL_INCREASING) for u in _ENERGY},
    "V": (SensorDeviceClass.VOLTAGE, SensorStateClass.MEASUREMENT),
    "A": (SensorDeviceClass.CURRENT, SensorStateClass.MEASUREMENT),
    "Hz": (SensorDeviceClass.FREQUENCY, SensorStateClass.MEASUREMENT),
    "VA": (SensorDeviceClass.APPARENT_POWER, SensorStateClass.MEASUREMENT),
    "var": (SensorDeviceClass.REACTIVE_POWER, SensorStateClass.MEASUREMENT),
    "°C": (SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT),
}
_CORE_ENDPOINTS = {"site", "overview", "power", "energy", "lifetime", "meters_lifetime", "storage_lifetime"}

_NAMES = {
    "power_values": "Solar power",
    "overview_production_total": "Production today",
    "energy_thisMonth": "Energy this month",
    "energy_thisYear": "Energy this year",
    "site_peakPower": "Peak power",
    "site_lastUpdateTime": "Last update from site",
    "alerts_count": "Open alerts",
    "devices_count": "Devices",
}
_INVERTER_METRICS = {
    "power": "AC power",
    "energy": "AC energy",
    "consumedAcPower": "Consumed AC power",
    "consumedAcEnergy": "Consumed AC energy",
    "voltage": "AC voltage",
    "current": "AC current",
    "frequency": "Grid frequency",
}
_INVERTER_RE = re.compile(
    r"^inverters_inverters_(?P<sn>.+?)_(?P<metric>" + "|".join(_INVERTER_METRICS) + r")(?P<rest>_.*)?$"
)
_HINTS = (
    "power", "energy", "stateof", "soc", "charge", "production", "consumption",
    "import", "export", "lifetime", "voltage", "frequency",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: SolarEdgeCoordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = []
        for key, value in (coordinator.data or {}).items():
            if key.endswith(NOISE_SUFFIXES + (TIMESTAMP_SUFFIX,)):
                continue  # request window / bucket time: no entities
            if key not in known:
                known.add(key)
                new.append(SolarEdgeSensor(coordinator, entry, key, value))
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))
    async_add_entities(
        [
            SolarEdgeCreditSensor(coordinator, entry, "used"),
            SolarEdgeCreditSensor(coordinator, entry, "remaining"),
        ]
    )


def _device_info(coordinator: SolarEdgeCoordinator, entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.client.site_id)},
        name=entry.title,
        manufacturer="SolarEdge",
        model="Monitoring API v2",
    )


class SolarEdgeSensor(CoordinatorEntity[SolarEdgeCoordinator], SensorEntity):
    """A single value from a V2 response."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SolarEdgeCoordinator,
        entry: ConfigEntry,
        key: str,
        first: dict[str, Any],
    ) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.client.site_id}_{key}"
        self._attr_name = _NAMES.get(key) or humanize(key)
        self._attr_device_info = _device_info(coordinator, entry)
        if match := _INVERTER_RE.match(key):
            serial = match["sn"].replace("_", "-")
            rest = match["rest"] or ""
            metric = _INVERTER_METRICS[match["metric"]]
            self._attr_name = metric if rest in ("", "_values") else f"{metric} {humanize(rest)}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{coordinator.client.site_id}_{serial}")},
                name=f"SolarEdge inverter {serial}",
                manufacturer="SolarEdge",
                via_device=(DOMAIN, coordinator.client.site_id),
            )

        value = first["value"]
        numeric = isinstance(value, (int, float))
        low = key.lower()
        unit = _UNIT_ALIASES.get(str(first.get("unit") or "").strip().lower())
        if numeric and unit in _CLASS_BY_UNIT:
            self._attr_native_unit_of_measurement = unit
            self._attr_device_class, self._attr_state_class = _CLASS_BY_UNIT[unit]
        elif numeric and unit == "%":
            self._attr_native_unit_of_measurement = "%"
            self._attr_state_class = SensorStateClass.MEASUREMENT
            if any(h in low for h in ("soc", "stateofenergy", "stateofcharge")):
                self._attr_device_class = SensorDeviceClass.BATTERY
        elif numeric and first.get("unit"):
            self._attr_native_unit_of_measurement = str(first["unit"])
            self._attr_state_class = SensorStateClass.MEASUREMENT
        elif not numeric and low.endswith(("time", "timestamp")) and self._parse(value):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

        core = first["ep"] in _CORE_ENDPOINTS
        hinted = any(h in low for h in _HINTS)
        self._attr_entity_registry_enabled_default = (
            numeric and not low.endswith("_count") and (core or hinted)
        ) or low.endswith("lastupdatetime")
        if not self._attr_entity_registry_enabled_default:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @staticmethod
    def _parse(value: Any) -> datetime | None:
        parsed = dt_util.parse_datetime(str(value))
        if parsed is not None and parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    @property
    def available(self) -> bool:
        return super().available and self._key in (self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Time of the 15-minute bucket the value belongs to (SolarEdge lags 15-30 min)."""
        stamp = (self.coordinator.data or {}).get(f"{self._key}_timestamp")
        return {"data_timestamp": stamp["value"]} if stamp else None

    @property
    def native_value(self) -> Any:
        item = (self.coordinator.data or {}).get(self._key)
        if item is None:
            return None
        if self.device_class == SensorDeviceClass.TIMESTAMP:
            return self._parse(item["value"])
        return item["value"]


class SolarEdgeCreditSensor(CoordinatorEntity[SolarEdgeCoordinator], SensorEntity):
    """API credits used / remaining in this billing cycle (own calls only)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = "credits"
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: SolarEdgeCoordinator, entry: ConfigEntry, kind: str) -> None:
        super().__init__(coordinator)
        self._kind = kind
        self._attr_unique_id = f"{coordinator.client.site_id}_credits_{kind}"
        self._attr_name = f"API credits {kind}"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def native_value(self) -> int:
        c = self.coordinator
        return c.credits_used if self._kind == "used" else c.credits_remaining
