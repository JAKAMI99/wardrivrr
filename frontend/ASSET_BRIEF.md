# Visuals to produce (hand-drawn / designed — not AI)

Classic UI is now a quieter dark shell. These assets give it identity and give Kidcore something real to hang stickers on.

Deliver as SVG (preferred for UI chrome) or PNG @1x/@2x/@3x. Keep a transparent background unless noted.

---

## Must-have (ship Classic)

### 1. Favicon set
- `favicon.svg` — simple mark that reads at 16×16
- `favicon-32.png`, `apple-touch-icon-180.png`
- Idea: abstract **radar wedge / street fork / signal bars**, not a car emoji

### 2. Wordmark + mark
- **Mark only** (square): for favicon, PWA, account avatar fallback
- **Wordmark** `wardrivrr` in your chosen lettering (matches Sora/Figtree energy: geometric, slightly tight tracking)
- Light-on-dark + dark-on-light versions
- Clear space = height of the “w”

### 3. App / PWA icons
- 192 and 512 maskable PNGs (safe zone inset ~20%)
- Same mark as favicon; flat, high contrast

### 4. Open Graph / share card (optional but nice)
- 1200×630: mark + “wardrivrr” + one short line (“local street explorer”)
- Dark field, no fake screenshots

---

## Motion / chrome (Classic)

### 5. Empty-state illustrations (3)
Sparse line drawings, ~320×240, single accent stroke:
1. **No region yet** — folded map / empty city outline
2. **No GPS** — quiet satellite / pin waiting
3. **Routing building** — streets assembling (geometric, not cartoon)

### 6. Nav tab icons (optional upgrade)
Replace the current inline SVGs with a matched set (24×24, 1.5px stroke):
Home · Drive · Regions · Progress · Database · Status · Settings

### 7. Cursors (Classic) — only if you want character
Default / pointer / “grab map” — subtle custom, **not** novelty.
Skip if it fights map usability; Drive should keep OS cursors.

---

## Background / atmosphere

### 8. Classic grain (subtle)
- Seamless 256–512 noise tile, very low contrast
- Used as 3–6% overlay on `.page-glow` — no neon, no grid

### 9. Hero texture (Home only)
- Soft topographic or street-grid fragment, desaturated
- Edge-fades to `#0c0d0f`; never a full photo of a real city unless you own it

---

## Kidcore / “smol” pack (theme art you draw)

Keep Classic clean; dump the cuteness **only** into Kidcore slots.

### 10. Sticker sheet + favicon — done
Shipped under `frontend/brand/kidcore/`: `favicon.png`, `stickers.json`, and 111 PNGs in `stickers/` (kc-001…kc-111). Style: flat plastic toy / Y2K — thick stroke, few colors.

### 11. Kidcore cursor set (optional)
- Default + pointer — soft toy shapes
- **Do not** use on Drive map if it hides click targets; Progress/Home/Regions only is fine

### 12. Kidcore wallpaper fragments
- 2–3 seamless pastel patterns (stars, squiggles, checker) for `.page-glow` layers
- Plus 4–6 “floating” stickers for corners (already phrase-driven in `theme.js`)

### 13. Achievement / badge art (later)
- Shared badge frames (bronze / silver / gold plastic)
- Icon holes 64×64 for per-achievement glyphs

---

## CRT theme (small)

### 14. Scanline + phosphor bloom
- 1px scanline tile (opacity controlled in CSS)
- Optional terminal “boot” glyph for Status empty state

---

## Production notes

| Asset | Format | Color |
| --- | --- | --- |
| Favicon / mark | SVG + PNG | 1–2 colors + transparent |
| Stickers | PNG | Full color, hard edges |
| Grain / patterns | PNG or SVG | Grayscale or pastel |
| Tab icons | SVG | `currentColor` |

**Avoid:** photoreal cars, stock neon cyberpunk, random Midjourney mashups, text baked into stickers (we localize / Kidcore-rewrite in CSS/JS).

**Folder:** `frontend/brand/` and `frontend/brand/kidcore/` (served as `/static/brand/…`).
