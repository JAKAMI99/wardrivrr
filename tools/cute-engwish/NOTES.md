# Cute Engwish research notes

Runtime speech lives in `frontend/theme.js` (Kidcore theme). This folder is
attribution / research only — no source dumps checked in.

## Upstream

- **Cute Engwish** (`en@uwu`) — Prism Launcher translations  
  https://github.com/PrismLauncher/Translations (`en@uwu.ts`)  
  Weblate: https://hosted.weblate.org/projects/prismlauncher/launcher/en@uwu/
- **OwOify** — baseline Prism asks translators to use  
  https://github.com/aqua-lzma/OwOify  
  Also: https://github.com/PrismarineJS/node-minecraft-protocol related OwOify ports

## What Prism / OwOify typically do

1. **Word map** — love→wuv, friend→fwend, hello→henwo, stop→stawp, …
2. **r/l → w** — folder→fowdew, version→vewsion, error→ewwow
3. **ny after n+vowel** — no→nyo, not→nyot, name→nyame, need→nyeed
4. **Repeaty** — long `…y` words get a w-echo (`probably` → `pwobabwy wobabwy`)
5. **Stutter** — occasional doubled first consonant (~10% in OwOify)
6. **Suffix sprinkle** — OwO / UwU / :3 (rare)

## Wardrivrr adaptation

`theme.js` keeps an app-specific `PHRASE_DICT` / phrase pool, then applies a
wholesome OwOify-like pipeline (no NSFW prefixes). Protects URLs, codes, and
all-caps tokens (API, GPS, XP…).
