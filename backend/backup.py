from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from db import connect_dict
from paths import user_exports

ExportKind = Literal["user_calculated", "full", "calculated_only", "raw_only"]


def _samples_csv(user_id: int) -> str:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, network_id, encryption, seen_at, signal, accuracy,
                       network_type, channel, altitude, lat, lon, source_file, source_format
                FROM signal_samples WHERE user_id = %s ORDER BY id
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    buf = io.StringIO()
    w = csv.DictWriter(
        buf,
        fieldnames=[
            "name",
            "network_id",
            "encryption",
            "seen_at",
            "signal",
            "accuracy",
            "network_type",
            "channel",
            "altitude",
            "lat",
            "lon",
            "source_file",
            "source_format",
        ],
    )
    w.writeheader()
    for r in rows:
        out = dict(r)
        if out.get("seen_at") is not None:
            out["seen_at"] = out["seen_at"].isoformat()
        w.writerow(out)
    return buf.getvalue()


def _networks_csv(user_id: int) -> str:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT network_id, name, encryption, network_type, channel, sample_count,
                       lat, lon, altitude, avg_signal, first_seen, last_seen, localization_mode,
                       address, city, postcode, country, country_code,
                       location_accuracy_m, avg_gps_accuracy_m
                FROM networks WHERE user_id = %s ORDER BY network_id
                """,
                (user_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    buf = io.StringIO()
    fields = [
        "network_id",
        "name",
        "encryption",
        "network_type",
        "channel",
        "sample_count",
        "lat",
        "lon",
        "altitude",
        "avg_signal",
        "first_seen",
        "last_seen",
        "localization_mode",
        "address",
        "city",
        "postcode",
        "country",
        "country_code",
        "location_accuracy_m",
        "avg_gps_accuracy_m",
    ]
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for r in rows:
        out = {k: r.get(k) for k in fields}
        for ts in ("first_seen", "last_seen"):
            if out.get(ts) is not None:
                out[ts] = out[ts].isoformat()
        w.writerow(out)
    return buf.getvalue()


def _user_settings(user_id: int) -> dict:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT key, value FROM user_settings WHERE user_id = %s",
                (user_id,),
            )
            return {r["key"]: r["value"] for r in cur.fetchall()}
    finally:
        conn.close()


def create_export(user_id: int, kind: ExportKind = "user_calculated") -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = user_exports(user_id) / f"wardrivrr_{kind}_{ts}.zip"
    meta = {
        "format": "wardrivrr-backup-v1",
        "kind": kind,
        "exported_at": ts,
        "user_id": user_id,
    }
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("meta.json", json.dumps(meta, indent=2))
        if kind in ("user_calculated", "full", "raw_only"):
            zf.writestr("signal_samples.csv", _samples_csv(user_id))
            # raw file manifest
            incoming = Path(__file__).resolve().parents[1] / "data" / "users" / str(user_id) / "incoming"
            if incoming.exists():
                names = [p.name for p in incoming.iterdir() if p.is_file()]
                zf.writestr("incoming_manifest.json", json.dumps(names, indent=2))
        if kind in ("user_calculated", "full", "calculated_only"):
            zf.writestr("networks.csv", _networks_csv(user_id))
        if kind in ("user_calculated", "full"):
            zf.writestr("user_settings.json", json.dumps(_user_settings(user_id), indent=2))
        if kind == "full":
            zf.writestr(
                "app_meta.json",
                json.dumps({"note": "Minimal restore meta", "schema": "multiuser_levels"}, indent=2),
            )
    return out


def import_backup(
    user_id: int,
    archive: Path,
    mode: Literal["merge", "replace"] = "merge",
) -> dict:
    stats = {"samples": 0, "networks": 0, "settings": 0, "mode": mode}
    with zipfile.ZipFile(archive, "r") as zf:
        names = set(zf.namelist())
        if "meta.json" not in names:
            raise ValueError("Not a wardrivrr backup (missing meta.json)")
        meta = json.loads(zf.read("meta.json"))
        if meta.get("format") != "wardrivrr-backup-v1":
            raise ValueError("Unsupported backup format")

        conn = connect_dict()
        try:
            with conn.cursor() as cur:
                if mode == "replace":
                    cur.execute("DELETE FROM networks WHERE user_id = %s", (user_id,))
                    cur.execute("DELETE FROM signal_samples WHERE user_id = %s", (user_id,))

                if "signal_samples.csv" in names:
                    text = zf.read("signal_samples.csv").decode("utf-8")
                    reader = csv.DictReader(io.StringIO(text))
                    rows = []
                    for r in reader:
                        rows.append(
                            (
                                r.get("name") or None,
                                r["network_id"],
                                r.get("encryption") or None,
                                r.get("seen_at") or None,
                                float(r["signal"]) if r.get("signal") else None,
                                float(r["accuracy"]) if r.get("accuracy") else None,
                                r.get("network_type") or "WIFI",
                                int(r["channel"]) if r.get("channel") else None,
                                float(r["altitude"]) if r.get("altitude") else None,
                                float(r["lat"]),
                                float(r["lon"]),
                                r.get("source_file") or None,
                                r.get("source_format") or None,
                                user_id,
                            )
                        )
                    if rows:
                        from psycopg2.extras import execute_values

                        execute_values(
                            cur,
                            """
                            INSERT INTO signal_samples (
                                name, network_id, encryption, seen_at, signal, accuracy,
                                network_type, channel, altitude, lat, lon, source_file,
                                source_format, user_id
                            ) VALUES %s
                            ON CONFLICT DO NOTHING
                            """,
                            rows,
                            page_size=1000,
                        )
                        stats["samples"] = len(rows)

                if "networks.csv" in names:
                    text = zf.read("networks.csv").decode("utf-8")
                    reader = csv.DictReader(io.StringIO(text))
                    for r in reader:
                        cur.execute(
                            """
                            INSERT INTO networks (
                                user_id, network_id, name, encryption, network_type, channel,
                                sample_count, lat, lon, altitude, avg_signal,
                                first_seen, last_seen, localization_mode,
                                address, city, postcode, country, country_code,
                                location_accuracy_m, avg_gps_accuracy_m, computed_at
                            ) VALUES (
                                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                                %s,%s,%s,%s,%s,%s,%s,NOW()
                            )
                            ON CONFLICT (user_id, network_id) DO UPDATE SET
                                name = EXCLUDED.name,
                                encryption = EXCLUDED.encryption,
                                network_type = EXCLUDED.network_type,
                                channel = EXCLUDED.channel,
                                sample_count = EXCLUDED.sample_count,
                                lat = EXCLUDED.lat,
                                lon = EXCLUDED.lon,
                                altitude = EXCLUDED.altitude,
                                avg_signal = EXCLUDED.avg_signal,
                                first_seen = EXCLUDED.first_seen,
                                last_seen = EXCLUDED.last_seen,
                                localization_mode = EXCLUDED.localization_mode,
                                address = COALESCE(EXCLUDED.address, networks.address),
                                city = COALESCE(EXCLUDED.city, networks.city),
                                postcode = COALESCE(EXCLUDED.postcode, networks.postcode),
                                country = COALESCE(EXCLUDED.country, networks.country),
                                country_code = COALESCE(EXCLUDED.country_code, networks.country_code),
                                location_accuracy_m = COALESCE(EXCLUDED.location_accuracy_m, networks.location_accuracy_m),
                                avg_gps_accuracy_m = COALESCE(EXCLUDED.avg_gps_accuracy_m, networks.avg_gps_accuracy_m),
                                computed_at = NOW()
                            """,
                            (
                                user_id,
                                r["network_id"],
                                r.get("name"),
                                r.get("encryption"),
                                r.get("network_type") or "WIFI",
                                int(r["channel"]) if r.get("channel") else None,
                                int(r["sample_count"]) if r.get("sample_count") else 0,
                                float(r["lat"]),
                                float(r["lon"]),
                                float(r["altitude"]) if r.get("altitude") else None,
                                float(r["avg_signal"]) if r.get("avg_signal") else None,
                                r.get("first_seen") or None,
                                r.get("last_seen") or None,
                                r.get("localization_mode") or "2d",
                                r.get("address") or None,
                                r.get("city") or None,
                                r.get("postcode") or None,
                                r.get("country") or None,
                                r.get("country_code") or None,
                                float(r["location_accuracy_m"]) if r.get("location_accuracy_m") else None,
                                float(r["avg_gps_accuracy_m"]) if r.get("avg_gps_accuracy_m") else None,
                            ),
                        )
                        stats["networks"] += 1

                if "user_settings.json" in names:
                    settings = json.loads(zf.read("user_settings.json"))
                    for k, v in settings.items():
                        cur.execute(
                            """
                            INSERT INTO user_settings (user_id, key, value) VALUES (%s,%s,%s)
                            ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value
                            """,
                            (user_id, k, str(v)),
                        )
                        stats["settings"] += 1
            conn.commit()
        finally:
            conn.close()
    return stats
