"""End-to-end tests with pytest-homeassistant-custom-component."""

from urllib.parse import parse_qs, urlparse

from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.solaredge_v2 import coordinator as coord_mod
from custom_components.solaredge_v2.const import DOMAIN

from .helpers import MockResp

TOKEN = "https://monitoringapi.solaredge.com/v2/oauth2/token"
BASE = "https://monitoringapi.solaredge.com/v2/sites/4711"


def _series(unit, rows):
    return {"period": {"from": "2026-10-25T00:00:00+01:00", "to": "2026-10-25T14:00:00+01:00"},
            "unit": unit, "resolution": "QUARTER_HOUR",
            "values": [{"timestamp": t, "value": v} for t, v in rows]}


def _mock_api(aioclient_mock):
    aioclient_mock.post(TOKEN, json={"access_token": "A1", "refresh_token": "R1", "expires_in": 3600})
    aioclient_mock.get(BASE, json={"siteId": 4711, "name": "Huis", "peakPower": 4.5,
                                   "lastUpdateTime": "2026-10-25T12:48:18.584Z"})
    aioclient_mock.get(f"{BASE}/overview",
                       json={"siteId": 4711, "production": {"total": 4160.0}, "unit": "WH"})
    # newest bucket (13:45) is still empty, as SolarEdge really answers
    aioclient_mock.get(f"{BASE}/power", json=_series("W", [
        ("2026-10-25T13:15:00+01:00", 700.0), ("2026-10-25T13:30:00+01:00", 848.7),
        ("2026-10-25T13:45:00+01:00", None)]))
    aioclient_mock.get(f"{BASE}/inverters/telemetry", json={"inverters": [{
        "serialNumber": "731D15D6-7B",
        "power": _series("W", [("2026-10-25T13:30:00+01:00", 850.0), ("2026-10-25T13:45:00+01:00", None)]),
        "voltage": _series("V", [("2026-10-25T13:30:00+01:00", 238.2), ("2026-10-25T13:45:00+01:00", None)]),
    }]})
    aioclient_mock.get(f"{BASE}/energy", json={"unit": "WH", "resolution": "MONTH", "values": [
        {"timestamp": "2026-09-01T00:00:00+02:00", "value": 150000.0},
        {"timestamp": "2026-10-01T00:00:00+02:00", "value": 90000.0}]})
    aioclient_mock.get(f"{BASE}/lifetime-energy", json={"unit": "WH", "lifetimeEnergy": 22000000.0})
    aioclient_mock.get(f"{BASE}/alerts", json={"alerts": []})
    aioclient_mock.get(f"{BASE}/devices", json={"devices": [
        {"serialNumber": "731D15D6-7B", "type": "INVERTER", "name": "Inverter 1"}]})


async def test_full_flow_and_entities(hass, hass_client_no_auth, aioclient_mock, monkeypatch):
    monkeypatch.setattr(coord_mod, "CALL_SPACING_SECONDS", 0)
    _mock_api(aioclient_mock)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"client_id": "cid", "client_secret": "sec",
         "redirect_uri": "https://example.com/solaredge-callback.html",
         "authorize_extra": "scope=SITE_DATA DEVICE_DATA"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "auto"})
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    query = parse_qs(urlparse(result["url"]).query)
    assert query["code_challenge_method"] == ["S256"] and query["scope"] == ["SITE_DATA DEVICE_DATA"]

    client = await hass_client_no_auth()
    resp = await client.get("/api/solaredge_v2/callback",
                            params={"code": "CODE", "site_id": "4711", "external_id": query["external_id"][0]})
    assert resp.status == 200
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY and result["title"] == "SolarEdge Huis"
    await hass.async_block_till_done()

    registry = er.async_get(hass)

    def state(uid):
        eid = registry.async_get_entity_id("sensor", DOMAIN, f"4711_{uid}")
        assert eid, f"entity for {uid} missing"
        return hass.states.get(eid)

    # live power = newest FILLED bucket, bucket time as attribute
    power = state("power_values")
    assert power.state == "848.7" and power.attributes["unit_of_measurement"] == "W"
    assert power.attributes["friendly_name"].endswith("Solar power")
    assert power.attributes["data_timestamp"].startswith("2026-10-25T13:30")
    assert state("overview_production_total").state == "4160.0"
    assert state("energy_thisYear").state == "240000.0"
    assert state("energy_thisMonth").state == "90000.0"
    inv_power = state("inverters_inverters_731D15D6_7B_power_values")
    assert inv_power.state == "850.0"
    assert inv_power.attributes["friendly_name"].endswith("AC power")
    assert state("inverters_inverters_731D15D6_7B_voltage_values").state == "238.2"

    # no request-window noise entities at all
    uids = {e.unique_id for e in registry.entities.values() if e.platform == DOMAIN}
    assert not [u for u in uids if u.endswith(("_period_from", "_period_to", "_resolution", "_values_timestamp"))]

    # request parameters follow the documented names
    power_calls = [c for c in aioclient_mock.mock_calls if str(c[1]).startswith(f"{BASE}/power")]
    q = parse_qs(urlparse(str(power_calls[0][1])).query)
    assert {"from", "to", "resolution"} <= set(q) and q["resolution"] == ["QUARTER_HOUR"]
    assert "+" in q["from"][0] or q["from"][0].endswith("Z") or "-" in q["from"][0][10:]
    # no meter/battery in the inventory -> those endpoints are never called
    assert not [c for c in aioclient_mock.mock_calls if "/meters/" in str(c[1]) or "/storage/" in str(c[1])]


async def test_callback_without_flow(hass, hass_client_no_auth):
    from homeassistant.setup import async_setup_component

    from custom_components.solaredge_v2 import async_setup

    assert await async_setup_component(hass, "http", {})
    await async_setup(hass, {})
    client = await hass_client_no_auth()
    resp = await client.get("/api/solaredge_v2/callback", params={"code": "X"})
    assert resp.status == 400


async def test_callback_in_manual_mode_does_not_break_flow(hass, hass_client_no_auth):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"client_id": "cid", "client_secret": "sec",
         "redirect_uri": "https://example.com/solaredge-callback.html", "authorize_extra": ""})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "manual"})
    assert result["step_id"] == "manual"
    hass.data[DOMAIN]["pending"]["ext"] = result["flow_id"]
    client = await hass_client_no_auth()
    resp = await client.get("/api/solaredge_v2/callback", params={"code": "C", "site_id": "1", "external_id": "ext"})
    assert resp.status == 200 and "Almost done" in await resp.text()
    assert hass.config_entries.flow.async_get(result["flow_id"])["step_id"] == "manual"


async def test_exchange_retries_without_redirect_uri(hass, aioclient_mock):
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    from custom_components.solaredge_v2.api import SolarEdgeAuthError, exchange_code

    sent = []

    async def handler(method, url, data):
        sent.append(dict(data))
        if "redirect_uri" in data:
            return MockResp(400, '{"error_description":"Invalid redirect_uri that does not match"}')
        return MockResp(200, '{"access_token":"A","refresh_token":"R","expires_in":60}')

    aioclient_mock.post(TOKEN, side_effect=handler)
    tok = await exchange_code(async_get_clientsession(hass), "cid", "sec", "CODE", "https://x/y", "VER")
    assert tok["refresh_token"] == "R" and "redirect_uri" not in sent[-1]

    async def always_bad(method, url, data):
        return MockResp(400, '{"error_description":"Invalid redirect_uri"}')

    aioclient_mock.clear_requests()
    aioclient_mock.post(TOKEN, side_effect=always_bad)
    try:
        await exchange_code(async_get_clientsession(hass), "cid", "sec", "CODE", "https://x/y", None)
    except SolarEdgeAuthError as err:
        assert "redirect_uri" in str(err)
    else:
        raise AssertionError("expected SolarEdgeAuthError")
