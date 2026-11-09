"""Own OAuth callback: SolarEdge does not return `state`, so HA's default fails."""

from __future__ import annotations

import html
import logging

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import CALLBACK_PATH, DOMAIN

try:  # newer Home Assistant versions
    from homeassistant.helpers.http import KEY_HASS
except ImportError:  # pragma: no cover
    KEY_HASS = "hass"

_LOGGER = logging.getLogger(__name__)

_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SolarEdge</title>
<style>body{{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem;text-align:center}}</style>
</head><body><h2>{title}</h2><p>{text}</p>
<script>setTimeout(function(){{window.close()}},2500)</script></body></html>"""


def async_register_view(hass: HomeAssistant) -> None:
    """Register the callback view once (flows run before async_setup does)."""
    domain_data = hass.data.setdefault(DOMAIN, {"pending": {}})
    domain_data.setdefault("pending", {})
    if not domain_data.get("view_registered"):
        hass.http.register_view(SolarEdgeCallbackView())
        domain_data["view_registered"] = True


def _page(title: str, text: str, status: int = 200) -> web.Response:
    return web.Response(
        text=_PAGE.format(title=html.escape(title), text=html.escape(text)),
        content_type="text/html",
        status=status,
    )


class SolarEdgeCallbackView(HomeAssistantView):
    """Receives ?code=...&site_id=...[&external_id=...] from the relay page."""

    url = CALLBACK_PATH
    name = "api:solaredge_v2:callback"
    requires_auth = False

    async def get(self, request: web.Request) -> web.Response:
        hass: HomeAssistant = request.app[KEY_HASS]
        query = request.query
        pending: dict[str, str] = hass.data.get(DOMAIN, {}).get("pending", {})

        if error := query.get("error"):
            _LOGGER.warning("SolarEdge authorization returned an error: %s", error)
            return _page("Authorization failed", f"SolarEdge returned: {error}", 400)

        code = query.get("code")
        if not code:
            return _page("Nothing to do", "No authorization code in this request.", 400)

        external_id = query.get("external_id")
        flow_id = pending.get(external_id) if external_id else None
        if flow_id is None and len(pending) == 1:
            flow_id = next(iter(pending.values()))
        if flow_id is None:
            return _page(
                "No setup in progress",
                "Start the SolarEdge setup in Home Assistant first, then sign in again.",
                400,
            )

        try:
            progress = hass.config_entries.flow.async_get(flow_id)
        except Exception:  # noqa: BLE001 - UnknownFlow
            return _page(
                "No setup in progress",
                "That setup was closed. Start it again in Home Assistant.",
                400,
            )
        if progress.get("step_id") != "auto":
            # Manual sign-in (or another step): do not touch the flow. The code is
            # still unused, so the address of this tab can be pasted into Home Assistant.
            return _page(
                "Almost done",
                "Copy the full address of this browser tab (it contains code=) and paste "
                "it in Home Assistant under 'Sign in manually'. Or restart the setup and "
                "choose 'Sign in automatically'.",
            )

        try:
            await hass.config_entries.flow.async_configure(
                flow_id=flow_id,
                user_input={"code": code, "site_id": query.get("site_id", "")},
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Could not continue the SolarEdge setup flow")
            return _page("Setup could not continue", "See the Home Assistant log.", 500)

        return _page("Connected", "SolarEdge access approved. You can close this tab.")
