"""Thin HTTP client for local Valhalla (turn-by-turn + shapes)."""

from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from typing import Any

DEFAULT_VALHALLA_URL = os.getenv("VALHALLA_URL", "http://127.0.0.1:8002")

# Cache /status so every /route doesn't pay an extra RTT (was doubling latency).
_STATUS_CACHE: dict[str, Any] = {"at": 0.0, "ok": False, "payload": None}
_STATUS_TTL_S = 8.0


class ValhallaError(RuntimeError):
    pass


def valhalla_base_url() -> str:
    return (os.getenv("VALHALLA_URL") or DEFAULT_VALHALLA_URL).rstrip("/")


def valhalla_status(timeout_s: float = 2.0, *, bypass_cache: bool = False) -> dict[str, Any]:
    """Probe /status. During tile build the port may accept then drop — report that."""
    import time

    now = time.monotonic()
    if (
        not bypass_cache
        and _STATUS_CACHE["payload"] is not None
        and (now - float(_STATUS_CACHE["at"])) < _STATUS_TTL_S
    ):
        return dict(_STATUS_CACHE["payload"])

    url = f"{valhalla_base_url()}/status"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body) if body else {}
            except json.JSONDecodeError:
                payload = {"raw": body[:200]}
            out = {
                "ok": 200 <= resp.status < 300,
                "url": valhalla_base_url(),
                "status_code": resp.status,
                "detail": payload,
            }
    except Exception as exc:
        out = {
            "ok": False,
            "url": valhalla_base_url(),
            "status_code": None,
            "detail": str(exc),
            "building_hint": (
                "Valhalla is probably still downloading/building tiles. "
                "Check: docker logs -f wardrivrr_valhalla"
            ),
        }
    _STATUS_CACHE["at"] = now
    _STATUS_CACHE["ok"] = bool(out.get("ok"))
    _STATUS_CACHE["payload"] = out
    return out


def valhalla_reachable(timeout_s: float = 2.0) -> bool:
    return bool(valhalla_status(timeout_s).get("ok"))


def _post(path: str, body: dict[str, Any], timeout_s: float = 25.0) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{valhalla_base_url()}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ValhallaError(f"Valhalla HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ValhallaError(
            f"Valhalla unreachable at {valhalla_base_url()} — still building tiles? "
            f"({exc.reason})"
        ) from exc
    except (http.client.RemoteDisconnected, http.client.IncompleteRead, TimeoutError, OSError) as exc:
        raise ValhallaError(
            f"Valhalla closed the connection (often still building tiles). "
            f"Wait and check: docker logs -f wardrivrr_valhalla — {exc}"
        ) from exc


def route(
    locations: list[dict[str, float]],
    *,
    costing: str = "auto",
    language: str = "en-US",
    units: str = "kilometers",
    heading_deg: float | None = None,
    heading_tolerance: float = 45.0,
) -> dict[str, Any]:
    """
    locations: [{"lat": …, "lon": …}, …]  (first = origin, last = destination)
    heading_deg: preferred departure bearing (0=N, 90=E) applied to the origin.
    Returns Valhalla /route JSON.
    """
    if len(locations) < 2:
        raise ValhallaError("Need at least origin and one destination")
    if not valhalla_reachable(1.2):
        st = valhalla_status(1.2, bypass_cache=True)
        raise ValhallaError(
            st.get("building_hint")
            or f"Valhalla not ready at {valhalla_base_url()}: {st.get('detail')}"
        )
    n = len(locations)
    locs: list[dict[str, Any]] = []
    for i, p in enumerate(locations):
        # break at ends only — intermediate "through" keeps a single A* leg
        # (multi-break legs were the main reason replans felt single-core / slow)
        explicit = p.get("type")
        if explicit in ("break", "through", "via"):
            loc_type = explicit
        elif i == 0 or i == n - 1:
            loc_type = "break"
        else:
            loc_type = "through"
        loc: dict[str, Any] = {
            "lat": float(p["lat"]),
            "lon": float(p["lon"]),
            "type": loc_type,
        }
        # Prefer caller-supplied per-point heading, else origin heading_deg
        h = p.get("heading")
        if h is None and i == 0 and heading_deg is not None:
            h = heading_deg
        if h is not None:
            loc["heading"] = float(h) % 360.0
            loc["heading_tolerance"] = float(
                p.get("heading_tolerance", heading_tolerance)
            )
        locs.append(loc)
    return _post(
        "/route",
        {
            "locations": locs,
            "costing": costing,
            "directions_options": {"units": units, "language": language},
        },
    )


def decode_polyline6(encoded: str) -> list[list[float]]:
    """Decode Valhalla polyline6 → [[lon, lat], …] GeoJSON order."""
    coords: list[list[float]] = []
    index = 0
    lat = 0
    lon = 0
    length = len(encoded)
    while index < length:
        for quant in (0, 1):
            result = 0
            shift = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if quant == 0:
                lat += delta
            else:
                lon += delta
        coords.append([lon / 1e6, lat / 1e6])
    return coords


def summarize_route(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize Valhalla response for the navigate HUD."""
    trip = raw.get("trip") or {}
    legs = trip.get("legs") or []
    if not legs:
        raise ValhallaError("Valhalla returned no legs")

    maneuvers: list[dict[str, Any]] = []
    shape_coords: list[list[float]] = []
    total_km = float(trip.get("summary", {}).get("length") or 0)
    total_s = float(trip.get("summary", {}).get("time") or 0)

    for leg in legs:
        shape = leg.get("shape") or ""
        if shape:
            shape_coords.extend(decode_polyline6(shape))
        for m in leg.get("maneuvers") or []:
            maneuvers.append(
                {
                    "type": m.get("type"),
                    "instruction": m.get("instruction") or "",
                    "verbal": m.get("verbal_pre_transition_instruction")
                    or m.get("instruction")
                    or "",
                    "street": (m.get("street_names") or [None])[0],
                    "length_km": float(m.get("length") or 0),
                    "time_s": float(m.get("time") or 0),
                    "begin_shape_index": m.get("begin_shape_index"),
                    "end_shape_index": m.get("end_shape_index"),
                }
            )

    # Drop duplicate joint vertices between legs
    cleaned: list[list[float]] = []
    for c in shape_coords:
        if not cleaned or cleaned[-1] != c:
            cleaned.append(c)

    next_m = maneuvers[0] if maneuvers else None
    then_m = maneuvers[1] if len(maneuvers) > 1 else None

    return {
        "length_km": total_km,
        "time_s": total_s,
        "maneuvers": maneuvers,
        "next": next_m,
        "then": then_m,
        "geometry": {"type": "LineString", "coordinates": cleaned},
        "raw_summary": trip.get("summary"),
    }
