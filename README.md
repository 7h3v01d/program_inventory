# Program Inventory

![Version](https://img.shields.io/badge/version-3.2.0-2fd6c3)
![Python](https://img.shields.io/badge/python-3.11%2B-4be08a)
![Qt](https://img.shields.io/badge/Qt-PySide6%20%7C%20PyQt6-2fd6c3)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-ffb454)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

**A governed Windows software inventory console.** Scans the uninstall
registry across all hives and architecture views, keeps a chain-hashed
SQLite history of every scan, tells you what changed between any two points
in time, checks winget for available updates, and runs uninstalls behind a
deny-first confirmation gate — every action logged.

Single file. One dependency. Dark-industrial GUI.

---

## Features

### Inventory
- Scans **HKLM (64-bit view)**, **HKLM (32-bit / WOW64 view)**, and **HKCU**
  using proper `KEY_WOW64_*` access flags — every entry gets a real
  architecture tag, not a string-matched guess
- Captures name, version, publisher, install date (normalised to ISO),
  estimated size, install location, uninstall strings, info URL, and the
  exact registry path
- Filters system components, Windows updates, and hotfix noise
- Live search across name / publisher / version, publisher dropdown,
  install-recency filter (30 / 90 / 365 days), and an **UPDATABLE** toggle
- Sortable columns with numeric-aware sorting (size, date)
- Detail pane with uninstall commands and registry path
- Right-click: open install folder, copy uninstall / silent uninstall
  command, copy registry path, view program history, web search

### History (chain-hashed audit)
- Every scan is **automatically persisted** to a local SQLite database
  (`~/.program_inventory/history.db`, WAL mode)
- Each scan row carries a SHA-256 hash chained to the previous scan's hash,
  computed over a canonical form of every entry — name, version, and a
  digest of the full record blob. Tampering with any of them breaks the
  chain, verifiable via **HISTORY → Verify audit chain**
- On launch the app reloads your latest scan and shows a **drift chip**
  (`+added / -removed / ~changed` since the previous scan)
- **Timeline** view of every recorded scan — diff any historical scan
  against the current table, or reload it as a read-only view
- Per-program history: first seen, every install / upgrade / removal event,
  and every logged action
- Manual JSON snapshots remain available as a portable format for comparing
  across machines

### Update intelligence (winget)
- **CHECK UPDATES** shells `winget upgrade --include-unknown` in a worker
  thread (no console flash) and parses the fixed-width table output —
  handles multiple table sections, truncated names/ids, and prose lines
- Amber **Update** column with the available version; updates chip shows
  matched and unmatched counts
- Copy-ready `winget upgrade --id "…"` command per program (falls back to
  `--name` matching when winget truncates the id)

### Governed uninstall
- Deny-first: the **UNINSTALL** button stays disabled until the exact
  program name is typed
- Silent mode is offered **only** when the vendor recorded a
  `QuietUninstallString` — no synthesised `/quiet` flags
- The command string is passed verbatim to `CreateProcess` — no `cmd.exe`
  shell layer
- MSI exit codes decoded (`1602` cancelled, `1618` install in progress,
  `3010` success + reboot required)
- Every run is logged to the actions table with its exit code; on success
  the app rescans automatically so the removal lands in the chain-hashed
  scan history

### Exports
- CSV, JSON, TXT report, Markdown table
- Exports respect the active filters — what you see is what you export

---

## Install

```
pip install -r requirements.txt
python program_inventory.py
```

Requires **Windows 10/11** and **Python 3.11+**. PySide6 is the preferred
Qt binding; if PyQt6 is installed instead, the app detects and uses it
automatically. Update checking additionally requires **winget**
("App Installer" from the Microsoft Store — preinstalled on current
Windows 10/11 builds).

No elevation required for scanning. Uninstalling may trigger UAC prompts
from the vendor's own uninstaller.

---

## Data & privacy

Everything is local. The only data written outside the app directory is:

| Path | Purpose |
|---|---|
| `~/.program_inventory/history.db` | Scan history, events, action log |
| Files you explicitly export | CSV / JSON / TXT / MD / snapshots |

No telemetry, no network access except the winget check you trigger and
web searches you launch yourself.

---

## Security notes

- The audit chain detects tampering with recorded history; it does not
  prevent it. An attacker with write access to the database can rewrite
  the entire chain — the threat model is accidental edits and casual
  tampering, not a hostile administrator.
- The actions table is informational and outside the hash chain; the
  inventory consequences of actions are captured by the chained scan diff.
- Uninstall commands come straight from the registry. Review the command
  shown in the confirmation dialog before arming.

## Known limitations

- winget table parsing can mis-slice rows containing wide CJK glyphs
  (winget pads by display width, not characters)
- winget entries that can't be name-matched to a registry entry are
  reported as "unmatched" in the updates chip rather than shown per-row
- MSI per-user vs per-machine duplicates are deduplicated by
  (name, version); intentional side-by-side installs of the same version
  in different hives collapse to one row

## Roadmap

- Startup entries / Services / Scheduled Tasks tabs (full machine surface)
- Multi-host snapshot comparison

---

## License

Apache License 2.0 — Copyright 2026 **Leon Priest** ([7h3v01d](https://github.com/7h3v01d))
