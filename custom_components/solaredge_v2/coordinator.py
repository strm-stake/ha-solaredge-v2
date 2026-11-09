"""Credit-aware coordinator: daylight-only polling planned from the credit budget."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api import (
    SolarEdgeApiError,
    SolarEdgeAuthError,
    SolarEdgeQuotaError,
    SolarEdgeV2Client,
)
from .const import (
    AFTER_SUNSET_GRACE,
    CALL_SPACING_SECONDS,
    CONF_BILLING_DAY,
    CONF_BUDGET,
    CONF_DAYLIGHT,
    CONF_INTERVAL,
    CONF_TELEMETRY,
    CORE_ENDPOINTS,
    DAY,
    DEFAULT_BILLING_DAY,
    DEFAULT_BUDGET,
    DEFAULT_DAYLIGHT,
    DEFAULT_INTERVAL,
    DEFAULT_TELEMETRY,
    DOMAIN,
    ENDPOINTS,
    HALF_DAY,
    MAX_CALLS_PER_TICK,
    MAX_LIVE_MINUTES,
    MIN_LIVE_MINUTES,
    NOISE_SUFFIXES,
    REQUIRES_DEVICE,
    SKIP_SECONDS,
    SKIP_SECONDS_CORE,
    TELEMETRY_ENDPOINTS,
    TICK_MINUTES,
)
from .parse import flatten

_LOGGER = logging.getLogger(__name__)

# Poll plan: (endpoint, interval multiplier of the live interval | fixed seconds, daylight only)
# power = "live"; overview every 2x, device telemetry every 4x; the rest is slow and
# runs day and night.
_LIVE_FACTORS = {"power": 1.0, "overview": 2.0, "inverters": 4.0, "meters": 4.0, "storage": 4.0}
_SLOW_SECONDS = {
    "devices": DAY,
    "site": DAY,
    "energy": HALF_DAY,
    "lifetime": HALF_DAY,
    "alerts": HALF_DAY,
    "meters_lifetime": HALF_DAY,
    "storage_lifetime": HALF_DAY,
}


def plan_live_minutes(
    budget: int, slow_calls_per_day: float, live_factor: float, daylight_hours: float
) -> int:
    """Minutes between power polls so that everything fits in the credit budget.

    live_factor = calls per power poll (power itself 1, overview 1/2, telemetry 1/4 each).
    """
    remaining = budget - slow_calls_per_day * 30
    if remaining <= 0:
        return MAX_LIVE_MINUTES
    minutes = 30 * daylight_hours * live_factor * 60 / remaining
    rounded = math.ceil(minutes / 5) * 5
    return int(min(max(rounded, MIN_LIVE_MINUTES), MAX_LIVE_MINUTES))


class SolarEdgeCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """Holds the latest flattened values (persisted, so restarts cost no credits)."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: SolarEdgeV2Client
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(minutes=TICK_MINUTES),
        )
        self.client = client
        self.options_snapshot: dict[str, Any] = dict(entry.options)
        self._store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self._state: dict[str, Any] = {
            "ver": 2,
            "values": {},
            "last": {},
            "skip": {},
            "credits": {"cycle": "", "used": 0},
            "blocked_until": 0.0,
        }
        self._budget_warned = False
        self._last_above_horizon = 0.0

    # -- options ---------------------------------------------------------
    def _opt(self, key: str, default: Any) -> Any:
        return self.config_entry.options.get(key, default)

    @property
    def budget(self) -> int:
        return int(self._opt(CONF_BUDGET, DEFAULT_BUDGET))

    # -- persistence -----------------------------------------------------
    async def async_load(self) -> None:
        if saved := await self._store.async_load():
            if saved.get("ver") != 2:  # upgrade from 0.1.x: refetch with the new endpoints
                saved = {"credits": saved.get("credits", self._state["credits"])}
            for key in self._state:
                if key in saved:
                    self._state[key] = saved[key]
        self.data = dict(self._state["values"])

    # -- credit ledger ---------------------------------------------------
    def _cycle_start(self, now: datetime) -> date:
        day = int(self._opt(CONF_BILLING_DAY, DEFAULT_BILLING_DAY))
        if now.day >= day:
            return date(now.year, now.month, day)
        year, month = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        return date(year, month, day)

    def _next_cycle_start(self, now: datetime) -> datetime:
        start = self._cycle_start(now)
        year = start.year + (1 if start.month == 12 else 0)
        month = start.month % 12 + 1
        return datetime(year, month, start.day, tzinfo=UTC)

    def _roll_cycle(self) -> None:
        key = str(self._cycle_start(datetime.now(UTC)))
        credits = self._state["credits"]
        if credits["cycle"] != key:
            credits["cycle"] = key
            credits["used"] = 0
            self._state["blocked_until"] = 0.0
            self._budget_warned = False

    def count_request(self) -> None:
        self._roll_cycle()
        self._state["credits"]["used"] += 1

    @property
    def credits_used(self) -> int:
        return int(self._state["credits"]["used"])

    @property
    def credits_remaining(self) -> int:
        return max(self.budget - self.credits_used, 0)

    # -- inventory -------------------------------------------------------
    def device_types(self) -> set[str]:
        return {
            str(v["value"])
            for k, v in self._state["values"].items()
            if k.startswith("devices_") and k.endswith("_type")
        }

    def _allowed(self, ep: str, now: float) -> bool:
        if self._state["skip"].get(ep, 0) > now:
            return False
        if ep in TELEMETRY_ENDPOINTS and not self._opt(CONF_TELEMETRY, DEFAULT_TELEMETRY):
            return False
        needed = REQUIRES_DEVICE.get(ep)
        return needed is None or needed in self.device_types()

    # -- daylight --------------------------------------------------------
    def _is_daylight(self, now: float) -> bool:
        sun = self.hass.states.get("sun.sun")
        if sun is not None and sun.state == "above_horizon":
            self._last_above_horizon = now
            return True
        if sun is not None and sun.state == "below_horizon":
            return now - self._last_above_horizon < AFTER_SUNSET_GRACE
        return 6 <= dt_util.now().hour < 20  # no sun entity: fixed window

    # -- planning --------------------------------------------------------
    def live_interval_minutes(self, now: float | None = None) -> int:
        """Minutes between power polls (manual option, or derived from the budget)."""
        now = now or time.time()
        manual = int(self._opt(CONF_INTERVAL, DEFAULT_INTERVAL))
        if manual > 0:
            return max(manual, MIN_LIVE_MINUTES)
        live_factor = sum(
            1.0 / _LIVE_FACTORS[ep] for ep in _LIVE_FACTORS if self._allowed(ep, now)
        )
        slow_calls = sum(
            DAY / every for ep, every in _SLOW_SECONDS.items() if self._allowed(ep, now)
        )
        hours = 12.0 if self._opt(CONF_DAYLIGHT, DEFAULT_DAYLIGHT) else 24.0
        return plan_live_minutes(self.budget, slow_calls, live_factor, hours)

    def _schedule(self, now: float) -> list[tuple[str, float, bool]]:
        """(endpoint, interval seconds, only in daylight) in priority order."""
        live = self.live_interval_minutes(now) * 60
        daylight_only = bool(self._opt(CONF_DAYLIGHT, DEFAULT_DAYLIGHT))
        plan: list[tuple[str, float, bool]] = [("devices", _SLOW_SECONDS["devices"], False)]
        plan += [(ep, live * f, daylight_only) for ep, f in _LIVE_FACTORS.items()]
        plan += [(ep, s, False) for ep, s in _SLOW_SECONDS.items() if ep != "devices"]
        return plan

    def _params(self, kind: str | None) -> Any:
        if kind is None:
            return None
        now = dt_util.now().replace(microsecond=0)
        if kind == "today":
            start = now.replace(hour=0, minute=0, second=0)
            return {"from": start.isoformat(), "to": now.isoformat()}
        if kind == "year_by_month":
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0)
            return {"from": start.isoformat(), "to": now.isoformat(), "resolution": "MONTH"}
        if kind == "recent":
            return {
                "from": (now - timedelta(hours=3)).isoformat(),
                "to": now.isoformat(),
                "resolution": "QUARTER_HOUR",
            }
        if kind == "open":
            return {"only-open": "true"}
        if kind == "devices":
            return [("types", t) for t in ("INVERTER", "BATTERY", "METER")]
        return None

    # -- update ----------------------------------------------------------
    async def _async_update_data(self) -> dict[str, dict[str, Any]]:
        now = time.time()
        self._roll_cycle()
        if now < self._state["blocked_until"]:
            return dict(self._state["values"])

        daylight = self._is_daylight(now)
        calls = 0
        for ep, every, daylight_only in self._schedule(now):
            if calls >= MAX_CALLS_PER_TICK:
                break
            if not self._allowed(ep, now):
                continue
            last = self._state["last"].get(ep, 0)
            if now - last < every:
                continue
            # Daylight-only endpoints sleep at night, but are always fetched once.
            if daylight_only and last and not daylight:
                continue
            if self.credits_used >= self.budget:
                if not self._budget_warned:
                    _LOGGER.warning(
                        "SolarEdge credit budget (%s) reached; polling paused until the "
                        "next billing cycle. Raise it under Configure if needed.",
                        self.budget,
                    )
                    self._budget_warned = True
                break
            if calls:
                await asyncio.sleep(CALL_SPACING_SECONDS)
            calls += 1
            if not await self._fetch(ep, now):
                break

        if calls:
            await self._store.async_save(self._state)
        return dict(self._state["values"])

    async def _fetch(self, ep: str, now: float) -> bool:
        """Fetch one endpoint. Returns False when polling must stop this tick."""
        path, kind = ENDPOINTS[ep]
        try:
            raw = await self.client.get(path, self._params(kind))
        except SolarEdgeAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except SolarEdgeQuotaError as err:
            if "monthly" in str(err).lower():
                self._state["blocked_until"] = self._next_cycle_start(
                    datetime.now(UTC)
                ).timestamp()
                _LOGGER.warning("SolarEdge monthly credit limit reached: %s", err)
            else:
                self._state["blocked_until"] = now + 120
                _LOGGER.debug("SolarEdge rate limit, pausing 2 minutes: %s", err)
            return False
        except SolarEdgeApiError as err:
            if 400 <= err.status < 500:
                ttl = SKIP_SECONDS_CORE if ep in CORE_ENDPOINTS else SKIP_SECONDS
                self._state["skip"][ep] = now + ttl
                self._state["last"][ep] = now
                _LOGGER.warning(
                    "SolarEdge endpoint '%s' answered %s; skipping it for %s h. Response: %s",
                    ep,
                    err.status,
                    round(ttl / 3600),
                    err.message,
                )
            else:
                _LOGGER.debug("SolarEdge endpoint '%s' failed: %s", ep, err)
            return True

        values: dict[str, dict[str, Any]] = {
            k: v for k, v in self._state["values"].items() if v["ep"] != ep
        }
        for path_key, value, unit in self._leaves(ep, raw):
            if path_key.endswith(NOISE_SUFFIXES):
                continue
            values[path_key] = {"ep": ep, "value": value, "unit": unit, "ts": now}
        self._state["values"] = values
        self._state["last"][ep] = now
        return True

    @staticmethod
    def _leaves(ep: str, raw: Any) -> list[tuple[str, Any, str | None]]:
        """Flatten a response; `energy` (monthly buckets) becomes month and year totals."""
        if ep == "energy" and isinstance(raw, dict):
            try:
                buckets = [
                    b for b in raw.get("values", []) if isinstance(b, dict) and b.get("value") is not None
                ]
                if buckets:
                    unit = raw.get("unit")
                    latest = max(buckets, key=lambda b: str(b.get("timestamp", "")))
                    return [
                        ("energy_thisMonth", latest["value"], unit),
                        ("energy_thisYear", sum(b["value"] for b in buckets), unit),
                    ]
            except (TypeError, ValueError):
                pass
        return flatten(raw, ep)
