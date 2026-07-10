#!/usr/bin/env python3
# =============================================================================
#  Program Inventory — governed Windows installed-software scanner
#  Copyright 2026 Leon Priest / 7h3v01d
#  Licensed under the Apache License, Version 2.0
# =============================================================================
#  Single-file desktop app. Scans the Windows uninstall registry (HKLM 64-bit,
#  HKLM 32-bit via WOW64 view, HKCU), presents a filterable/sortable table,
#  exports CSV / JSON / TXT / Markdown, and supports snapshot + diff so you
#  can see exactly what was installed, removed, or upgraded between scans.
# =============================================================================

import sys
import os
import sqlite3
import hashlib
import csv
import json
import datetime
import webbrowser
import subprocess
from pathlib import Path

# --- Qt binding shim: PySide6 first (installed binding), PyQt6 fallback -----
try:
    from PySide6.QtCore import Qt, QThread, Signal, Slot, QSortFilterProxyModel, QModelIndex
    from PySide6.QtGui import QStandardItemModel, QStandardItem, QFont, QColor
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QLineEdit, QComboBox, QTableView, QHeaderView, QMenu,
        QPlainTextEdit, QFileDialog, QMessageBox, QDialog, QSplitter,
        QAbstractItemView,
    )
    QT_BINDING = "PySide6"
except ImportError:
    from PyQt6.QtCore import (Qt, QThread, pyqtSignal as Signal,           # type: ignore
                              pyqtSlot as Slot, QSortFilterProxyModel, QModelIndex)
    from PyQt6.QtGui import QStandardItemModel, QStandardItem, QFont, QColor  # type: ignore
    from PyQt6.QtWidgets import (                                          # type: ignore
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
        QPushButton, QLineEdit, QComboBox, QTableView, QHeaderView, QMenu,
        QPlainTextEdit, QFileDialog, QMessageBox, QDialog, QSplitter,
        QAbstractItemView,
    )
    QT_BINDING = "PyQt6"

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import winreg

APP_NAME = "Program Inventory"
APP_VERSION = "3.2.0"

# --- Dark-industrial palette -------------------------------------------------
OBSIDIAN = "#0b0f14"
STEEL    = "#232b35"
STEEL_HI = "#2c3642"
TEAL     = "#2fd6c3"
PHOSPHOR = "#4be08a"
AMBER    = "#ffb454"
RED      = "#ff5c66"
TEXT     = "#d7e0ea"
TEXT_DIM = "#7a8794"
MONO     = "JetBrains Mono"

QSS = f"""
* {{ font-family: '{MONO}', 'Consolas', monospace; font-size: 12px; }}
QMainWindow, QDialog {{ background: {OBSIDIAN}; }}
QWidget {{ color: {TEXT}; }}
QLabel#Header {{ color: {TEAL}; font-size: 16px; font-weight: bold; letter-spacing: 2px; }}
QLabel#SubHeader {{ color: {TEXT_DIM}; font-size: 11px; letter-spacing: 1px; }}
QLabel.chip {{
    background: {STEEL}; color: {TEXT}; padding: 4px 10px;
    border: 1px solid {STEEL_HI}; border-radius: 0px;
}}
QLabel.chipOk    {{ color: {PHOSPHOR}; }}
QLabel.chipWarn  {{ color: {AMBER}; }}
QLabel.chipErr   {{ color: {RED}; }}
QPushButton {{
    background: {STEEL}; color: {TEXT}; border: 1px solid {STEEL_HI};
    padding: 7px 16px; border-radius: 0px; font-weight: bold;
}}
QPushButton:hover  {{ border-color: {TEAL}; color: {TEAL}; }}
QPushButton:pressed {{ background: {OBSIDIAN}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; border-color: {STEEL}; }}
QPushButton#Primary {{ border-color: {TEAL}; color: {TEAL}; }}
QPushButton#Primary:hover {{ background: {TEAL}; color: {OBSIDIAN}; }}
QPushButton#Danger:hover {{ border-color: {RED}; color: {RED}; }}
QPushButton:checked {{ background: {AMBER}; color: {OBSIDIAN}; border-color: {AMBER}; }}
QLineEdit, QComboBox {{
    background: {STEEL}; color: {TEXT}; border: 1px solid {STEEL_HI};
    padding: 6px 10px; border-radius: 0px; selection-background-color: {TEAL};
    selection-color: {OBSIDIAN};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {TEAL}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {STEEL}; color: {TEXT}; border: 1px solid {TEAL};
    selection-background-color: {TEAL}; selection-color: {OBSIDIAN};
    outline: none;
}}
QTableView {{
    background: {OBSIDIAN}; alternate-background-color: #10161d;
    color: {TEXT}; gridline-color: {STEEL};
    border: 1px solid {STEEL_HI}; border-radius: 0px;
    selection-background-color: {STEEL_HI}; selection-color: {TEAL};
}}
QHeaderView::section {{
    background: {STEEL}; color: {TEAL}; border: none;
    border-right: 1px solid {OBSIDIAN}; border-bottom: 1px solid {TEAL};
    padding: 6px 8px; font-weight: bold;
}}
QPlainTextEdit {{
    background: #10161d; color: {TEXT}; border: 1px solid {STEEL_HI};
    border-radius: 0px; selection-background-color: {TEAL};
    selection-color: {OBSIDIAN};
}}
QMenu {{ background: {STEEL}; color: {TEXT}; border: 1px solid {TEAL}; }}
QMenu::item {{ padding: 6px 24px; }}
QMenu::item:selected {{ background: {TEAL}; color: {OBSIDIAN}; }}
QScrollBar:vertical {{ background: {OBSIDIAN}; width: 12px; }}
QScrollBar::handle:vertical {{ background: {STEEL_HI}; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {TEAL}; }}
QScrollBar:horizontal {{ background: {OBSIDIAN}; height: 12px; }}
QScrollBar::handle:horizontal {{ background: {STEEL_HI}; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {TEAL}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QSplitter::handle {{ background: {STEEL}; }}
"""

COLUMNS = ["Name", "Version", "Update", "Publisher", "Installed", "Size (MB)", "Arch", "Source", "Location"]
(COL_NAME, COL_VER, COL_UPD, COL_PUB, COL_DATE, COL_SIZE, COL_ARCH, COL_SRC,
 COL_LOC) = range(9)
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
DATA_ROLE = Qt.ItemDataRole.UserRole + 2   # full record dict on column 0

NOISE_TERMS = ("windows update", "security update", "hotfix", "edge webview")


# =============================================================================
#  Registry scan
# =============================================================================
def _parse_install_date(raw: str) -> str:
    """Normalise InstallDate ('20240315', sometimes 'MM/DD/YYYY') to ISO."""
    raw = (raw or "").strip()
    if not raw:
        return ""
    for fmt in ("%Y%m%d", "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return raw


def scan_installed_programs() -> list[dict]:
    """Enumerate uninstall entries across HKLM(64), HKLM(32/WOW64), HKCU."""
    if not IS_WINDOWS:
        raise RuntimeError("Registry scan requires Windows.")

    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    views = [
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY, "64-bit", "HKLM"),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY, "32-bit", "HKLM"),
        (winreg.HKEY_CURRENT_USER,  0,                      "user",   "HKCU"),
    ]

    programs: list[dict] = []
    for hive, wow_flag, arch, hive_name in views:
        try:
            root = winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | wow_flag)
        except OSError:
            continue
        with root:
            count = winreg.QueryInfoKey(root)[0]
            for i in range(count):
                try:
                    sub_name = winreg.EnumKey(root, i)
                    with winreg.OpenKey(root, sub_name, 0, winreg.KEY_READ | wow_flag) as sub:
                        def gv(name, _sub=sub):
                            try:
                                return winreg.QueryValueEx(_sub, name)[0]
                            except OSError:
                                return ""

                        name = str(gv("DisplayName")).strip()
                        if not name:
                            continue
                        low = name.lower()
                        if any(t in low for t in NOISE_TERMS) or low.startswith("kb"):
                            continue
                        if gv("SystemComponent") == 1 or str(gv("SystemComponent")) == "1":
                            continue

                        size_kb = gv("EstimatedSize")
                        try:
                            size_mb = round(int(size_kb) / 1024, 1) if size_kb else None
                        except (ValueError, TypeError):
                            size_mb = None

                        programs.append({
                            "Name": name,
                            "Version": str(gv("DisplayVersion")).strip(),
                            "Publisher": str(gv("Publisher")).strip(),
                            "InstallDate": _parse_install_date(str(gv("InstallDate"))),
                            "SizeMB": size_mb,
                            "Arch": arch,
                            "Source": hive_name,
                            "InstallLocation": str(gv("InstallLocation")).strip(),
                            "UninstallString": str(gv("UninstallString")).strip(),
                            "QuietUninstallString": str(gv("QuietUninstallString")).strip(),
                            "URLInfoAbout": str(gv("URLInfoAbout")).strip(),
                            "RegistryPath": f"{hive_name}\\{uninstall}\\{sub_name}"
                                            + (f"  [{arch} view]" if arch == "32-bit" else ""),
                        })
                except OSError:
                    continue

    # Dedupe by (name, version) — HKLM 64 wins over 32 wins over HKCU (scan order).
    seen: set[tuple] = set()
    unique = []
    for p in programs:
        key = (p["Name"].lower(), p["Version"])
        if key not in seen:
            seen.add(key)
            unique.append(p)
    unique.sort(key=lambda p: p["Name"].lower())
    return unique


# =============================================================================
#  History store — SQLite timeline with chain-hashed audit log
# =============================================================================
class HistoryStore:
    """Every scan is persisted automatically. Each scan row carries a SHA-256
    hash chained to the previous scan's hash, so history tampering is
    detectable via verify_chain(). All access is main-thread only."""

    def __init__(self, db_path: Path | None = None):
        self.path = db_path or Path.home() / ".program_inventory" / "history.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS scans(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, host TEXT, count INTEGER,
                added INTEGER, removed INTEGER, changed INTEGER,
                prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entries(
                scan_id INTEGER NOT NULL, name TEXT NOT NULL,
                version TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL, ts TEXT NOT NULL,
                kind TEXT NOT NULL, name TEXT NOT NULL,
                old_version TEXT, new_version TEXT);
            CREATE TABLE IF NOT EXISTS actions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
                command TEXT, exit_code INTEGER);
            CREATE INDEX IF NOT EXISTS idx_entries_scan ON entries(scan_id);
            CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
            CREATE INDEX IF NOT EXISTS idx_actions_name ON actions(name);
        """)
        self.con.commit()

    # --- hashing ---------------------------------------------------------
    @staticmethod
    def _canonical(rows: list[tuple[str, str, str]]) -> str:
        """Canonical form over (name, version, data_json) rows. Covers the
        columns diffs read AND the full record blobs, so tampering with any
        of them breaks the chain."""
        items = sorted(
            (n, v or "", hashlib.sha256(d.encode("utf-8")).hexdigest())
            for n, v, d in rows)
        return json.dumps(items, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _scan_hash(prev_hash: str, ts: str, host: str, canonical: str) -> str:
        return hashlib.sha256(
            f"{prev_hash}|{ts}|{host}|{canonical}".encode("utf-8")).hexdigest()

    # --- write ------------------------------------------------------------
    def save_scan(self, programs: list[dict]) -> dict:
        """Persist a scan, diff against the previous one, record events.
        Returns {'scan_id', 'added', 'removed', 'changed', 'baseline'}."""
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        host = os.environ.get("COMPUTERNAME", "")
        prev = self.con.execute(
            "SELECT id, hash FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        prev_id, prev_hash = (prev if prev else (None, "GENESIS"))

        new_map = {p["Name"]: p.get("Version", "") for p in programs}
        added: list[str] = []
        removed: list[str] = []
        changed: list[tuple[str, str, str]] = []
        old_map: dict[str, str] = {}
        if prev_id is not None:
            old_map = dict(self.con.execute(
                "SELECT name, version FROM entries WHERE scan_id=?", (prev_id,)))
            added = sorted(set(new_map) - set(old_map), key=str.lower)
            removed = sorted(set(old_map) - set(new_map), key=str.lower)
            changed = sorted(
                ((n, old_map[n], new_map[n])
                 for n in set(new_map) & set(old_map) if new_map[n] != old_map[n]),
                key=lambda t: t[0].lower())

        entry_rows = [(p["Name"], p.get("Version", ""),
                       json.dumps(p, ensure_ascii=False)) for p in programs]
        canonical = self._canonical(entry_rows)
        h = self._scan_hash(prev_hash, ts, host, canonical)
        cur = self.con.execute(
            "INSERT INTO scans(ts, host, count, added, removed, changed, prev_hash, hash)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (ts, host, len(programs), len(added), len(removed), len(changed),
             prev_hash, h))
        scan_id = cur.lastrowid
        self.con.executemany(
            "INSERT INTO entries(scan_id, name, version, data) VALUES(?,?,?,?)",
            [(scan_id, n, v, d) for n, v, d in entry_rows])
        ev = ([(scan_id, ts, "added", n, None, new_map[n]) for n in added]
              + [(scan_id, ts, "removed", n, old_map[n], None) for n in removed]
              + [(scan_id, ts, "changed", n, o, v) for n, o, v in changed])
        if ev:
            self.con.executemany(
                "INSERT INTO events(scan_id, ts, kind, name, old_version, new_version)"
                " VALUES(?,?,?,?,?,?)", ev)
        self.con.commit()
        return {"scan_id": scan_id, "added": added, "removed": removed,
                "changed": changed, "baseline": prev_id is None}

    # --- read --------------------------------------------------------------
    def latest_scan(self) -> tuple[int, str, list[dict]] | None:
        row = self.con.execute(
            "SELECT id, ts FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return row[0], row[1], self.entries_for(row[0])

    def entries_for(self, scan_id: int) -> list[dict]:
        rows = self.con.execute(
            "SELECT data FROM entries WHERE scan_id=? ORDER BY name COLLATE NOCASE",
            (scan_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def scans(self) -> list[tuple]:
        """(id, ts, host, count, added, removed, changed, hash) newest first."""
        return self.con.execute(
            "SELECT id, ts, host, count, added, removed, changed, hash"
            " FROM scans ORDER BY id DESC").fetchall()

    def events_for_program(self, name: str) -> list[tuple]:
        return self.con.execute(
            "SELECT ts, kind, old_version, new_version FROM events"
            " WHERE name=? ORDER BY id", (name,)).fetchall()

    def first_seen(self, name: str) -> str | None:
        row = self.con.execute(
            "SELECT s.ts FROM entries e JOIN scans s ON s.id=e.scan_id"
            " WHERE e.name=? ORDER BY e.scan_id LIMIT 1", (name,)).fetchone()
        return row[0] if row else None

    def log_action(self, kind: str, name: str, command: str,
                   exit_code: int | None):
        """Informational action log (uninstall runs etc.). The resulting
        inventory change itself is captured by the chain-hashed scan diff."""
        self.con.execute(
            "INSERT INTO actions(ts, kind, name, command, exit_code)"
            " VALUES(?,?,?,?,?)",
            (datetime.datetime.now().isoformat(timespec="seconds"),
             kind, name, command, exit_code))
        self.con.commit()

    def actions_for_program(self, name: str) -> list[tuple]:
        return self.con.execute(
            "SELECT ts, kind, command, exit_code FROM actions"
            " WHERE name=? ORDER BY id", (name,)).fetchall()

    # --- integrity / maintenance --------------------------------------------
    def verify_chain(self) -> tuple[bool, str]:
        rows = self.con.execute(
            "SELECT id, ts, host, prev_hash, hash FROM scans ORDER BY id").fetchall()
        if not rows:
            return True, "Audit chain empty — nothing to verify."
        expected_prev = "GENESIS"
        for sid, ts, host, prev_hash, stored in rows:
            if prev_hash != expected_prev:
                return False, f"BREAK at scan #{sid}: prev_hash linkage mismatch."
            rows_ = self.con.execute(
                "SELECT name, version, data FROM entries WHERE scan_id=?",
                (sid,)).fetchall()
            canonical = self._canonical(rows_)
            if self._scan_hash(prev_hash, ts, host or "", canonical) != stored:
                return False, f"BREAK at scan #{sid}: recomputed hash != stored hash."
            expected_prev = stored
        return True, f"Audit chain intact — {len(rows)} scans verified."

    def purge(self):
        self.con.executescript(
            "DELETE FROM events; DELETE FROM entries; DELETE FROM scans;"
            " DELETE FROM actions;")
        self.con.commit()
        self.con.execute("VACUUM")

    def close(self):
        self.con.close()


class ScanWorker(QThread):
    """QThread subclass (project convention) — never moveToThread."""
    scan_done = Signal(list)
    scan_failed = Signal(str)

    def run(self):
        try:
            self.scan_done.emit(scan_installed_programs())
        except Exception as exc:  # noqa: BLE001 — surface everything to UI
            self.scan_failed.emit(str(exc))


# =============================================================================
#  Winget update intelligence
# =============================================================================
WINGET_ELLIPSIS = "\u2026"


def parse_winget_upgrade(output: str) -> list[dict]:
    """Parse `winget upgrade` fixed-width table output.

    winget has no JSON output for the upgrade list, so we locate header
    lines ('Name ... Id ... Version ... Available ...'), take the column
    start offsets from the header, and slice each data row. Handles multiple
    table sections (regular + 'require explicit targeting') and skips
    separators/summary lines. Known limitation: rows containing wide CJK
    glyphs can mis-slice because winget pads by display width, not chars.
    """
    rows: list[dict] = []
    offsets: list[tuple[str, int]] | None = None
    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        if (stripped.startswith("Name") and " Id" in line
                and "Version" in line and "Available" in line):
            offsets = sorted(
                ((col, line.index(col)) for col in
                 ("Name", "Id", "Version", "Available", "Source")
                 if col in line),
                key=lambda t: t[1])
            continue
        if offsets is None:
            continue
        if set(stripped) <= {"-"}:          # separator row
            continue
        # Aligned data rows have a space immediately before each column
        # start; prose lines ("The following packages ...") don't.
        if any(start > 0 and len(line) > start and line[start - 1] != " "
               for _, start in offsets):
            continue
        rec: dict = {}
        for j, (col, start) in enumerate(offsets):
            end = offsets[j + 1][1] if j + 1 < len(offsets) else None
            rec[col] = line[start:end].strip()
        if rec.get("Name") and rec.get("Available"):
            rows.append(rec)
    return rows


def match_winget_row(registry_name: str, winget_name: str) -> bool:
    """winget truncates long names/ids with '…' — prefix-match those."""
    rn, wn = registry_name.lower(), winget_name.lower()
    if wn.endswith(WINGET_ELLIPSIS):
        return rn.startswith(wn[:-1])
    return rn == wn


def winget_upgrade_command(update: dict) -> str:
    """Build a copy-ready upgrade command. If the Id was display-truncated,
    fall back to matching by name (quoted)."""
    wid = update.get("Id", "")
    if wid and WINGET_ELLIPSIS not in wid:
        return f'winget upgrade --id "{wid}"'
    return f'winget upgrade --name "{update.get("Name", "")}"'


class WingetWorker(QThread):
    """QThread subclass (project convention). Shells out to winget."""
    updates_done = Signal(list)
    updates_failed = Signal(str)

    def run(self):
        if not IS_WINDOWS:
            self.updates_failed.emit("winget requires Windows.")
            return
        try:
            proc = subprocess.run(
                ["winget", "upgrade", "--include-unknown",
                 "--disable-interactivity", "--accept-source-agreements"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180,
                creationflags=0x08000000,  # CREATE_NO_WINDOW — no console flash
            )
        except FileNotFoundError:
            self.updates_failed.emit(
                "winget not found — install 'App Installer' from the Microsoft Store.")
            return
        except subprocess.TimeoutExpired:
            self.updates_failed.emit("winget timed out after 180 s.")
            return
        if proc.returncode not in (0,):
            # winget exits non-zero for 'no applicable upgrade' etc. — still
            # try to parse; only fail if we also got nothing usable.
            parsed = parse_winget_upgrade(proc.stdout or "")
            if parsed:
                self.updates_done.emit(parsed)
            else:
                self.updates_failed.emit(
                    f"winget exit code {proc.returncode}:\n"
                    f"{(proc.stderr or proc.stdout or '').strip()[:400]}")
            return
        self.updates_done.emit(parse_winget_upgrade(proc.stdout or ""))


# =============================================================================
#  Governed uninstall
# =============================================================================
MSI_EXIT = {
    0:    ("success", True),
    1602: ("cancelled by user", False),
    1603: ("fatal error during uninstall", False),
    1618: ("another installation is already in progress", False),
    3010: ("success — reboot required", True),
}


class UninstallWorker(QThread):
    """Runs a registry UninstallString. On Windows the command string is
    passed verbatim to CreateProcess (no cmd.exe shell layer)."""
    finished_code = Signal(int)
    failed = Signal(str)

    def __init__(self, command: str, silent: bool):
        super().__init__()
        self.command = command
        self.silent = silent

    def run(self):
        try:
            proc = subprocess.run(
                self.command, timeout=900,
                creationflags=(0x08000000 if self.silent else 0),
            )
            self.finished_code.emit(proc.returncode)
        except subprocess.TimeoutExpired:
            self.failed.emit("Uninstaller timed out after 15 minutes.")
        except (OSError, ValueError) as exc:
            self.failed.emit(str(exc))


class UninstallDialog(QDialog):
    """Deny-first confirmation gate. The UNINSTALL button stays disabled
    until the exact program name is typed. Silent mode is offered only when
    the vendor recorded a QuietUninstallString — no synthesised flags."""

    def __init__(self, rec: dict, parent=None):
        super().__init__(parent)
        self.rec = rec
        self.chosen_command = ""
        self.silent = False
        self.setWindowTitle("Governed Uninstall")
        self.resize(640, 360)

        lay = QVBoxLayout(self)
        head = QLabel("GOVERNED UNINSTALL")
        head.setObjectName("Header")
        lay.addWidget(head)

        info = QPlainTextEdit()
        info.setReadOnly(True)
        info.setMaximumHeight(130)
        info.setPlainText(
            f"NAME       {rec['Name']}\n"
            f"VERSION    {rec['Version'] or '—'}\n"
            f"PUBLISHER  {rec['Publisher'] or '—'}\n"
            f"COMMAND    {rec['UninstallString']}\n"
            + (f"SILENT     {rec['QuietUninstallString']}\n"
               if rec.get("QuietUninstallString") else ""))
        lay.addWidget(info)

        self.silent_combo = QComboBox()
        self.silent_combo.addItem("Interactive — vendor uninstaller UI", False)
        if rec.get("QuietUninstallString"):
            self.silent_combo.addItem("Silent — vendor QuietUninstallString", True)
        lay.addWidget(self.silent_combo)

        prompt = QLabel(f"Type the program name exactly to arm:  {rec['Name']}")
        prompt.setWordWrap(True)
        lay.addWidget(prompt)
        self.confirm_edit = QLineEdit()
        self.confirm_edit.setPlaceholderText("program name…")
        self.confirm_edit.textChanged.connect(self._check_armed)
        lay.addWidget(self.confirm_edit)

        btns = QHBoxLayout()
        self.go_btn = QPushButton("UNINSTALL")
        self.go_btn.setObjectName("Danger")
        self.go_btn.setEnabled(False)
        self.go_btn.clicked.connect(self._accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addStretch(1)
        btns.addWidget(cancel)
        btns.addWidget(self.go_btn)
        lay.addLayout(btns)

    @Slot()
    def _check_armed(self):
        self.go_btn.setEnabled(self.confirm_edit.text() == self.rec["Name"])

    @Slot()
    def _accept(self):
        self.silent = bool(self.silent_combo.currentData())
        self.chosen_command = (self.rec["QuietUninstallString"] if self.silent
                               else self.rec["UninstallString"])
        self.accept()


# =============================================================================
#  Filter proxy
# =============================================================================
class InventoryProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_text = ""
        self.publisher = ""            # "" = all
        self.max_age_days = 0          # 0 = all
        self.updates_only = False
        self.setSortRole(SORT_ROLE)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_filters(self, search: str, publisher: str, max_age_days: int,
                    updates_only: bool = False):
        self.search_text = search.lower().strip()
        self.publisher = publisher
        self.max_age_days = max_age_days
        self.updates_only = updates_only
        self.invalidateFilter()

    def filterAcceptsRow(self, row: int, parent: QModelIndex) -> bool:
        m = self.sourceModel()
        rec = m.index(row, COL_NAME, parent).data(DATA_ROLE)
        if rec is None:
            return False
        if self.search_text:
            hay = f"{rec['Name']} {rec['Publisher']} {rec['Version']}".lower()
            if self.search_text not in hay:
                return False
        if self.publisher and rec["Publisher"] != self.publisher:
            return False
        if self.updates_only and not rec.get("_update"):
            return False
        if self.max_age_days:
            date = rec.get("InstallDate", "")
            try:
                dt = datetime.datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                return False
            if (datetime.datetime.now() - dt).days > self.max_age_days:
                return False
        return True


# =============================================================================
#  Snapshot diff dialog
# =============================================================================
class DiffDialog(QDialog):
    def __init__(self, report: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Snapshot Comparison")
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        head = QLabel("SNAPSHOT DIFF")
        head.setObjectName("Header")
        lay.addWidget(head)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(report)
        lay.addWidget(text)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)


class TimelineDialog(QDialog):
    """Every recorded scan, newest first. Select one to diff against the
    current table contents or to reload it."""

    def __init__(self, store: HistoryStore, current: list[dict], parent=None):
        super().__init__(parent)
        self.store = store
        self.current = current
        self.loaded_scan: list[dict] | None = None
        self.setWindowTitle("Scan Timeline")
        self.resize(860, 520)

        lay = QVBoxLayout(self)
        head = QLabel("SCAN TIMELINE")
        head.setObjectName("Header")
        lay.addWidget(head)

        self.model = QStandardItemModel(0, 7)
        self.model.setHorizontalHeaderLabels(
            ["#", "Timestamp", "Host", "Programs", "+ / − / ~", "Hash", ""])
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, stretch=1)

        self._scan_ids: list[int] = []
        for sid, ts, host, count, a, r, c, h in store.scans():
            self._scan_ids.append(sid)
            row = [QStandardItem(str(x)) for x in
                   (sid, ts, host or "—", count, f"+{a} / -{r} / ~{c}",
                    h[:16] + "…", "")]
            for it in row:
                it.setEditable(False)
            self.model.appendRow(row)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 170)
        self.table.setColumnWidth(3, 90)
        self.table.setColumnWidth(4, 120)

        btns = QHBoxLayout()
        diff_btn = QPushButton("Diff selected vs current")
        diff_btn.clicked.connect(self.diff_selected)
        load_btn = QPushButton("Load selected into table")
        load_btn.clicked.connect(self.load_selected)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(diff_btn)
        btns.addWidget(load_btn)
        btns.addStretch(1)
        btns.addWidget(close)
        lay.addLayout(btns)

    def _selected_scan_id(self) -> int | None:
        sel = self.table.selectionModel().selectedRows()
        return self._scan_ids[sel[0].row()] if sel else None

    def diff_selected(self):
        sid = self._selected_scan_id()
        if sid is None:
            return
        old_entries = self.store.entries_for(sid)
        old = {p["Name"]: p.get("Version", "") for p in old_entries}
        new = {p["Name"]: p.get("Version", "") for p in self.current}
        added = sorted(set(new) - set(old), key=str.lower)
        removed = sorted(set(old) - set(new), key=str.lower)
        changed = sorted((n for n in set(new) & set(old) if new[n] != old[n]),
                         key=str.lower)
        lines = [f"Scan #{sid} -> current table", ""]
        lines.append(f"[+] ADDED ({len(added)})")
        lines += [f"    + {n}  {new[n]}" for n in added] or ["    (none)"]
        lines.append("")
        lines.append(f"[-] REMOVED ({len(removed)})")
        lines += [f"    - {n}  {old[n]}" for n in removed] or ["    (none)"]
        lines.append("")
        lines.append(f"[~] VERSION CHANGED ({len(changed)})")
        lines += [f"    ~ {n}  {old[n]}  ->  {new[n]}" for n in changed] or ["    (none)"]
        DiffDialog("\n".join(lines), self).exec()

    def load_selected(self):
        sid = self._selected_scan_id()
        if sid is None:
            return
        self.loaded_scan = self.store.entries_for(sid)
        self.accept()


class ProgramHistoryDialog(QDialog):
    def __init__(self, store: HistoryStore, name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"History — {name}")
        self.resize(680, 420)
        lay = QVBoxLayout(self)
        head = QLabel("PROGRAM HISTORY")
        head.setObjectName("Header")
        lay.addWidget(head)

        lines = [f"Program : {name}"]
        first = store.first_seen(name)
        lines.append(f"First seen in history : {first or 'never recorded'}")
        lines.append("")
        events = store.events_for_program(name)
        if not events:
            lines.append("No change events recorded — present and unchanged "
                         "since first recorded scan, or never scanned.")
        else:
            for ts, kind, old, new in events:
                if kind == "added":
                    lines.append(f"{ts}  [+] installed  {new or ''}")
                elif kind == "removed":
                    lines.append(f"{ts}  [-] removed    (was {old or '?'})")
                else:
                    lines.append(f"{ts}  [~] upgraded   {old or '?'}  ->  {new or '?'}")
        actions = store.actions_for_program(name)
        if actions:
            lines.append("")
            lines.append("Logged actions:")
            for ts, kind, cmd, code in actions:
                code_txt = "did not run" if code is None else f"exit {code}"
                lines.append(f"{ts}  [!] {kind} ({code_txt})  {cmd or ''}")
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines))
        lay.addWidget(text)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)


# =============================================================================
#  Main window
# =============================================================================
class InventoryWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — 7h3v01d")
        self.resize(1320, 780)
        self.setMinimumSize(1024, 620)

        self.programs: list[dict] = []
        self._worker_refs: set = set()   # GC-safety for QThreads (convention)
        self.updates: dict[str, dict] = {}   # registry Name -> winget row
        self.history = HistoryStore()

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # --- Header ---------------------------------------------------------
        head_row = QHBoxLayout()
        title = QLabel("PROGRAM INVENTORY")
        title.setObjectName("Header")
        sub = QLabel(f"// installed software scanner · {QT_BINDING}")
        sub.setObjectName("SubHeader")
        head_row.addWidget(title)
        head_row.addWidget(sub)
        head_row.addStretch(1)
        root.addLayout(head_row)

        # --- Toolbar --------------------------------------------------------
        bar = QHBoxLayout()
        self.scan_btn = QPushButton("SCAN")
        self.scan_btn.setObjectName("Primary")
        self.scan_btn.clicked.connect(self.start_scan)
        bar.addWidget(self.scan_btn)

        self.updates_btn = QPushButton("CHECK UPDATES")
        self.updates_btn.setToolTip("Query winget for available upgrades")
        self.updates_btn.clicked.connect(self.start_update_check)
        bar.addWidget(self.updates_btn)

        self.export_btn = QPushButton("EXPORT ▾")
        exp_menu = QMenu(self)
        exp_menu.addAction("CSV", self.export_csv)
        exp_menu.addAction("JSON", self.export_json)
        exp_menu.addAction("TXT report", self.export_txt)
        exp_menu.addAction("Markdown table", self.export_md)
        self.export_btn.setMenu(exp_menu)
        bar.addWidget(self.export_btn)

        self.snap_btn = QPushButton("SNAPSHOT ▾")
        snap_menu = QMenu(self)
        snap_menu.addAction("Save snapshot…", self.save_snapshot)
        snap_menu.addAction("Compare against snapshot…", self.compare_snapshot)
        self.snap_btn.setMenu(snap_menu)
        bar.addWidget(self.snap_btn)

        self.hist_btn = QPushButton("HISTORY ▾")
        hist_menu = QMenu(self)
        hist_menu.addAction("Timeline…", self.show_timeline)
        hist_menu.addAction("Verify audit chain", self.verify_chain)
        hist_menu.addSeparator()
        hist_menu.addAction("Open database folder", self.open_db_folder)
        hist_menu.addAction("Purge history…", self.purge_history)
        self.hist_btn.setMenu(hist_menu)
        bar.addWidget(self.hist_btn)

        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setObjectName("Danger")
        self.clear_btn.clicked.connect(self.clear_table)
        bar.addWidget(self.clear_btn)
        bar.addStretch(1)

        # Filters
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("filter name / publisher / version…")
        self.search_edit.setMinimumWidth(260)
        self.search_edit.textChanged.connect(self.apply_filters)
        bar.addWidget(self.search_edit)

        self.pub_combo = QComboBox()
        self.pub_combo.addItem("All publishers", "")
        self.pub_combo.setMinimumWidth(180)
        self.pub_combo.currentIndexChanged.connect(self.apply_filters)
        bar.addWidget(self.pub_combo)

        self.age_combo = QComboBox()
        for label, days in [("Any age", 0), ("Last 30 days", 30),
                            ("Last 90 days", 90), ("Last year", 365)]:
            self.age_combo.addItem(label, days)
        self.age_combo.currentIndexChanged.connect(self.apply_filters)
        bar.addWidget(self.age_combo)

        self.upd_toggle = QPushButton("UPDATABLE")
        self.upd_toggle.setCheckable(True)
        self.upd_toggle.setToolTip("Show only programs with a winget update available")
        self.upd_toggle.toggled.connect(self.apply_filters)
        bar.addWidget(self.upd_toggle)
        root.addLayout(bar)

        # --- Table + detail splitter -----------------------------------------
        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.proxy = InventoryProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.selectionModel().selectionChanged.connect(self.update_detail)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        for col, w in [(COL_NAME, 320), (COL_VER, 100), (COL_UPD, 100),
                       (COL_PUB, 190), (COL_DATE, 100), (COL_SIZE, 85),
                       (COL_ARCH, 65), (COL_SRC, 65)]:
            self.table.setColumnWidth(col, w)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a program to inspect uninstall strings, registry path, and links.")
        self.detail.setMaximumHeight(170)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 1)
        root.addWidget(split, stretch=1)

        # --- Status chips -----------------------------------------------------
        chips = QHBoxLayout()
        self.chip_status = self._chip("READY — hit SCAN", "chip")
        self.chip_count = self._chip("0 programs", "chip")
        self.chip_shown = self._chip("0 shown", "chip")
        self.chip_size = self._chip("— MB total", "chip")
        self.chip_drift = self._chip("no history", "chip")
        self.chip_updates = self._chip("updates: —", "chip")
        for c in (self.chip_status, self.chip_count, self.chip_shown,
                  self.chip_size, self.chip_drift, self.chip_updates):
            chips.addWidget(c)
        chips.addStretch(1)
        root.addLayout(chips)

        self._restore_latest_scan()

    def _restore_latest_scan(self):
        """On launch, reload the most recent scan so the app opens with data."""
        try:
            latest = self.history.latest_scan()
        except (sqlite3.Error, json.JSONDecodeError):
            return
        if not latest:
            return
        scan_id, ts, entries = latest
        self.programs = entries
        self.populate()
        self._set_status(f"LOADED FROM HISTORY — scan #{scan_id} @ {ts}", TEAL)
        row = self.history.con.execute(
            "SELECT added, removed, changed FROM scans WHERE id=?",
            (scan_id,)).fetchone()
        if row:
            self._set_drift(*row)

    def _set_drift(self, a: int, r: int, c: int):
        total = a + r + c
        color = PHOSPHOR if total == 0 else AMBER
        text = "no drift" if total == 0 else f"drift +{a} / -{r} / ~{c}"
        self.chip_drift.setText(text)
        self.chip_drift.setStyleSheet(
            f"background:{STEEL}; border:1px solid {STEEL_HI}; "
            f"padding:4px 10px; color:{color};")

    # --- helpers --------------------------------------------------------------
    def _chip(self, text: str, cls: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setProperty("class", cls)
        lbl.setObjectName("chip")
        lbl.setStyleSheet(f"background:{STEEL}; border:1px solid {STEEL_HI}; padding:4px 10px;")
        return lbl

    def _set_status(self, text: str, color: str = TEXT):
        self.chip_status.setText(text)
        self.chip_status.setStyleSheet(
            f"background:{STEEL}; border:1px solid {STEEL_HI}; padding:4px 10px; color:{color};")

    # --- scan -------------------------------------------------------------
    @Slot()
    def start_scan(self):
        if not IS_WINDOWS:
            QMessageBox.critical(self, "Unsupported OS",
                                 "Registry scanning requires Windows.")
            return
        self.scan_btn.setEnabled(False)
        self._set_status("SCANNING…", AMBER)
        worker = ScanWorker()
        self._worker_refs.add(worker)
        worker.scan_done.connect(self.on_scan_done)
        worker.scan_failed.connect(self.on_scan_failed)
        worker.finished.connect(lambda w=worker: self._worker_refs.discard(w))
        worker.start()

    @Slot(list)
    def on_scan_done(self, programs: list):
        for p in programs:
            p.pop("_update", None)   # fresh scans never carry winget state
        self.programs = programs
        self.updates.clear()
        self.chip_updates.setText("updates: —")
        self.chip_updates.setStyleSheet(
            f"background:{STEEL}; border:1px solid {STEEL_HI}; padding:4px 10px;")
        self.populate()
        self.scan_btn.setEnabled(True)
        try:
            result = self.history.save_scan(programs)
        except sqlite3.Error as exc:
            self._set_status("SCAN OK — HISTORY WRITE FAILED", RED)
            QMessageBox.warning(self, "History error",
                                f"Scan succeeded but could not be recorded:\n{exc}")
            return
        if result["baseline"]:
            self._set_status(
                f"SCAN COMPLETE — {len(programs)} programs · baseline recorded",
                PHOSPHOR)
            self.chip_drift.setText("baseline")
        else:
            a, r, c = (len(result["added"]), len(result["removed"]),
                       len(result["changed"]))
            self._set_status(f"SCAN COMPLETE — {len(programs)} programs", PHOSPHOR)
            self._set_drift(a, r, c)
            if a + r + c:
                lines = ["Changes since previous scan:", ""]
                lines.append(f"[+] ADDED ({a})")
                lines += [f"    + {n}" for n in result["added"]] or ["    (none)"]
                lines.append("")
                lines.append(f"[-] REMOVED ({r})")
                lines += [f"    - {n}" for n in result["removed"]] or ["    (none)"]
                lines.append("")
                lines.append(f"[~] VERSION CHANGED ({c})")
                lines += [f"    ~ {n}  {o}  ->  {v}"
                          for n, o, v in result["changed"]] or ["    (none)"]
                DiffDialog("\n".join(lines), self).exec()

    @Slot(str)
    def on_scan_failed(self, msg: str):
        self.scan_btn.setEnabled(True)
        self._set_status("SCAN FAILED", RED)
        QMessageBox.critical(self, "Scan error", msg)

    # --- winget update check -------------------------------------------------
    @Slot()
    def start_update_check(self):
        if not self.programs:
            QMessageBox.information(self, "No inventory",
                                    "Scan (or load history) first, then check updates.")
            return
        self.updates_btn.setEnabled(False)
        self._set_status("CHECKING WINGET…", AMBER)
        worker = WingetWorker()
        self._worker_refs.add(worker)
        worker.updates_done.connect(self.on_updates_done)
        worker.updates_failed.connect(self.on_updates_failed)
        worker.finished.connect(lambda w=worker: self._worker_refs.discard(w))
        worker.start()

    @Slot(list)
    def on_updates_done(self, winget_rows: list):
        self.updates_btn.setEnabled(True)
        self.updates.clear()
        for rec in self.programs:
            rec.pop("_update", None)
        matched = 0
        for wrow in winget_rows:
            for rec in self.programs:
                if match_winget_row(rec["Name"], wrow["Name"]):
                    rec["_update"] = wrow
                    self.updates[rec["Name"]] = wrow
                    matched += 1
                    break
        unmatched = len(winget_rows) - matched
        self.populate()
        if matched == 0:
            self.chip_updates.setText("up to date")
            self.chip_updates.setStyleSheet(
                f"background:{STEEL}; border:1px solid {STEEL_HI}; "
                f"padding:4px 10px; color:{PHOSPHOR};")
            self._set_status("WINGET: NO MATCHING UPDATES", PHOSPHOR)
        else:
            txt = f"{matched} updates"
            if unmatched:
                txt += f" (+{unmatched} unmatched)"
            self.chip_updates.setText(txt)
            self.chip_updates.setStyleSheet(
                f"background:{STEEL}; border:1px solid {STEEL_HI}; "
                f"padding:4px 10px; color:{AMBER};")
            self._set_status(f"WINGET: {matched} UPDATES AVAILABLE", AMBER)

    @Slot(str)
    def on_updates_failed(self, msg: str):
        self.updates_btn.setEnabled(True)
        self._set_status("WINGET CHECK FAILED", RED)
        QMessageBox.warning(self, "winget", msg)

    # --- governed uninstall ---------------------------------------------------
    def start_uninstall(self, rec: dict):
        if not IS_WINDOWS:
            QMessageBox.critical(self, "Unsupported OS",
                                 "Uninstall requires Windows.")
            return
        dlg = UninstallDialog(rec, self)
        if not dlg.exec():
            return
        self._pending_uninstall = (rec["Name"], dlg.chosen_command)
        self._set_status(f"UNINSTALLING — {rec['Name']}", AMBER)
        worker = UninstallWorker(dlg.chosen_command, dlg.silent)
        self._worker_refs.add(worker)
        worker.finished_code.connect(self.on_uninstall_done)
        worker.failed.connect(self.on_uninstall_failed)
        worker.finished.connect(lambda w=worker: self._worker_refs.discard(w))
        worker.start()

    @Slot(int)
    def on_uninstall_done(self, code: int):
        name, cmd = getattr(self, "_pending_uninstall", ("?", "?"))
        self.history.log_action("uninstall", name, cmd, code)
        meaning, ok = MSI_EXIT.get(code, (f"exit code {code}", code == 0))
        if ok:
            self._set_status(
                f"UNINSTALL OK ({meaning}) — RESCANNING", PHOSPHOR)
            self.start_scan()   # removal lands in the chain-hashed history
        else:
            self._set_status(f"UNINSTALL: {meaning.upper()}", RED)
            QMessageBox.warning(
                self, "Uninstall",
                f"{name}\n\nUninstaller finished with: {meaning}\n"
                f"(exit code {code})\n\nAction logged to history database.")

    @Slot(str)
    def on_uninstall_failed(self, msg: str):
        name, cmd = getattr(self, "_pending_uninstall", ("?", "?"))
        self.history.log_action("uninstall", name, cmd, None)
        self._set_status("UNINSTALL FAILED TO RUN", RED)
        QMessageBox.critical(self, "Uninstall", msg)

    # --- model ---------------------------------------------------------------
    def populate(self):
        self.model.setRowCount(0)
        publishers = set()
        total_mb = 0.0
        for rec in self.programs:
            size = rec.get("SizeMB")
            total_mb += size or 0
            publishers.add(rec["Publisher"]) if rec["Publisher"] else None

            def item(text, sort_key=None):
                it = QStandardItem(str(text))
                it.setData(sort_key if sort_key is not None else str(text).lower(), SORT_ROLE)
                return it

            upd = rec.get("_update")
            avail = upd.get("Available", "") if upd else ""
            row = [
                item(rec["Name"]),
                item(rec["Version"]),
                item(avail, avail or "~~~~"),
                item(rec["Publisher"]),
                item(rec["InstallDate"], rec["InstallDate"] or "0000-00-00"),
                item("" if rec["SizeMB"] is None else f"{rec['SizeMB']:.1f}",
                     rec["SizeMB"] if rec["SizeMB"] is not None else -1.0),
                item(rec["Arch"]),
                item(rec["Source"]),
                item(rec["InstallLocation"]),
            ]
            row[COL_NAME].setData(rec, DATA_ROLE)
            if upd:
                row[COL_UPD].setForeground(QColor(AMBER))
            if rec["Arch"] == "32-bit":
                row[COL_ARCH].setForeground(QColor(AMBER))
            elif rec["Arch"] == "user":
                row[COL_ARCH].setForeground(QColor(TEAL))
            self.model.appendRow(row)

        # Publisher combo
        current = self.pub_combo.currentData()
        self.pub_combo.blockSignals(True)
        self.pub_combo.clear()
        self.pub_combo.addItem("All publishers", "")
        for pub in sorted(publishers, key=str.lower):
            self.pub_combo.addItem(pub, pub)
        idx = self.pub_combo.findData(current)
        self.pub_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.pub_combo.blockSignals(False)

        self.chip_count.setText(f"{len(self.programs)} programs")
        self.chip_size.setText(f"{total_mb / 1024:.2f} GB total" if total_mb > 1024
                               else f"{total_mb:.0f} MB total")
        self.apply_filters()

    @Slot()
    def apply_filters(self):
        self.proxy.set_filters(
            self.search_edit.text(),
            self.pub_combo.currentData() or "",
            self.age_combo.currentData() or 0,
            self.upd_toggle.isChecked(),
        )
        self.chip_shown.setText(f"{self.proxy.rowCount()} shown")

    @Slot()
    def clear_table(self):
        self.programs = []
        self.updates.clear()
        self.chip_updates.setText("updates: —")
        self.chip_updates.setStyleSheet(
            f"background:{STEEL}; border:1px solid {STEEL_HI}; padding:4px 10px;")
        self.model.setRowCount(0)
        self.detail.clear()
        self.chip_count.setText("0 programs")
        self.chip_shown.setText("0 shown")
        self.chip_size.setText("— MB total")
        self._set_status("CLEARED", TEXT_DIM)

    # --- detail pane -----------------------------------------------------------
    def _selected_record(self) -> dict | None:
        sel = self.table.selectionModel().selectedRows()
        if not sel:
            return None
        src = self.proxy.mapToSource(sel[0])
        return self.model.index(src.row(), COL_NAME).data(DATA_ROLE)

    @Slot()
    def update_detail(self, *_):
        rec = self._selected_record()
        if not rec:
            self.detail.clear()
            return
        lines = [
            f"NAME       {rec['Name']}",
            f"VERSION    {rec['Version'] or '—'}    PUBLISHER  {rec['Publisher'] or '—'}",
            f"INSTALLED  {rec['InstallDate'] or '—'}    SIZE  "
            f"{'—' if rec['SizeMB'] is None else str(rec['SizeMB']) + ' MB'}    "
            f"ARCH  {rec['Arch']}  ({rec['Source']})",
            f"LOCATION   {rec['InstallLocation'] or '—'}",
            f"UNINSTALL  {rec['UninstallString'] or '—'}",
        ]
        if rec["QuietUninstallString"]:
            lines.append(f"SILENT     {rec['QuietUninstallString']}")
        upd = rec.get("_update")
        if upd:
            lines.append(f"UPDATE     {rec['Version'] or '?'}  ->  "
                         f"{upd['Available']}   ({winget_upgrade_command(upd)})")
        if rec["URLInfoAbout"]:
            lines.append(f"URL        {rec['URLInfoAbout']}")
        lines.append(f"REGISTRY   {rec['RegistryPath']}")
        self.detail.setPlainText("\n".join(lines))

    # --- context menu ---------------------------------------------------------
    @Slot()
    def show_context_menu(self, pos):
        rec = self._selected_record()
        if not rec:
            return
        menu = QMenu(self)
        if rec["InstallLocation"]:
            menu.addAction("Open install folder",
                           lambda: self._open_folder(rec["InstallLocation"]))
        if rec["UninstallString"]:
            menu.addAction("Copy uninstall command",
                           lambda: self._copy(rec["UninstallString"]))
        if rec["QuietUninstallString"]:
            menu.addAction("Copy silent uninstall command",
                           lambda: self._copy(rec["QuietUninstallString"]))
        menu.addAction("Copy name + version",
                       lambda: self._copy(f"{rec['Name']} {rec['Version']}".strip()))
        menu.addAction("Copy registry path",
                       lambda: self._copy(rec["RegistryPath"].split("  [")[0]))
        upd = rec.get("_update")
        if upd:
            menu.addAction("Copy winget upgrade command",
                           lambda: self._copy(winget_upgrade_command(upd)))
        menu.addSeparator()
        menu.addAction("View program history",
                       lambda: ProgramHistoryDialog(
                           self.history, rec["Name"], self).exec())
        menu.addAction("Search web for this program",
                       lambda: webbrowser.open(
                           "https://duckduckgo.com/?q="
                           + rec["Name"].replace(" ", "+")))
        if rec["UninstallString"]:
            menu.addSeparator()
            menu.addAction("Uninstall… (governed)",
                           lambda: self.start_uninstall(rec))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy(self, text: str):
        QApplication.clipboard().setText(text)
        self._set_status("COPIED TO CLIPBOARD", TEAL)

    def _open_folder(self, path: str):
        p = Path(path.strip('"'))
        if p.exists():
            os.startfile(str(p))  # noqa: S606 — Windows-only, user-initiated
        else:
            QMessageBox.warning(self, "Not found", f"Folder does not exist:\n{p}")

    # --- exports ----------------------------------------------------------------
    def _visible_records(self) -> list[dict]:
        """Export respects active filters — WYSIWYG."""
        recs = []
        for row in range(self.proxy.rowCount()):
            src = self.proxy.mapToSource(self.proxy.index(row, COL_NAME))
            recs.append(self.model.index(src.row(), COL_NAME).data(DATA_ROLE))
        return recs

    def _require_data(self) -> list[dict] | None:
        recs = self._visible_records()
        if not recs:
            QMessageBox.warning(self, "No data", "Nothing to export — scan first.")
            return None
        return recs

    def _save_path(self, ext: str, filt: str) -> str:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", f"program_inventory_{stamp}.{ext}", filt)
        return path

    @Slot()
    def export_csv(self):
        recs = self._require_data()
        if not recs:
            return
        path = self._save_path("csv", "CSV (*.csv)")
        if not path:
            return
        fields = ["Name", "Version", "Publisher", "InstallDate", "SizeMB",
                  "Arch", "Source", "InstallLocation", "UninstallString"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(recs)
        self._set_status(f"EXPORTED {len(recs)} → CSV", PHOSPHOR)

    @Slot()
    def export_json(self):
        recs = self._require_data()
        if not recs:
            return
        path = self._save_path("json", "JSON (*.json)")
        if not path:
            return
        payload = {
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "host": os.environ.get("COMPUTERNAME", ""),
            "count": len(recs),
            "programs": recs,
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._set_status(f"EXPORTED {len(recs)} → JSON", PHOSPHOR)

    @Slot()
    def export_txt(self):
        recs = self._require_data()
        if not recs:
            return
        path = self._save_path("txt", "Text (*.txt)")
        if not path:
            return
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"PROGRAM INVENTORY — {now} — {len(recs)} programs", "=" * 100]
        for p in recs:
            lines += [
                f"Name      : {p['Name']}",
                f"Version   : {p['Version'] or 'N/A'}",
                f"Publisher : {p['Publisher'] or 'N/A'}",
                f"Installed : {p['InstallDate'] or 'N/A'}",
                f"Size      : {'N/A' if p['SizeMB'] is None else str(p['SizeMB']) + ' MB'}",
                f"Arch      : {p['Arch']} ({p['Source']})",
                f"Location  : {p['InstallLocation'] or 'N/A'}",
                "-" * 100,
            ]
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._set_status(f"EXPORTED {len(recs)} → TXT", PHOSPHOR)

    @Slot()
    def export_md(self):
        recs = self._require_data()
        if not recs:
            return
        path = self._save_path("md", "Markdown (*.md)")
        if not path:
            return
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [f"# Program Inventory — {now}", "",
                 f"{len(recs)} programs.", "",
                 "| Name | Version | Publisher | Installed | Size (MB) | Arch |",
                 "|---|---|---|---|---|---|"]
        for p in recs:
            esc = lambda s: str(s).replace("|", "\\|")
            lines.append(
                f"| {esc(p['Name'])} | {esc(p['Version'])} | {esc(p['Publisher'])} "
                f"| {p['InstallDate']} | {'' if p['SizeMB'] is None else p['SizeMB']} "
                f"| {p['Arch']} |")
        Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        self._set_status(f"EXPORTED {len(recs)} → MARKDOWN", PHOSPHOR)

    # --- snapshots ---------------------------------------------------------------
    @Slot()
    def save_snapshot(self):
        if not self.programs:
            QMessageBox.warning(self, "No data", "Scan first, then snapshot.")
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save snapshot", f"inventory_snapshot_{stamp}.json",
            "Snapshot (*.json)")
        if not path:
            return
        payload = {
            "snapshot_version": 1,
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "host": os.environ.get("COMPUTERNAME", ""),
            "programs": {p["Name"]: p["Version"] for p in self.programs},
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._set_status("SNAPSHOT SAVED", PHOSPHOR)

    @Slot()
    def compare_snapshot(self):
        if not self.programs:
            QMessageBox.warning(self, "No data",
                                "Scan first, then compare against a snapshot.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open snapshot", "", "Snapshot (*.json)")
        if not path:
            return
        try:
            snap = json.loads(Path(path).read_text(encoding="utf-8"))
            old = snap["programs"]
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            QMessageBox.critical(self, "Bad snapshot", f"Could not read snapshot:\n{exc}")
            return

        new = {p["Name"]: p["Version"] for p in self.programs}
        added = sorted(set(new) - set(old), key=str.lower)
        removed = sorted(set(old) - set(new), key=str.lower)
        changed = sorted(
            (n for n in set(new) & set(old) if new[n] != old[n]), key=str.lower)

        lines = [f"Snapshot : {snap.get('generated', '?')}  "
                 f"(host: {snap.get('host', '?')})",
                 f"Current  : {datetime.datetime.now().isoformat(timespec='seconds')}",
                 ""]
        lines.append(f"[+] ADDED ({len(added)})")
        lines += [f"    + {n}  {new[n]}" for n in added] or ["    (none)"]
        lines.append("")
        lines.append(f"[-] REMOVED ({len(removed)})")
        lines += [f"    - {n}  {old[n]}" for n in removed] or ["    (none)"]
        lines.append("")
        lines.append(f"[~] VERSION CHANGED ({len(changed)})")
        lines += [f"    ~ {n}  {old[n]}  ->  {new[n]}" for n in changed] or ["    (none)"]

        DiffDialog("\n".join(lines), self).exec()
        self._set_status(
            f"DIFF: +{len(added)} / -{len(removed)} / ~{len(changed)}", AMBER)

    # --- history UI ------------------------------------------------------------
    @Slot()
    def show_timeline(self):
        if not self.history.scans():
            QMessageBox.information(self, "Timeline",
                                    "No scans recorded yet — run a scan first.")
            return
        dlg = TimelineDialog(self.history, self.programs, self)
        if dlg.exec() and dlg.loaded_scan is not None:
            self.programs = dlg.loaded_scan
            self.populate()
            self._set_status("HISTORICAL SCAN LOADED (read-only view)", AMBER)

    @Slot()
    def verify_chain(self):
        ok, msg = self.history.verify_chain()
        if ok:
            self._set_status("AUDIT CHAIN VERIFIED", PHOSPHOR)
            QMessageBox.information(self, "Audit chain", msg)
        else:
            self._set_status("AUDIT CHAIN BROKEN", RED)
            QMessageBox.critical(self, "Audit chain", msg)

    @Slot()
    def open_db_folder(self):
        folder = self.history.path.parent
        if IS_WINDOWS:
            os.startfile(str(folder))  # noqa: S606
        else:
            QMessageBox.information(self, "Database", str(self.history.path))

    @Slot()
    def purge_history(self):
        n = len(self.history.scans())
        if not n:
            return
        if QMessageBox.question(
                self, "Purge history",
                f"Delete ALL {n} recorded scans and their audit chain?\n"
                "This cannot be undone.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        self.history.purge()
        self.chip_drift.setText("no history")
        self._set_status("HISTORY PURGED", RED)

    def closeEvent(self, event):
        self.history.close()
        super().closeEvent(event)


# =============================================================================
def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    font = QFont(MONO, 10)
    font.setStyleHint(QFont.StyleHint.Monospace)
    app.setFont(font)
    win = InventoryWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
