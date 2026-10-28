"""Prepare regional map pack + city/district outline options for the levels wizard."""

from __future__ import annotations

from admin_areas import place_options_for_city, prepare_extract
from geofabrik import resolve_feature


def _city_short_name(osm_name: str | None, parent_label: str | None, fallback: str | None) -> str:
    if osm_name:
        return osm_name
    if parent_label:
        return parent_label.split(",")[0].strip()
    return fallback or "City"


def fixed_level_name(city_name: str, district_name: str | None = None) -> str:
    city = (city_name or "").strip()
    dist = (district_name or "").strip()
    if dist:
        return f"{city}, {dist}"
    return city


def prepare_place_options(
    *,
    lat: float,
    lon: float,
    name: str | None,
    geofabrik_id: str,
    population: int | None = None,
    bbox: list[float] | None = None,
    parent_label: str | None = None,
    country_code: str | None = None,
    geoname_id: int | None = None,
    user_id: int | None = None,
    progress_cb=None,
) -> dict:
    feat = resolve_feature(geofabrik_id)
    if not feat or not feat.get("pbf_url"):
        raise ValueError("Unknown map pack")

    prep = prepare_extract(
        feat["id"],
        pbf_url=feat["pbf_url"],
        progress_cb=progress_cb,
    )
    pack_levels_count = 0
    if user_id is not None:
        from levels import count_levels_for_extract

        pack_levels_count = count_levels_for_extract(user_id, feat["id"])
    opts = place_options_for_city(
        lat=lat,
        lon=lon,
        name=name,
        population=population,
        bbox=bbox,
    )
    city = opts.get("city")
    city_name = _city_short_name(
        city.get("name") if city else None,
        parent_label,
        name,
    )
    city_place = None
    if city:
        city_place = {
            "label": fixed_level_name(city_name),
            "display_name": f"Whole city · ~{city.get('area_km2') or '?'} km²",
            "lat": city["lat"],
            "lon": city["lon"],
            "bbox": city["bbox"],
            "boundary": city["boundary"],
            "boundary_approximate": False,
            "area_km2": city.get("area_km2"),
            "geoname_id": geoname_id,
            "name": city_name,
            "population": population,
            "place_type": "city",
            "place_kind": "city",
            "place_query": city_name,
            "country_code": country_code,
            # Do not set parent_label on the city itself — that made the UI treat
            # it like a sub-region in some older checks.
            "parent_label": None,
            "osm_relation_id": city["osm_id"],
            "osm_admin_level": city["admin_level"],
            "map_pack": prep["map_pack"],
            "source": "local_admin_index",
        }

    districts = []
    for d in opts.get("districts") or []:
        level_name = fixed_level_name(city_name, d["name"])
        has_boundary = bool(d.get("boundary") and d["boundary"].get("type"))
        districts.append(
            {
                "label": level_name,
                "display_name": f"Sub-region · {city_name}",
                "lat": d["lat"],
                "lon": d["lon"],
                "bbox": d["bbox"],
                "boundary": d.get("boundary"),
                "boundary_approximate": not has_boundary,
                "area_km2": d.get("area_km2"),
                "geoname_id": None,
                "name": d["name"],
                "population": None,
                "place_type": "district",
                "place_kind": "district",
                "place_query": level_name,
                "country_code": country_code,
                "part_label": "Sub-region",
                "parent_label": city_name,
                "parent_geoname_id": geoname_id,
                "osm_relation_id": d["osm_id"],
                "osm_admin_level": d["admin_level"],
                "map_pack": prep["map_pack"],
                "source": "osm_district",
            }
        )

    return {
        "city": city_place,
        "districts": districts,
        "skipped_reason": opts.get("skipped_reason"),
        "map_pack": prep["map_pack"],
        "downloaded": prep.get("downloaded"),
        "pbf_kept": True,
        "extract_id": prep.get("extract_id"),
        "pack_levels_count": pack_levels_count,
    }
