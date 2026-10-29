"""Live / replay ingest: samples → networks (positions) → optional geocode job.

Used by Kismet live (always-on), tools/drive_sim, and uploads so the Database
map and XP counters stay in sync without the Drive UI being open.
"""

from __future__ import annotations

from typing import Any, Iterable

from db import insert_observations
from localize import recompute_networks


def _credit_find_progress(user_id: int, *, networks_touched: int) -> list[dict[str, Any]]:
    """Unlock achievements when live finds land — not gated on Drive."""
    if networks_touched <= 0:
        return []
    try:
        from achievements import maybe_evaluate_achievements

        return maybe_evaluate_achievements(user_id) or []
    except Exception:
        return []


def ingest_observation_batch(
    user_id: int,
    rows: list[tuple],
    *,
    localize: bool = True,
    enqueue_geocode: bool = False,
) -> dict[str, Any]:
    """
    Insert raw samples, then 2D-localize those networks (no reverse-geocode).

    Addresses are filled later by the geocode worker once address packs / postal
    data are available. Network XP is lifetime-count based; we still evaluate
    achievements here so badges unlock while collecting without Drive open.
    """
    if not rows:
        return {
            "samples": 0,
            "networks_updated": 0,
            "geocode_job_id": None,
            "newly_unlocked": [],
        }

    n = insert_observations(rows, user_id=user_id)
    network_ids = list({r[1] for r in rows if len(r) > 1 and r[1]})
    updated = 0
    if localize and network_ids:
        updated = recompute_networks(
            network_ids,
            mode="2d",
            user_id=user_id,
            precision="balanced",
            geocode=False,
        )

    geocode_job_id = None
    if enqueue_geocode and network_ids:
        try:
            from jobs import enqueue_job

            job = enqueue_job(
                user_id,
                "geocode",
                {"network_ids": network_ids, "only_missing": True, "priority": 50},
            )
            geocode_job_id = job.get("id")
        except Exception:
            geocode_job_id = None

    newly = _credit_find_progress(user_id, networks_touched=len(network_ids))

    return {
        "samples": n,
        "networks_updated": updated,
        "network_ids": network_ids,
        "geocode_job_id": geocode_job_id,
        "newly_unlocked": newly,
    }


def flush_pending_ids(
    user_id: int,
    network_ids: Iterable[str],
    *,
    enqueue_geocode: bool = True,
) -> dict[str, Any]:
    """Localize a set of ids collected over several batches."""
    ids = list({n for n in network_ids if n})
    if not ids:
        return {"networks_updated": 0, "geocode_job_id": None, "newly_unlocked": []}
    updated = recompute_networks(
        ids,
        mode="2d",
        user_id=user_id,
        precision="balanced",
        geocode=False,
    )
    geocode_job_id = None
    if enqueue_geocode:
        try:
            from jobs import enqueue_job

            job = enqueue_job(
                user_id,
                "geocode",
                {"network_ids": ids, "only_missing": True, "priority": 50},
            )
            geocode_job_id = job.get("id")
        except Exception:
            pass
    newly = _credit_find_progress(user_id, networks_touched=len(ids))
    return {
        "networks_updated": updated,
        "geocode_job_id": geocode_job_id,
        "newly_unlocked": newly,
    }
