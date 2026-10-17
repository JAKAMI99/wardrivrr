from __future__ import annotations

import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from psycopg2 import OperationalError
from pydantic import BaseModel, Field

from auth import (
    clear_session_cookie,
    create_access_token,
    ensure_bootstrap_admin,
    generate_api_key,
    get_current_user,
    get_optional_user,
    hash_password,
    require_admin,
    set_session_cookie,
    verify_password,
    get_user_by_username,
)
from backup import create_export, import_backup
from db import connect_dict, get_setting, get_user_setting, set_user_setting
from ingest_upload import ingest_file_for_user
from jobs import enqueue_job, ensure_worker, get_job, list_jobs
from geocode import geocode_place, geocode_postalcode, reverse_geocode
from levels import (
    create_level,
    delete_level,
    get_level,
    get_level_road_map,
    list_levels,
    search_geofabrik,
    search_level_places,
)
from localize import recompute_2d, recompute_3d
from network_api import get_network_detail, search_geojson, search_networks
from stats_dashboard import build_stats_dashboard
from system_status import collect_system_status

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"

app = FastAPI(
    title="wardrivrr",
    version="0.5.0",
    description=(
        "Local triangulated network database API. "
        "Authenticate with `X-API-Key: wr_…` or `Authorization: Bearer <jwt|wr_…>`."
    ),
    docs_url=None,  # custom /api/docs — auto-authorizes from WebUI login token
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

EMPTY_SQL = "(name IS NULL OR btrim(name) = '' OR lower(btrim(name)) IN ('(no ssid)', '<no ssid>', '[no ssid]', 'null', 'none'))"


class LoginBody(BaseModel):
    username: str
    password: str
    keep_logged_in: bool = False


class CreateUserBody(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    is_admin: bool = False


class UpdateUsernameBody(BaseModel):
    username: str = Field(min_length=2, max_length=64)


class ChangePasswordBody(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=4, max_length=128)


class ApiKeyCreateBody(BaseModel):
    name: str = "default"


class RecomputeBody(BaseModel):
    mode: str = Field(default="2d", pattern="^(2d|3d)$")
    precision: str = Field(default="balanced", pattern="^(fast|balanced|precise)$")
    network_ids: list[str] | None = None
    async_job: bool = True


class SettingsBody(BaseModel):
    default_localization_mode: str | None = Field(default=None, pattern="^(2d|3d)$")
    default_localize_precision: str | None = Field(
        default=None, pattern="^(fast|balanced|precise)$"
    )
    localize_nightly: bool | None = None
    navigation_active: bool | None = None
    anomaly_alerts: bool | None = None
    achievement_sounds: bool | None = None
    units: str | None = Field(default=None, pattern="^(metric|imperial)$")
    theme: str | None = Field(
        default=None, pattern="^(classic|kidcore|kawaii|crt)$"
    )  # kawaii = legacy alias for kidcore


class PlacePrepareBody(BaseModel):
    lat: float
    lon: float
    name: str | None = None
    geofabrik_id: str
    population: int | None = None
    bbox: list[float] | None = None
    parent_label: str | None = None
    country_code: str | None = None
    geoname_id: int | None = None


class NavigationBody(BaseModel):
    active: bool


class GpsFixBody(BaseModel):
    lat: float
    lon: float
    heading_deg: float | None = None
    speed_mps: float | None = None
    accuracy_m: float | None = Field(default=15.0, ge=0.5, le=500)
    source: str = Field(default="sim", pattern="^(sim|gpsd|client)$")
    level_id: int | None = None
    unlock: bool = True
    session_started_at: str | None = None  # ISO time when drive spawn began


class ExploreRouteBody(BaseModel):
    level_id: int
    lat: float | None = None
    lon: float | None = None
    heading_deg: float | None = None
    target_km: float = Field(default=5.0, ge=0.5, le=40.0)
    language: str = "en-US"
    # When true, skip all cul-de-sac tip waypoints; short tips (<40 m) are always skipped.
    exclude_dead_ends: bool = False


class LevelCreateBody(BaseModel):
    name: str
    place_query: str
    profile: str = Field(pattern="^(foot|bicycle|car)$")
    geofabrik_id: str
    place_bbox: list[float] | None = None  # west,south,east,north
    place_boundary: dict | None = None  # GeoJSON Polygon / MultiPolygon
    download_now: bool = True
    place_kind: str = "city"  # city | district (city_part accepted as alias)
    geoname_id: int | None = None
    parent_geoname_id: int | None = None
    parent_label: str | None = None
    part_label: str | None = None
    osm_relation_id: int | None = None
    osm_admin_level: int | None = None


class ActiveLevelBody(BaseModel):
    level_id: int | None = None


class ExportBody(BaseModel):
    kind: str = Field(
        default="user_calculated",
        pattern="^(user_calculated|full|calculated_only|raw_only)$",
    )


class ImportBody(BaseModel):
    mode: str = Field(default="merge", pattern="^(merge|replace)$")


def apply_filters(sql: str, params: list, **filters) -> tuple[str, list]:
    if filters.get("user_id") is not None:
        sql += " AND user_id = %s"
        params.append(filters["user_id"])
    if filters.get("network_type"):
        sql += " AND network_type = %s"
        params.append(filters["network_type"].upper())
    if filters.get("encryption"):
        if filters["encryption"] == "None":
            sql += " AND encryption IN ('None', 'Unknown')"
        else:
            sql += " AND encryption = %s"
            params.append(filters["encryption"])
    if filters.get("name"):
        sql += " AND name ILIKE %s"
        params.append(f"%{filters['name']}%")
    if filters.get("network_id"):
        sql += " AND lower(network_id) = lower(%s)"
        params.append(filters["network_id"])
    if filters.get("exclude_no_ssid"):
        sql += f" AND NOT {EMPTY_SQL}"
    if filters.get("seen_after"):
        sql += " AND last_seen >= %s"
        params.append(filters["seen_after"])
    if filters.get("seen_before"):
        sql += " AND last_seen <= %s"
        params.append(filters["seen_before"])
    bbox = filters.get("bbox")
    if bbox:
        west, south, east, north = bbox
        sql += " AND geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)"
        params.extend([west, south, east, north])
    return sql, params


def parse_bbox(value: str | None):
    if not value:
        return None
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 4:
        raise HTTPException(400, "bbox must be west,south,east,north")
    try:
        west, south, east, north = map(float, parts)
    except ValueError as exc:
        raise HTTPException(400, "bbox values must be numbers") from exc
    return west, south, east, north


@app.on_event("startup")
def on_startup():
    try:
        ensure_bootstrap_admin()
        ensure_worker()
    except Exception:
        pass
    # Offline geo DBs (prefer `python scripts/prepare_offline_data.py` / docker/prepare-data)
    try:
        from cities_db import ensure_cities_db

        ensure_cities_db()
    except Exception as exc:
        print(f"[startup] cities DB: {exc}")
    try:
        from local_geocode import ensure_postal_db

        ensure_postal_db()
    except Exception as exc:
        print(f"[startup] postal DB: {exc}")
    try:
        from geofabrik import ensure_index

        ensure_index()
    except Exception as exc:
        print(f"[startup] geofabrik index: {exc}")
    try:
        from gpsd_poller import start_gpsd_poller

        start_gpsd_poller()
    except Exception as exc:
        print(f"[startup] gpsd poller: {exc}")
    try:
        from kismet_live import start_kismet_live

        start_kismet_live()
    except Exception as exc:
        print(f"[startup] kismet live: {exc}")


# ----- Auth -----


@app.get("/api/auth/status")
def auth_status(user: dict | None = Depends(get_optional_user)):
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            n = cur.fetchone()["n"]
    except OperationalError:
        n = 0
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return {
        "authenticated": user is not None,
        "user": (
            {"id": user["id"], "username": user["username"], "is_admin": user["is_admin"]}
            if user
            else None
        ),
        "users_exist": n > 0,
        "invite_only": True,
    }


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    ensure_bootstrap_admin()
    row = get_user_by_username(body.username.strip())
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid username or password")
    keep = bool(body.keep_logged_in)
    token = create_access_token(
        row["id"], row["username"], row["is_admin"], keep_logged_in=keep
    )
    secure = request.url.scheme == "https"
    set_session_cookie(response, token, keep_logged_in=keep, secure=secure)
    return {
        "access_token": token,
        "token_type": "bearer",
        "keep_logged_in": keep,
        "user": {"id": row["id"], "username": row["username"], "is_admin": row["is_admin"]},
    }


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "id": user["id"],
        "username": user["username"],
        "is_admin": user["is_admin"],
        "remember": bool(user.get("remember")),
    }


def _normalize_username(raw: str) -> str:
    name = (raw or "").strip()
    if len(name) < 2 or len(name) > 64:
        raise HTTPException(400, "Username must be 2–64 characters")
    # Letters, digits, underscore, hyphen, period — no spaces
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
        raise HTTPException(
            400, "Username may only use letters, numbers, _ . -"
        )
    return name


@app.patch("/api/auth/username")
def change_username(
    body: UpdateUsernameBody,
    request: Request,
    response: Response,
    user: dict = Depends(get_current_user),
):
    """Rename the signed-in user. Issues a fresh JWT so the session stays valid."""
    if user.get("auth") == "api_key":
        raise HTTPException(400, "Use a WebUI login to change username")
    new_name = _normalize_username(body.username)
    if new_name.lower() == str(user["username"]).lower() and new_name == user["username"]:
        return {
            "ok": True,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "is_admin": user["is_admin"],
            },
            "access_token": None,
        }
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM users
                WHERE lower(username) = lower(%s) AND id <> %s
                """,
                (new_name, user["id"]),
            )
            if cur.fetchone():
                raise HTTPException(409, "That username is already taken")
            cur.execute(
                """
                UPDATE users SET username = %s
                WHERE id = %s
                RETURNING id, username, is_admin
                """,
                (new_name, user["id"]),
            )
            row = cur.fetchone()
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    finally:
        conn.close()

    remember = bool(user.get("remember"))
    token = create_access_token(
        row["id"], row["username"], row["is_admin"], keep_logged_in=remember
    )
    secure = request.url.scheme == "https"
    set_session_cookie(response, token, keep_logged_in=remember, secure=secure)
    return {
        "ok": True,
        "access_token": token,
        "keep_logged_in": remember,
        "user": {
            "id": row["id"],
            "username": row["username"],
            "is_admin": row["is_admin"],
        },
    }


@app.post("/api/auth/password")
def change_password(body: ChangePasswordBody, user: dict = Depends(get_current_user)):
    """Change password for the signed-in user (requires current password)."""
    if user.get("auth") == "api_key":
        raise HTTPException(400, "Use a WebUI login to change password")
    row = get_user_by_username(user["username"])
    if not row or not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    if body.current_password == body.new_password:
        raise HTTPException(400, "New password must be different")
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hash_password(body.new_password), user["id"]),
            )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.post("/api/admin/users")
def admin_create_user(body: CreateUserBody, admin: dict = Depends(require_admin)):
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, password_hash, is_admin)
                VALUES (%s, %s, %s)
                RETURNING id, username, is_admin, created_at
                """,
                (body.username.strip(), hash_password(body.password), body.is_admin),
            )
            user = cur.fetchone()
            cur.execute(
                """
                INSERT INTO user_settings (user_id, key, value) VALUES
                  (%s, 'default_localization_mode', '2d'),
                  (%s, 'default_localize_precision', 'balanced'),
                  (%s, 'localize_nightly', 'false')
                ON CONFLICT DO NOTHING
                """,
                (user["id"], user["id"], user["id"]),
            )
        conn.commit()
        return user
    except Exception as exc:
        if "unique" in str(exc).lower():
            raise HTTPException(409, "Username already exists") from exc
        raise
    finally:
        conn.close()


@app.get("/api/admin/users")
def admin_list_users(admin: dict = Depends(require_admin)):
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, is_admin, created_at FROM users ORDER BY id"
            )
            return cur.fetchall()
    finally:
        conn.close()


# ----- API keys -----


@app.get("/api/keys")
def list_keys(user: dict = Depends(get_current_user)):
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, key_prefix, created_at, last_used_at, revoked_at
                FROM api_keys WHERE user_id = %s ORDER BY id DESC
                """,
                (user["id"],),
            )
            return cur.fetchall()
    finally:
        conn.close()


@app.post("/api/keys")
def create_key(body: ApiKeyCreateBody, user: dict = Depends(get_current_user)):
    raw, prefix, digest = generate_api_key()
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO api_keys (user_id, name, key_prefix, key_hash)
                VALUES (%s, %s, %s, %s)
                RETURNING id, name, key_prefix, created_at
                """,
                (user["id"], body.name, prefix, digest),
            )
            row = cur.fetchone()
        conn.commit()
        return {**row, "key": raw, "note": "Copy now — key is shown only once."}
    finally:
        conn.close()


@app.delete("/api/keys/{key_id}")
def revoke_key(key_id: int, user: dict = Depends(get_current_user)):
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE api_keys SET revoked_at = NOW()
                WHERE id = %s AND user_id = %s AND revoked_at IS NULL
                RETURNING id
                """,
                (key_id, user["id"]),
            )
            row = cur.fetchone()
        conn.commit()
        if not row:
            raise HTTPException(404, "Key not found")
        return {"ok": True, "id": key_id}
    finally:
        conn.close()


# ----- Ingest / upload -----


@app.post("/api/v1/ingest/upload")
async def ingest_upload(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """API-key or JWT upload. Auto-detects Kismet / WiGLE."""
    from paths import user_incoming

    final_name = Path(file.filename or "upload.bin").name
    dest = user_incoming(user["id"]) / final_name
    content = await file.read()
    dest.write_bytes(content)
    try:
        mode = get_user_setting(user["id"], "default_localization_mode", "2d") or "2d"
        precision = (
            get_user_setting(user["id"], "default_localize_precision", "balanced")
            or "balanced"
        )
        result = ingest_file_for_user(
            user["id"], dest, mode=mode, precision=precision, copy_to_incoming=False
        )
        try:
            from achievements import evaluate_achievements

            result["newly_unlocked"] = evaluate_achievements(user["id"])
        except Exception:
            result["newly_unlocked"] = []
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


# ----- Export / import -----


@app.post("/api/backup/export")
def backup_export(body: ExportBody, user: dict = Depends(get_current_user)):
    path = create_export(user["id"], body.kind)  # type: ignore[arg-type]
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/zip",
    )


@app.post("/api/backup/import")
async def backup_import(
    file: UploadFile = File(...),
    mode: str = Form(default="merge"),
    user: dict = Depends(get_current_user),
):
    if mode not in ("merge", "replace"):
        raise HTTPException(400, "mode must be merge or replace")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)
    try:
        stats = import_backup(user["id"], tmp_path, mode=mode)  # type: ignore[arg-type]
        return {"ok": True, **stats}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)


# ----- Health / stats (scoped) -----


@app.get("/api/health")
def health(user: dict | None = Depends(get_optional_user)):
    try:
        conn = connect_dict()
        with conn.cursor() as cur:
            if user:
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM signal_samples WHERE user_id = %s) AS samples,
                        (SELECT COUNT(*) FROM networks WHERE user_id = %s) AS networks
                    """,
                    (user["id"], user["id"]),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM signal_samples) AS samples,
                        (SELECT COUNT(*) FROM networks) AS networks
                    """
                )
            row = cur.fetchone()
            cur.execute("SELECT PostGIS_Version() AS postgis")
            pg = cur.fetchone()
            mode = (
                get_user_setting(user["id"], "default_localization_mode", "2d", conn=conn)
                if user
                else get_setting("default_localization_mode", "2d", conn=conn)
            )
        conn.close()
        return {
            "ok": True,
            "postgis": pg["postgis"],
            "samples": row["samples"],
            "networks": row["networks"],
            "observations": row["samples"],
            "localization_mode_default": mode,
            "authenticated": user is not None,
        }
    except OperationalError as exc:
        raise HTTPException(503, f"database unavailable: {exc}") from exc


@app.get("/api/stats")
def stats(user: dict = Depends(get_current_user)):
    conn = connect_dict()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM signal_samples WHERE user_id = %s) AS samples,
                COUNT(*) AS networks,
                MIN(first_seen) AS first_seen,
                MAX(last_seen) AS last_seen,
                COUNT(*) FILTER (WHERE localization_mode = '3d') AS networks_3d,
                COUNT(*) FILTER (WHERE localization_mode = '2d') AS networks_2d,
                COUNT(*) FILTER (WHERE upper(network_type) = 'WIFI') AS networks_wifi,
                COUNT(*) FILTER (WHERE upper(network_type) = 'BT') AS networks_bt,
                COUNT(*) FILTER (WHERE upper(network_type) = 'BLE') AS networks_ble
            FROM networks
            WHERE user_id = %s
            """,
            (user["id"], user["id"]),
        )
        summary = cur.fetchone()
        cur.execute(
            """
            SELECT network_type, COUNT(*) AS networks
            FROM networks WHERE user_id = %s
            GROUP BY network_type ORDER BY networks DESC
            """,
            (user["id"],),
        )
        by_type = cur.fetchall()
        cur.execute(
            """
            SELECT COALESCE(encryption, 'Unknown') AS encryption, COUNT(*) AS networks
            FROM networks WHERE user_id = %s
            GROUP BY 1 ORDER BY networks DESC
            """,
            (user["id"],),
        )
        by_enc = cur.fetchall()
    conn.close()
    return {"summary": summary, "by_type": by_type, "by_encryption": by_enc}


@app.get("/api/stats/dashboard")
def stats_dashboard(user: dict = Depends(get_current_user)):
    try:
        return build_stats_dashboard(user_id=user["id"])
    except OperationalError as exc:
        raise HTTPException(503, f"database unavailable: {exc}") from exc
    except TypeError:
        return build_stats_dashboard()


def _normalize_theme(theme: str) -> str:
    t = (theme or "classic").strip().lower()
    if t == "kawaii":
        return "kidcore"
    return t


@app.get("/api/settings")
def read_settings(user: dict = Depends(get_current_user)):
    return {
        "default_localization_mode": get_user_setting(
            user["id"], "default_localization_mode", "2d"
        )
        or "2d",
        "default_localize_precision": get_user_setting(
            user["id"], "default_localize_precision", "balanced"
        )
        or "balanced",
        "localize_nightly": (
            get_user_setting(user["id"], "localize_nightly", "false") or "false"
        ).lower()
        == "true",
        "navigation_active": (
            get_user_setting(user["id"], "navigation_active", "false") or "false"
        ).lower()
        == "true",
        "active_level_id": get_user_setting(user["id"], "active_level_id", None),
        "units": get_user_setting(user["id"], "units", "metric") or "metric",
        "theme": _normalize_theme(
            get_user_setting(user["id"], "theme", "classic") or "classic"
        ),
        "anomaly_alerts": (
            get_user_setting(user["id"], "anomaly_alerts", "true") or "true"
        ).lower()
        == "true",
        "achievement_sounds": (
            get_user_setting(user["id"], "achievement_sounds", "true") or "true"
        ).lower()
        == "true",
    }


@app.patch("/api/settings")
def patch_settings(body: SettingsBody, user: dict = Depends(get_current_user)):
    if body.default_localization_mode:
        set_user_setting(user["id"], "default_localization_mode", body.default_localization_mode)
    if body.default_localize_precision:
        set_user_setting(
            user["id"], "default_localize_precision", body.default_localize_precision
        )
    if body.localize_nightly is not None:
        set_user_setting(
            user["id"], "localize_nightly", "true" if body.localize_nightly else "false"
        )
    if body.navigation_active is not None:
        set_user_setting(
            user["id"],
            "navigation_active",
            "true" if body.navigation_active else "false",
        )
    if body.anomaly_alerts is not None:
        set_user_setting(
            user["id"],
            "anomaly_alerts",
            "true" if body.anomaly_alerts else "false",
        )
    if body.achievement_sounds is not None:
        set_user_setting(
            user["id"],
            "achievement_sounds",
            "true" if body.achievement_sounds else "false",
        )
    if body.units is not None:
        set_user_setting(user["id"], "units", body.units)
    if body.theme is not None:
        set_user_setting(user["id"], "theme", _normalize_theme(body.theme))
    return read_settings(user)


@app.put("/api/navigation/active")
def set_navigation_active(body: NavigationBody, user: dict = Depends(get_current_user)):
    """UI calls this when turn-by-turn starts/stops — throttles background geocode."""
    set_user_setting(
        user["id"], "navigation_active", "true" if body.active else "false"
    )
    return {"ok": True, "navigation_active": body.active}


@app.get("/api/gps/fix")
def gps_get_fix(
    session_started_at: str | None = None,
    user: dict = Depends(get_current_user),
):
    """Current GPS fix. Pass session_started_at to also get drive radio HUD stats."""
    from gps_state import get_fix

    fix = get_fix(user["id"])
    if not fix:
        return {"ok": True, "fix": None}
    out: dict = {"ok": True, "fix": fix}
    session_key = session_started_at or fix.get("session_started_at")
    if session_key:
        from drive_session import parse_session_start, session_radio_stats

        since = parse_session_start(session_key)
        if since is not None:
            try:
                out["radio"] = session_radio_stats(user["id"], since)
            except Exception:
                out["radio"] = None
            try:
                from anomalies import session_anomaly_hits

                out["anomalies"] = session_anomaly_hits(user["id"], since)
            except Exception:
                out["anomalies"] = None
            try:
                from achievements import evaluate_achievements

                out["newly_unlocked"] = evaluate_achievements(user["id"])
            except Exception:
                out["newly_unlocked"] = []
    return out


@app.post("/api/gps/fix")
def gps_post_fix(body: GpsFixBody, user: dict = Depends(get_current_user)):
    """Push a sim or live GPS fix. Snaps to road; fog unlock uses snapped coords."""
    from achievements import record_drive_step
    from gps_snap import resolve_level_id, snap_to_road
    from gps_state import set_fix
    from levels import unlock_near_point

    level_id = body.level_id
    if level_id is None:
        level_id = resolve_level_id(user["id"])
    snap = snap_to_road(
        body.lon,
        body.lat,
        level_id,
        user_id=user["id"],
        heading_deg=body.heading_deg,
    )
    use_lat = snap["lat"]
    use_lon = snap["lon"]

    try:
        prev, fix = set_fix(
            user["id"],
            lat=use_lat,
            lon=use_lon,
            heading_deg=body.heading_deg,
            speed_mps=body.speed_mps,
            accuracy_m=body.accuracy_m,
            source=body.source,
            level_id=level_id,
            session_started_at=body.session_started_at,
            raw_lat=body.lat,
            raw_lon=body.lon,
            snap=snap,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    unlock_stats = None
    if body.unlock and level_id is not None:
        level = get_level(user["id"], level_id)
        if level and level.get("status") == "ready":
            # Fog / road-tile unlock uses snapped position (not raw GPS)
            unlock_stats = unlock_near_point(
                level_id,
                use_lon,
                use_lat,
                accuracy_m=body.accuracy_m,
                heading_deg=body.heading_deg,
            )
            if unlock_stats is not None:
                unlock_stats = dict(unlock_stats)
                unlock_stats["snap"] = {
                    "snapped": snap.get("snapped"),
                    "held": snap.get("held"),
                    "degraded": snap.get("degraded"),
                    "distance_m": snap.get("distance_m"),
                    "threshold_m": snap.get("threshold_m"),
                }

    explored_km = 0.0
    if unlock_stats and unlock_stats.get("newly_explored"):
        # ~20 m average segment length estimate for achievement flavour counters
        explored_km = float(unlock_stats["newly_explored"]) * 0.02

    drive = record_drive_step(
        user["id"],
        lat=use_lat,
        lon=use_lon,
        prev_lat=prev["lat"] if prev else None,
        prev_lon=prev["lon"] if prev else None,
        prev_ts=prev.get("updated_at") if prev else None,
        now_ts=fix.get("updated_at"),
        explored_km_delta=explored_km,
    )

    radio = None
    anomalies = None
    from drive_session import parse_session_start, session_radio_stats

    since = parse_session_start(body.session_started_at)
    if since is not None:
        try:
            radio = session_radio_stats(user["id"], since)
        except Exception:
            radio = None
        try:
            from anomalies import session_anomaly_hits

            anomalies = session_anomaly_hits(user["id"], since)
        except Exception:
            anomalies = None

    return {
        "ok": True,
        "fix": fix,
        "snap": snap,
        "unlock": unlock_stats,
        "drive": drive,
        "newly_unlocked": drive.get("newly_unlocked") or [],
        "radio": radio,
        "anomalies": anomalies,
    }


@app.get("/api/achievements")
def achievements_list(user: dict = Depends(get_current_user)):
    from achievements import list_achievements

    return list_achievements(user["id"])


@app.get("/api/me/progress")
def me_progress(user: dict = Depends(get_current_user)):
    """Explorer XP/level derived from unlocked achievement XP."""
    from achievements import explorer_progress

    return explorer_progress(user["id"])


@app.post("/api/achievements/evaluate")
def achievements_evaluate(user: dict = Depends(get_current_user)):
    from achievements import evaluate_achievements, list_achievements

    newly = evaluate_achievements(user["id"])
    data = list_achievements(user["id"])
    data["newly_unlocked"] = newly
    return data


@app.get("/api/navigate/status")
def navigate_status(user: dict = Depends(get_current_user)):
    """Valhalla readiness for the navigate HUD."""
    _ = user
    from valhalla_client import valhalla_status
    from valhalla_prep import ACTIVE_META, ACTIVE_PBF

    meta = None
    if ACTIVE_META.exists():
        try:
            meta = json.loads(ACTIVE_META.read_text(encoding="utf-8"))
        except Exception:
            meta = None
    return {
        "ok": True,
        "valhalla": valhalla_status(),
        "active_extract": {
            "path": str(ACTIVE_PBF),
            "bytes": ACTIVE_PBF.stat().st_size if ACTIVE_PBF.exists() else 0,
            "meta": meta,
        },
    }


class NavigatePrepareBody(BaseModel):
    level_id: int
    restart: bool = True
    force: bool = False


@app.post("/api/navigate/prepare")
def navigate_prepare(body: NavigatePrepareBody, user: dict = Depends(get_current_user)):
    """
    Clip the level's map pack PBF to the level bbox and (re)start Valhalla on that clip.
    Much smaller than building the whole Regierungsbezirk.
    """
    from valhalla_prep import ValhallaPrepError, prepare_valhalla_for_level

    level = get_level(user["id"], body.level_id)
    if not level:
        raise HTTPException(404, "Level not found")
    try:
        return prepare_valhalla_for_level(
            user["id"],
            body.level_id,
            restart=body.restart,
            force=body.force,
        )
    except ValhallaPrepError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/navigate/contains")
def navigate_contains(
    lat: float = Query(...),
    lon: float = Query(...),
    level_id: int | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Is the fix inside the active (or given) level boundary?"""
    from level_suggest import level_contains_point

    lid = level_id
    if lid is None:
        raw = get_user_setting(user["id"], "active_level_id", None)
        if raw:
            try:
                lid = int(raw)
            except (TypeError, ValueError):
                lid = None
    if lid is None:
        return {"ok": True, "inside": False, "reason": "no_level"}
    return level_contains_point(user["id"], lid, lat, lon)


@app.get("/api/navigate/suggest-level")
def navigate_suggest_level(
    lat: float = Query(...),
    lon: float = Query(...),
    user: dict = Depends(get_current_user),
):
    """City or City (District) suggestion for auto-load when leaving a level."""
    from level_suggest import suggest_level_at

    return suggest_level_at(user["id"], lat, lon)


@app.post("/api/navigate/explore")
def navigate_explore(body: ExploreRouteBody, user: dict = Depends(get_current_user)):
    """
    Infinite-explorer route: ~target_km toward unexplored segments via Valhalla.
    Uses posted lat/lon or the last GPS/sim fix.
    """
    from explorer_route import plan_explore_route
    from gps_state import get_fix
    from valhalla_client import ValhallaError

    lat, lon = body.lat, body.lon
    heading = body.heading_deg
    fix = None
    if lat is None or lon is None or heading is None:
        fix = get_fix(user["id"])
    if lat is None or lon is None:
        if not fix:
            raise HTTPException(400, "No GPS fix — spawn on the map or send lat/lon")
        lat, lon = fix["lat"], fix["lon"]
    if heading is None and fix:
        heading = fix.get("heading_deg")

    level = get_level(user["id"], body.level_id)
    if not level:
        raise HTTPException(404, "Level not found")
    if level.get("status") != "ready":
        raise HTTPException(409, "Level is not ready yet")

    set_user_setting(user["id"], "navigation_active", "true")
    try:
        result = plan_explore_route(
            user["id"],
            body.level_id,
            float(lat),
            float(lon),
            target_km=body.target_km,
            language=body.language,
            heading_deg=float(heading) if heading is not None else None,
            exclude_dead_ends=bool(body.exclude_dead_ends),
        )
    except ValhallaError as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        # e.g. connection dropped mid-build — never 500 the HUD
        raise HTTPException(
            503,
            f"Valhalla error (still building?). {exc}",
        ) from exc
    return {"ok": True, "route": result}


@app.get("/api/system/status")
def system_status(user: dict | None = Depends(get_optional_user)):
    return collect_system_status(user_id=user["id"] if user else None)


@app.post("/api/localize/recompute")
def localize_recompute(body: RecomputeBody, user: dict = Depends(get_current_user)):
    if body.async_job and not body.network_ids:
        job = enqueue_job(
            user["id"],
            "localize",
            {"mode": body.mode, "precision": body.precision},
        )
        return {"ok": True, "queued": True, "job_id": job["id"], "mode": body.mode, "precision": body.precision}
    if body.mode == "3d":
        updated = recompute_3d(
            body.network_ids,
            user_id=user["id"],
            precision=body.precision,
            geocode=False,
        )
    else:
        updated = recompute_2d(
            body.network_ids,
            user_id=user["id"],
            precision=body.precision,
            geocode=False,
        )
    geo_job = enqueue_job(
        user["id"],
        "geocode",
        {
            "network_ids": body.network_ids,
            "only_missing": False,
            "priority": 50,
        },
    )
    return {
        "ok": True,
        "queued": False,
        "mode": body.mode,
        "precision": body.precision,
        "updated": updated,
        "geocode_job_id": geo_job["id"],
    }


@app.get("/api/jobs")
def jobs_list(user: dict = Depends(get_current_user)):
    return list_jobs(user["id"])


@app.get("/api/jobs/{job_id}")
def jobs_get(job_id: int, user: dict = Depends(get_current_user)):
    job = get_job(job_id, user["id"])
    if not job:
        raise HTTPException(404, "Job not found")
    return job


# ----- Levels -----


@app.get("/api/geofabrik/search")
def geofabrik_search(q: str = Query(min_length=1), user: dict = Depends(get_current_user)):
    """Low-level extract search (admin/debug). Prefer /api/levels/places/search."""
    return search_geofabrik(q)


@app.get("/api/levels/places/search")
def levels_place_search(
    q: str = Query(min_length=1, description="e.g. Berlin, Germany"),
    user: dict = Depends(get_current_user),
):
    """Place-first search for the levels wizard (local cities DB; map pack resolved in background)."""
    _ = user
    try:
        return search_level_places(q)
    except FileNotFoundError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/api/levels/places/prepare")
def levels_place_prepare(body: PlacePrepareBody, user: dict = Depends(get_current_user)):
    """
    Download (and keep) the regional Geofabrik PBF if needed, index admin outlines,
    then return whole-city + district options with approximate areas.
    """
    job = enqueue_job(
        user["id"],
        "prepare_place",
        {
            "lat": body.lat,
            "lon": body.lon,
            "name": body.name,
            "geofabrik_id": body.geofabrik_id,
            "population": body.population,
            "bbox": body.bbox,
            "parent_label": body.parent_label,
            "country_code": body.country_code,
            "geoname_id": body.geoname_id,
        },
    )
    return {"job": job}


@app.get("/api/levels/places/parts")
def levels_place_parts(
    lat: float = Query(...),
    lon: float = Query(...),
    name: str | None = Query(default=None),
    country_code: str | None = Query(default=None),
    geoname_id: int | None = Query(default=None),
    population: int | None = Query(default=None),
    parent_label: str | None = Query(default=None),
    geofabrik_id: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """
    OSM districts (next admin level) for a large city — names/centroids only.

    Full polygons load when a district is selected. Small cities return [].
    """
    _ = user
    from level_places import city_parts_as_places
    from geofabrik import resolve_feature

    map_pack = None
    if geofabrik_id:
        feat = resolve_feature(geofabrik_id)
        if feat and feat.get("pbf_url"):
            map_pack = {
                "id": feat["id"],
                "name": feat.get("name"),
                "pbf_url": feat["pbf_url"],
                "size_bytes": feat.get("size_bytes"),
                "blurb": "regional OpenStreetMap road data",
            }
    try:
        return city_parts_as_places(
            lat=lat,
            lon=lon,
            name=name,
            country_code=country_code,
            geoname_id=geoname_id,
            population=population,
            parent_label=parent_label,
            map_pack=map_pack,
        )
    except Exception as exc:
        raise HTTPException(502, f"District lookup failed: {exc}") from exc


@app.get("/api/levels/places/boundary")
def levels_place_boundary(
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    name: str | None = Query(default=None),
    country_code: str | None = Query(default=None),
    geoname_id: int | None = Query(default=None),
    osm_relation_id: int | None = Query(default=None),
    geofabrik_id: str | None = Query(default=None),
    user: dict = Depends(get_current_user),
):
    """Exact OSM administrative boundary from the local admin index."""
    _ = user
    from city_boundaries import resolve_city_boundary, resolve_relation_boundary

    try:
        if osm_relation_id is not None:
            result = resolve_relation_boundary(osm_relation_id)
        elif lat is not None and lon is not None:
            result = resolve_city_boundary(
                lat=lat,
                lon=lon,
                name=name,
                country_code=country_code,
                geoname_id=geoname_id,
                geofabrik_id=geofabrik_id,
            )
        else:
            raise HTTPException(400, "Provide osm_relation_id or lat/lon")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Boundary lookup failed: {exc}") from exc
    if not result.get("boundary"):
        raise HTTPException(
            404, result.get("error") or "Boundary not found"
        )
    return result


@app.get("/api/levels")
def levels_list(user: dict = Depends(get_current_user)):
    return list_levels(user["id"])


@app.post("/api/levels")
def levels_create(body: LevelCreateBody, user: dict = Depends(get_current_user)):
    try:
        level = create_level(
            user["id"],
            body.name,
            body.place_query,
            body.profile,
            body.geofabrik_id,
            place_bbox=body.place_bbox,
            place_boundary=body.place_boundary,
            place_kind=body.place_kind,
            geoname_id=body.geoname_id,
            parent_geoname_id=body.parent_geoname_id,
            parent_label=body.parent_label,
            part_label=body.part_label,
            osm_relation_id=body.osm_relation_id,
            osm_admin_level=body.osm_admin_level,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    job = None
    if body.download_now:
        job = enqueue_job(
            user["id"], "geofabrik_level", {"level_id": level["id"]}
        )
    return {"level": level, "job": job}


@app.get("/api/levels/{level_id}")
def levels_get(level_id: int, user: dict = Depends(get_current_user)):
    level = get_level(user["id"], level_id)
    if not level:
        raise HTTPException(404, "Level not found")
    return level


@app.delete("/api/levels/{level_id}")
def levels_delete(level_id: int, user: dict = Depends(get_current_user)):
    if not delete_level(user["id"], level_id):
        raise HTTPException(404, "Level not found")
    return {"ok": True}


@app.post("/api/levels/{level_id}/download")
def levels_download(level_id: int, user: dict = Depends(get_current_user)):
    level = get_level(user["id"], level_id)
    if not level:
        raise HTTPException(404, "Level not found")
    job = enqueue_job(user["id"], "geofabrik_level", {"level_id": level_id})
    return {"ok": True, "job": job}


@app.post("/api/levels/active")
def set_active_level(body: ActiveLevelBody, user: dict = Depends(get_current_user)):
    if body.level_id is None:
        set_user_setting(user["id"], "active_level_id", "")
        return {"active_level_id": None}
    level = get_level(user["id"], body.level_id)
    if not level:
        raise HTTPException(404, "Level not found")
    set_user_setting(user["id"], "active_level_id", str(body.level_id))
    return {"active_level_id": body.level_id, "level": level}


@app.get("/api/levels/{level_id}/roads")
def levels_roads_map(level_id: int, user: dict = Depends(get_current_user)):
    """Discover view: locked vs explored road grid (not turn-by-turn)."""
    data = get_level_road_map(user["id"], level_id)
    if not data:
        raise HTTPException(404, "Level not found")
    if data["level"]["status"] != "ready":
        raise HTTPException(409, "Level is not ready yet")
    return data


# ----- Triangulated DB API v2 (WiGLE-style search) -----


def _parse_bbox_tuple(value: str | None):
    box = parse_bbox(value)
    return box


@app.get(
    "/api/v2/network/search",
    tags=["network"],
    summary="Search triangulated networks",
)
def network_search(
    ssid: str | None = Query(default=None, description="SSID / name (substring, case-insensitive)"),
    ssid_exact: bool = Query(default=False, description="Exact SSID match"),
    netid: str | None = Query(default=None, description="MAC / BSSID (partial OK, separators ignored)"),
    mac: str | None = Query(default=None, description="Alias for netid"),
    network_type: str | None = Query(
        default=None, alias="type", description="WIFI | BT | BLE"
    ),
    encryption: str | None = None,
    exclude_no_ssid: bool = False,
    seen_after: datetime | None = None,
    seen_before: datetime | None = None,
    min_samples: int | None = Query(default=None, ge=1),
    localization_mode: str | None = Query(default=None, pattern="^(2d|3d)$"),
    place: str | None = Query(
        default=None,
        description="Place name → geocoded bbox (e.g. Berlin, or street + city)",
    ),
    postalcode: str | None = Query(default=None, description="ZIP / postal code (e.g. 10115)"),
    zip_code: str | None = Query(
        default=None, alias="zip", description="Alias for postalcode"
    ),
    country: str | None = Query(default=None, description="ISO country code hint, e.g. de"),
    city: str | None = Query(default=None, description="Filter stored city (after localization)"),
    address: str | None = Query(
        default=None, description="Substring match on stored address"
    ),
    max_accuracy_m: float | None = Query(
        default=None,
        ge=0,
        description="Only networks with location_accuracy_m <= this (meters)",
    ),
    bbox: str | None = Query(default=None, description="west,south,east,north"),
    latrange1: float | None = None,
    latrange2: float | None = None,
    longrange1: float | None = None,
    longrange2: float | None = None,
    near: str | None = Query(default=None, description="lat,lon — order by distance"),
    radius_m: float = Query(default=500.0, ge=1, le=50000),
    search_after: str | None = Query(default=None, alias="searchAfter"),
    limit: int = Query(default=100, ge=1, le=1000),
    reverse: bool = Query(
        default=False,
        description="Live reverse-geocode if address not yet stored (slower)",
    ),
    onlyresults: bool = False,
    user: dict = Depends(get_current_user),
):
    """
    Search your triangulated (`networks`) database.

    Combine freely, e.g. SSID + place: `?ssid=XY&place=Berlin`  
    or MAC + ZIP: `?mac=AA:BB:CC&postalcode=10115&country=de`

    After localization, `address` / `city` / `postcode` / `location_accuracy_m` are stored
    on each network and returned in results.
    """
    box = _parse_bbox_tuple(bbox)
    return search_networks(
        user["id"],
        ssid=ssid,
        ssid_exact=ssid_exact,
        netid=netid,
        mac=mac,
        network_type=network_type,
        encryption=encryption,
        exclude_no_ssid=exclude_no_ssid,
        seen_after=seen_after,
        seen_before=seen_before,
        min_samples=min_samples,
        localization_mode=localization_mode,
        place=place,
        postalcode=postalcode,
        zip_code=zip_code,
        country=country,
        city=city,
        address_q=address,
        max_location_accuracy_m=max_accuracy_m,
        bbox=box,
        latrange1=latrange1,
        latrange2=latrange2,
        longrange1=longrange1,
        longrange2=longrange2,
        near=near,
        radius_m=radius_m,
        search_after=search_after,
        limit=limit,
        reverse=reverse,
        onlyresults=onlyresults,
    )


@app.get(
    "/api/v2/network/detail",
    tags=["network"],
    summary="Network detail by MAC/BSSID",
)
def network_detail(
    netid: str = Query(..., description="MAC / BSSID"),
    include_samples: bool = Query(default=False, description="Include raw sample summary"),
    reverse: bool = Query(default=True, description="Reverse-geocode the triangulated point"),
    user: dict = Depends(get_current_user),
):
    detail = get_network_detail(
        user["id"], netid, include_samples=include_samples, reverse=reverse
    )
    if not detail:
        raise HTTPException(404, "Network not found")
    return {"success": True, "result": detail}


@app.get(
    "/api/v2/network/geojson",
    tags=["network"],
    summary="Search as GeoJSON FeatureCollection",
)
def network_geojson(
    ssid: str | None = None,
    ssid_exact: bool = False,
    netid: str | None = None,
    mac: str | None = None,
    network_type: str | None = Query(default=None, alias="type"),
    encryption: str | None = None,
    exclude_no_ssid: bool = False,
    seen_after: datetime | None = None,
    seen_before: datetime | None = None,
    min_samples: int | None = Query(default=None, ge=1),
    localization_mode: str | None = Query(default=None, pattern="^(2d|3d)$"),
    place: str | None = None,
    postalcode: str | None = None,
    zip_code: str | None = Query(default=None, alias="zip"),
    country: str | None = None,
    bbox: str | None = None,
    latrange1: float | None = None,
    latrange2: float | None = None,
    longrange1: float | None = None,
    longrange2: float | None = None,
    near: str | None = None,
    radius_m: float = Query(default=500.0, ge=1, le=50000),
    search_after: str | None = Query(default=None, alias="searchAfter"),
    limit: int = Query(default=100, ge=1, le=1000),
    user: dict = Depends(get_current_user),
):
    box = _parse_bbox_tuple(bbox)
    return search_geojson(
        user["id"],
        ssid=ssid,
        ssid_exact=ssid_exact,
        netid=netid,
        mac=mac,
        network_type=network_type,
        encryption=encryption,
        exclude_no_ssid=exclude_no_ssid,
        seen_after=seen_after,
        seen_before=seen_before,
        min_samples=min_samples,
        localization_mode=localization_mode,
        place=place,
        postalcode=postalcode,
        zip_code=zip_code,
        country=country,
        bbox=box,
        latrange1=latrange1,
        latrange2=latrange2,
        longrange1=longrange1,
        longrange2=longrange2,
        near=near,
        radius_m=radius_m,
        search_after=search_after,
        limit=limit,
    )


@app.get("/api/v2/stats", tags=["network"], summary="Triangulated DB stats")
def network_stats_v2(user: dict = Depends(get_current_user)):
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM signal_samples WHERE user_id = %s) AS samples,
                    COUNT(*) AS networks,
                    COUNT(*) FILTER (WHERE upper(network_type)='WIFI') AS wifi,
                    COUNT(*) FILTER (WHERE upper(network_type)='BT') AS bt,
                    COUNT(*) FILTER (WHERE upper(network_type)='BLE') AS ble
                FROM networks WHERE user_id = %s
                """,
                (user["id"], user["id"]),
            )
            return {"success": True, **cur.fetchone()}
    finally:
        conn.close()


@app.get("/api/v2/geocode", tags=["geocode"], summary="Forward geocode place or ZIP")
def api_geocode(
    place: str | None = None,
    postalcode: str | None = None,
    zip_code: str | None = Query(default=None, alias="zip"),
    country: str | None = Query(default="de"),
    user: dict = Depends(get_current_user),
):
    """Resolve Berlin / 10115 → bbox for composing searches."""
    _ = user
    pc = postalcode or zip_code
    if pc:
        return {"success": True, "results": geocode_postalcode(pc, country=country)}
    if place:
        return {"success": True, "results": geocode_place(place, country=country)}
    raise HTTPException(400, "Provide place or postalcode")


@app.get("/api/v2/geocode/reverse", tags=["geocode"], summary="Reverse geocode lat,lon")
def api_geocode_reverse(
    lat: float,
    lon: float,
    user: dict = Depends(get_current_user),
):
    _ = user
    hit = reverse_geocode(lat, lon)
    if not hit:
        raise HTTPException(404, "No reverse geocode result")
    return {"success": True, "result": hit}


@app.get("/api/explore/view")
def explore_view(user: dict = Depends(get_current_user)):
    """
    Camera helper for the Database map (no markers drawn).

    Until the user has at least 100 triangulated networks, return enough=false
    so the UI keeps the default Europe view. At 100+, sample 100 random points
    and return their bbox so the map can fit all of them.
    """
    sample_n = 100
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)::int AS total
                FROM networks
                WHERE user_id = %s
                  AND geom IS NOT NULL
                  AND lat BETWEEN -90 AND 90
                  AND lon BETWEEN -180 AND 180
                """,
                (user["id"],),
            )
            total = int((cur.fetchone() or {}).get("total") or 0)
            if total < sample_n:
                return {
                    "ok": True,
                    "n": total,
                    "enough": False,
                    "center": None,
                    "bbox": None,
                    "default": "europe",
                }

            cur.execute(
                """
                SELECT
                  COUNT(*)::int AS n,
                  AVG(lat)::float AS center_lat,
                  AVG(lon)::float AS center_lon,
                  MIN(lon)::float AS west,
                  MIN(lat)::float AS south,
                  MAX(lon)::float AS east,
                  MAX(lat)::float AS north
                FROM (
                  SELECT lat, lon
                  FROM networks
                  WHERE user_id = %s
                    AND geom IS NOT NULL
                    AND lat BETWEEN -90 AND 90
                    AND lon BETWEEN -180 AND 180
                  ORDER BY random()
                  LIMIT %s
                ) sample
                """,
                (user["id"], sample_n),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    n = int(row["n"] or 0) if row else 0
    if n < sample_n:
        return {
            "ok": True,
            "n": n,
            "enough": False,
            "center": None,
            "bbox": None,
            "default": "europe",
        }

    west, south, east, north = (
        float(row["west"]),
        float(row["south"]),
        float(row["east"]),
        float(row["north"]),
    )
    # Degenerate / single-point sample: tiny pad so Leaflet can zoom sensibly
    if west == east:
        west -= 0.01
        east += 0.01
    if south == north:
        south -= 0.01
        north += 0.01

    return {
        "ok": True,
        "n": n,
        "enough": True,
        "center": {
            "lat": float(row["center_lat"]),
            "lon": float(row["center_lon"]),
        },
        "bbox": [west, south, east, north],
    }


@app.get("/api/explore")
def explore(
    network_type: str | None = None,
    encryption: str | None = None,
    name: str | None = None,
    network_id: str | None = None,
    exclude_no_ssid: bool = False,
    seen_after: datetime | None = None,
    seen_before: datetime | None = None,
    bbox: str | None = Query(default=None, description="west,south,east,north"),
    limit: int = Query(default=8000, ge=1, le=20000),
    user: dict = Depends(get_current_user),
):
    box = parse_bbox(bbox)
    filters = dict(
        user_id=user["id"],
        network_type=network_type,
        encryption=encryption,
        name=name,
        network_id=network_id,
        exclude_no_ssid=exclude_no_ssid,
        seen_after=seen_after,
        seen_before=seen_before,
        bbox=box,
    )

    sql = "SELECT * FROM networks WHERE 1=1"
    sql, params = apply_filters(sql, [], **filters)
    sql += " ORDER BY last_seen DESC NULLS LAST LIMIT %s"
    params = list(params) + [limit]

    conn = connect_dict()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        count_sql, count_params = apply_filters(
            "SELECT COUNT(*) AS matched FROM networks WHERE 1=1", [], **filters
        )
        cur.execute(count_sql, count_params)
        matched = cur.fetchone()["matched"]
    conn.close()

    features = []
    for row in rows:
        props = dict(row)
        props.pop("geom", None)
        props["seen_at"] = props.get("last_seen")
        props["signal"] = props.get("avg_signal")
        for key in ("first_seen", "last_seen", "computed_at", "seen_at"):
            if props.get(key) is not None:
                props[key] = props[key].isoformat()
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [props["lon"], props["lat"]]},
                "properties": props,
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "returned": len(features),
            "matched_networks": matched,
            "matched_observations": matched,
            "truncated": matched > len(features),
            "unique": True,
        },
    }


# ----- Pages -----


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")


@app.get("/login")
def login_page():
    return FileResponse(FRONTEND / "login.html")


@app.get("/database")
def database_page():
    return FileResponse(FRONTEND / "database.html")


@app.get("/status")
def status_page():
    return FileResponse(FRONTEND / "status.html")


@app.get("/stats")
def stats_page():
    return FileResponse(FRONTEND / "stats.html")


@app.get("/settings")
def settings_page():
    return FileResponse(FRONTEND / "settings.html")


@app.get("/levels")
def levels_page():
    return FileResponse(FRONTEND / "levels.html")


@app.get("/discover")
def discover_page():
    return FileResponse(FRONTEND / "discover.html")


@app.get("/navigate")
def navigate_page():
    return FileResponse(FRONTEND / "navigate.html")


@app.get("/achievements")
def achievements_page():
    return FileResponse(FRONTEND / "achievements.html")


@app.get("/api")
def api_page():
    """Friendly API explorer WebUI (interactive docs also at /api/docs)."""
    return FileResponse(FRONTEND / "api.html")


@app.get("/api/docs", include_in_schema=False)
def swagger_ui():
    """
    Swagger UI that auto-authorizes with the WebUI JWT from localStorage
    (`wardrivrr_token` — same origin as the API menu).
    """
    html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>wardrivrr — API</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"/>
  <style>
    body { margin: 0; background: #fafafa; }
    .topbar { display: none; }
    .auth-banner {
      font: 13px/1.4 system-ui, sans-serif;
      padding: 8px 16px;
      background: #1b4332;
      color: #d8f3dc;
    }
    .auth-banner.warn { background: #6c3b2a; color: #ffe8d6; }
  </style>
</head>
<body>
  <div id="authBanner" class="auth-banner">Authorizing with your WebUI login…</div>
  <div id="swagger-ui"></div>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"></script>
  <script>
  (function () {
    var TOKEN_KEY = "wardrivrr_token";
    var token = null;
    try { token = localStorage.getItem(TOKEN_KEY); } catch (e) {}
    var banner = document.getElementById("authBanner");
    if (!token) {
      banner.className = "auth-banner warn";
      banner.textContent = "No WebUI login token found — use Authorize, or open Swagger from the API page while logged in.";
    } else {
      banner.textContent = "Authorized with your current WebUI login (Bearer). You can still change it via Authorize.";
    }
    var ui = SwaggerUIBundle({
      url: "/api/openapi.json",
      dom_id: "#swagger-ui",
      presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset],
      layout: "StandaloneLayout",
      persistAuthorization: true,
      displayRequestDuration: true,
      onComplete: function () {
        if (!token) return;
        try {
          ui.preauthorizeApiKey("HTTPBearer", token);
        } catch (e) {}
        try {
          ui.authActions.authorize({
            HTTPBearer: {
              name: "HTTPBearer",
              schema: { type: "http", scheme: "bearer", bearerFormat: "JWT" },
              value: token
            }
          });
        } catch (e) { console.warn(e); }
      }
    });
    window.ui = ui;
  })();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
