# =============================================================================
#  Program Inventory — diff, timeline, and program-history dialogs
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================

from .diffengine import diff_scans, format_diff_report
from .history import HistoryStore
from .qt_shim import (Qt, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                      QPushButton, QPlainTextEdit, QTableView,
                      QAbstractItemView, QStandardItemModel, QStandardItem)


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
            ["#", "Timestamp", "Host", "Programs", "+ / − / ~ / ±", "Hash", ""])
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table, stretch=1)

        self._scan_ids: list[int] = []
        for sid, ts, host, count, a, r, c, m, h in store.scans():
            self._scan_ids.append(sid)
            row = [QStandardItem(str(x)) for x in
                   (sid, ts, host or "—", count,
                    f"+{a} / -{r} / ~{c} / ±{m}", h[:16] + "…", "")]
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
        diff = diff_scans(self.store.entries_for(sid), self.current)
        DiffDialog(format_diff_report(
            diff, [f"Scan #{sid} -> current table"]), self).exec()

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
                elif kind == "changed":
                    lines.append(f"{ts}  [~] upgraded   {old or '?'}  ->  {new or '?'}")
                else:
                    lines.append(f"{ts}  [±] metadata modified  (v{new or '?'})")
        actions = store.actions_for_program(name)
        if actions:
            lines.append("")
            lines.append("Logged actions:")
            for ts, kind, cmd, code, outcome in actions:
                code_txt = f"exit {code}" if code is not None else "no exit code"
                lines.append(
                    f"{ts}  [!] {kind}: {outcome or '?'} ({code_txt})  {cmd or ''}")
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText("\n".join(lines))
        lay.addWidget(text)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)


