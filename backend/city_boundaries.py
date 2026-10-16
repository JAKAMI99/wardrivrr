"""
Exact city / district boundaries for the levels wizard.

Fully local: reads the admin-boundary index built from Geofabrik PBFs by
scripts/build_admin_areas.py (see admin_areas.py). No network lookups.
"""

from __future__ import annotations

import math

import admin_areas

# Offer districts once the city is roughly ≥ 30 km² (or large by population).
PARTS_MIN_POPULATION = 80_000
PARTS_MIN_AREA_KM2 = 30.0
PARTS_MIN_BBOX_KM2 = 30.0

NOT_INDEXED = (
    "City outlines for this region are not indexed yet. "
    "Run: python scripts/build_admin_areas.py --city \"{name}\""
)


def _bbox_area_km2(bbox: list[float]) -> float:
    minlon, minlat, maxlon, maxlat = bbox
    mid_lat = (minlat + maxlat) / 2.0
    km_lat = abs(maxlat - minlat) * 111.0
    km_lon = abs(maxlon - minlon) * 111.0 * max(0.2, math.cos(math.radians(mid_lat)))
    return km_lat * km_lon


def city_may_have_parts(
    *,
    population: int | None = None,
    bbox: list[float] | None = None,
    area_km2: float | None = None,
) -> bool:
    """Heuristic: large enough that districts are worth offering (~30 km²+)."""
    if area_km2 is not None:
        try:
            if float(area_km2) >= PARTS_MIN_AREA_KM2:
                return True
        except (TypeError, ValueError):
            pass
    if population is not None and int(population) >= PARTS_MIN_POPULATION:
        return True
    if bbox and len(bbox) == 4:
        try:
            return _bbox_area_km2([float(x) for x in bbox]) >= PARTS_MIN_BBOX_KM2
        except (TypeError, ValueError):
            return False
    return False


def resolve_city_boundary(
    *,
    lat: float,
    lon: float,
    name: str | None = None,
    country_code: str | None = None,
    geoname_id: int | None = None,
    geofabrik_id: str | None = None,
) -> dict:
    """Return { boundary, bbox, approximate, source, osm_id, admin_level }."""
    _ = country_code, geoname_id
    city = admin_areas.find_city(lat, lon, name)
    if not city and geofabrik_id:
        # Opportunistic: index from an already-downloaded regional PBF
        if admin_areas.ensure_extract_indexed(geofabrik_id):
            city = admin_areas.find_city(lat, lon, name)
    if not city:
        return {
            "boundary": None,
            "bbox": None,
            "approximate": True,
            "source": None,
            "error": NOT_INDEXED.format(name=name or f"{lat},{lon}"),
        }
    return {
        "boundary": city["boundary"],
        "bbox": city["bbox"],
        "approximate": False,
        "source": "local_admin_index",
        "osm_id": city["osm_id"],
        "admin_level": city["admin_level"],
        "osm_name": city["name"],
    }


def resolve_relation_boundary(osm_relation_id: int) -> dict:
    """Polygon for a single admin area (used when the user picks a district)."""
    area = admin_areas.get_area(osm_relation_id)
    if not area:
        return {
            "boundary": None,
            "bbox": None,
            "approximate": True,
            "source": None,
            "error": "District outline not found in the local index",
        }
    return {
        "boundary": area["boundary"],
        "bbox": area["bbox"],
        "approximate": False,
        "source": "local_admin_index",
        "osm_id": area["osm_id"],
        "admin_level": area["admin_level"],
    }


def resolve_city_parts(
    *,
    lat: float,
    lon: float,
    name: str | None = None,
    country_code: str | None = None,
    geoname_id: int | None = None,
    population: int | None = None,
    bbox: list[float] | None = None,
    geofabrik_id: str | None = None,
) -> dict:
    """
    Districts directly below a large city — names + label points only.
    Polygons are read on select via resolve_relation_boundary.
    """
    _ = country_code, geoname_id
    if not city_may_have_parts(population=population, bbox=bbox):
        return {
            "parts": [],
            "skipped_reason": "city_too_small",
            "parent_admin_level": None,
            "child_admin_level": None,
        }
    city = admin_areas.find_city(lat, lon, name)
    if not city and geofabrik_id:
        if admin_areas.ensure_extract_indexed(geofabrik_id):
            city = admin_areas.find_city(lat, lon, name)
    if not city:
        return {
            "parts": [],
            "skipped_reason": "not_indexed",
            "parent_admin_level": None,
            "child_admin_level": None,
        }
    level, districts = admin_areas.find_districts(city)
    return {
        "parts": [
            {
                "osm_id": d["osm_id"],
                "name": d["name"],
                "admin_level": d["admin_level"],
                "part_label": "District",
                "lat": d["lat"],
                "lon": d["lon"],
                "bbox": d["bbox"],
                "boundary": None,
            }
            for d in districts
        ],
        "skipped_reason": None if districts else "no_city_parts",
        "parent_admin_level": city["admin_level"],
        "child_admin_level": level,
        "parent_osm_id": city["osm_id"],
        "parent_name": city["name"],
    }
