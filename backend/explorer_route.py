"""
Infinite-explorer routing: build an ~X km Valhalla route that prefers unexplored
road segments using a light greedy look-ahead (not a full TSP).

Algorithm (cheap, good enough for live replan):
  1. Load unexplored segment midpoints near the GPS fix (PostGIS), filtered by
     Navigate profile highways.
  2. Tag whole cul-de-sac branches (not just tip segments).
  3. Score = length_m / (1 + dist_m) × density bonus (nearby unexplored count).
  4. Greedy chain: from current position, repeatedly pick the best remaining
     candidate within a hop budget until cumulative crow-flies ≈ target_km.
  5. Ask Valhalla to stitch origin → waypoints into a driveable path.
  6. Replan when the client asks again (off-route / horizon eaten).
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from db import connect_dict
from drive_profiles import normalize_profile, profile_highways, routing_policy
from levels import get_level, set_level_default_profile
from valhalla_client import ValhallaError, route, summarize_route

# Fallback when profile has no min (legacy callers)
DEAD_END_MIN_M = 100.0

# First metres of a new route must continue along current heading.
# Replans take a second or two; by then the car has already moved — a straight
# lead-in keeps the path usable instead of turning behind the vehicle.
STRAIGHT_LEAD_M = 160.0

Node = tuple[float, float]


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _tag_dead_end_branches(segs: list[dict[str, Any]], deg: dict[Node, int]) -> None:
    """
    Mark whole cul-de-sac corridors, not only tip segments.

    Walk from each degree-1 tip along degree-≤2 nodes until a junction (deg≥3).
    Every segment on that walk is a dead-end branch member; branch length is the
    sum of those segment lengths (used for small_car min-length policy).
    Mutates segs in place: is_dead_end, dead_end_branch_m.
    """
    by_id: dict[int, dict[str, Any]] = {}
    # node -> list of (seg_id, other_node)
    adj: dict[Node, list[tuple[int, Node]]] = defaultdict(list)

    for s in segs:
        sid = int(s["id"])
        by_id[sid] = s
        a: Node = (float(s["sx"]), float(s["sy"]))
        b: Node = (float(s["ex"]), float(s["ey"]))
        s["_a"] = a
        s["_b"] = b
        adj[a].append((sid, b))
        adj[b].append((sid, a))
        s["is_dead_end"] = False
        s["dead_end_branch_m"] = 0.0

    claimed: set[int] = set()
    tips = [n for n, d in deg.items() if d <= 1]

    for tip in tips:
        if tip not in adj:
            continue
        branch_ids: list[int] = []
        branch_m = 0.0
        cur = tip
        prev: Node | None = None
        used_edges: set[int] = set()

        while True:
            edges = [
                (sid, other)
                for sid, other in adj.get(cur, [])
                if sid not in used_edges and sid not in claimed
            ]
            if prev is not None:
                edges = [(sid, other) for sid, other in edges if other != prev]
            if not edges:
                break
            # At a real junction stop — do not pull through-routes into the branch
            if deg.get(cur, 0) >= 3 and cur != tip:
                break
            # Prefer continuing along deg≤2 corridor (pick any remaining edge)
            sid, nxt = edges[0]
            used_edges.add(sid)
            if sid not in claimed:
                branch_ids.append(sid)
                branch_m += float(by_id[sid].get("length_m") or 0)
            prev, cur = cur, nxt
            # Safety: bound walk
            if len(branch_ids) > 80:
                break

        if not branch_ids:
            continue
        for sid in branch_ids:
            claimed.add(sid)
            s = by_id[sid]
            s["is_dead_end"] = True
            s["dead_end_branch_m"] = branch_m

    # Tip-only fallback when degree map missed a corridor walk
    for s in segs:
        if s.get("is_dead_end"):
            continue
        a, b = s["_a"], s["_b"]
        if deg.get(a, 1) <= 1 or deg.get(b, 1) <= 1:
            s["is_dead_end"] = True
            s["dead_end_branch_m"] = float(s.get("length_m") or 0)


def _fetch_unexplored_candidates(
    level_id: int,
    lon: float,
    lat: float,
    search_m: float,
    highways: list[str],
    limit: int = 160,
) -> list[dict[str, Any]]:
    """
    Midpoints of locked segments inside a geographic radius, for this profile's
    highways. Dead-end trees use endpoint degree on the local profile subgraph
    (explored + unexplored) so cul-de-sac interiors are excluded too.
    """
    if not highways:
        return []

    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  id,
                  length_m,
                  ST_X(ST_LineInterpolatePoint(geom, 0.5)) AS lon,
                  ST_Y(ST_LineInterpolatePoint(geom, 0.5)) AS lat,
                  ST_Distance(
                    geom::geography,
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography
                  ) AS dist_m,
                  ROUND(ST_X(ST_StartPoint(geom))::numeric, 5) AS sx,
                  ROUND(ST_Y(ST_StartPoint(geom))::numeric, 5) AS sy,
                  ROUND(ST_X(ST_EndPoint(geom))::numeric, 5) AS ex,
                  ROUND(ST_Y(ST_EndPoint(geom))::numeric, 5) AS ey
                FROM road_segments
                WHERE level_id = %s
                  AND is_explored = FALSE
                  AND highway = ANY(%s)
                  AND geom && ST_Expand(
                    ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                    %s / 111320.0
                  )
                ORDER BY geom <-> ST_SetSRID(ST_MakePoint(%s, %s), 4326)
                LIMIT %s
                """,
                (
                    lon,
                    lat,
                    level_id,
                    highways,
                    lon,
                    lat,
                    search_m,
                    lon,
                    lat,
                    limit,
                ),
            )
            rows = list(cur.fetchall())
            if not rows:
                return []

            xs = [float(r["sx"]) for r in rows] + [float(r["ex"]) for r in rows]
            ys = [float(r["sy"]) for r in rows] + [float(r["ey"]) for r in rows]
            pad = max(0.002, search_m / 111320.0 * 0.15)
            west, south = min(xs) - pad, min(ys) - pad
            east, north = max(xs) + pad, max(ys) + pad

            # Local profile subgraph (explored + locked) for accurate degrees + walks
            cur.execute(
                """
                SELECT
                  id,
                  length_m,
                  ROUND(ST_X(ST_StartPoint(geom))::numeric, 5) AS sx,
                  ROUND(ST_Y(ST_StartPoint(geom))::numeric, 5) AS sy,
                  ROUND(ST_X(ST_EndPoint(geom))::numeric, 5) AS ex,
                  ROUND(ST_Y(ST_EndPoint(geom))::numeric, 5) AS ey
                FROM road_segments
                WHERE level_id = %s
                  AND highway = ANY(%s)
                  AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
                """,
                (level_id, highways, west, south, east, north),
            )
            local = list(cur.fetchall())

            deg: dict[Node, int] = defaultdict(int)
            for r in local:
                a = (float(r["sx"]), float(r["sy"]))
                b = (float(r["ex"]), float(r["ey"]))
                deg[a] += 1
                deg[b] += 1

            # Tag cul-de-sacs on the local subgraph, then apply to unexplored rows
            local_segs = [
                {
                    "id": r["id"],
                    "length_m": r["length_m"],
                    "sx": float(r["sx"]),
                    "sy": float(r["sy"]),
                    "ex": float(r["ex"]),
                    "ey": float(r["ey"]),
                }
                for r in local
            ]
            _tag_dead_end_branches(local_segs, dict(deg))
            dead_meta = {
                int(s["id"]): (
                    bool(s.get("is_dead_end")),
                    float(s.get("dead_end_branch_m") or 0),
                )
                for s in local_segs
            }

            out: list[dict[str, Any]] = []
            for r in rows:
                if float(r["dist_m"] or 0) > search_m:
                    continue
                sid = int(r["id"])
                is_de, branch_m = dead_meta.get(sid, (False, 0.0))
                if not is_de:
                    ds = deg.get((float(r["sx"]), float(r["sy"])), 1)
                    de = deg.get((float(r["ex"]), float(r["ey"])), 1)
                    if ds <= 1 or de <= 1:
                        is_de = True
                        branch_m = float(r["length_m"] or 0)
                out.append(
                    {
                        "id": sid,
                        "length_m": r["length_m"],
                        "lon": r["lon"],
                        "lat": r["lat"],
                        "dist_m": r["dist_m"],
                        "is_dead_end": is_de,
                        "dead_end_branch_m": branch_m,
                    }
                )
            return out
    finally:
        conn.close()


def filter_dead_end_candidates(
    candidates: list[dict[str, Any]],
    *,
    exclude_all: bool = False,
    min_length_m: float = DEAD_END_MIN_M,
) -> list[dict[str, Any]]:
    """
    Drop cul-de-sac branches from explore waypoints.
    Always skip branches shorter than min_length_m; if exclude_all, skip every
    dead-end branch (big_car).
    """
    out: list[dict[str, Any]] = []
    for c in candidates:
        if not c.get("is_dead_end"):
            out.append(c)
            continue
        branch = float(c.get("dead_end_branch_m") or c.get("length_m") or 0)
        if exclude_all:
            continue
        if branch < min_length_m:
            continue
        out.append(c)
    return out


def _density_bonus(candidates: list[dict[str, Any]], cell_m: float = 120.0) -> dict[int, int]:
    """Count how many other candidates fall in the same ~cell_m grid cell."""
    counts: dict[tuple[int, int], int] = {}
    keys: dict[int, tuple[int, int]] = {}
    for c in candidates:
        gx = int(float(c["lon"]) * 111320.0 * math.cos(math.radians(float(c["lat"]))) / cell_m)
        gy = int(float(c["lat"]) * 111320.0 / cell_m)
        key = (gx, gy)
        keys[int(c["id"])] = key
        counts[key] = counts.get(key, 0) + 1
    return {cid: counts[key] for cid, key in keys.items()}


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing from point 1 → 2 (0=N, 90=E)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _angle_diff_deg(a: float, b: float) -> float:
    """Smallest signed difference a−b in (−180, 180]."""
    return (float(a) - float(b) + 180.0) % 360.0 - 180.0


def _offset_point(lat: float, lon: float, bearing_deg: float, dist_m: float) -> dict[str, float]:
    """Point `dist_m` metres from (lat, lon) along compass bearing."""
    r = 6371000.0
    br = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    d = dist_m / r
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d)
        + math.cos(lat1) * math.sin(d) * math.cos(br)
    )
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return {
        "lat": math.degrees(lat2),
        "lon": (math.degrees(lon2) + 540.0) % 360.0 - 180.0,
    }


def _score(
    c: dict[str, Any],
    density: int,
    from_lat: float,
    from_lon: float,
    *,
    heading_deg: float | None = None,
    heading_weight: float = 1.0,
) -> float:
    dist = _haversine_m(from_lat, from_lon, float(c["lat"]), float(c["lon"]))
    length = float(c["length_m"] or 0)
    base = (length / (1.0 + dist)) * (1.0 + 0.12 * max(0, density - 1))
    if heading_deg is None or dist < 15:
        return base
    brg = _bearing_deg(from_lat, from_lon, float(c["lat"]), float(c["lon"]))
    align = math.cos(math.radians(_angle_diff_deg(brg, heading_deg)))
    return base * (1.0 + heading_weight * align)


def pick_waypoints(
    lat: float,
    lon: float,
    candidates: list[dict[str, Any]],
    *,
    target_km: float,
    max_waypoints: int = 4,
    heading_deg: float | None = None,
) -> list[dict[str, float]]:
    if not candidates:
        return []

    density = _density_bonus(candidates)
    remaining = {int(c["id"]): c for c in candidates}
    cur_lat, cur_lon = lat, lon
    walked = 0.0
    target_m = max(400.0, target_km * 1000.0)
    waypoints: list[dict[str, float]] = []
    drive_heading = heading_deg

    while remaining and len(waypoints) < max_waypoints and walked < target_m * 0.92:
        best_id = None
        best_score = -1.0
        first_hop = not waypoints
        hw = 2.4 if first_hop else 0.55
        for cid, c in remaining.items():
            hop = _haversine_m(cur_lat, cur_lon, float(c["lat"]), float(c["lon"]))
            if hop < 40:
                continue
            if hop > max(900.0, target_m * 0.35):
                continue
            if first_hop and drive_heading is not None:
                brg = _bearing_deg(cur_lat, cur_lon, float(c["lat"]), float(c["lon"]))
                if abs(_angle_diff_deg(brg, drive_heading)) > 70.0:
                    continue
            s = _score(
                c,
                density.get(cid, 1),
                cur_lat,
                cur_lon,
                heading_deg=drive_heading,
                heading_weight=hw,
            )
            if s > best_score:
                best_score = s
                best_id = cid
        if best_id is None:
            for cid, c in remaining.items():
                if first_hop and drive_heading is not None:
                    brg = _bearing_deg(
                        cur_lat, cur_lon, float(c["lat"]), float(c["lon"])
                    )
                    if abs(_angle_diff_deg(brg, drive_heading)) > 110.0:
                        continue
                s = _score(
                    c,
                    density.get(cid, 1),
                    cur_lat,
                    cur_lon,
                    heading_deg=drive_heading,
                    heading_weight=hw,
                )
                if s > best_score:
                    best_score = s
                    best_id = cid
        if best_id is None:
            break
        c = remaining.pop(best_id)
        hop = _haversine_m(cur_lat, cur_lon, float(c["lat"]), float(c["lon"]))
        walked += hop
        drive_heading = _bearing_deg(
            cur_lat, cur_lon, float(c["lat"]), float(c["lon"])
        )
        cur_lat, cur_lon = float(c["lat"]), float(c["lon"])
        waypoints.append({"lat": cur_lat, "lon": cur_lon})

    return waypoints


def plan_explore_route(
    user_id: int,
    level_id: int,
    lat: float,
    lon: float,
    *,
    target_km: float = 5.0,
    language: str = "en-US",
    heading_deg: float | None = None,
    profile: str | None = None,
    exclude_dead_ends: bool | None = None,
) -> dict[str, Any]:
    level = get_level(user_id, level_id)
    if not level:
        raise ValueError("Level not found")
    if level.get("status") != "ready":
        raise ValueError("Level is not ready")

    # Request profile wins; level.profile is only a last-used default
    profile = normalize_profile(profile or level.get("profile"))
    policy = routing_policy(profile, exclude_dead_ends=exclude_dead_ends)
    costing = str(policy["costing"])
    costing_opts = dict(policy.get("costing_options") or {})
    dead_min = float(policy["dead_end_min_m"])
    highways = sorted(profile_highways(profile))
    search_m = max(2500.0, min(12000.0, target_km * 1000.0 * 1.6))
    heading = float(heading_deg) % 360.0 if heading_deg is not None else None

    raw_candidates = _fetch_unexplored_candidates(
        level_id, lon, lat, search_m, highways
    )
    candidates = filter_dead_end_candidates(
        raw_candidates,
        exclude_all=bool(policy["exclude_all_dead_ends"]),
        min_length_m=dead_min,
    )

    pick_lat, pick_lon = lat, lon
    lead: dict[str, float] | None = None
    if heading is not None and STRAIGHT_LEAD_M > 0:
        lead = _offset_point(lat, lon, heading, STRAIGHT_LEAD_M)
        pick_lat, pick_lon = float(lead["lat"]), float(lead["lon"])

    waypoints = pick_waypoints(
        pick_lat,
        pick_lon,
        candidates,
        target_km=target_km,
        heading_deg=heading,
    )

    if not waypoints:
        raise ValhallaError(
            "No unexplored road segments nearby for this vehicle mode — "
            "try another mode, spawn, or a larger level"
        )

    locations: list[dict[str, Any]] = [{"lat": lat, "lon": lon}]
    if lead is not None:
        locations.append(
            {
                "lat": lead["lat"],
                "lon": lead["lon"],
                "type": "through",
                "heading": heading,
                "heading_tolerance": 30.0,
            }
        )
    locations.extend(waypoints)
    raw = route(
        locations,
        costing=costing,
        language=language,
        heading_deg=heading,
        heading_tolerance=35.0,
        costing_options=costing_opts or None,
    )
    summary = summarize_route(raw)

    try:
        set_level_default_profile(user_id, level_id, profile)
    except Exception:
        pass

    summary.update(
        {
            "level_id": level_id,
            "level_name": level.get("name"),
            "profile": profile,
            "profile_label": policy.get("label"),
            "costing": costing,
            "target_km": target_km,
            "waypoint_count": len(waypoints),
            "candidate_count": len(candidates),
            "candidate_count_raw": len(raw_candidates),
            "exclude_dead_ends": bool(policy["exclude_all_dead_ends"]),
            "dead_end_min_m": dead_min,
            "straight_lead_m": STRAIGHT_LEAD_M if lead is not None else 0.0,
            "origin": {"lat": lat, "lon": lon},
            "heading_deg": heading,
        }
    )
    return summary
