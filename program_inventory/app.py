# =============================================================================
#  Program Inventory — main window, filter proxy, application entry point
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================
#  The window is a UI shell: worker lifecycles live in controllers.py,
#  file writing in exporters.py, diff logic in diffengine.py. This class
#  owns widgets, the table model, and the bindings between them.
# =============================================================================
import datetime
import sys
import webbrowser
from pathlib import Path

from . import exporters
from .constants import (IS_WINDOWS, APP_NAME, APP_VERSION, COLUMNS, COL_NAME,
                        COL_VER, COL_UPD, COL_PUB, COL_DATE, COL_SIZE,
                        COL_ARCH, COL_SRC, SORT_ROLE, DATA_ROLE)
from .controllers import ScanController, UpdateController, UninstallController
from .diffengine import diff_scans, format_diff_report
from .dialogs import DiffDialog, TimelineDialog, ProgramHistoryDialog
from .history import HistoryStore
from .qt_shim import (QT_BINDING, Qt, Slot, QSortFilterProxyModel,
                      QModelIndex, QStandardItemModel, QStandardItem, QFont,
                      QColor, QApplication, QMainWindow, QWidget, QVBoxLayout,
                      QHBoxLayout, QLabel, QPushButton, QLineEdit, QComboBox,
                      QTableView, QHeaderView, QMenu, QPlainTextEdit,
                      QFileDialog, QMessageBox, QSplitter, QAbstractItemView)
from .theme import (QSS, STEEL, STEEL_HI, TEAL, PHOSPHOR, AMBER, RED, TEXT,
                    TEXT_DIM, MONO)
from .uninstall import (UninstallDialog, OUTCOME_SUCCESS, OUTCOME_DECLINED,
                        OUTCOME_TIMEOUT, OUTCOME_UNKNOWN)
from .wingetcheck import winget_upgrade_command


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
            try:
                dt = datetime.datetime.strptime(
                    rec.get("InstallDate", ""), "%Y-%m-%d")
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
        self.history = HistoryStore()
        self.scan_ctl = ScanController(self)
        self.update_ctl = UpdateController(self)
        self.uninstall_ctl = UninstallController(self)

        self._build_ui()
        self._bind_controllers()
        self._report_store_health()
        self._restore_latest_scan()

    # --- UI construction --------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        head_row = QHBoxLayout()
        title = QLabel("PROGRAM INVENTORY")
        title.setObjectName("Header")
        sub = QLabel(f"// installed software scanner · {QT_BINDING}")
        sub.setObjectName("SubHeader")
        head_row.addWidget(title)
        head_row.addWidget(sub)
        head_row.addStretch(1)
        root.addLayout(head_row)

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
        self.upd_toggle.setToolTip(
            "Show only programs with a winget update available")
        self.upd_toggle.toggled.connect(self.apply_filters)
        bar.addWidget(self.upd_toggle)
        root.addLayout(bar)

        self.model = QStandardItemModel(0, len(COLUMNS))
        self.model.setHorizontalHeaderLabels(COLUMNS)
        self.proxy = InventoryProxy(self)
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(COL_NAME, Qt.SortOrder.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
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
        self.detail.setPlaceholderText(
            "Select a program to inspect uninstall strings, registry path,"
            " and links.")
        self.detail.setMaximumHeight(170)

        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.table)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 1)
        root.addWidget(split, stretch=1)

        chips = QHBoxLayout()
        self.chip_status = self._chip("READY — hit SCAN")
        self.chip_count = self._chip("0 programs")
        self.chip_shown = self._chip("0 shown")
        self.chip_size = self._chip("— MB total")
        self.chip_drift = self._chip("no history")
        self.chip_updates = self._chip("updates: —")
        for c in (self.chip_status, self.chip_count, self.chip_shown,
                  self.chip_size, self.chip_drift, self.chip_updates):
            chips.addWidget(c)
        chips.addStretch(1)
        root.addLayout(chips)

    def _bind_controllers(self):
        self.scan_ctl.started.connect(
            lambda: (self.scan_btn.setEnabled(False),
                     self._set_status("SCANNING…", AMBER)))
        self.scan_ctl.done.connect(self.on_scan_done)
        self.scan_ctl.failed.connect(self.on_scan_failed)

        self.update_ctl.started.connect(
            lambda: (self.updates_btn.setEnabled(False),
                     self._set_status("CHECKING WINGET…", AMBER)))
        self.update_ctl.matched.connect(self.on_updates_matched)
        self.update_ctl.no_updates.connect(self.on_no_updates)
        self.update_ctl.failed.connect(self.on_updates_failed)

        self.uninstall_ctl.started.connect(
            lambda name: self._set_status(f"UNINSTALLING — {name}", AMBER))
        self.uninstall_ctl.completed.connect(self.on_uninstall_completed)

    # --- chips ------------------------------------------------------------------
    def _chip(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("chip")
        lbl.setStyleSheet(
            f"background:{STEEL}; border:1px solid {STEEL_HI};"
            f" padding:4px 10px;")
        return lbl

    def _chip_style(self, chip: QLabel, text: str, color: str = TEXT):
        chip.setText(text)
        chip.setStyleSheet(
            f"background:{STEEL}; border:1px solid {STEEL_HI};"
            f" padding:4px 10px; color:{color};")

    def _set_status(self, text: str, color: str = TEXT):
        self._chip_style(self.chip_status, text, color)

    def _set_drift(self, a: int, r: int, c: int, m: int = 0):
        total = a + r + c + m
        text = "no drift" if total == 0 else f"drift +{a} / -{r} / ~{c}"
        if m:
            text += f" / ±{m}"
        self._chip_style(self.chip_drift, text,
                         PHOSPHOR if total == 0 else AMBER)

    # --- store health / startup ----------------------------------------------
    def _report_store_health(self):
        if self.history.recovered_from_corruption:
            self._set_status("HISTORY DB WAS CORRUPT — SET ASIDE,"
                             " STARTED FRESH", RED)
            QMessageBox.warning(
                self, "History database",
                "The history database could not be read and was renamed"
                " with a .corrupt suffix (not deleted). A fresh database"
                " has been started.")
        elif self.history.migrated_from is not None:
            self._set_status(
                f"HISTORY MIGRATED v{self.history.migrated_from} → v2"
                " (backup saved)", TEAL)

    def _restore_latest_scan(self):
        try:
            latest = self.history.latest_scan()
        except Exception:                     # noqa: BLE001 — never block launch
            return
        if not latest:
            return
        scan_id, ts, entries = latest
        self.programs = entries
        self.populate()
        if not (self.history.recovered_from_corruption
                or self.history.migrated_from):
            self._set_status(f"LOADED FROM HISTORY — scan #{scan_id} @ {ts}",
                             TEAL)
        summary = self.history.scan_summary(scan_id)
        if summary:
            self._set_drift(*summary)

    # --- scan -------------------------------------------------------------
    @Slot()
    def start_scan(self):
        if not IS_WINDOWS:
            QMessageBox.critical(self, "Unsupported OS",
                                 "Registry scanning requires Windows.")
            return
        self.scan_ctl.start()

    @Slot(list)
    def on_scan_done(self, programs: list):
        self.programs = programs
        self._chip_style(self.chip_updates, "updates: —")
        self.populate()
        self.scan_btn.setEnabled(True)
        try:
            result = self.history.save_scan(programs)
        except Exception as exc:              # noqa: BLE001 — surface, don't die
            self._set_status("SCAN OK — HISTORY WRITE FAILED", RED)
            QMessageBox.warning(self, "History error",
                                f"Scan succeeded but could not be recorded:"
                                f"\n{exc}")
            return
        if result["baseline"]:
            self._set_status(
                f"SCAN COMPLETE — {len(programs)} programs"
                " · baseline recorded", PHOSPHOR)
            self.chip_drift.setText("baseline")
            return
        a, r = len(result["added"]), len(result["removed"])
        c, m = len(result["changed"]), len(result["modified"])
        self._set_status(f"SCAN COMPLETE — {len(programs)} programs", PHOSPHOR)
        self._set_drift(a, r, c, m)
        if a + r + c + m:
            DiffDialog(format_diff_report(
                result, ["Changes since previous scan:"]), self).exec()

    @Slot(str)
    def on_scan_failed(self, msg: str):
        self.scan_btn.setEnabled(True)
        self._set_status("SCAN FAILED", RED)
        QMessageBox.critical(self, "Scan error", msg)

    # --- model ---------------------------------------------------------------
    def populate(self):
        self.model.setRowCount(0)
        publishers = set()
        total_mb = 0.0
        for rec in self.programs:
            total_mb += rec.get("SizeMB") or 0
            if rec.get("Publisher"):
                publishers.add(rec["Publisher"])

            def item(text, sort_key=None):
                it = QStandardItem(str(text))
                it.setData(sort_key if sort_key is not None
                           else str(text).lower(), SORT_ROLE)
                return it

            upd = rec.get("_update")
            avail = upd.get("Available", "") if upd else ""
            upd_text = avail
            if upd and upd.get("MatchKind") == "probable" and avail:
                upd_text = f"{avail} ?"          # heuristic match — say so
            row = [
                item(rec["Name"]),
                item(rec.get("Version", "")),
                item(upd_text, avail or "~~~~"),
                item(rec.get("Publisher", "")),
                item(rec.get("InstallDate", ""),
                     rec.get("InstallDate") or "0000-00-00"),
                item("" if rec.get("SizeMB") is None
                     else f"{rec['SizeMB']:.1f}",
                     rec["SizeMB"] if rec.get("SizeMB") is not None else -1.0),
                item(rec.get("Arch", "")),
                item(rec.get("Source", "")),
                item(rec.get("InstallLocation", "")),
            ]
            row[COL_NAME].setData(rec, DATA_ROLE)
            if upd:
                row[COL_UPD].setForeground(
                    QColor(AMBER if upd.get("MatchKind") == "exact"
                           else TEXT_DIM))
            if rec.get("Arch") == "32-bit":
                row[COL_ARCH].setForeground(QColor(AMBER))
            elif rec.get("Arch") == "user":
                row[COL_ARCH].setForeground(QColor(TEAL))
            self.model.appendRow(row)

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
        self.chip_size.setText(
            f"{total_mb / 1024:.2f} GB total" if total_mb > 1024
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
        self.model.setRowCount(0)
        self.detail.clear()
        self.chip_count.setText("0 programs")
        self.chip_shown.setText("0 shown")
        self.chip_size.setText("— MB total")
        self._chip_style(self.chip_updates, "updates: —")
        self._set_status("CLEARED", TEXT_DIM)

    # --- winget updates -------------------------------------------------------
    @Slot()
    def start_update_check(self):
        if not self.programs:
            QMessageBox.information(
                self, "No inventory",
                "Scan (or load history) first, then check updates.")
            return
        self.update_ctl.start(self.programs)

    @Slot(int, int, list)
    def on_updates_matched(self, exact: int, probable: int, unmatched: list):
        self.updates_btn.setEnabled(True)
        self.populate()
        matched = exact + probable
        if matched == 0:
            # winget DID return updates — none matched our inventory. That
            # is not "up to date" and must never be reported as such.
            self._chip_style(self.chip_updates,
                             f"0 matched ({len(unmatched)} unmatched)", AMBER)
            self._set_status(
                f"WINGET: NO MATCHES — {len(unmatched)} update(s) could not"
                " be matched to inventory", AMBER)
            return
        parts = [f"{matched} updates"]
        if probable:
            parts.append(f"{probable} probable")
        if unmatched:
            parts.append(f"{len(unmatched)} unmatched")
        self._chip_style(self.chip_updates,
                         parts[0] + (f" ({', '.join(parts[1:])})"
                                     if parts[1:] else ""), AMBER)
        self._set_status(f"WINGET: {matched} UPDATES AVAILABLE", AMBER)

    @Slot()
    def on_no_updates(self):
        self.updates_btn.setEnabled(True)
        self.populate()
        # Only this branch — winget itself returned zero rows — earns it.
        self._chip_style(self.chip_updates, "up to date", PHOSPHOR)
        self._set_status("WINGET: NO UPDATES AVAILABLE", PHOSPHOR)

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
        self.uninstall_ctl.start(rec["Name"], dlg.chosen_command, dlg.silent)

    @Slot(str, str, dict)
    def on_uninstall_completed(self, name: str, cmd: str, result: dict):
        outcome, code = result["outcome"], result["exit_code"]
        detail = result["detail"]
        self.history.log_action("uninstall", name, cmd, code, outcome)
        if outcome == OUTCOME_SUCCESS:
            self._set_status(f"UNINSTALL OK ({detail}) — RESCANNING", PHOSPHOR)
            self.start_scan()   # removal lands in the chain-hashed history
        elif outcome == OUTCOME_UNKNOWN:
            self._set_status("UNINSTALL LAUNCHED — OUTCOME UNKNOWN", AMBER)
            QMessageBox.information(self, "Uninstall — outcome unknown",
                                    f"{name}\n\n{detail}")
        elif outcome == OUTCOME_TIMEOUT:
            self._set_status("UNINSTALL: STOPPED WAITING — MAY STILL BE"
                             " RUNNING", AMBER)
            QMessageBox.information(self, "Uninstall — still running?",
                                    f"{name}\n\n{detail}")
        elif outcome == OUTCOME_DECLINED:
            self._set_status("UNINSTALL: UAC PROMPT DECLINED", RED)
        else:                                  # failed / error
            self._set_status(f"UNINSTALL: {detail.upper()}", RED)
            QMessageBox.warning(
                self, "Uninstall",
                f"{name}\n\nUninstaller result: {detail}"
                + (f"\n(exit code {code})" if code is not None else "")
                + "\n\nAction logged to history database.")

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
        size = rec.get("SizeMB")
        lines = [
            f"NAME       {rec['Name']}",
            f"VERSION    {rec.get('Version') or '—'}    "
            f"PUBLISHER  {rec.get('Publisher') or '—'}",
            f"INSTALLED  {rec.get('InstallDate') or '—'}    SIZE  "
            f"{'—' if size is None else str(size) + ' MB'}    "
            f"ARCH  {rec.get('Arch', '')}  ({rec.get('Source', '')})",
            f"IDENTITY   {rec.get('EntryId') or '— (legacy record)'}",
            f"LOCATION   {rec.get('InstallLocation') or '—'}",
            f"UNINSTALL  {rec.get('UninstallString') or '—'}",
        ]
        if rec.get("QuietUninstallString"):
            lines.append(f"SILENT     {rec['QuietUninstallString']}")
        upd = rec.get("_update")
        if upd:
            lines.append(
                f"UPDATE     {rec.get('Version') or '?'}  ->  "
                f"{upd.get('Available', '?')}   "
                f"[{upd.get('MatchKind', '?')} match]   "
                f"({winget_upgrade_command(upd)})")
        if rec.get("URLInfoAbout"):
            lines.append(f"URL        {rec['URLInfoAbout']}")
        lines.append(f"REGISTRY   {rec.get('RegistryPath', '')}")
        self.detail.setPlainText("\n".join(lines))

    # --- context menu ---------------------------------------------------------
    @Slot()
    def show_context_menu(self, pos):
        rec = self._selected_record()
        if not rec:
            return
        menu = QMenu(self)
        if rec.get("InstallLocation"):
            menu.addAction("Open install folder",
                           lambda: self._open_folder(rec["InstallLocation"]))
        if rec.get("UninstallString"):
            menu.addAction("Copy uninstall command",
                           lambda: self._copy(rec["UninstallString"]))
        if rec.get("QuietUninstallString"):
            menu.addAction("Copy silent uninstall command",
                           lambda: self._copy(rec["QuietUninstallString"]))
        menu.addAction("Copy name + version",
                       lambda: self._copy(
                           f"{rec['Name']} {rec.get('Version', '')}".strip()))
        menu.addAction("Copy registry path",
                       lambda: self._copy(
                           rec.get("RegistryPath", "").split("  [")[0]))
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
        if rec.get("UninstallString"):
            menu.addSeparator()
            menu.addAction("Uninstall… (governed)",
                           lambda: self.start_uninstall(rec))
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _copy(self, text: str):
        QApplication.clipboard().setText(text)
        self._set_status("COPIED TO CLIPBOARD", TEAL)

    def _open_folder(self, path: str):
        import os
        p = Path(path.strip('"'))
        if p.exists():
            os.startfile(str(p))  # noqa: S606 — Windows-only, user-initiated
        else:
            QMessageBox.warning(self, "Not found",
                                f"Folder does not exist:\n{p}")

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
            QMessageBox.warning(self, "No data",
                                "Nothing to export — scan first.")
            return None
        return recs

    def _save_path(self, ext: str, filt: str) -> str:
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export", f"program_inventory_{stamp}.{ext}", filt)
        return path

    def _export(self, ext: str, filt: str, writer, label: str):
        recs = self._require_data()
        if not recs:
            return
        path = self._save_path(ext, filt)
        if not path:
            return
        writer(recs, path)
        self._set_status(f"EXPORTED {len(recs)} → {label}", PHOSPHOR)

    @Slot()
    def export_csv(self):
        self._export("csv", "CSV (*.csv)", exporters.write_csv, "CSV")

    @Slot()
    def export_json(self):
        self._export("json", "JSON (*.json)", exporters.write_json, "JSON")

    @Slot()
    def export_txt(self):
        self._export("txt", "Text (*.txt)", exporters.write_txt, "TXT")

    @Slot()
    def export_md(self):
        self._export("md", "Markdown (*.md)", exporters.write_md, "MARKDOWN")

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
        exporters.write_snapshot(self.programs, path)
        self._set_status("SNAPSHOT SAVED", PHOSPHOR)

    @Slot()
    def compare_snapshot(self):
        if not self.programs:
            QMessageBox.warning(
                self, "No data",
                "Scan first, then compare against a snapshot.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open snapshot", "", "Snapshot (*.json)")
        if not path:
            return
        try:
            meta, old_records = exporters.load_snapshot(path)
        except Exception as exc:              # noqa: BLE001
            QMessageBox.critical(self, "Bad snapshot",
                                 f"Could not read snapshot:\n{exc}")
            return
        diff = diff_scans(old_records, self.programs)
        header = [f"Snapshot : {meta['generated']}  (host: {meta['host']},"
                  f" format v{meta['snapshot_version']})",
                  f"Current  : "
                  f"{datetime.datetime.now().isoformat(timespec='seconds')}"]
        DiffDialog(format_diff_report(diff, header), self).exec()
        a, r = len(diff["added"]), len(diff["removed"])
        c, m = len(diff["changed"]), len(diff["modified"])
        self._set_status(f"DIFF: +{a} / -{r} / ~{c} / ±{m}", AMBER)

    # --- history UI ------------------------------------------------------------
    @Slot()
    def show_timeline(self):
        if not self.history.scans():
            QMessageBox.information(
                self, "Timeline",
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
            self._set_status("AUDIT CHAIN PROBLEM", RED)
            QMessageBox.critical(self, "Audit chain", msg)

    @Slot()
    def open_db_folder(self):
        import os
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
