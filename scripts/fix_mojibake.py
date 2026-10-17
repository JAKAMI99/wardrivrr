"""
Repair double-encoded UTF-8 punctuation in frontend text.

On disk these show up as three Unicode chars (e.g. U+00E2 U+20AC U+2018)
instead of one (U+2011). Browsers then render Wiâ€˜Fi.

Replace with ASCII so the UI stays readable regardless of transport encoding.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Literal mojibake sequences as stored after UTF-8→cp1252→UTF-8 corruption.
REPLACEMENTS: list[tuple[str, str]] = [
    # Wi‑Fi (U+2011 non-breaking hyphen)
    ("Wi\u00e2\u20ac\u2018Fi", "Wi-Fi"),
    # Em dash —
    ("\u00e2\u20ac\u201d", "-"),
    # Ellipsis …
    ("\u00e2\u20ac\u00a6", "..."),
    # Right single quote ’
    ("\u00e2\u20ac\u2122", "'"),
    # Left single quote / nb-hyphen leftovers
    ("\u00e2\u20ac\u2018", "-"),
    ("\u00e2\u20ac\u2019", "'"),
    # Arrow →
    ("\u00e2\u2020\u2019", "->"),
    # Middle dot · and plus-minus ± as mojibake Â· / Â±
    ("\u00c2\u00b7", "·"),
    ("\u00c2\u00b1", "+/-"),
    # Also catch any remaining correct Unicode punctuation in HTML/JS copy
    ("Wi\u2011Fi", "Wi-Fi"),
    ("Wi\u2013Fi", "Wi-Fi"),
    ("\u2011", "-"),
    ("\u2013", "-"),
    ("\u2014", "-"),
    ("\u2026", "..."),
    ("\u2018", "'"),
    ("\u2019", "'"),
    ("\u201c", '"'),
    ("\u201d", '"'),
    ("\u2192", "->"),
    ("\u00a0", " "),
]


def fix_text(text: str) -> str:
    out = text
    for bad, good in REPLACEMENTS:
        if bad in out:
            out = out.replace(bad, good)
    return out


def main() -> int:
    write = "--write" in sys.argv
    paths = list((ROOT / "frontend").rglob("*"))
    paths += [
        ROOT / "backend" / "achievements.py",
        ROOT / "backend" / "system_status.py",
        ROOT / "backend" / "main.py",
    ]
    changed_files = 0
    for path in sorted(p for p in paths if p.is_file()):
        if path.suffix.lower() not in {".html", ".js", ".css", ".py"}:
            continue
        if "fix_mojibake" in path.name:
            continue
        before = path.read_text(encoding="utf-8")
        after = fix_text(before)
        if after == before:
            continue
        changed_files += 1
        rel = path.relative_to(ROOT)
        print(f"{'WRITE' if write else 'DRY'} {rel}")
        shown = 0
        for a, b in zip(before.splitlines(), after.splitlines()):
            if a != b:
                safe_a = a.strip().encode("ascii", "backslashreplace").decode()
                safe_b = b.strip().encode("ascii", "backslashreplace").decode()
                print(f"  - {safe_a[:110]}")
                print(f"  + {safe_b[:110]}")
                shown += 1
                if shown >= 3:
                    break
        if write:
            path.write_text(after, encoding="utf-8", newline="\n")
    print(f"{changed_files} file(s) {'updated' if write else 'would change'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
