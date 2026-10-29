"""Download a user's WiGLE uploads (CSV) and ingest into wardrivrr."""

from __future__ import annotations

import base64
import binascii
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

# Single field: WiGLE "Encoded for Use" (preferred) or legacy name:token
_KEY_API = "wigle_api_key"
# Legacy dual fields — still read for migration
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


def _legacy_combined(user_id: int) -> str:
    name = (get_user_setting(user_id, _KEY_NAME, "") or "").strip()
    token = (get_user_setting(user_id, _KEY_TOKEN, "") or "").strip()
    if name and token:
        return f"{name}:{token}"
    return ""


def _stored_key(user_id: int) -> str:
    key = (get_user_setting(user_id, _KEY_API, "") or "").strip()
    if key:
        return key
    return _legacy_combined(user_id)


def credentials_status(user_id: int) -> dict:
    key = _stored_key(user_id)
    return {
        "configured": bool(key),
        "api_key_suffix": _mask_suffix(key) if key else None,
        "account_url": WIGLE_ACCOUNT_URL,
    }


def save_credentials(user_id: int, api_key: str) -> dict:
    key = (api_key or "").strip()
    if not key:
        raise ValueError("WiGLE API key is required")
    # Normalize so we always store something usable as Basic auth material
    _basic_auth_header(key)  # validate shape early
    set_user_setting(user_id, _KEY_API, key)
    # Clear legacy split fields so status stays consistent
    set_user_setting(user_id, _KEY_NAME, "")
    set_user_setting(user_id, _KEY_TOKEN, "")
    return credentials_status(user_id)


def _basic_auth_header(api_key: str) -> str:
    """Accept Encoded-for-Use (base64) or legacy `APIName:APIToken`."""
    key = (api_key or "").strip()
    if not key:
        raise ValueError("WiGLE API key is empty")

    # Already looks like base64 of name:token (WiGLE "Encoded for Use")
    if ":" not in key:
        try:
            decoded = base64.b64decode(key, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            raise ValueError(
                "WiGLE API key must be the Encoded for Use value from wigle.net/account "
                "(or name:token)."
            ) from exc
        if ":" not in decoded:
            raise ValueError(
                "WiGLE API key does not decode to name:token. Copy Encoded for Use from wigle.net/account."
            )
        return "Basic " + key

    # Legacy plaintext name:token
    return "Basic " + base64.b64encode(key.encode("utf-8")).decode("ascii")


def _load_auth_header(user_id: int, *, api_key: str | None = None) -> str:
    key = (api_key or _stored_key(user_id) or "").strip()
    if not key:
        raise ValueError(
            "WiGLE API key is not saved. Paste Encoded for Use from wigle.net/account first."
        )
    return _basic_auth_header(key)


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
                "WiGLE rejected the API key (401). Copy Encoded for Use from wigle.net/account."
            ) from exc
        if exc.code == 429:
            raise RuntimeError(
                "WiGLE rate limit reached (429). Wait and try again."
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
    """Page through all uploads.

    WiGLE `pageend` is the *page size* (default 100), not an exclusive end index.
    Older code used pageend=pagestart+100 and stopped when totalResults was 0/missing
    after a full page — that capped imports at exactly 100 files.
    """
    transactions: list[dict] = []
    pagestart = 0
    while True:
        url = (
            f"{WIGLE_API_BASE}/api/v2/file/transactions"
            f"?pagestart={pagestart}&pageend={WIGLE_PAGE_SIZE}"
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
        pagestart += len(batch)
        total = int(data.get("totalResults") or 0)
        # Full page → keep going even if totalResults is missing/wrong.
        if len(batch) < WIGLE_PAGE_SIZE:
            break
        if total > 0 and pagestart >= total:
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
    api_key: str | None = None,
    mode: str = "2d",
    precision: str = "balanced",
    skip_existing: bool = True,
    progress_cb=None,
) -> dict:
    """Import all WiGLE uploads. progress_cb receives dict events for UI streaming."""

    def emit(**event: object) -> None:
        if progress_cb is not None:
            try:
                progress_cb(event)
            except Exception:
                pass

    if api_key and api_key.strip():
        save_credentials(user_id, api_key.strip())
    auth_header = _load_auth_header(user_id, api_key=api_key)

    emit(stage="listing", message="Listing WiGLE uploads…")
    transactions = _list_transactions(auth_header)
    total = len(transactions)
    emit(stage="listed", total=total, message=f"Found {total} upload(s)")

    incoming = user_incoming(user_id)
    downloaded = 0
    skipped = 0
    empty = 0
    failed: list[dict] = []
    files_ingested: list[dict] = []
    total_samples = 0
    total_networks = 0

    for index, item in enumerate(transactions, start=1):
        transid = (item.get("transid") or "").strip()
        file_name = (item.get("fileName") or item.get("filename") or "").strip()
        if not transid:
            emit(
                stage="file",
                current=index,
                total=total,
                status="skipped",
                message=f"{index}/{total} · missing transid",
            )
            continue
        dest_name = _sanitize_filename(file_name, transid)
        dest = incoming / dest_name
        if skip_existing and dest.is_file() and dest.stat().st_size > 0:
            skipped += 1
            emit(
                stage="file",
                current=index,
                total=total,
                file=dest_name,
                status="skipped",
                message=f"{index}/{total} · skipped (already have {dest_name})",
            )
            continue

        emit(
            stage="file",
            current=index,
            total=total,
            file=dest_name,
            status="downloading",
            message=f"{index}/{total} · downloading {dest_name}",
        )
        csv_url = f"{WIGLE_API_BASE}/api/v2/file/csv/{transid}"
        try:
            payload = _http_get(
                csv_url,
                auth_header=auth_header,
                accept="text/csv",
            )
        except Exception as exc:
            failed.append({"transid": transid, "file": dest_name, "error": str(exc)})
            emit(
                stage="file",
                current=index,
                total=total,
                file=dest_name,
                status="failed",
                message=f"{index}/{total} · failed {dest_name}",
                error=str(exc)[:200],
            )
            continue

        text = payload.decode("utf-8-sig", errors="replace").strip()
        if not text:
            empty += 1
            emit(
                stage="file",
                current=index,
                total=total,
                file=dest_name,
                status="empty",
                message=f"{index}/{total} · empty {dest_name}",
            )
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
            emit(
                stage="file",
                current=index,
                total=total,
                file=dest_name,
                status="failed",
                message=f"{index}/{total} · not a WiGLE CSV ({dest_name})",
            )
            continue

        emit(
            stage="file",
            current=index,
            total=total,
            file=dest_name,
            status="ingesting",
            message=f"{index}/{total} · ingesting {dest_name}",
        )
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
            emit(
                stage="file",
                current=index,
                total=total,
                file=dest_name,
                status="ingested",
                samples=int(result.get("samples_submitted") or 0),
                message=f"{index}/{total} · done {dest_name}",
            )
        except Exception as exc:
            failed.append({"transid": transid, "file": dest_name, "error": str(exc)})
            emit(
                stage="file",
                current=index,
                total=total,
                file=dest_name,
                status="failed",
                message=f"{index}/{total} · ingest failed {dest_name}",
                error=str(exc)[:200],
            )
            continue

        time.sleep(0.35)

    summary = {
        "stage": "done",
        "transactions": total,
        "downloaded": downloaded,
        "skipped_existing": skipped,
        "empty": empty,
        "files_ingested": len(files_ingested),
        "samples_submitted": total_samples,
        "networks_updated": total_networks,
        "failed": failed[:20],
        "failed_count": len(failed),
        "message": (
            f"Done · {len(files_ingested)}/{total} files · "
            f"{total_samples} samples"
        ),
    }
    emit(**summary)
    return summary
