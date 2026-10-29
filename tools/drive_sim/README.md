# Drive sim — Kismet → live GPS replay

Replays `recording.kismet` into wardrivrr so **Navigate** thinks you are driving live: GPS fixes + signal samples stream in at a chosen speed.

## Folder

| File | Role |
|------|------|
| `recording.kismet` | Your biggest drive log (hard-linked from `data/incoming/Kismet_Out/…`) |
| `replay.py` | CLI that posts GPS + inserts samples |
| `track_cache.json` | Auto-built GPS track (first run is slower) |

## Prerequisites

1. API running (`python run_dev.py`)
2. Logged-in user exists (default `admin` / `admin`)
3. Open **http://localhost:8000/navigate**, spawn if needed, enable **Follow live GPS**

## Run

From the repo root. Pick the Kismet DB with `--db` / `-d`, `--recording` / `-r`, or a positional path.
If you omit it, `tools/drive_sim/recording.kismet` is used when present.

```bash
# Explicit database file
.\venv\Scripts\python.exe tools\drive_sim\replay.py --db data\incoming\Kismet_Out\Kismet-20261015-15-02-35-1.kismet
.\venv\Scripts\python.exe tools\drive_sim\replay.py -d path\to\drive.kismet -x 8
.\venv\Scripts\python.exe tools\drive_sim\replay.py path\to\drive.kismet --speed 16

# Default recording.kismet in this folder (4×)
.\venv\Scripts\python.exe tools\drive_sim\replay.py

# Faster / slower
.\venv\Scripts\python.exe tools\drive_sim\replay.py --db path\to\drive.kismet --speed 8
.\venv\Scripts\python.exe tools\drive_sim\replay.py -d path\to\drive.kismet -x 2

# Skip the first 30 minutes, only play 15 minutes (at 8×)
.\venv\Scripts\python.exe tools\drive_sim\replay.py -d path\to\drive.kismet -x 8 --start 30m --duration 15m
```

Stop with `Ctrl+C`.

## Notes

- Samples are inserted with **current** timestamps so the Drive radio HUD counts them as this session.
- GPS `source` is `client` — Navigate’s **Follow live GPS** tracks that feed.
- First run per file builds `track_cache_<name>.json` (one-time scan). Use `--rebuild-cache` to force a rebuild.
