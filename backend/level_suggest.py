"""
Suggest which level to load for a GPS fix: whole city (small) or City (District) (large).
"""

from __future__ import annotations

from typing import Any

from admin_areas import find_city, find_covering_district
from city_boundaries import city_may_have_parts, resolve_relation_boundary
from geofabrik import resolve_place_extract
from levels import find_duplicate_level, get_level, list_levels, point_in_boundary


def level_contains_point(user_id: int, level_id: int, lat: float, lon: float) -> dict[str, Any]:
    level = get_level(user_id, level_id)
    if not level:
        return {"ok": False, "inside": False, "reason": "not_found"}
    boundary = level.get("boundary")
    inside = False
    if boundary:
        inside = point_in_boundary(lon, lat, boundary)
    else:
        bbox = level.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            w, s, e, n = (float(x) for x in bbox)
            inside = w <= lon <= e and s <= lat <= n
    return {
        "ok": True,
        "inside": bool(inside),
        "level_id": level_id,
        "name": level.get("name"),
        "status": level.get("status"),
    }


def _map_pack(lat: float, lon: float, bbox: list[float] | None, name: str | None) -> dict | None:
    extract = resolve_place_extract(lat, lon, place_bbox=bbox, place_name=name)
    if not extract or not extract.get("pbf_url"):
        return None
    return {
        "id": extract["id"],
        "name": extract.get("name"),
        "pbf_url": extract["pbf_url"],
        "size_bytes": extract.get("size_bytes"),
    }


def suggest_level_at(user_id: int, lat: float, lon: float) -> dict[str, Any]:
    """
    Resolve city at point. Large cities → district containing the point.
    Returns a create payload + display label, or an existing matching level.
    """
    city = find_city(lat, lon, None)
    if not city:
        return {
            "ok": False,
            "reason": "no_city",
            "detail": "No indexed city at this location",
        }

    city_name = city.get("name") or "City"
    city_bbox = city.get("bbox")
    may_parts = city_may_have_parts(population=None, bbox=city_bbox)
    pack = _map_pack(lat, lon, city_bbox, city_name)
    if not pack:
        return {"ok": False, "reason": "no_pack", "detail": "No map pack for this place"}

    place_kind = "city"
    osm_relation_id = int(city["osm_id"])
    parent_label = city_name
    part_label = None
    label = city_name
    lat_c = float(city.get("lat") or lat)
    lon_c = float(city.get("lon") or lon)
    bbox = city_bbox
    osm_admin_level = city.get("admin_level")

    if may_parts:
        hit = find_covering_district(city, lat, lon)
        if hit:
            place_kind = "district"
            osm_relation_id = int(hit["osm_id"])
            part_label = hit.get("name") or "District"
            label = f"{city_name} ({part_label})"
            lat_c = float(hit.get("lat") or lat)
            lon_c = float(hit.get("lon") or lon)
            bbox = hit.get("bbox") or city_bbox
            osm_admin_level = hit.get("admin_level")

    existing = find_duplicate_level(
        user_id,
        place_kind=place_kind,
        osm_relation_id=osm_relation_id,
    )
    if existing:
        return {
            "ok": True,
            "already_have": True,
            "label": existing.get("name") or label,
            "level": {
                "id": existing["id"],
                "name": existing.get("name"),
                "status": existing.get("status"),
            },
            "suggestion": None,
        }

    for lv in list_levels(user_id):
        if lv.get("status") == "error":
            continue
        if (lv.get("name") or "").strip().lower() == label.strip().lower():
            return {
                "ok": True,
                "already_have": True,
                "label": lv.get("name") or label,
                "level": {
                    "id": lv["id"],
                    "name": lv.get("name"),
                    "status": lv.get("status"),
                },
                "suggestion": None,
            }

    boundary = None
    try:
        br = resolve_relation_boundary(osm_relation_id)
        boundary = (br or {}).get("boundary")
        if (br or {}).get("bbox"):
            bbox = br["bbox"]
    except Exception:
        boundary = city.get("boundary") if place_kind == "city" else None

    return {
        "ok": True,
        "already_have": False,
        "label": label,
        "suggestion": {
            "name": label,
            "place_query": label,
            "place_kind": place_kind,
            "profile": "car",
            "geofabrik_id": pack["id"],
            "geoname_id": None,
            "parent_geoname_id": None,
            "parent_label": parent_label,
            "part_label": part_label,
            "osm_relation_id": osm_relation_id,
            "osm_admin_level": osm_admin_level,
            "place_bbox": bbox,
            "place_boundary": boundary,
            "lat": lat_c,
            "lon": lon_c,
            "map_pack": pack,
            "download_now": True,
        },
    }
