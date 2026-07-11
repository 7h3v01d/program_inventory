# Program Inventory

![Version](https://img.shields.io/badge/version-4.1.0-2fd6c3)
![Python](https://img.shields.io/badge/python-3.11%2B-4be08a)
![Qt](https://img.shields.io/badge/Qt-PySide6%20%7C%20PyQt6-2fd6c3)
![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-ffb454)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)

**A governed Windows software inventory console.** Scans the uninstall
registry across all hives and architecture views, tracks every installation
under a **stable identity** (not its display name), keeps a chain-hashed
SQLite history of every scan, tells you what changed between any two points
in time, checks winget for available updates with graded match confidence,
and runs uninstalls behind a deny-first confirmation gate — every action
logged with the outcome that was actually observed.

One dependency. Dark-industrial GUI. 89-test pytest suite.

---

## Features

### Inventory
- Scans **HKLM (64-bit view)**, **HKLM (32-bit / WOW64 view)**, and **HKCU**
  using proper `KEY_WOW64_*` access flags — every entry gets a real
  architecture tag, not a string-matched guess
- Captures name, version, publisher, install date (normalised to ISO),
  estimated size, install location, uninstall strings, info URL, and the
  exact registry path
- Every registry entry is a **distinct record with a stable EntryId**
  (hive + registry view + subkey). Per-user and per-machine installs,
  32/64-bit siblings, and same-name products from different publishers
  coexist as separate rows — nothing is collapsed by display name
- Filters system components, Windows updates, and hotfix noise
- Live search across name / publisher / version, publisher dropdown,
  install-recency filter (30 / 90 / 365 days), and an **UPDATABLE** toggle
- Sortable columns with numeric-aware sorting (size, date)
- Detail pane with uninstall commands and registry path
- Right-click: open install folder, copy uninstall / silent uninstall
  command, copy registry path, view program history, web search

### History (chain-hashed audit)
- Every scan is **automatically persisted** to a local SQLite database
  (`~/.program_inventory/history.db`, WAL mode, schema-versioned) inside an
  explicit transaction — a scan is recorded completely or not at all
- Each scan row carries a SHA-256 hash chained to the previous scan's hash,
  computed over a canonical form of every entry — entry id, name, version,
  and a digest of the full record blob. Tampering with any of them breaks
  the chain, verifiable via **HISTORY → Verify audit chain**
- **Verification recomputes the diffs too.** Summary counts are derivative
  data and are never trusted independently: verify re-derives every scan's
  added/removed/changed/modified counts from the stored entries and flags
  any stored summary that doesn't match — even though the chain itself is
  intact
- **Two-tier diff engine.** Scans are compared by EntryId first (tracking
  the actual installation: version changes, metadata edits, key moves);
  leftovers are then correlated by name + publisher, so MSI upgrades that
  rewrite the registry key (new ProductCode, same display name) still read
  as an upgrade — not a spurious remove + add. When both the key *and* the
  name change, it is honestly reported as remove + add
- Diffs distinguish four states: **added**, **removed**, **version
  changed** (`~`), and **metadata modified** (`±` — same version, other
  fields changed)
- On launch the app reloads your latest scan and shows a **drift chip**
  (`+added / -removed / ~changed / ±modified` since the previous scan)
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
- **Graded match confidence.** An exact name match renders amber; a
  prefix match against a winget-truncated (`…`) name renders dimmed with a
  `?` suffix and is labelled `[probable match]` in the detail pane — a
  heuristic is never presented as an identification
- The updates chip reports exact, probable, and unmatched counts.
  **"up to date" appears only when winget itself returned zero rows** — if
  winget reported updates that couldn't be matched to inventory, the chip
  says so instead
- Copy-ready `winget upgrade --id "…"` command per program (falls back to
  `--name` matching when winget truncates the id)

### Governed uninstall
- Deny-first: the **UNINSTALL** button stays disabled until the exact
  program name is typed
- Silent mode is offered **only** when the vendor recorded a
  `QuietUninstallString` — no synthesised `/quiet` flags
- The command string is passed verbatim to `CreateProcess` — no `cmd.exe`
  shell layer. If the uninstaller's manifest requires administrator rights
  (WinError 740), the app retries through `ShellExecuteEx` with the `runas`
  verb so Windows shows a normal UAC prompt — declining the prompt is
  reported and logged, never retried silently
- MSI exit codes decoded (`1602` cancelled, `1618` install in progress,
  `3010` success + reboot required)
- **Outcome-honest reporting.** Every run resolves to one of six observed
  states — `success`, `failed`, `declined` (UAC), `timeout`, `unknown`, or
  `error` — and is logged with that outcome plus the exit code. If the
  elevated process launches but Windows returns no handle to track, that is
  reported as *outcome unknown*, never assumed to be success. If the app
  stops waiting after 15 minutes, it says the uninstaller **may still be
  running** — it does not pretend the process was stopped
- Automatic rescan happens **only on observed success**, so the removal
  lands in the chain-hashed scan history; unknown and timeout outcomes
  prompt you to rescan manually once the dust settles

### Exports
- CSV, JSON, TXT report, Markdown table
- Exports respect the active filters — what you see is what you export

---

## Install

```
pip install -r requirements.txt
python program_inventory.py        # launcher script
python -m program_inventory        # or as a module
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
| `history.bak-v1` (once, on upgrade) | Pre-migration backup of a v1 database |
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
  Scan summary counts are also outside the chain — which is exactly why
  verification recomputes them from the chained entries instead of
  trusting them.
- Uninstall commands come straight from the registry. Review the command
  shown in the confirmation dialog before arming.

## Upgrading from v4.0.x

On first launch, an existing v1 history database is migrated to schema v2
automatically: the file is **backed up first** (`history.bak-v1`), entry
ids are backfilled onto legacy records from their stored registry paths,
and legacy scan hashes remain verifiable under the original algorithm — the
chain runs unbroken across the version boundary. A database that can't be
read at all is renamed with a `.corrupt-<timestamp>` suffix (never
deleted) and a fresh one is started.

Because v4.0.x deduplicated by (name, version) and v4.1.0 does not, your
first scan after upgrading may report a handful of "added" entries — those
are real registry entries the old version was collapsing.

## Known limitations

- winget table parsing can mis-slice rows containing wide CJK glyphs
  (winget pads by display width, not characters)
- winget entries that can't be name-matched to a registry entry are
  reported as "unmatched" in the updates chip rather than shown per-row
- Tier-2 upgrade correlation is name-based: an upgrade that changes both
  the registry key *and* the display name is reported as remove + add

## Project structure

```
program_inventory/
├── app.py             main window (UI shell), filter proxy, entry point
├── controllers.py     scan / update / uninstall worker lifecycles
├── diffengine.py      EntryId identity + two-tier diff (no Qt — importable)
├── exporters.py       CSV/JSON/TXT/MD writers, snapshot IO (no Qt)
├── qt_shim.py         PySide6 / PyQt6 binding shim
├── theme.py           dark-industrial palette + stylesheet
├── constants.py       shared constants and model roles
├── scan.py            registry scan (HKLM 64/32, HKCU) + ScanWorker
├── history.py         chain-hashed SQLite timeline, schema migration (no Qt)
├── wingetcheck.py     winget parser, graded matcher, worker
├── uninstall.py       command splitting, elevation, outcome model, dialog
└── dialogs.py         diff / timeline / program-history dialogs
tests/                 pytest suite (89 collected tests, offscreen Qt)
program_inventory.py   thin launcher for double-click compatibility
```

`diffengine.py`, `history.py`, `exporters.py` and `wingetcheck.py` are
Qt-free or Qt-light and importable standalone for reuse in other tools.

## Tests

```
pip install -r requirements-dev.txt
python -m pytest tests/
```

89 collected test cases (some parametrized). Covers the identity engine
(EntryId stability, tier-2 upgrade correlation, publisher disambiguation,
per-user/per-machine coexistence), the chain-integrity tamper matrix
(name / version column / data blob / hash linkage / forged summary
counts), v1→v2 schema migration including verification across the
algorithm boundary and corruption set-aside, all six UninstallString
shapes, the WinError 740 elevation fallback including UAC-declined,
no-handle-unknown, and timeout paths, winget table parsing and match
grading, exporters and snapshot compatibility, and full GUI behaviour
under offscreen Qt.

## Roadmap

Now unblocked by the v4.1.0 identity model:

- Startup entries / Services / Scheduled Tasks tabs (full machine surface)
- Multi-host snapshot comparison

---

## License

Apache License 2.0 — Copyright 2026 **Leon Priest** ([7h3v01d](https://github.com/7h3v01d))
