from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, Response, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from db import connect_dict

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "wardrivrr_dev_change_me")
JWT_ALG = "HS256"

# New random value every process start → all prior JWTs/cookies become invalid.
SESSION_EPOCH = secrets.token_urlsafe(24)

COOKIE_NAME = "wardrivrr_session"
COOKIE_PATH = "/"
# Persistent login (Keep me logged in) — absolute max lifetime for any WebUI session
REMEMBER_DAYS = 30
# Without the checkbox: browser session cookie (no Max-Age). JWT still capped at 30d
# so a stolen bearer cannot outlive the "keep logged in" maximum.

bearer_scheme = HTTPBearer(auto_error=False)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(
    user_id: int,
    username: str,
    is_admin: bool,
    *,
    keep_logged_in: bool = False,
) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=REMEMBER_DAYS)
    payload = {
        "sub": str(user_id),
        "username": username,
        "is_admin": is_admin,
        "exp": exp,
        "iat": now,
        "epoch": SESSION_EPOCH,
        "remember": bool(keep_logged_in),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def decode_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc
    if payload.get("epoch") != SESSION_EPOCH:
        raise HTTPException(401, "Session expired (server restarted)")
    return payload


def set_session_cookie(
    response: Response,
    token: str,
    *,
    keep_logged_in: bool,
    secure: bool = False,
) -> None:
    """HttpOnly session cookie. Session cookie if not keep_logged_in; else max 30 days."""
    kwargs: dict[str, Any] = {
        "key": COOKIE_NAME,
        "value": token,
        "httponly": True,
        "samesite": "lax",
        "secure": secure,
        "path": COOKIE_PATH,
    }
    if keep_logged_in:
        kwargs["max_age"] = REMEMBER_DAYS * 24 * 3600
    response.set_cookie(**kwargs)


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH)


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (full_key, prefix, hash). Full key shown once."""
    raw = "wr_" + secrets.token_urlsafe(32)
    prefix = raw[:10]
    return raw, prefix, hash_api_key(raw)


def get_user_by_id(user_id: int) -> dict | None:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, is_admin, created_at FROM users WHERE id = %s",
                (user_id,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash, is_admin, created_at FROM users WHERE username = %s",
                (username,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def ensure_bootstrap_admin(username: str = "admin", password: str = "admin") -> dict | None:
    """Create first admin if no users exist. Returns created user or None."""
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM users")
            if cur.fetchone()["n"] > 0:
                return None
            cur.execute(
                """
                INSERT INTO users (username, password_hash, is_admin)
                VALUES (%s, %s, TRUE)
                RETURNING id, username, is_admin, created_at
                """,
                (username, hash_password(password)),
            )
            user = cur.fetchone()
            # Assign orphaned data to admin
            cur.execute(
                "UPDATE signal_samples SET user_id = %s WHERE user_id IS NULL",
                (user["id"],),
            )
            cur.execute(
                "UPDATE networks SET user_id = %s WHERE user_id IS NULL",
                (user["id"],),
            )
            cur.execute(
                """
                INSERT INTO user_settings (user_id, key, value)
                VALUES (%s, 'default_localization_mode', '2d'),
                       (%s, 'default_localize_precision', 'balanced')
                ON CONFLICT DO NOTHING
                """,
                (user["id"], user["id"]),
            )
        conn.commit()
        return user
    finally:
        conn.close()


def authenticate_api_key(raw_key: str) -> dict | None:
    if not raw_key or not raw_key.startswith("wr_"):
        return None
    prefix = raw_key[:10]
    digest = hash_api_key(raw_key)
    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT k.id AS key_id, k.user_id, u.username, u.is_admin
                FROM api_keys k
                JOIN users u ON u.id = k.user_id
                WHERE k.key_prefix = %s AND k.revoked_at IS NULL
                """,
                (prefix,),
            )
            rows = cur.fetchall()
            for row in rows:
                cur.execute("SELECT key_hash FROM api_keys WHERE id = %s", (row["key_id"],))
                stored = cur.fetchone()
                if stored and hmac.compare_digest(stored["key_hash"], digest):
                    cur.execute(
                        "UPDATE api_keys SET last_used_at = NOW() WHERE id = %s",
                        (row["key_id"],),
                    )
                    conn.commit()
                    return {
                        "id": row["user_id"],
                        "username": row["username"],
                        "is_admin": row["is_admin"],
                        "auth": "api_key",
                        "key_id": row["key_id"],
                    }
        return None
    finally:
        conn.close()


def _token_from_request(
    request: Request,
    creds: HTTPAuthorizationCredentials | None,
) -> str | None:
    token = None
    if creds and creds.scheme.lower() == "bearer":
        token = creds.credentials
    if not token:
        auth = request.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if not token:
        cookie = request.cookies.get(COOKIE_NAME)
        if cookie:
            token = cookie.strip()
    return token or None


# Sync on purpose: FastAPI runs sync dependencies in its threadpool, so the
# psycopg2 lookups below never block the event loop.
def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key: str | None = Security(api_key_header),
) -> dict:
    token = _token_from_request(request, creds)

    # Allow Authorization: Bearer wr_… as API key
    raw_key = api_key or (token if token and token.startswith("wr_") else None)
    if raw_key:
        user = authenticate_api_key(raw_key)
        if user:
            return user
        if api_key or (token and token.startswith("wr_")):
            raise HTTPException(401, "Invalid API key")

    if not token or token.startswith("wr_"):
        raise HTTPException(401, "Authentication required")

    payload = decode_token(token)
    user = get_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(401, "User not found")
    user["auth"] = "jwt"
    user["remember"] = bool(payload.get("remember"))
    return user


def get_optional_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    api_key: str | None = Security(api_key_header),
) -> dict | None:
    try:
        return get_current_user(request, creds, api_key)
    except HTTPException:
        return None


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(403, "Admin required")
    return user
