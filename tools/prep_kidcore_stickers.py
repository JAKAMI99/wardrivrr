"""
Re-process extracted Kidcore stickers:
  - edge flood-fill / magic-wand matting (border-connected bg only;
    preserves interior white eyes/teeth/highlights)
  - generic cuts → stickers/random_character/kc-001.png …
  - Bluey → stickers/bluey/bluey-01.png
  - Winnie the Pooh → stickers/winnie_pooh/winnie-01.png
  - Word-art / text PNGs → stickers/legacy/ (optional; HTML phrases in theme.js
    are the main legacy text floats)

Workflow (user-supplied local sheets/PNGs — do not scrape copyrighted art):
  1. Drop transparent PNGs or sheets into frontend/brand/kidcore/
     — Bluey: s-l1600.jpg (or bluey-*.png); Pooh: winnie*/pooh*/winniethepooh*
  2. python tools/extract_kidcore_stickers.py   # if using sheets
  3. python tools/prep_kidcore_stickers.py
  Packs ship under stickers/{bluey,winnie_pooh,random_character,legacy}/ + stickers.json
  See CREDITS.md (DisneyClips gallery links) — we do not redistribute scraped clipart.

Usage:
  python tools/prep_kidcore_stickers.py
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
STICKERS = ROOT / "frontend" / "brand" / "kidcore" / "stickers"
MANIFEST = ROOT / "frontend" / "brand" / "kidcore" / "stickers.json"

PACK_DIRS = {
    "bluey": STICKERS / "bluey",
    "winnie_pooh": STICKERS / "winnie_pooh",
    "random_character": STICKERS / "random_character",
    "legacy": STICKERS / "legacy",
}

# Generic / baby-item / animal sheets → random_character/kc-NNN.png
GENERIC_PREFIXES = (
    "bvmfyckymuha1-",
    "cute-cartoon-animal-kid-journal-sticker-sku1-",
    "cute-cartoon-animal-kid-journal-sticker-sku2-",
    # Etsy / marketplace sheet exports (il_794xN.*)
    "il-794xn-",
)

# Extract slug prefix → recognizable shipped prefix
FRANCHISE_FROM_SHEET = {
    "s-l1600-": "bluey",
}

WINNIE_STEM_PREFIXES = ("winniethepooh", "winnie", "pooh")

# Filenames that are word-art / phrase stickers → legacy/
LEGACY_NAMES = frozenset({"kc-082.png"})


def is_generic(name: str) -> bool:
    n = name.lower()
    if any(n.startswith(p) for p in GENERIC_PREFIXES):
        return True
    return bool(re.fullmatch(r"kc-\d{3}\.png", n))


def _matches_stem_prefix(name: str, stem: str) -> bool:
    n = name.lower()
    if n.startswith(f"{stem}-"):
        return True
    if n.startswith(stem) and len(n) > len(stem) and n[len(stem)].isdigit():
        return True
    return False


def franchise_group(name: str) -> str | None:
    """Return 'bluey' / 'winnie' or None."""
    n = name.lower()
    for sheet_prefix, ship_prefix in FRANCHISE_FROM_SHEET.items():
        if n.startswith(sheet_prefix):
            return ship_prefix
    if n.startswith("bluey-") or _matches_stem_prefix(n, "bluey"):
        return "bluey"
    for stem in WINNIE_STEM_PREFIXES:
        if _matches_stem_prefix(n, stem):
            return "winnie"
    return None


def remove_white_bg(bgra: np.ndarray) -> np.ndarray:
    """Edge flood-fill / magic-wand only — keep interior white (eyes/teeth)."""
    # Shared aggressive halo remat (see tools/_kidcore_remat_franchise.py)
    from _kidcore_remat_franchise import edge_flood_matte

    return edge_flood_matte(bgra)


def load_bgra(path: Path) -> np.ndarray | None:
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        return None
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        b, g, r = cv2.split(img)
        a = np.full(b.shape, 255, np.uint8)
        img = cv2.merge([b, g, r, a])
    return img


def _iter_source_pngs() -> list[Path]:
    """Flat stickers/*.png plus existing pack folders (re-prep safe)."""
    files: list[Path] = []
    files.extend(STICKERS.glob("*.png"))
    for d in PACK_DIRS.values():
        if d.is_dir():
            files.extend(d.glob("*.png"))
    # Dedup by resolved path
    seen: set[Path] = set()
    out: list[Path] = []
    for p in files:
        rp = p.resolve()
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return sorted(out, key=lambda p: p.name.lower())


def main() -> None:
    STICKERS.mkdir(parents=True, exist_ok=True)
    src_files = _iter_source_pngs()

    # Word-art stays legacy by source filename — never by renumbered kc-NNN slot
    legacy_srcs = [p for p in src_files if p.name in LEGACY_NAMES]
    generic = [
        p
        for p in src_files
        if is_generic(p.name) and p.name not in LEGACY_NAMES
    ]
    by_franchise: dict[str, list[Path]] = {"bluey": [], "winnie": []}
    for p in src_files:
        group = franchise_group(p.name)
        if group:
            by_franchise[group].append(p)

    if not generic and not any(by_franchise.values()):
        print("No shippable stickers found")
        return

    tmp = STICKERS / "_tmp_prep"
    if tmp.exists():
        shutil.rmtree(tmp)
    for sub in ("bluey", "winnie_pooh", "random_character", "legacy"):
        (tmp / sub).mkdir(parents=True)

    packs: dict[str, list[str]] = {
        "bluey": [],
        "winnie_pooh": [],
        "random_character": [],
        "legacy": [],
    }

    # Generic → random_character/kc-001… (skip reserved legacy slot numbers)
    next_i = 1
    for path in generic:
        img = load_bgra(path)
        if img is None:
            print(f"  skip unreadable {path.name}")
            continue
        cleaned = remove_white_bg(img)
        while f"kc-{next_i:03d}.png" in LEGACY_NAMES:
            next_i += 1
        name = f"kc-{next_i:03d}.png"
        next_i += 1
        cv2.imwrite(str(tmp / "random_character" / name), cleaned)
        packs["random_character"].append(name)

    # Explicit legacy word-art (preserve original filenames)
    for path in legacy_srcs:
        img = load_bgra(path)
        if img is None:
            print(f"  skip unreadable {path.name}")
            continue
        cleaned = remove_white_bg(img)
        cv2.imwrite(str(tmp / "legacy" / path.name), cleaned)
        packs["legacy"].append(path.name)

    # Franchise → bluey/ / winnie_pooh/
    franchise_ship = (("bluey", "bluey"), ("winnie", "winnie_pooh"))
    for src_key, pack_key in franchise_ship:
        paths = sorted(by_franchise[src_key], key=lambda p: p.name.lower())
        prefix = "bluey" if pack_key == "bluey" else "winnie"
        for i, path in enumerate(paths, start=1):
            img = load_bgra(path)
            if img is None:
                print(f"  skip unreadable {path.name}")
                continue
            cleaned = remove_white_bg(img)
            name = f"{prefix}-{i:02d}.png"
            cv2.imwrite(str(tmp / pack_key / name), cleaned)
            packs[pack_key].append(name)

    total = sum(len(v) for v in packs.values())
    if not total:
        shutil.rmtree(tmp)
        print("No shippable stickers found")
        return

    # Clear old pack dirs + any leftover flat PNGs, then install
    for d in PACK_DIRS.values():
        if d.exists():
            shutil.rmtree(d)
    for p in STICKERS.glob("*.png"):
        p.unlink()

    for pack_key, names in packs.items():
        dest_dir = PACK_DIRS[pack_key]
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            (tmp / pack_key / name).replace(dest_dir / name)

    shutil.rmtree(tmp)

    manifest = {
        "base": "/static/brand/kidcore/stickers",
        "packs": packs,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(
        "Shipped "
        + ", ".join(f"{k}={len(v)}" for k, v in packs.items())
        + f" → {MANIFEST.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
