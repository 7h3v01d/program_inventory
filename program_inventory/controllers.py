# =============================================================================
#  Program Inventory — controllers: worker lifecycles out of the window
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================
#  Each controller owns its workers (QThread subclasses, _worker_refs GC
#  guard per project convention) and exposes signals; the window binds those
#  to widgets. No widget code lives here.
# =============================================================================
from .qt_shim import QObject, Signal, Slot
from .scan import ScanWorker
from .wingetcheck import WingetWorker, match_winget_row
from .uninstall import UninstallWorker


class ScanController(QObject):
    started = Signal()
    done = Signal(list)          # fresh records (transient state stripped)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker_refs: set = set()

    @Slot()
    def start(self):
        self.started.emit()
        worker = ScanWorker()
        self._worker_refs.add(worker)
        worker.scan_done.connect(self._on_done)
        worker.scan_failed.connect(self.failed)
        worker.finished.connect(lambda w=worker: self._worker_refs.discard(w))
        worker.start()

    @Slot(list)
    def _on_done(self, programs: list):
        for p in programs:
            p.pop("_update", None)      # fresh scans never carry winget state
        self.done.emit(programs)


class UpdateController(QObject):
    """Runs the winget check and grades every match. Emits
    matched(count_exact, count_probable, unmatched_rows) after annotating
    the records in place with _update = {**winget_row, 'MatchKind': kind}."""
    started = Signal()
    matched = Signal(int, int, list)     # exact, probable, unmatched rows
    no_updates = Signal()                # winget returned zero rows
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker_refs: set = set()
        self._programs: list[dict] = []

    @Slot(list)
    def start(self, programs: list):
        self._programs = programs
        self.started.emit()
        worker = WingetWorker()
        self._worker_refs.add(worker)
        worker.updates_done.connect(self._on_rows)
        worker.updates_failed.connect(self.failed)
        worker.finished.connect(lambda w=worker: self._worker_refs.discard(w))
        worker.start()

    @Slot(list)
    def _on_rows(self, winget_rows: list):
        for rec in self._programs:
            rec.pop("_update", None)
        if not winget_rows:
            self.no_updates.emit()
            return
        exact = probable = 0
        unmatched: list[dict] = []
        for wrow in winget_rows:
            best_kind, best_rec = None, None
            for rec in self._programs:
                if "_update" in rec:
                    continue
                kind = match_winget_row(rec["Name"], wrow["Name"])
                if kind == "exact":
                    best_kind, best_rec = kind, rec
                    break
                if kind == "probable" and best_kind is None:
                    best_kind, best_rec = kind, rec
            if best_rec is None:
                unmatched.append(wrow)
            else:
                best_rec["_update"] = {**wrow, "MatchKind": best_kind}
                if best_kind == "exact":
                    exact += 1
                else:
                    probable += 1
        self.matched.emit(exact, probable, unmatched)


class UninstallController(QObject):
    """Owns the uninstall worker; emits the outcome-honest result dict from
    uninstall.OUTCOME_* along with the program name and command run."""
    started = Signal(str)                # program name
    completed = Signal(str, str, dict)   # name, command, result

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker_refs: set = set()

    def start(self, name: str, command: str, silent: bool):
        self.started.emit(name)
        worker = UninstallWorker(command, silent)
        self._worker_refs.add(worker)
        worker.completed.connect(
            lambda result, n=name, c=command: self.completed.emit(n, c, result))
        worker.finished.connect(lambda w=worker: self._worker_refs.discard(w))
        worker.start()
