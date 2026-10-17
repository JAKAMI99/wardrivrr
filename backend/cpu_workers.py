"""
CPU-scaled worker counts for map build + Valhalla.

Uses logical cores (os.cpu_count). Leaves headroom for PostGIS / API / OS,
and caps so tile builds don't OOM on RAM-heavy Valhalla workers.
"""

from __future__ import annotations

import os


def accessible_cores() -> int:
    """Logical processors visible to this process (respects cgroup limits in containers)."""
    return max(1, int(os.cpu_count() or 1))


def worker_count(
    *,
    reserve: int = 1,
    min_n: int = 2,
    max_n: int = 16,
) -> int:
    """
    Reasonable parallelism: use most cores, keep `reserve` free, clamp to [min_n, max_n].
    """
    cores = accessible_cores()
    use = cores - max(0, int(reserve))
    use = max(int(min_n), use)
    use = min(int(max_n), use)
    return max(1, use)


def map_build_workers() -> int:
    """Clip + segmentize for level road maps (CPU-bound, moderate RAM)."""
    return worker_count(reserve=1, min_n=2, max_n=16)


def valhalla_server_threads() -> int:
    """
    Valhalla tile build + HTTP workers (server_threads).
    Each build worker can hold a large tile cache — keep the cap lower than map build.
    """
    override = (os.getenv("VALHALLA_SERVER_THREADS") or "").strip()
    if override.isdigit() and int(override) > 0:
        return int(override)
    return worker_count(reserve=1, min_n=2, max_n=12)
