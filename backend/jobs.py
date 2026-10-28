from __future__ import annotations

import json
import threading
import traceback
from typing import Any

from db import connect, connect_dict
from localize import recompute_networks

_worker_started = False
_lock = threading.Lock()

# Map / region work must never sit behind long background fills.
_INTERACTIVE_JOB_TYPES = frozenset({"prepare_place", "geofabrik_level"})
_BACKGROUND_JOB_TYPES = frozenset({"geocode", "level_addresses", "localize"})


class JobPreempted(Exception):
    """Background job yielded so an interactive map job can run."""


def reclaim_orphaned_running_jobs() -> int:
    """
    Single in-process worker: anything still 'running' at startup is orphaned
    (API restart / crash). Requeue so interactive work is not permanently stuck
    behind a zombie row.
    """
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE jobs
                SET status = 'queued',
                    started_at = NULL,
                    progress = 0,
                    error = COALESCE(
                      NULLIF(error, ''),
                      'Requeued after worker restart (previous run was interrupted)'
                    )
                WHERE status = 'running'
                """
            )
            n = cur.rowcount
        conn.commit()
        if n:
            print(f"[jobs] reclaimed {n} orphaned running job(s)")
        return int(n or 0)
    finally:
        conn.close()


def _interactive_jobs_waiting() -> bool:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM jobs
                WHERE status = 'queued'
                  AND job_type = ANY(%s)
                LIMIT 1
                """,
                (list(_INTERACTIVE_JOB_TYPES),),
            )
            return cur.fetchone() is not None
    finally:
        conn.close()


def enqueue_job(user_id: int | None, job_type: str, payload: dict | None = None) -> dict:
    conn = connect_dict()
    try:
        payload = payload or {}
        # Coalesce duplicate queued geocode jobs for the same user
        if job_type == "geocode" and user_id is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, job_type, payload, status, progress, created_at
                    FROM jobs
                    WHERE user_id = %s AND job_type = 'geocode' AND status = 'queued'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (user_id,),
                )
                existing = cur.fetchone()
            if existing:
                # Broaden queued job so later imports aren't skipped
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE jobs SET payload = %s::jsonb
                        WHERE id = %s
                        """,
                        (
                            json.dumps(
                                {"only_missing": False, "priority": 50}
                            ),
                            existing["id"],
                        ),
                    )
                conn.commit()
                ensure_worker()
                return existing
        # Coalesce duplicate address fills for the same level
        if job_type == "level_addresses" and payload.get("level_id") is not None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, job_type, payload, status, progress, created_at
                    FROM jobs
                    WHERE job_type = 'level_addresses'
                      AND status IN ('queued', 'running')
                      AND (payload->>'level_id')::int = %s
                    ORDER BY id DESC LIMIT 1
                    """,
                    (int(payload["level_id"]),),
                )
                existing = cur.fetchone()
            if existing:
                ensure_worker()
                return existing
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO jobs (user_id, job_type, payload, status)
                VALUES (%s, %s, %s::jsonb, 'queued')
                RETURNING id, user_id, job_type, payload, status, progress, created_at
                """,
                (user_id, job_type, json.dumps(payload)),
            )
            job = cur.fetchone()
        conn.commit()
        ensure_worker()
        return job
    finally:
        conn.close()


def get_job(job_id: int, user_id: int | None = None) -> dict | None:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            if user_id is None:
                cur.execute("SELECT * FROM jobs WHERE id = %s", (job_id,))
            else:
                cur.execute(
                    "SELECT * FROM jobs WHERE id = %s AND user_id = %s",
                    (job_id, user_id),
                )
            job = cur.fetchone()
            if not job:
                return None
            # For interactive map jobs, only count other interactive work ahead —
            # background geocode/address fills preempt and should not look like a queue.
            if job.get("status") == "queued":
                if job.get("job_type") in _INTERACTIVE_JOB_TYPES:
                    cur.execute(
                        """
                        SELECT COUNT(*)::int AS n FROM jobs
                        WHERE id <> %s
                          AND job_type = ANY(%s)
                          AND (
                            status = 'running'
                            OR (status = 'queued' AND id < %s)
                          )
                        """,
                        (job_id, list(_INTERACTIVE_JOB_TYPES), job_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT COUNT(*)::int AS n FROM jobs
                        WHERE id <> %s
                          AND (
                            status = 'running'
                            OR (status = 'queued' AND id < %s)
                          )
                        """,
                        (job_id, job_id),
                    )
                row = cur.fetchone() or {}
                job["queue_ahead"] = int(row.get("n") or 0)
                # Make sure the worker is alive so a lone job does not sit forever
                ensure_worker()
            else:
                job["queue_ahead"] = 0
            return job
    finally:
        conn.close()


def list_jobs(user_id: int, limit: int = 20) -> list[dict]:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, job_type, status, progress, error, created_at, started_at, finished_at, result
                FROM jobs WHERE user_id = %s
                ORDER BY id DESC LIMIT %s
                """,
                (user_id, limit),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _set_job(job_id: int, **fields: Any) -> None:
    cols = []
    vals = []
    for k, v in fields.items():
        if k == "result" and not isinstance(v, str):
            cols.append(f"{k} = %s::jsonb")
            vals.append(json.dumps(v))
        else:
            cols.append(f"{k} = %s")
            vals.append(v)
    vals.append(job_id)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = %s", vals)
        conn.commit()
    finally:
        conn.close()


def _run_localize(job: dict) -> dict:
    payload = job.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    mode = payload.get("mode", "2d")
    precision = payload.get("precision", "balanced")
    user_id = job["user_id"]
    # Positions only — enqueue address fill afterwards
    updated = recompute_networks(
        None, mode=mode, user_id=user_id, precision=precision, geocode=False
    )
    enqueue_job(
        user_id,
        "geocode",
        {"only_missing": False, "priority": 50},
    )
    return {"updated": updated, "mode": mode, "precision": precision}


def _run_geocode(job: dict) -> dict:
    from geocode_worker import geocode_networks

    payload = job.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    job_id = job["id"]
    if _interactive_jobs_waiting():
        raise JobPreempted("map job waiting — geocode will resume after")

    def progress_cb(frac, done, total):
        # Yield to region prepare / map build — do not block the Regions wizard.
        if _interactive_jobs_waiting():
            raise JobPreempted("map job waiting — geocode will resume after")
        _set_job(
            job_id,
            progress=min(0.99, float(frac)),
            result={"done": done, "total": total, "stage": "geocode"},
        )

    return geocode_networks(
        user_id=job.get("user_id"),
        network_ids=payload.get("network_ids"),
        only_missing=bool(payload.get("only_missing", True)),
        progress_cb=progress_cb,
    )


def _run_geofabrik_level(job: dict) -> dict:
    from levels import process_level_job

    payload = job.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    job_id = job["id"]

    def progress_cb(progress, stage, message, eta_seconds):
        _set_job(
            job_id,
            progress=float(progress),
            result={
                "stage": stage,
                "message": message,
                "eta_seconds": eta_seconds,
                "level_id": payload.get("level_id"),
            },
        )

    return process_level_job(
        job["user_id"], int(payload["level_id"]), progress_cb=progress_cb
    )


def _run_level_addresses(job: dict) -> dict:
    from levels import build_level_addresses_job

    payload = job.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    job_id = job["id"]
    if _interactive_jobs_waiting():
        raise JobPreempted("map job waiting — address fill will resume after")

    def progress_cb(progress, stage, message, eta_seconds):
        if _interactive_jobs_waiting():
            raise JobPreempted("map job waiting — address fill will resume after")
        _set_job(
            job_id,
            progress=float(progress),
            result={
                "stage": stage,
                "message": message,
                "eta_seconds": eta_seconds,
                "level_id": payload.get("level_id"),
            },
        )

    return build_level_addresses_job(
        job["user_id"],
        int(payload["level_id"]),
        pbf=payload.get("pbf"),
        bbox=payload.get("bbox"),
        progress_cb=progress_cb,
    )


def _run_prepare_place(job: dict) -> dict:
    from place_prepare import prepare_place_options

    payload = job.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)
    job_id = job["id"]

    def progress_cb(progress, stage, message, eta_seconds):
        _set_job(
            job_id,
            progress=float(progress),
            result={
                "stage": stage,
                "message": message,
                "eta_seconds": eta_seconds,
            },
        )

    return prepare_place_options(
        lat=float(payload["lat"]),
        lon=float(payload["lon"]),
        name=payload.get("name"),
        geofabrik_id=payload["geofabrik_id"],
        population=payload.get("population"),
        bbox=payload.get("bbox"),
        parent_label=payload.get("parent_label"),
        country_code=payload.get("country_code"),
        geoname_id=payload.get("geoname_id"),
        user_id=job.get("user_id"),
        progress_cb=progress_cb,
    )


def process_one_job() -> bool:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            # Interactive map jobs first. Never start background fills while a
            # prepare_place / geofabrik_level is waiting in queue.
            cur.execute(
                """
                SELECT id, user_id, job_type, payload, status
                FROM jobs
                WHERE status = 'queued'
                  AND NOT (
                    job_type = ANY(%s)
                    AND EXISTS (
                      SELECT 1 FROM jobs j2
                      WHERE j2.status = 'queued'
                        AND j2.job_type = ANY(%s)
                    )
                  )
                ORDER BY
                  CASE job_type
                    WHEN 'prepare_place' THEN 0
                    WHEN 'geofabrik_level' THEN 0
                    WHEN 'localize' THEN 1
                    WHEN 'level_addresses' THEN 50
                    WHEN 'geocode' THEN 80
                    ELSE 40
                  END,
                  COALESCE((payload->>'priority')::int, 50),
                  id ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (list(_BACKGROUND_JOB_TYPES), list(_INTERACTIVE_JOB_TYPES)),
            )
            job = cur.fetchone()
            if not job:
                conn.commit()
                return False
            cur.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    started_at = NOW(),
                    progress = 0.05,
                    error = NULL
                WHERE id = %s
                """,
                (job["id"],),
            )
        conn.commit()
    finally:
        conn.close()

    try:
        if job["job_type"] == "localize":
            result = _run_localize(job)
        elif job["job_type"] == "geocode":
            result = _run_geocode(job)
        elif job["job_type"] == "geofabrik_level":
            _set_job(job["id"], progress=0.2)
            result = _run_geofabrik_level(job)
        elif job["job_type"] == "level_addresses":
            _set_job(job["id"], progress=0.05)
            result = _run_level_addresses(job)
        elif job["job_type"] == "prepare_place":
            _set_job(job["id"], progress=0.05)
            result = _run_prepare_place(job)
        else:
            raise ValueError(f"Unknown job type: {job['job_type']}")
        _set_job(job["id"], status="done", progress=1.0, result=result, error=None)
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET finished_at = NOW() WHERE id = %s",
                    (job["id"],),
                )
            conn.commit()
        finally:
            conn.close()
    except JobPreempted as exc:
        # Put background work back in queue so map prepare can run now.
        _set_job(
            job["id"],
            status="queued",
            progress=0,
            error=str(exc),
        )
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET started_at = NULL, finished_at = NULL WHERE id = %s",
                    (job["id"],),
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        _set_job(
            job["id"],
            status="error",
            error=f"{exc}\n{traceback.format_exc()[:2000]}",
        )
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE jobs SET finished_at = NOW() WHERE id = %s",
                    (job["id"],),
                )
            conn.commit()
        finally:
            conn.close()
    return True


def _maybe_enqueue_nightly() -> None:
    """Once per local calendar day, queue localize for users with nightly enabled."""
    from datetime import date

    from db import get_user_setting, set_user_setting

    today = date.today().isoformat()
    try:
        conn = connect_dict()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users")
                user_ids = [row["id"] for row in cur.fetchall()]
        finally:
            conn.close()
        for uid in user_ids:
            if (get_user_setting(uid, "localize_nightly", "false") or "false").lower() != "true":
                continue
            if get_user_setting(uid, "localize_nightly_last", "") == today:
                continue
            conn = connect_dict()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id FROM jobs
                        WHERE user_id = %s AND job_type = 'localize'
                          AND status IN ('queued', 'running')
                        LIMIT 1
                        """,
                        (uid,),
                    )
                    busy = cur.fetchone()
            finally:
                conn.close()
            if busy:
                continue
            precision = get_user_setting(uid, "default_localize_precision", "balanced") or "balanced"
            mode = get_user_setting(uid, "default_localization_mode", "2d") or "2d"
            set_user_setting(uid, "localize_nightly_last", today)
            enqueue_job(uid, "localize", {"mode": mode, "precision": precision})
    except Exception:
        pass


def _worker_loop() -> None:
    import time

    ticks = 0
    while True:
        try:
            ran = process_one_job()
            ticks += 1
            if ticks % 30 == 0:
                _maybe_enqueue_nightly()
            if not ran:
                time.sleep(2)
        except Exception:
            time.sleep(5)


def ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        try:
            reclaim_orphaned_running_jobs()
        except Exception as exc:
            print(f"[jobs] reclaim failed: {exc}")
        # Register ProcessPool atexit on this (startup) thread before workers import it.
        try:
            import concurrent.futures.process  # noqa: F401
        except Exception as exc:
            print(f"[jobs] process pool warmup: {exc}")
        # Non-daemon so level builds can use ProcessPoolExecutor (multi-core clip/segmentize)
        t = threading.Thread(target=_worker_loop, name="wardrivrr-jobs", daemon=False)
        t.start()
        _worker_started = True
