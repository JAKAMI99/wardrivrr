# Backup format

Wardrivrr user backups are **ZIP_DEFLATED** archives written by `backend/backup.py`.

## Members (format_version 1)

| File | Required | Contents |
| --- | --- | --- |
| `meta.json` | yes | Identity + `format_version` (new exports). Legacy zips only have `format: "wardrivrr-backup-v1"`. |
| `wardrivrr-backup.json` | new exports | Same versioned manifest (`format_version`, `app_version`, `created_at`, `counts`, …). |
| `signal_samples.csv` | by kind | Raw observations (not fog / achievements). |
| `networks.csv` | by kind | Localized network rows. |
| `user_settings.json` | some kinds | Per-user settings. |
| `incoming_manifest.json` | optional | Filenames under `incoming/` only (files themselves are not packed). |
| `app_meta.json` | `full` only | Tiny schema note; not used by restore. |

Kinds: `user_calculated` (default), `full`, `calculated_only`, `raw_only`.

**Not included:** fog / road exploration, achievements, levels, XP counters, capture binaries.

## Versioning

- `format_version` is an integer. Current: **1**.
- Archives **without** `format_version` but with `format: "wardrivrr-backup-v1"` are treated as **version 1 (legacy)** and restore as today.
- Restoring a **higher** `format_version` than the running app supports fails with a clear error.
- Bump `CURRENT_FORMAT_VERSION` in `backup.py` only when the on-disk layout or restore semantics change; keep handlers for older versions.
