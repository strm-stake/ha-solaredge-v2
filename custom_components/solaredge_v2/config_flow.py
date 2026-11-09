"""Config flow: own OAuth (relay redirect + own callback, PKCE) and options."""

from __future__ import annotations

import logging
import secrets
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    SolarEdgeApiError,
    SolarEdgeAuthError,
    SolarEdgeQuotaError,
    SolarEdgeV2Client,
    exchange_code,
    generate_pkce,
)
from .const import (
    AUTHORIZE_URL,
    CALLBACK_PATH,
    CONF_AUTHORIZE_EXTRA,
    CONF_BILLING_DAY,
    CONF_BUDGET,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_DAYLIGHT,
    CONF_INTERVAL,
    CONF_REDIRECT_URI,
    CONF_SITE_ID,
    CONF_TELEMETRY,
    CONF_TOKEN,
    DEFAULT_AUTHORIZE_EXTRA,
    DEFAULT_BILLING_DAY,
    DEFAULT_BUDGET,
    DEFAULT_DAYLIGHT,
    DEFAULT_INTERVAL,
    DEFAULT_REDIRECT_URI,
    DEFAULT_TELEMETRY,
    DOMAIN,
)
from .http_view import async_register_view

_LOGGER = logging.getLogger(__name__)


class SolarEdgeV2ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SolarEdge Monitoring API v2."""

    VERSION = 1

    def __init__(self) -> None:
        self._client_id = ""
        self._client_secret = ""
        self._redirect_uri = DEFAULT_REDIRECT_URI
        self._extra = DEFAULT_AUTHORIZE_EXTRA
        self._verifier = ""
        self._external_id = ""
        self._code = ""
        self._site_id = ""
        self._reauth_entry: config_entries.ConfigEntry | None = None
        self._auth_url = ""

    # -- helpers ---------------------------------------------------------
    def _prepare_auth(self, register: bool = True) -> str:
        """Create PKCE + external id, return the authorize URL.

        register=False for manual sign-in: the callback view must then ignore the
        redirect, because the user pastes the address instead.
        """
        async_register_view(self.hass)
        self._verifier, challenge = generate_pkce()
        self._external_id = secrets.token_urlsafe(16)
        if register:
            self.hass.data.setdefault(DOMAIN, {}).setdefault("pending", {})[
                self._external_id
            ] = self.flow_id
        params: list[tuple[str, str]] = [
            ("client_id", self._client_id),
            ("response_type", "code"),
            ("redirect_uri", self._redirect_uri),
            ("external_id", self._external_id),
            ("code_challenge", challenge),
            ("code_challenge_method", "S256"),
        ]
        params += parse_qsl(self._extra, keep_blank_values=False)
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def _make_manual_url(self) -> str:
        self._auth_url = self._prepare_auth(register=False)
        return self._auth_url

    @callback
    def async_remove(self) -> None:
        """Flow removed: forget the pending registration."""
        pending = self.hass.data.get(DOMAIN, {}).get("pending", {})
        pending.pop(self._external_id, None)

    # -- steps -----------------------------------------------------------
    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            self._client_id = user_input[CONF_CLIENT_ID].strip()
            self._client_secret = user_input[CONF_CLIENT_SECRET].strip()
            self._redirect_uri = user_input[CONF_REDIRECT_URI].strip()
            self._extra = user_input.get(CONF_AUTHORIZE_EXTRA, "").strip()
            return await self.async_step_method()

        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ID): str,
                vol.Required(CONF_CLIENT_SECRET): str,
                vol.Required(CONF_REDIRECT_URI, default=DEFAULT_REDIRECT_URI): str,
                vol.Optional(CONF_AUTHORIZE_EXTRA, default=DEFAULT_AUTHORIZE_EXTRA): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            description_placeholders={"callback_path": CALLBACK_PATH},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        assert self._reauth_entry is not None
        data = self._reauth_entry.data
        self._client_id = data[CONF_CLIENT_ID]
        self._client_secret = data[CONF_CLIENT_SECRET]
        self._redirect_uri = data[CONF_REDIRECT_URI]
        self._extra = data.get(CONF_AUTHORIZE_EXTRA, DEFAULT_AUTHORIZE_EXTRA)
        self._site_id = data[CONF_SITE_ID]
        return await self.async_step_method()

    async def async_step_method(self, user_input: dict[str, Any] | None = None):
        return self.async_show_menu(step_id="method", menu_options=["auto", "manual"])

    async def async_step_auto(self, user_input: dict[str, Any] | None = None):
        """External step: browser tab -> SolarEdge -> relay -> our callback view."""
        if user_input is None:
            return self.async_external_step(
                step_id="auto", url=self._prepare_auth()
            )
        self._code = user_input["code"]
        if user_input.get("site_id"):
            self._site_id = str(user_input["site_id"])
        return self.async_external_step_done(next_step_id="finish")

    async def async_step_manual(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            raw = user_input["redirect_url"].strip()
            query = parse_qs(urlparse(raw).query) if "?" in raw else parse_qs(raw)
            code = (query.get("code") or [""])[0]
            if code:
                self._code = code
                if site := (query.get("site_id") or [""])[0]:
                    self._site_id = site
                return await self.async_step_finish()
            errors["base"] = "no_code"

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required("redirect_url"): str}),
            errors=errors,
            description_placeholders={
                "auth_url": self._auth_url or self._make_manual_url()
            },
        )

    async def async_step_site(self, user_input: dict[str, Any] | None = None):
        """Ask for the site id if SolarEdge did not return one."""
        if user_input is not None:
            self._site_id = user_input[CONF_SITE_ID].strip()
            return await self.async_step_finish()
        return self.async_show_form(
            step_id="site", data_schema=vol.Schema({vol.Required(CONF_SITE_ID): str})
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        if not self._site_id:
            return await self.async_step_site()

        session = async_get_clientsession(self.hass)
        try:
            token = await exchange_code(
                session,
                self._client_id,
                self._client_secret,
                self._code,
                self._redirect_uri,
                self._verifier or None,
            )

            async def _noop(_: dict[str, Any]) -> None:
                return None

            client = SolarEdgeV2Client(
                session, self._client_id, self._client_secret, self._site_id, token, _noop
            )
            site = await client.get("/sites/{site}")
        except SolarEdgeAuthError as err:
            _LOGGER.warning("SolarEdge authorization failed: %s", err)
            return self.async_abort(
                reason="auth_failed", description_placeholders={"error": str(err)[:400]}
            )
        except SolarEdgeQuotaError:
            return self.async_abort(reason="quota")
        except SolarEdgeApiError as err:
            _LOGGER.warning("SolarEdge API error during setup: %s", err)
            return self.async_abort(reason="cannot_connect")

        data = {
            CONF_CLIENT_ID: self._client_id,
            CONF_CLIENT_SECRET: self._client_secret,
            CONF_REDIRECT_URI: self._redirect_uri,
            CONF_AUTHORIZE_EXTRA: self._extra,
            CONF_SITE_ID: self._site_id,
            CONF_TOKEN: token,
        }

        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(
                self._reauth_entry, data=data, reason="reauth_successful"
            )

        await self.async_set_unique_id(self._site_id)
        self._abort_if_unique_id_configured()
        name = (
            (site.get("name") or site.get("siteName")) if isinstance(site, dict) else None
        ) or self._site_id
        return self.async_create_entry(title=f"SolarEdge {name}", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return SolarEdgeOptionsFlow()


class SolarEdgeOptionsFlow(config_entries.OptionsFlow):
    """Polling and credit budget options."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        o = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(CONF_TELEMETRY, default=o.get(CONF_TELEMETRY, DEFAULT_TELEMETRY)): bool,
                vol.Required(CONF_DAYLIGHT, default=o.get(CONF_DAYLIGHT, DEFAULT_DAYLIGHT)): bool,
                vol.Required(CONF_INTERVAL, default=o.get(CONF_INTERVAL, DEFAULT_INTERVAL)): vol.All(
                    int, vol.Range(min=0, max=1440)
                ),
                vol.Required(CONF_BUDGET, default=o.get(CONF_BUDGET, DEFAULT_BUDGET)): vol.All(
                    int, vol.Range(min=100, max=100000)
                ),
                vol.Required(CONF_BILLING_DAY, default=o.get(CONF_BILLING_DAY, DEFAULT_BILLING_DAY)): vol.All(
                    int, vol.Range(min=1, max=28)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
