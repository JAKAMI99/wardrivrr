#!/usr/bin/env python3
"""
Replay a Kismet recording into wardrivrr as live GPS + live samples.

Pass any .kismet with --db / -d / --recording / -r, or as a positional path.
If omitted, uses tools/drive_sim/recording.kismet when present.

Default speed: 4× wall-clock. Change with --speed / -x.

Examples:
  python tools/drive_sim/replay.py --db path\\to\\drive.kismet
  python tools/drive_sim/replay.py -d data\\incoming\\Kismet_Out\\foo.kismet -x 8
  python tools/drive_sim/replay.py path\\to\\drive.kismet --speed 16
  python tools/drive_sim/replay.py --speed 2 --start 30m --duration 10m
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

HERE = Path(__file__).resolve().parent
DEFAULT_RECORDING = HERE / "recording.kismet"


def _track_cache_path(db_path: Path) -> Path:
    """Per-file cache so switching --db does not reuse another track."""
    stem = db_path.resolve().name.replace(".", "_")
    return HERE / f"track_cache_{stem}.json"


def _parse_duration(text: str | None) -> float | None:
    """Parse 90, 90s, 2m, 1.5h into seconds."""
    if text is None or text == "":
        return None
    s = str(text).strip().lower()
    mult = 1.0
    if s.endswith("h"):
        mult = 3600.0
        s = s[:-1]
    elif s.endswith("m"):
        mult = 60.0
        s = s[:-1]
    elif s.endswith("s"):
        s = s[:-1]
    return float(s) * mult


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _mac(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (bytes, memoryview)):
        b = bytes(value)
        if len(b) == 6:
            return ":".join(f"{x:02x}" for x in b)
        try:
            value = b.decode("utf-8", errors="ignore")
        except Exception:
            return None
    text = str(value).strip().lower().replace("-", ":")
    return text or None


def _phy_type(phy: str | None) -> str:
    blob = (phy or "").lower()
    if "ble" in blob or "btle" in blob:
        return "BLE"
    if "bluetooth" in blob or blob.strip() in {"bt", "br/edr"}:
        return "BT"
    return "WIFI"


def build_track(db_path: Path, force: bool = False) -> list[dict]:
    """One GPS point per second from packets (cached next to the tool)."""
    cache_path = _track_cache_path(db_path)
    sig = f"{db_path.resolve()}|{db_path.stat().st_size}|{int(db_path.stat().st_mtime)}"
    if cache_path.exists() and not force:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("sig") == sig and cached.get("points"):
                print(f"[cache] {len(cached['points'])} GPS points from {cache_path.name}")
                return cached["points"]
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    print(f"[build] scanning GPS track in {db_path.name} …")
    t0 = time.time()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    points: list[dict] = []
    try:
        sql = """
            SELECT ts_sec,
                   AVG(lat) AS lat,
                   AVG(lon) AS lon,
                   AVG(CASE WHEN speed IS NOT NULL AND speed > 0 THEN speed END) AS speed,
                   AVG(CASE WHEN heading IS NOT NULL THEN heading END) AS heading
            FROM packets
            WHERE lat IS NOT NULL AND lon IS NOT NULL
              AND lat != 0 AND lon != 0
            GROUP BY ts_sec
            ORDER BY ts_sec
        """
        for ts, lat, lon, speed, heading in conn.execute(sql):
            points.append(
                {
                    "ts": int(ts),
                    "lat": float(lat),
                    "lon": float(lon),
                    "speed": float(speed) if speed is not None else None,
                    "heading": float(heading) if heading is not None else None,
                }
            )
    finally:
        conn.close()

    # Fill missing heading/speed from consecutive points
    for i, p in enumerate(points):
        if i + 1 < len(points):
            nxt = points[i + 1]
            if p.get("heading") is None:
                p["heading"] = _bearing(p["lat"], p["lon"], nxt["lat"], nxt["lon"])
            if p.get("speed") is None:
                dt = max(1, nxt["ts"] - p["ts"])
                p["speed"] = _haversine_m(p["lat"], p["lon"], nxt["lat"], nxt["lon"]) / dt
        elif i > 0:
            prev = points[i - 1]
            p["heading"] = prev.get("heading") or 0.0
            p["speed"] = prev.get("speed") or 0.0

    cache_path.write_text(
        json.dumps({"sig": sig, "points": points}, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"[build] {len(points)} points in {time.time() - t0:.1f}s → {cache_path.name}")
    return points


def samples_between(db_path: Path, t0: int, t1: int) -> list[tuple]:
    """Packet samples in (t0, t1] with wall-clock seen_at filled later."""
    from wigle import observation_tuple  # noqa: WPS433

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows_out: list[tuple] = []
    try:
        sql = """
            SELECT sourcemac, lat, lon, alt, signal, phyname, ts_sec
            FROM packets
            WHERE ts_sec > ? AND ts_sec <= ?
              AND lat IS NOT NULL AND lon IS NOT NULL
              AND lat != 0 AND lon != 0
              AND sourcemac IS NOT NULL AND sourcemac != ''
        """
        source = f"drive_sim:{db_path.name}"
        for row in conn.execute(sql, (t0, t1)):
            mac = _mac(row["sourcemac"])
            if not mac:
                continue
            rec = {
                "network_id": mac,
                "name": None,
                "encryption": None,
                "network_type": _phy_type(row["phyname"]),
                "channel": None,
                "signal": row["signal"] if row["signal"] not in (0, "0", None) else None,
                "lat": row["lat"],
                "lon": row["lon"],
                "altitude": row["alt"],
                "seen_at": datetime.now(timezone.utc),  # overwritten by caller if needed
                "accuracy": 12.0,
            }
            tup = observation_tuple(rec, source, source_format="kismet")
            if tup:
                rows_out.append(tup)
    finally:
        conn.close()
    return rows_out


class ApiClient:
    def __init__(self, base: str, token: str):
        self.base = base.rstrip("/")
        self.token = token

    def post_json(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base + path,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc

    @classmethod
    def login(cls, base: str, user: str, password: str) -> "ApiClient":
        data = json.dumps(
            {"username": user, "password": password, "keep_logged_in": True}
        ).encode("utf-8")
        req = urllib.request.Request(
            base.rstrip("/") + "/api/auth/login",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("Login failed — no access_token")
        return cls(base, token)


def stamp_seen_at(rows: list[tuple], when: datetime) -> list[tuple]:
    """observation_tuple: index 3 is seen_at."""
    out = []
    for row in rows:
        lst = list(row)
        lst[3] = when
        out.append(tuple(lst))
    return out


def resolve_db_path(args: argparse.Namespace) -> Path | None:
    """Prefer explicit --db / positional; else default recording.kismet if present."""
    raw = args.db or args.recording_positional
    if raw is not None:
        return Path(raw).expanduser().resolve()
    if DEFAULT_RECORDING.exists():
        return DEFAULT_RECORDING.resolve()
    return None


def run(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args)
    if db_path is None:
        print(
            "No Kismet database specified.\n"
            "  Use:  --db path\\to\\file.kismet\n"
            "  Or:   python tools\\drive_sim\\replay.py path\\to\\file.kismet\n"
            f"  Or put a default at {DEFAULT_RECORDING}",
            file=sys.stderr,
        )
        return 1
    if not db_path.exists():
        print(f"Missing Kismet database: {db_path}", file=sys.stderr)
        return 1
    if not db_path.is_file():
        print(f"Not a file: {db_path}", file=sys.stderr)
        return 1
    print(f"[db] {db_path}")

    speed = float(args.speed)
    if speed <= 0:
        print("--speed must be > 0", file=sys.stderr)
        return 1

    points = build_track(db_path, force=args.rebuild_cache)
    if len(points) < 2:
        print("No GPS points in recording.", file=sys.stderr)
        return 1

    rec_start = points[0]["ts"]
    rec_end = points[-1]["ts"]
    skip = _parse_duration(args.start) or 0.0
    dur = _parse_duration(args.duration)
    play_start = rec_start + int(skip)
    play_end = rec_end if dur is None else min(rec_end, play_start + int(dur))

    # Index by recording second for O(1) lookup
    by_ts = {p["ts"]: p for p in points}
    timeline = [p for p in points if play_start <= p["ts"] <= play_end]
    if not timeline:
        print("No GPS points in the selected window.", file=sys.stderr)
        return 1

    wall_rec = play_end - play_start
    wall_eta = wall_rec / speed
    print(
        f"[replay] {db_path.name} · {len(timeline)} fixes · "
        f"record {wall_rec/60:.1f} min → wall {wall_eta/60:.1f} min @ {speed:g}×"
    )
    print(f"[replay] open Navigate → enable “Follow live GPS” → watch the drive")
    print(f"[replay] API {args.base}")

    client = ApiClient.login(args.base, args.user, args.password)
    session_started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Import DB helpers only after login (needs .env / PostGIS)
    from auth import get_user_by_username  # noqa: WPS433
    from live_ingest import ingest_observation_batch  # noqa: WPS433

    user_row = get_user_by_username(args.user)
    if not user_row:
        print(f"User {args.user!r} not found in DB", file=sys.stderr)
        return 1
    user_id = int(user_row["id"])
    print(f"[session] {session_started} — enable Follow live GPS before/during this run")

    wall0 = time.monotonic()
    last_rec_ts = play_start - 1
    samples_total = 0
    networks_total = 0
    last_geocode_flush = wall0
    i = 0

    try:
        while True:
            elapsed_wall = time.monotonic() - wall0
            rec_now = play_start + int(elapsed_wall * speed)
            if rec_now > play_end:
                break

            # Advance GPS to the latest point at or before rec_now
            while i + 1 < len(timeline) and timeline[i + 1]["ts"] <= rec_now:
                i += 1
            pt = timeline[i]

            # Ingest packets → signal_samples + networks (map positions, no addresses yet)
            if rec_now > last_rec_ts:
                batch = samples_between(db_path, last_rec_ts, rec_now)
                if batch:
                    when = datetime.now(timezone.utc)
                    # Geocode enqueue every ~45s wall so addresses fill in background
                    do_geo = (time.monotonic() - last_geocode_flush) >= 45.0
                    result = ingest_observation_batch(
                        user_id,
                        stamp_seen_at(batch, when),
                        localize=True,
                        enqueue_geocode=do_geo,
                    )
                    samples_total += int(result.get("samples") or 0)
                    networks_total += int(result.get("networks_updated") or 0)
                    if do_geo:
                        last_geocode_flush = time.monotonic()
                last_rec_ts = rec_now

            heading = pt.get("heading") or 0.0
            speed_mps = pt.get("speed")
            if speed_mps is None:
                speed_mps = 0.0
            # Recording speed is already m/s-ish from Kismet; keep as-is
            body = {
                "lat": pt["lat"],
                "lon": pt["lon"],
                "heading_deg": heading,
                "speed_mps": float(speed_mps),
                "accuracy_m": 10.0,
                "source": "client",
                "unlock": True,
                "session_started_at": session_started,
            }
            data = client.post_json("/api/gps/fix", body)
            radio = data.get("radio") or {}
            wifi = (radio.get("wifi") or {}).get("seen", 0)
            wifi_new = (radio.get("wifi") or {}).get("new", 0)
            pct = 100.0 * (rec_now - play_start) / max(1, play_end - play_start)
            print(
                f"\r[{pct:5.1f}%] {speed:g}×  "
                f"{pt['lat']:.5f},{pt['lon']:.5f}  "
                f"wifi {wifi_new}/{wifi} new/seen  "
                f"samples+={samples_total} nets={networks_total}   ",
                end="",
                flush=True,
            )

            # Sleep until next recording second at this speed
            next_boundary = last_rec_ts + 1
            target_wall = (next_boundary - play_start) / speed
            sleep_s = target_wall - (time.monotonic() - wall0)
            if sleep_s > 0:
                time.sleep(min(sleep_s, 0.5 / max(1.0, speed / 4.0)))
            else:
                time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n[replay] stopped by user")
        return 0

    print(f"\n[replay] done · samples inserted ≈ {samples_total}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Replay Kismet → live GPS + samples for the Drive dashboard"
    )
    p.add_argument(
        "recording_positional",
        nargs="?",
        type=Path,
        default=None,
        metavar="KISMET_DB",
        help="Path to a .kismet / .kis_db file (optional if --db or default recording exists)",
    )
    p.add_argument(
        "--db",
        "-d",
        "--recording",
        "-r",
        dest="db",
        type=Path,
        default=None,
        metavar="PATH",
        help="Kismet database file to replay (same as positional KISMET_DB)",
    )
    p.add_argument(
        "--speed",
        "-x",
        type=float,
        default=4.0,
        help="Replay speed multiplier (default: 4). Example: -x 8 or --speed 16",
    )
    p.add_argument("--base", default="http://127.0.0.1:8000", help="API base URL")
    p.add_argument("--user", default="admin", help="WebUI username")
    p.add_argument(
        "--password",
        required=True,
        help="WebUI password (set at first-boot /setup)",
    )
    p.add_argument(
        "--start",
        default="0",
        help="Skip into the recording (e.g. 30m, 1h, 900s)",
    )
    p.add_argument(
        "--duration",
        default=None,
        help="Only replay this much recording time (e.g. 15m). Default: full file",
    )
    p.add_argument(
        "--rebuild-cache",
        action="store_true",
        help="Rebuild GPS track cache from the .kismet",
    )
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
