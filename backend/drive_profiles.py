"""
Drive / exploration profiles (Navigate-time).

Levels import the union of all playable highways once. Mode (big_car / small_car /
bicycle / foot) filters fog candidates, progress display, Valhalla costing, and
dead-end policy while routing — never a second map for the same place.

Presets:
  big_car   — "Car B-road+" arterials & collectors; few turns; skip cul-de-sacs
  small_car — "Car" full street grid; cul-de-sacs only if ≥ 100 m; no driveways
  bicycle   — bike-friendly net; every dead end
  foot      — paths, tracks, gravel/mud-friendly; every dead end

Legacy DB value `car` aliases to `small_car`.
`levels.profile` stores last-used Navigate mode only.
"""

from __future__ import annotations

from typing import Any

# 90% explored → level / district counts as complete in the menu
COMPLETE_PCT = 90.0

PROFILE_ALIASES = {
    "car": "small_car",
}

# OSM highway=* allowed into road_segments per profile
PROFILE_HIGHWAYS: dict[str, set[str]] = {
    "big_car": {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        # Village / through-town connectors (OSM "medium" roads without a class)
        "unclassified",
    },
    "small_car": {
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary",
        "primary_link",
        "secondary",
        "secondary_link",
        "tertiary",
        "tertiary_link",
        "unclassified",
        "residential",
        "living_street",
        "service",
    },
    "bicycle": {
        "cycleway",
        "path",
        "living_street",
        "residential",
        "service",
        "unclassified",
        "tertiary",
        "tertiary_link",
        "secondary",
        "secondary_link",
        "primary",
        "primary_link",
        "track",
        "bridleway",
        "footway",
    },
    "foot": {
        "footway",
        "path",
        "pedestrian",
        "steps",
        "living_street",
        "residential",
        "service",
        "unclassified",
        "tertiary",
        "secondary",
        "primary",
        "track",
        "bridleway",
        "cycleway",
    },
}

# service=* values that mean parking / private access — never enter the playable net
PARKING_SERVICE_TAGS = frozenset(
    {
        "parking_aisle",
        "parking",
        "drive-through",
        "drive_through",
        "driveway",
    }
)

PROFILE_META: dict[str, dict[str, Any]] = {
    "big_car": {
        "label": "Car B-road+",
        "blurb": "Main and medium roads. Skips cul-de-sacs and driveways.",
        "costing": "auto",
        "dead_end_min_m": 70.0,
        "exclude_all_dead_ends": True,
        "costing_options": {
            "maneuver_penalty": 28.0,
            "alley_factor": 2.5,
            "use_highways": 1.0,
            "use_living_streets": 0.05,
            "service_factor": 10.0,
            "exclude_driveways": True,
        },
    },
    "small_car": {
        "label": "Car",
        "blurb": "Full street grid. Dead ends ≥ 100 m. No driveways.",
        "costing": "auto",
        "dead_end_min_m": 100.0,
        "exclude_all_dead_ends": False,
        "costing_options": {
            "maneuver_penalty": 5.0,
            "use_living_streets": 0.5,
            "exclude_driveways": True,
        },
    },
    "bicycle": {
        "label": "Bike",
        "blurb": "Cycleways and streets. Includes dead ends.",
        "costing": "bicycle",
        "dead_end_min_m": 0.0,
        "exclude_all_dead_ends": False,
        "costing_options": {
            "use_roads": 0.5,
            "use_living_streets": 0.7,
        },
    },
    "foot": {
        "label": "On foot",
        "blurb": "Paths and tracks. Includes dead ends.",
        "costing": "pedestrian",
        "dead_end_min_m": 0.0,
        "exclude_all_dead_ends": False,
        "costing_options": {
            "walkway_factor": 1.0,
            "use_tracks": 1.0,
            "use_hills": 0.5,
        },
    },
}

VALID_PROFILES = frozenset(PROFILE_HIGHWAYS.keys()) | frozenset(PROFILE_ALIASES.keys())


def normalize_profile(profile: str | None) -> str:
    p = (profile or "small_car").strip().lower()
    p = PROFILE_ALIASES.get(p, p)
    if p not in PROFILE_HIGHWAYS:
        return "small_car"
    return p


def profile_highways(profile: str | None) -> set[str]:
    return set(PROFILE_HIGHWAYS[normalize_profile(profile)])


def all_playable_highways() -> set[str]:
    """Union of every profile's highways — what a level imports once."""
    out: set[str] = set()
    for hw in PROFILE_HIGHWAYS.values():
        out |= set(hw)
    return out


def profile_meta(profile: str | None) -> dict[str, Any]:
    return dict(PROFILE_META[normalize_profile(profile)])


def profile_label(profile: str | None) -> str:
    return str(profile_meta(profile).get("label") or normalize_profile(profile))


def is_parking_way(tags: dict[str, str] | None) -> bool:
    """True if this OSM way is a parking lot aisle / parking service road."""
    if not tags:
        return False
    svc = (tags.get("service") or "").strip().lower()
    if svc in PARKING_SERVICE_TAGS:
        return True
    if (tags.get("amenity") or "").strip().lower() == "parking":
        return True
    # Explicit parking highway (rare) or area=yes service stubs
    hw = (tags.get("highway") or "").strip().lower()
    if hw in {"parking", "parking_aisle"}:
        return True
    return False


def is_complete(explored_pct: float | None, *, threshold: float = COMPLETE_PCT) -> bool:
    try:
        return float(explored_pct or 0) >= float(threshold)
    except (TypeError, ValueError):
        return False


def profile_uses_road_snap(profile: str | None) -> bool:
    """Cars snap GPS onto road_segments; foot/bike keep raw GPS and unlock by radius."""
    return normalize_profile(profile) in {"big_car", "small_car"}


def routing_policy(
    profile: str | None,
    *,
    exclude_dead_ends: bool | None = None,
) -> dict[str, Any]:
    """
    Dead-end + costing policy for explore routes.
    If exclude_dead_ends is not None, it overrides the profile default for
    exclude_all (optional legacy client override).
    """
    meta = profile_meta(profile)
    exclude_all = bool(meta["exclude_all_dead_ends"])
    if exclude_dead_ends is not None:
        exclude_all = bool(exclude_dead_ends)
    return {
        "profile": normalize_profile(profile),
        "label": meta["label"],
        "costing": meta["costing"],
        "costing_options": dict(meta.get("costing_options") or {}),
        "dead_end_min_m": float(meta["dead_end_min_m"]),
        "exclude_all_dead_ends": exclude_all,
    }
