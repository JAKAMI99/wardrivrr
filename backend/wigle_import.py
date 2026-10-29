"""Download a user's WiGLE uploads (CSV) and ingest into wardrivrr."""

from __future__ import annotations

import base64
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from db import get_user_setting, set_user_setting
from ingest_upload import ingest_file_for_user
from paths import user_incoming

WIGLE_API_BASE = "https://api.wigle.net"
WIGLE_ACCOUNT_URL = "https://wigle.net/account"
WIGLE_PAGE_SIZE = 100
WIGLE_REQUEST_TIMEOUT = 120

_KEY_NAME = "wigle_api_name"
_KEY_TOKEN = "wigle_api_token"

_ALLOWED_FILENAME = re.compile(r"[^a-zA-Z0-9._-]+")


def wigle_account_url() -> str:
    return WIGLE_ACCOUNT_URL


def _mask_suffix(value: str | None, *, tail: int = 4) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if len(text) <= tail:
        return "*" * len(text)
    return f"{'*' * (len(text) - tail)}{text[-tail:]}"


def credentials_status(user_id: int) -> dict:
    name = (get_user_setting(user_id, _KEY_NAME, "") or "").strip()
    token = (get_user_setting(user_id, _KEY_TOKEN, "") or "").strip()
    configured = bool(name and token)
    return {
        "configured": configured,
        "api_name_suffix": _mask_suffix(name) if name else None,
        "api_token_suffix": _mask_suffix(token) if token else None,
        "account_url": WIGLE_ACCOUNT_URL,
    }


def save_credentials(user_id: int, api_name: str, api_token: str) -> dict:
    name = (api_name or "").strip()
    token = (api_token or "").strip()
    if not name or not token:
        raise ValueError("WiGLE API name and token are both required")
    set_user_setting(user_id, _KEY_NAME, name)
    set_user_setting(user_id, _KEY_TOKEN, token)
    return credentials_status(user_id)


def _load_credentials(
    user_id: int,
    *,
    api_name: str | None = None,
    api_token: str | None = None,
) -> tuple[str, str]:
    name = (api_name or get_user_setting(user_id, _KEY_NAME, "") or "").strip()
    token = (api_token or get_user_setting(user_id, _KEY_TOKEN, "") or "").strip()
    if not name or not token:
        raise ValueError(
            "WiGLE API credentials are not saved. Enter API name and token first."
        )
    return name, token


def _basic_auth_header(api_name: str, api_token: str) -> str:
    raw = f"{api_name}:{api_token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _http_get(
    url: str,
    *,
    auth_header: str,
    accept: str,
) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "Authorization": auth_header,
            "User-Agent": "wardrivrr/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=WIGLE_REQUEST_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code == 401:
            raise PermissionError(
                "WiGLE rejected the API credentials (401). Check API name and token at wigle.net/account."
            ) from exc
        if exc.code == 429:
            raise RuntimeError(
                "WiGLE rate limit reached (429). Wait and try again, or import fewer files at a time."
            ) from exc
        raise RuntimeError(f"WiGLE HTTP {exc.code}: {body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach WiGLE API: {exc.reason}") from exc


def _sanitize_filename(name: str, transid: str) -> str:
    base = (name or f"wigle-{transid}").strip()
    if not base.lower().endswith(".csv"):
        base = f"{base}.csv"
    safe = _ALLOWED_FILENAME.sub("_", base)
    return safe or f"wigle-{transid}.csv"


def _list_transactions(auth_header: str) -> list[dict]:
    transactions: list[dict] = []
    pagestart = 0
    while True:
        pageend = pagestart + WIGLE_PAGE_SIZE
        url = (
            f"{WIGLE_API_BASE}/api/v2/file/transactions"
            f"?pagestart={pagestart}&pageend={pageend}"
        )
        raw = _http_get(url, auth_header=auth_header, accept="application/json")
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("WiGLE returned invalid JSON for file list") from exc
        if not data.get("success", True) and not data.get("results"):
            detail = data.get("message") or data.get("error") or "unknown error"
            raise RuntimeError(f"WiGLE file list failed: {detail}")
        batch = data.get("results") or []
        if not batch:
            break
        transactions.extend(batch)
        total = int(data.get("totalResults") or 0)
        pagestart += len(batch)
        if pagestart >= total or len(batch) < WIGLE_PAGE_SIZE:
            break
        time.sleep(0.25)
    return transactions


def _csv_header_ok(path: Path) -> bool:
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
            first = handle.readline()
        return first.lower().startswith("wiglewifi")
    except OSError:
        return False


def import_from_wigle(
    user_id: int,
    *,
    api_name: str | None = None,
    api_token: str | None = None,
    mode: str = "2d",
    precision: str = "balanced",
    skip_existing: bool = True,
) -> dict:
    name, token = _load_credentials(user_id, api_name=api_name, api_token=api_token)
    if api_name and api_token:
        save_credentials(user_id, name, token)

    auth_header = _basic_auth_header(name, token)
    transactions = _list_transactions(auth_header)
    incoming = user_incoming(user_id)

    downloaded = 0
    skipped = 0
    empty = 0
    failed: list[dict] = []
    files_ingested: list[dict] = []
    total_samples = 0
    total_networks = 0

    for item in transactions:
        transid = (item.get("transid") or "").strip()
        file_name = (item.get("fileName") or item.get("filename") or "").strip()
        if not transid:
            continue
        dest_name = _sanitize_filename(file_name, transid)
        dest = incoming / dest_name
        if skip_existing and dest.is_file() and dest.stat().st_size > 0:
            skipped += 1
            continue

        csv_url = f"{WIGLE_API_BASE}/api/v2/file/csv/{transid}"
        try:
            payload = _http_get(
                csv_url,
                auth_header=auth_header,
                accept="text/csv",
            )
        except Exception as exc:
            failed.append({"transid": transid, "file": dest_name, "error": str(exc)})
            continue

        text = payload.decode("utf-8-sig", errors="replace").strip()
        if not text:
            empty += 1
            continue

        dest.write_bytes(payload)
        if not _csv_header_ok(dest):
            failed.append(
                {
                    "transid": transid,
                    "file": dest_name,
                    "error": "Download is not a WiGLE CSV (missing WigleWifi header)",
                }
            )
            dest.unlink(missing_ok=True)
            continue

        downloaded += 1
        try:
            result = ingest_file_for_user(
                user_id,
                dest,
                mode=mode,
                precision=precision,
                copy_to_incoming=False,
            )
            files_ingested.append(result)
            total_samples += int(result.get("samples_submitted") or 0)
            total_networks += int(result.get("networks_updated") or 0)
        except Exception as exc:
            failed.append({"transid": transid, "file": dest_name, "error": str(exc)})
            continue

        time.sleep(0.35)

    return {
        "transactions": len(transactions),
        "downloaded": downloaded,
        "skipped_existing": skipped,
        "empty": empty,
        "files_ingested": len(files_ingested),
        "samples_submitted": total_samples,
        "networks_updated": total_networks,
        "failed": failed[:20],
        "failed_count": len(failed),
    }
