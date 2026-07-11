# =============================================================================
#  Program Inventory — main window, filter proxy, application entry point
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================

import csv
import datetime
import json
import os
import sqlite3
import webbrowser
from pathlib import Path

from .constants import (IS_WINDOWS, APP_NAME, APP_VERSION, COLUMNS, COL_NAME,
                        COL_VER, COL_UPD, COL_PUB, COL_DATE, COL_SIZE,
                        COL_ARCH, COL_SRC, SORT_ROLE, DATA_ROLE)
from .theme import (QSS, STEEL, TEXT, STEEL_HI, TEAL, PHOSPHOR, AMBER, RED,
                    TEXT_DIM, MONO)
from .qt_shim import (QT_BINDING, Qt, Slot, QSortFilterProxyModel,
                      QModelIndex, QStandardItemModel, QStandardItem, QFont,
                      QColor, QApplication, QMainWindow, QWidget, QVBoxLayout,
                      QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox,
                      QTableView, QHeaderView, QMenu, QPlainTextEdit,
                      QFileDialog, QMessageBox, QSplitter, QAbstractItemView)
from .scan import ScanWorker
from .history import HistoryStore
from .wingetcheck import WingetWorker, match_winget_row, winget_upgrade_command
from .uninstall import MSI_EXIT, UninstallWorker, UninstallDialog
from .dialogs import DiffDialog, TimelineDialog, ProgramHistoryDialog

import sys


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
        # Qt's filter-change API arrived in two pieces: beginFilterChange()
        # in 6.9 but endFilterChange() only in 6.10 — so detection MUST key
        # on endFilterChange. On 6.9 and below, invalidateFilter() after
        # mutation is the correct (non-deprecated) call.
        new_api = hasattr(self, "endFilterChange")
        if new_api:
            self.beginFilterChange()
        self.search_text = search.lower().strip()
        self.publisher = publisher
        self.max_age_days = max_age_days
        self.updates_only = updates_only
        if new_api:
            self.endFilterChange()
        else:
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



