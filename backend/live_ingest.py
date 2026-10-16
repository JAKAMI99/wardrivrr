"""Live / replay ingest: samples → networks (positions) → optional geocode job.

Used by tools/drive_sim and future background Kismet feeds so the Database
map and Drive “new” counters stay in sync without blocking on addresses.
"""

from __future__ import annotations

from typing import Any, Iterable

from db import insert_observations
from localize import recompute_networks


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
    data are available.
    """
    if not rows:
        return {"samples": 0, "networks_updated": 0, "geocode_job_id": None}

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

    return {
        "samples": n,
        "networks_updated": updated,
        "network_ids": network_ids,
        "geocode_job_id": geocode_job_id,
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
        return {"networks_updated": 0, "geocode_job_id": None}
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
    return {"networks_updated": updated, "geocode_job_id": geocode_job_id}
