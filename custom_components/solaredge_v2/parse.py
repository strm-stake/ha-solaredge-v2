"""Turn arbitrary SolarEdge V2 JSON into flat (path, value, unit) leaves.

Home Assistant independent so it can be unit tested on its own.

Rules:
* dict -> recurse, key names are joined with "_"; a sibling "unit" key is the
  unit of the numeric values next to it.
* list of dicts with a strong id (serialNumber, ...) -> one branch per device.
* list of dicts/numbers with a timestamp (or plain number list) -> latest item.
* other lists -> indexed, plus a "<path>_count" leaf.
"""

from __future__ import annotations

import re
from typing import Any

TS_KEYS = ("timestamp", "time", "date", "startTime", "start", "endTime", "end", "measuredAt")
STRONG_ID_KEYS = ("serialNumber", "serial", "deviceId", "meterId", "batteryId", "inverterId")
WEAK_ID_KEYS = ("id", "name")
UNIT_KEYS = ("unit", "units", "unitOfMeasurement", "unitOfMeasure")
MAX_LEAVES = 400

Leaf = tuple[str, Any, "str | None"]


def slug(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_")


def humanize(key: str) -> str:
    """'overview_lastDayData_production' -> 'Overview Last Day Data Production'."""
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key.replace("_", " "))
    return " ".join(w[:1].upper() + w[1:] for w in spaced.split())


def flatten(obj: Any, prefix: str = "") -> list[Leaf]:
    out: list[Leaf] = []
    _walk(obj, prefix, out, None)
    return out[:MAX_LEAVES]


def _join(path: str, key: str) -> str:
    return f"{path}_{slug(key)}" if path else slug(key)


def _has_data(item: dict[str, Any], ts_key: str) -> bool:
    """True when the bucket carries at least one non-null value besides its timestamp."""
    return any(v is not None for k, v in item.items() if k != ts_key)


def _latest(items: list[dict[str, Any]], ts_key: str) -> dict[str, Any]:
    """Newest bucket that has data.

    SolarEdge returns the current, not yet reported 15-minute bucket with null
    values; reading that one would yield nothing, so fall back to the newest
    bucket that is filled.
    """
    ordered = sorted(items, key=lambda i: str(i.get(ts_key, "")), reverse=True)
    return next((i for i in ordered if _has_data(i, ts_key)), ordered[0])


def _walk(node: Any, path: str, out: list[Leaf], unit: str | None) -> None:
    if len(out) >= MAX_LEAVES or node is None:
        return
    if isinstance(node, bool):
        out.append((path, str(node).lower(), None))
    elif isinstance(node, (int, float)):
        out.append((path, node, unit))
    elif isinstance(node, str):
        if len(node) <= 128:
            out.append((path, node, None))
    elif isinstance(node, dict):
        unit_here = next(
            (node[k] for k in UNIT_KEYS if isinstance(node.get(k), str)), None
        ) or unit
        for key, value in node.items():
            if key in UNIT_KEYS:
                continue
            child = path if key == "value" and path else _join(path, key)
            _walk(value, child, out, unit_here)
    elif isinstance(node, list):
        _walk_list(node, path, out, unit)


def _walk_list(node: list[Any], path: str, out: list[Leaf], unit: str | None) -> None:
    if not node:
        return
    if all(isinstance(i, dict) for i in node):
        first = node[0]
        ts_key = next((k for k in TS_KEYS if k in first), None)
        strong = next((k for k in STRONG_ID_KEYS if k in first), None)
        weak = next((k for k in WEAK_ID_KEYS if k in first), None)
        if strong:
            for item in node:
                _walk(item, _join(path, str(item.get(strong))), out, unit)
        elif ts_key:
            _walk(_latest(node, ts_key), path, out, unit)
        elif weak:
            for item in node:
                _walk(item, _join(path, str(item.get(weak))), out, unit)
        else:
            for idx, item in enumerate(node):
                _walk(item, _join(path, str(idx)), out, unit)
        if not ts_key or strong:
            out.append((_join(path, "count"), len(node), None))
    elif all(isinstance(i, (int, float)) and not isinstance(i, bool) for i in node):
        out.append((path, node[-1], unit))
    else:
        for idx, item in enumerate(node):
            _walk(item, _join(path, str(idx)), out, unit)
