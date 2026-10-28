#!/usr/bin/env python3
"""Download IEEE OUI registries into data/oui/oui.sqlite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local IEEE OUI vendor DB")
    parser.add_argument("--force", action="store_true", help="Rebuild even if present")
    args = parser.parse_args()
    from oui import build_oui_db, db_available

    build_oui_db(force=args.force)
    print(f"ok={db_available()}")
    return 0 if db_available() else 1


if __name__ == "__main__":
    sys.exit(main())
