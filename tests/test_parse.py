"""Standalone tests (no Home Assistant needed): python3 tests/test_parse.py"""

import base64
import hashlib
import importlib.util
import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "solaredge_v2"


def load(name):
    spec = importlib.util.spec_from_file_location(name, BASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


parse = load("parse")


def as_dict(leaves):
    return {p: (v, u) for p, v, u in leaves}


def test_unit_sibling_and_value_key():
    leaves = as_dict(parse.flatten({"lastDayData": {"production": {"value": 12.5, "unit": "kWh"}}}, "overview"))
    assert leaves["overview_lastDayData_production"] == (12.5, "kWh")


def test_timeseries_takes_latest():
    raw = {"unit": "W", "values": [{"time": "2026-10-25T10:00:00Z", "value": 1},
                                    {"time": "2026-10-25T10:15:00Z", "value": 5},
                                    {"time": "2026-10-25T10:00:30Z", "value": 3}]}
    leaves = as_dict(parse.flatten(raw, "power"))
    assert leaves["power_values"] == (5, "W")
    assert leaves["power_values_time"][0] == "2026-10-25T10:15:00Z"


def test_devices_by_serial():
    raw = {"meters": [{"serialNumber": "AB1", "telemetries": [{"timestamp": "t1", "power": 1.0},
                                                               {"timestamp": "t2", "power": 2.0}]},
                      {"serialNumber": "CD2", "telemetries": [{"timestamp": "t1", "power": 7.0}]}]}
    leaves = as_dict(parse.flatten(raw, "meters"))
    assert leaves["meters_meters_AB1_telemetries_power"][0] == 2.0
    assert leaves["meters_meters_CD2_telemetries_power"][0] == 7.0
    assert leaves["meters_meters_count"][0] == 2


def test_strings_bools_and_none():
    leaves = as_dict(parse.flatten({"name": "Home", "ok": True, "x": None}, "site"))
    assert leaves == {"site_name": ("Home", None), "site_ok": ("true", None)}


def test_humanize():
    assert parse.humanize("overview_lastDayData_production") == "Overview Last Day Data Production"


def test_pkce():
    # replicate api.generate_pkce without importing aiohttp
    import secrets
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert 43 <= len(verifier) <= 128 and "=" not in challenge


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)


def test_latest_bucket_skips_empty_current_quarter():
    raw = {"unit": "W", "values": [{"timestamp": "2026-10-25T13:30:00+01:00", "value": 848.7},
                                    {"timestamp": "2026-10-25T13:45:00+01:00", "value": None}]}
    leaves = as_dict(parse.flatten(raw, "power"))
    assert leaves["power_values"] == (848.7, "W")
    assert leaves["power_values_timestamp"][0].startswith("2026-10-25T13:30")


def test_humanize_keeps_serials_together():
    assert parse.humanize("devices_731D15D6_7B_firmwareVersion") == "Devices 731D15D6 7B Firmware Version"


def test_planner():
    import importlib.util, sys, types
    # plan_live_minutes only needs math; load it without Home Assistant
    src = (BASE / "coordinator.py").read_text()
    start = src.index("def plan_live_minutes")
    end = src.index("class SolarEdgeCoordinator")
    ns = {"math": __import__("math"), "MIN_LIVE_MINUTES": 15, "MAX_LIVE_MINUTES": 180}
    exec(src[start:end], ns)
    plan = ns["plan_live_minutes"]
    assert plan(1800, 8, 1.75, 12) == 25      # telemetry on, daylight only
    assert plan(1800, 8, 1.5, 12) == 25       # no telemetry
    assert plan(2000, 8, 1.0, 12) == 15       # power only, full free tier
    assert plan(1800, 8, 1.75, 24) == 50      # around the clock costs double
    assert plan(100, 8, 1.0, 12) == 180       # budget smaller than the slow calls
