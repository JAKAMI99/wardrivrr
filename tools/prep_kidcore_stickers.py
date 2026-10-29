"""
Re-process extracted Kidcore stickers:
  - edge flood-fill / magic-wand matting (border-connected bg only;
    preserves interior white eyes/teeth/highlights)
  - generic cuts → kc-001.png …
  - Bluey (s-l1600-*) and Winnie the Pooh (winnie-/pooh-/winniethepooh-*)
    stay in stickers/ as bluey-01.png / winnie-01.png (not moved to stickers-ref)

Workflow (user-supplied local sheets/PNGs — do not scrape copyrighted art):
  1. Drop transparent PNGs or sheets into frontend/brand/kidcore/
     — Bluey: s-l1600.jpg (or bluey-*.png); Pooh: winnie*/pooh*/winniethepooh*
  2. python tools/extract_kidcore_stickers.py   # if using sheets
  3. python tools/prep_kidcore_stickers.py
  Franchise stickers then ship in stickers/ + stickers.json alongside kc-*.
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

# Generic / baby-item sheets → kc-NNN.png
GENERIC_PREFIXES = (
    "bvmfyckymuha1-",
    "cute-cartoon-animal-kid-journal-sticker-sku1-",
    "cute-cartoon-animal-kid-journal-sticker-sku2-",
)

# Extract slug prefix → recognizable shipped prefix (stay in stickers/)
FRANCHISE_FROM_SHEET = {
    "s-l1600-": "bluey",
}

# Winnie the Pooh — accept common extract/local stem prefixes (longest first)
WINNIE_STEM_PREFIXES = ("winniethepooh", "winnie", "pooh")

SHIP_FRANCHISES = ("bluey", "winnie")


def is_generic(name: str) -> bool:
    n = name.lower()
    if any(n.startswith(p) for p in GENERIC_PREFIXES):
        return True
    return bool(re.fullmatch(r"kc-\d{3}\.png", n))


def _matches_stem_prefix(name: str, stem: str) -> bool:
    """True for stem-01.png, stem2-01.png, etc."""
    n = name.lower()
    if n.startswith(f"{stem}-"):
        return True
    if n.startswith(stem) and len(n) > len(stem) and n[len(stem)].isdigit():
        return True
    return False


def franchise_group(name: str) -> str | None:
    """Return shipped prefix ('bluey' / 'winnie') or None."""
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
    """Edge flood-fill / magic-wand only — keep interior white (eyes/teeth).

    Never globally punch near-white pixels. Only border-connected background
    (near-white or matching sampled border color) becomes transparent.
    """
    b, g, r, a = cv2.split(bgra)
    h, w = a.shape
    rgb = cv2.merge([r, g, b]).astype(np.float32)
    dist_white = np.linalg.norm(rgb - 255.0, axis=2)

    # Median border color (handles cyan/paper DisneyClips BGs)
    samples = np.concatenate(
        [rgb[0], rgb[h - 1], rgb[:, 0], rgb[:, w - 1]], axis=0
    )
    border_a = np.concatenate([a[0], a[h - 1], a[:, 0], a[:, w - 1]], axis=0)
    opaque = border_a > 40
    border_rgb = (
        np.median(samples[opaque].astype(np.float32), axis=0)
        if opaque.sum() >= 8
        else np.median(samples.astype(np.float32), axis=0)
    )
    dist_bg = np.linalg.norm(rgb - border_rgb.reshape(1, 1, 3), axis=2)

    white_dist = 28.0
    travel = (
        (dist_white < white_dist) | (dist_bg < 36.0) | (a < 40)
    ).astype(np.uint8) * 255
    ff = travel.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    for x in range(w):
        if ff[0, x]:
            cv2.floodFill(ff, mask, (x, 0), 128)
        if ff[h - 1, x]:
            cv2.floodFill(ff, mask, (x, h - 1), 128)
    for y in range(h):
        if ff[y, 0]:
            cv2.floodFill(ff, mask, (0, y), 128)
        if ff[y, w - 1]:
            cv2.floodFill(ff, mask, (w - 1, y), 128)

    border_bg = ff == 128
    alpha = a.astype(np.float32)
    alpha[border_bg] = 0.0

    bg_u8 = border_bg.astype(np.uint8) * 255
    dist_to_bg = cv2.distanceTransform(255 - bg_u8, cv2.DIST_L2, 3)
    near_edge = (~border_bg) & (dist_to_bg < 2.5) & (
        (dist_white < white_dist + 10) | (dist_bg < 42.0)
    )
    if near_edge.any():
        soft = np.clip(dist_to_bg[near_edge] / 1.2, 0, 1) * 255.0
        alpha[near_edge] = np.minimum(alpha[near_edge], soft)

    alpha_u8 = np.clip(alpha, 0, 255).astype(np.uint8)
    out = cv2.merge([b, g, r, alpha_u8])

    ys, xs = np.where(alpha_u8 > 8)
    if len(xs) == 0:
        return out
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    pad = 2
    y0, x0 = max(0, y0 - pad), max(0, x0 - pad)
    y1, x1 = min(h, y1 + pad), min(w, x1 + pad)
    return out[y0:y1, x0:x1]


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


def main() -> None:
    STICKERS.mkdir(parents=True, exist_ok=True)
    src_files = sorted(STICKERS.glob("*.png"))

    generic = [p for p in src_files if is_generic(p.name)]
    by_franchise: dict[str, list[Path]] = {k: [] for k in SHIP_FRANCHISES}
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
    tmp.mkdir()

    names: list[str] = []

    # Generic → kc-001…
    for i, path in enumerate(generic, start=1):
        img = load_bgra(path)
        if img is None:
            print(f"  skip unreadable {path.name}")
            continue
        cleaned = remove_white_bg(img)
        name = f"kc-{i:03d}.png"
        cv2.imwrite(str(tmp / name), cleaned)
        names.append(name)

    # Franchise → bluey-01 / winnie-01 … (stay in stickers/, not stickers-ref)
    for prefix in SHIP_FRANCHISES:
        paths = sorted(by_franchise[prefix], key=lambda p: p.name.lower())
        for i, path in enumerate(paths, start=1):
            img = load_bgra(path)
            if img is None:
                print(f"  skip unreadable {path.name}")
                continue
            cleaned = remove_white_bg(img)
            name = f"{prefix}-{i:02d}.png"
            cv2.imwrite(str(tmp / name), cleaned)
            names.append(name)

    if not names:
        shutil.rmtree(tmp)
        print("No shippable stickers found")
        return

    # Replace stickers dir contents with cleaned outputs
    for p in STICKERS.glob("*.png"):
        p.unlink()
    for p in sorted(tmp.glob("*.png")):
        p.replace(STICKERS / p.name)
    tmp.rmdir()

    manifest = {
        "base": "/static/brand/kidcore/stickers",
        "stickers": names,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    n_kc = sum(1 for n in names if n.startswith("kc-"))
    n_fr = len(names) - n_kc
    print(f"Shipped {n_kc} generic (kc-*) + {n_fr} franchise stickers")
    print(f"Manifest → {MANIFEST.relative_to(ROOT)} ({len(names)} total)")


if __name__ == "__main__":
    main()
