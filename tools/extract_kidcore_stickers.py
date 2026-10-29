"""
Split packed Kidcore sticker sheets into individual transparent PNGs.

After prep, shippable stickers live under stickers/{bluey,winnie_pooh,
random_character,legacy}/ + stickers.json packs.

To regenerate from user-supplied local sheets (do not scrape copyrighted art):
  1. Drop sheet images into frontend/brand/kidcore/
     — Bluey: s-l1600.jpg; Winnie the Pooh: winnie* / pooh* / winniethepooh*
     (gallery links in CREDITS.md — decorative stickers are local user assets)
  2. python tools/extract_kidcore_stickers.py
  3. python tools/prep_kidcore_stickers.py   # clean + pack folders + manifest

Usage:
  python tools/extract_kidcore_stickers.py
"""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "brand" / "kidcore"
OUT = SRC / "stickers"
SHEETS = SRC / "sheets"  # local archive of source sheets (not shipped)

# Near-white background (stickers have white die-cut borders + soft shadows)
WHITE_THRESH = 248
MIN_AREA_FRAC = 0.0012  # of image area
MAX_AREA_FRAC = 0.55
PAD = 4
# Merge tiny label blobs (numbers under onesies) into nearest large blob
MERGE_GAP_PX = 48


def slug(name: str) -> str:
    s = Path(name).stem.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:48] or "sheet"


def foreground_mask(bgr: np.ndarray) -> np.ndarray:
    # True = sticker / ink / shadow (not empty white)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB).astype(np.int16)
    near_white = (
        (rgb[:, :, 0] >= WHITE_THRESH)
        & (rgb[:, :, 1] >= WHITE_THRESH)
        & (rgb[:, :, 2] >= WHITE_THRESH)
    )
    return (~near_white).astype(np.uint8) * 255


def components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Return list of (x, y, w, h, area) for external contours."""
    cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = mask.shape[:2]
    img_area = h * w
    min_a = max(80, int(img_area * MIN_AREA_FRAC))
    max_a = int(img_area * MAX_AREA_FRAC)
    boxes = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        area = int(cv2.contourArea(c))
        if area < min_a or area > max_a:
            continue
        # Skip ultra-thin noise lines
        if bw < 12 or bh < 12:
            continue
        boxes.append((x, y, bw, bh, area))
    return boxes


def expand(box, w, h, pad=PAD):
    x, y, bw, bh, area = box
    x0 = max(0, x - pad)
    y0 = max(0, y - pad)
    x1 = min(w, x + bw + pad)
    y1 = min(h, y + bh + pad)
    return x0, y0, x1 - x0, y1 - y0, area


def centers(box):
    x, y, bw, bh, _ = box
    return x + bw / 2, y + bh / 2


def dist2(a, b):
    ax, ay = centers(a)
    bx, by = centers(b)
    return (ax - bx) ** 2 + (ay - by) ** 2


def merge_nearby(boxes: list) -> list:
    """Attach small blobs to nearest large blob if close (numbers under icons)."""
    if len(boxes) < 2:
        return boxes
    areas = sorted(b[4] for b in boxes)
    median = areas[len(areas) // 2]
    large = [b for b in boxes if b[4] >= median * 0.55]
    small = [b for b in boxes if b[4] < median * 0.55]
    if not large:
        return boxes

    groups = {i: [b] for i, b in enumerate(large)}
    for s in small:
        best_i = None
        best_d = None
        sx, sy = centers(s)
        for i, L in enumerate(large):
            lx, ly = centers(L)
            # Prefer labels below / near the icon
            if sy < ly - 8:
                continue
            d = dist2(s, L)
            gap = MERGE_GAP_PX + max(L[2], L[3]) * 0.15
            if d > gap * gap:
                continue
            if best_d is None or d < best_d:
                best_d = d
                best_i = i
        if best_i is None:
            # keep as its own if decent size, else drop dust
            if s[4] >= median * 0.25:
                groups[len(large) + len(groups)] = [s]
            continue
        groups[best_i].append(s)

    merged = []
    for parts in groups.values():
        xs = [p[0] for p in parts]
        ys = [p[1] for p in parts]
        x2 = [p[0] + p[2] for p in parts]
        y2 = [p[1] + p[3] for p in parts]
        x0, y0 = min(xs), min(ys)
        merged.append((x0, y0, max(x2) - x0, max(y2) - y0, sum(p[4] for p in parts)))
    return merged


def to_rgba(bgr_crop: np.ndarray) -> np.ndarray:
    """Crop as fully opaque RGBA.

    Do NOT punch global near-white here — that hollows eyes/teeth/fills.
    Border-connected background is removed later by prep's edge flood-fill.
    """
    rgb = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2RGB)
    alpha = np.full(rgb.shape[:2], 255, np.uint8)
    return np.dstack([rgb, alpha])


def extract_sheet(path: Path, out_dir: Path) -> int:
    bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if bgr is None:
        print(f"  skip (unreadable): {path.name}")
        return 0
    h, w = bgr.shape[:2]
    mask = foreground_mask(bgr)
    # Close tiny gaps inside stickers, open dust
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k, iterations=1)

    boxes = components(mask)
    boxes = merge_nearby(boxes)
    boxes = [expand(b, w, h) for b in boxes]
    # Reading order: top→bottom, left→right
    boxes.sort(key=lambda b: (b[1] // max(24, h // 20), b[0]))

    prefix = slug(path.name)
    out_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for i, (x, y, bw, bh, _) in enumerate(boxes, start=1):
        crop = bgr[y : y + bh, x : x + bw]
        rgba = to_rgba(crop)
        # Drop empty / almost empty
        if int(rgba[:, :, 3].sum()) < 500:
            continue
        n += 1
        out = out_dir / f"{prefix}-{n:02d}.png"
        cv2.imwrite(str(out), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    return n


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    SHEETS.mkdir(parents=True, exist_ok=True)

    skip_names = {"favicon.png", "favicon.jpg", "favicon.webp"}
    sheets = sorted(
        [
            *SRC.glob("*.jpg"),
            *SRC.glob("*.jpeg"),
            *SRC.glob("*.png"),
            *SRC.glob("*.webp"),
        ]
    )
    # Ignore already-extracted stickers folder + brand chrome
    sheets = [
        p
        for p in sheets
        if p.parent == SRC and p.name.lower() not in skip_names
    ]

    if not sheets:
        print(f"No sheets in {SRC}")
        return

    total = 0
    for path in sheets:
        # Archive original into sheets/
        dest = SHEETS / path.name
        if not dest.exists():
            path.replace(dest)
            src = dest
        else:
            src = path if path.exists() else dest
            if path.exists() and path.resolve() != dest.resolve():
                path.replace(dest)
                src = dest

        print(f"Extracting {src.name} …")
        n = extract_sheet(src, OUT)
        print(f"  → {n} stickers")
        total += n

    print(f"Done: {total} PNGs in {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
