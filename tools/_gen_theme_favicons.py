"""One-shot: generate classic / CRT W favicons matching .site-brand typography."""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = Path(os.environ.get("TEMP", "/tmp")) / "ward-fonts"
SIZE = 64


def render_w(
    path: Path,
    *,
    bg: tuple[int, int, int, int],
    fg: tuple[int, int, int, int],
    font_path: Path,
    font_size: int,
    letter_nudge_x: float = 0,
    y_nudge: float = -2,
    glow: tuple[int, int, int, int] | None = None,
) -> None:
    img = Image.new("RGBA", (SIZE, SIZE), bg)
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(font_path), font_size)
    text = "W"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (SIZE - tw) / 2 - bbox[0] + letter_nudge_x
    y = (SIZE - th) / 2 - bbox[1] + y_nudge

    if glow:
        glow_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        ImageDraw.Draw(glow_layer).text((x, y), text, font=font, fill=glow)
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=2.2))
        img = Image.alpha_composite(img, glow_layer)
        draw = ImageDraw.Draw(img)

    draw.text((x, y), text, font=font, fill=fg)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")
    print(f"wrote {path.relative_to(ROOT)} {img.size}")


def main() -> None:
    classic = ROOT / "frontend" / "brand" / "classic" / "favicon.png"
    crt = ROOT / "frontend" / "brand" / "crt" / "favicon.png"

    # Classic: Sora Bold (same as --font-display / .site-brand), night HUD cyan
    render_w(
        classic,
        bg=(12, 13, 15, 255),  # --bg #0c0d0f
        fg=(159, 208, 224, 255),  # --accent-strong #9fd0e0
        font_path=FONT_DIR / "Sora-Bold.ttf",
        font_size=46,
        letter_nudge_x=-1,  # matches letter-spacing: -0.04em feel
        y_nudge=-2,
    )

    # CRT: IBM Plex Mono Bold (site-brand on crt), phosphor green
    render_w(
        crt,
        bg=(5, 11, 5, 255),  # --bg #050b05
        fg=(0, 255, 102, 255),  # --accent #00ff66
        font_path=FONT_DIR / "IBMPlexMono-Bold.ttf",
        font_size=48,
        y_nudge=-1,
        glow=(0, 255, 102, 90),
    )

    kc = ROOT / "frontend" / "brand" / "kidcore" / "favicon.png"
    print("kidcore exists", kc.exists(), kc.stat().st_size if kc.exists() else 0)


if __name__ == "__main__":
    main()
