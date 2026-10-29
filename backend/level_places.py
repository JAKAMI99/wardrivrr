from __future__ import annotations

from cities_db import db_available, search_cities
from city_boundaries import city_may_have_parts
from geofabrik import resolve_place_extract


def _map_pack_for(hit: dict) -> dict | None:
    extract = resolve_place_extract(
        hit["lat"],
        hit["lon"],
        place_bbox=hit["bbox"],
        country_code=hit.get("country_code"),
        country_name=hit.get("country"),
        place_name=hit.get("name"),
    )
    if not extract or not extract.get("pbf_url"):
        return None
    return {
        "id": extract["id"],
        "name": extract.get("name"),
        "pbf_url": extract["pbf_url"],
        "size_bytes": extract.get("size_bytes"),
        "blurb": "regional OpenStreetMap road data",
    }


def search_level_places(query: str, limit: int = 8) -> list[dict]:
    """
    Place-first search using the **local** cities database (no Nominatim).

    Large cities may advertise `may_have_parts`; the wizard then loads OSM
    districts (next admin level) under the city result.
    """
    if not db_available():
        raise FileNotFoundError(
            "Local cities database missing. Run: python scripts/build_cities_db.py"
        )

    hits = search_cities(query, limit=limit, min_population=5_000)
    out = []
    for h in hits:
        pack = _map_pack_for(h)
        if not pack:
            continue
        may_parts = city_may_have_parts(
            population=h.get("population"),
            bbox=h.get("bbox"),
        )
        out.append(
            {
                "label": h["label"],
                "display_name": h["display_name"],
                "lat": h["lat"],
                "lon": h["lon"],
                "bbox": h["bbox"],
                # Exact admin polygon loaded on select via /api/levels/places/boundary
                "boundary": None,
                "boundary_approximate": True,
                "geoname_id": h.get("geoname_id"),
                "name": h.get("name"),
                "population": h["population"],
                "place_type": "city",
                "place_query": h["place_query"],
                "country_code": h["country_code"],
                "may_have_parts": may_parts,
                "map_pack": pack,
                "source": "local_cities_db",
            }
        )
    return out


def city_parts_as_places(
    *,
    lat: float,
    lon: float,
    name: str | None,
    country_code: str | None,
    geoname_id: int | None,
    population: int | None,
    parent_label: str | None,
    map_pack: dict | None,
    bbox: list[float] | None = None,
) -> dict:
    """Resolve OSM districts (names/centroids) as selectable predownloadable levels."""
    from city_boundaries import resolve_city_parts

    raw = resolve_city_parts(
        lat=lat,
        lon=lon,
        name=name,
        country_code=country_code,
        geoname_id=geoname_id,
        population=population,
        bbox=bbox,
        geofabrik_id=(map_pack or {}).get("id"),
    )
    parent = parent_label or name or "City"
    parts_out = []
    for p in raw.get("parts") or []:
        pack = map_pack
        if not pack:
            pack = _map_pack_for(
                {
                    "lat": p["lat"],
                    "lon": p["lon"],
                    "bbox": p["bbox"],
                    "country_code": country_code,
                    "country": None,
                    "name": p["name"],
                }
            )
        if not pack:
            continue
        parts_out.append(
            {
                "label": p["name"],
                "display_name": f"District · {parent}",
                "lat": p["lat"],
                "lon": p["lon"],
                "bbox": p["bbox"],
                "boundary": None,
                "boundary_approximate": True,
                "geoname_id": None,
                "name": p["name"],
                "population": None,
                "place_type": "district",
                "place_query": f"{p['name']}, {parent}",
                "country_code": country_code,
                "part_label": "District",
                "parent_label": parent,
                "parent_geoname_id": geoname_id,
                "osm_relation_id": p.get("osm_id"),
                "osm_admin_level": p.get("admin_level"),
                "may_have_parts": False,
                "map_pack": pack,
                "source": "osm_district",
            }
        )
    return {
        "parts": parts_out,
        "skipped_reason": raw.get("skipped_reason"),
        "parent_admin_level": raw.get("parent_admin_level"),
        "child_admin_level": raw.get("child_admin_level"),
    }
