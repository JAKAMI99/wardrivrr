"""
Parked / idle motion filter for gpsd.

Treat the receiver as stationary unless it has moved about MIN_MOVE_M within
WINDOW_S. GPS jitter alone must not keep fog unlock / drive XP / Kismet ingest
active overnight.

Algorithm (anchor displacement):
  Keep a deque of raw (timestamp, lat, lon) fixes covering the last WINDOW_S.
  Anchor = oldest sample still in the window.
  Movement = max haversine distance from that anchor to any newer sample.
  stationary = True only when the window is full (span >= WINDOW_S) AND
  movement < MIN_MOVE_M. First boot therefore does not pause immediately.
  When movement >= MIN_MOVE_M, clear stationary immediately (resume work).

Net oldest→newest alone can under-detect a out-and-back wander; path length
over-counts GPS cloud noise. Max distance from the window's oldest fix is the
compromise used here.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from typing import Deque


WINDOW_S = float(os.getenv("GPSD_STATIONARY_WINDOW_S", "300"))
MIN_MOVE_M = float(os.getenv("GPSD_STATIONARY_MIN_MOVE_M", "100"))


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


ENABLED = _env_bool("GPSD_STATIONARY_PAUSE", True)


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


class StationaryTracker:
    """Per-user raw-fix window → stationary flag with enter/exit logging."""

    def __init__(
        self,
        *,
        window_s: float = WINDOW_S,
        min_move_m: float = MIN_MOVE_M,
        enabled: bool = ENABLED,
    ) -> None:
        self.window_s = max(1.0, float(window_s))
        self.min_move_m = max(0.0, float(min_move_m))
        self.enabled = bool(enabled)
        self._lock = threading.Lock()
        self._points: dict[int, Deque[tuple[float, float, float]]] = {}
        self._stationary: dict[int, bool] = {}
        self._logged: dict[int, bool] = {}

    def update(self, user_id: int, lat: float, lon: float, now: float | None = None) -> bool:
        """
        Ingest a raw receiver fix. Returns True when effectively stationary.

        When the filter is disabled, always returns False (never pause).
        """
        if not self.enabled:
            return False
        ts = float(now if now is not None else time.time())
        with self._lock:
            q = self._points.get(user_id)
            if q is None:
                q = deque()
                self._points[user_id] = q
            q.append((ts, float(lat), float(lon)))
            cutoff = ts - self.window_s
            while q and q[0][0] < cutoff:
                q.popleft()

            span = (q[-1][0] - q[0][0]) if len(q) >= 2 else 0.0
            movement = 0.0
            if q:
                a_lat, a_lon = q[0][1], q[0][2]
                for _, lat_i, lon_i in q:
                    d = _haversine_m(a_lat, a_lon, lat_i, lon_i)
                    if d > movement:
                        movement = d

            # Settle: do not pause until the window is full.
            stationary = span >= self.window_s and movement < self.min_move_m
            prev = self._logged.get(user_id)
            if prev is None or prev != stationary:
                self._logged[user_id] = stationary
                if stationary:
                    print(
                        f"[gpsd] stationary: moved {movement:.0f} m in "
                        f"{span:.0f} s window (< {self.min_move_m:.0f} m) — "
                        "pausing fog unlock / drive XP / Kismet ingest"
                    )
                elif prev is True:
                    print(
                        f"[gpsd] moving again: {movement:.0f} m in "
                        f"{span:.0f} s window — resuming unlock + ingest"
                    )
            self._stationary[user_id] = stationary
            return stationary

    def is_stationary(self, user_id: int) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            return bool(self._stationary.get(user_id))

    def clear(self, user_id: int) -> None:
        with self._lock:
            self._points.pop(user_id, None)
            self._stationary.pop(user_id, None)
            self._logged.pop(user_id, None)


# Shared tracker used by gpsd_poller (and readable for diagnostics).
tracker = StationaryTracker()
