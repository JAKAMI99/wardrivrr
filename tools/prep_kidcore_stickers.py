"""
Re-process extracted Kidcore stickers:
  - stronger white-background removal
  - generic names kc-001.png …
  - ship only non-franchise sheets (animals + onesie/paci)

Shipped pack: frontend/brand/kidcore/stickers/ + stickers.json
Franchise / copyrighted cuts are parked under stickers-ref/ locally only —
that tree is gitignored and must not be committed.

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

# Source prefixes we ship (generic / baby items). Franchise sheets stay out.
SHIP_PREFIXES = (
    "bvmfyckymuha1-",
    "cute-cartoon-animal-kid-journal-sticker-sku1-",
    "cute-cartoon-animal-kid-journal-sticker-sku2-",
    "kc-",  # already renamed
)

# Drop these from the shipped pack (copyrighted characters → local stickers-ref/)
DROP_PREFIXES = (
    "s-l1600-",
    "shebnurm-",
)


def is_ship(name: str) -> bool:
    n = name.lower()
    if any(n.startswith(p) for p in DROP_PREFIXES):
        return False
    return any(n.startswith(p) for p in SHIP_PREFIXES) or re.fullmatch(
        r"kc-\d{3}\.png", n
    )


def remove_white_bg(bgra: np.ndarray) -> np.ndarray:
    """Aggressive near-white → transparent; flood-fill from edges."""
    b, g, r, a = cv2.split(bgra)
    rgb = cv2.merge([r, g, b]).astype(np.float32)
    # Distance from pure white
    dist = np.linalg.norm(rgb - 255.0, axis=2)
    # Soft mask: fully transparent under ~12, opaque above ~40
    alpha = np.clip((dist - 10.0) * (255.0 / 28.0), 0, 255).astype(np.uint8)

    # Flood-fill connected near-white from borders → kill leftover bg
    h, w = alpha.shape
    near = (dist < 18).astype(np.uint8) * 255
    ff = near.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    # Seed every border pixel that is near-white
    for x in range(w):
        if near[0, x]:
            cv2.floodFill(ff, mask, (x, 0), 128)
        if near[h - 1, x]:
            cv2.floodFill(ff, mask, (x, h - 1), 128)
    for y in range(h):
        if near[y, 0]:
            cv2.floodFill(ff, mask, (0, y), 128)
        if near[y, w - 1]:
            cv2.floodFill(ff, mask, (w - 1, y), 128)
    border_bg = ff == 128
    alpha = np.where(border_bg, 0, alpha)

    # Keep existing alpha if already processed (min)
    alpha = np.minimum(alpha, a)

    out = cv2.merge([b, g, r, alpha])
    # Trim empty margins
    ys, xs = np.where(alpha > 8)
    if len(xs) == 0:
        return out
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    pad = 2
    y0, x0 = max(0, y0 - pad), max(0, x0 - pad)
    y1, x1 = min(h, y1 + pad), min(w, x1 + pad)
    return out[y0:y1, x0:x1]


def main() -> None:
    STICKERS.mkdir(parents=True, exist_ok=True)
    src_files = sorted(STICKERS.glob("*.png"))
    ship = [p for p in src_files if is_ship(p.name)]
    drop = [p for p in src_files if any(p.name.lower().startswith(d) for d in DROP_PREFIXES)]

    # Park franchise cuts (keep for local experiments, not in rotation)
    ref = STICKERS.parent / "stickers-ref"
    if drop:
        ref.mkdir(parents=True, exist_ok=True)
        for p in drop:
            dest = ref / p.name
            if dest.exists():
                dest.unlink()
            p.replace(dest)
        print(f"Moved {len(drop)} franchise stickers → {ref.relative_to(ROOT)}")

    # Work from current ship set (may include old names)
    ship = sorted(p for p in STICKERS.glob("*.png") if is_ship(p.name))
    if not ship:
        print("No shippable stickers found")
        return

    tmp = STICKERS / "_tmp_prep"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()

    names = []
    for i, path in enumerate(ship, start=1):
        img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if img is None:
            print(f"  skip unreadable {path.name}")
            continue
        if img.ndim == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
        elif img.shape[2] == 3:
            b, g, r = cv2.split(img)
            a = np.full(b.shape, 255, np.uint8)
            img = cv2.merge([b, g, r, a])
        cleaned = remove_white_bg(img)
        name = f"kc-{i:03d}.png"
        out = tmp / name
        cv2.imwrite(str(out), cleaned)
        names.append(name)

    # Replace stickers dir contents with cleaned generic names
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
    print(f"Shipped {len(names)} stickers as kc-001…kc-{len(names):03d}")
    print(f"Manifest → {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
