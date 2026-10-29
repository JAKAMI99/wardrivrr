#!/usr/bin/env python3
"""Reset the admin account password using the same bcrypt hashing as the API.

Examples:
  # Inside the API container (recommended for Docker):
  python /app/scripts/reset_admin_password.py 'YourNewPassword'

  # Local debug (venv + PostGIS reachable):
  python scripts/reset_admin_password.py
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from auth import MIN_PASSWORD_LENGTH, hash_password  # noqa: E402
from db import connect_dict  # noqa: E402


def _pick_admin(cur) -> dict | None:
    cur.execute(
        """
        SELECT id, username FROM users
        WHERE is_admin IS TRUE
        ORDER BY CASE WHEN username = 'admin' THEN 0 ELSE 1 END, id
        LIMIT 1
        """
    )
    return cur.fetchone()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset wardrivrr admin password")
    parser.add_argument(
        "password",
        nargs="?",
        help=f"New password (min {MIN_PASSWORD_LENGTH} chars). Prompted if omitted.",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Specific admin username (default: prefer 'admin', else first admin)",
    )
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("New admin password: ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match", file=sys.stderr)
            return 1

    if len(password) < MIN_PASSWORD_LENGTH:
        print(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        return 1

    conn = connect_dict()
    try:
        with conn.cursor() as cur:
            if args.username:
                cur.execute(
                    """
                    SELECT id, username FROM users
                    WHERE username = %s AND is_admin IS TRUE
                    """,
                    (args.username.strip(),),
                )
                row = cur.fetchone()
            else:
                row = _pick_admin(cur)
            if not row:
                print(
                    "No admin user found. Complete first-boot setup at /setup, "
                    "or create an admin via the UI.",
                    file=sys.stderr,
                )
                return 1
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s",
                (hash_password(password), row["id"]),
            )
        conn.commit()
    finally:
        conn.close()

    print(f"Password updated for admin user '{row['username']}' (id={row['id']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
