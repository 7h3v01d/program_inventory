# =============================================================================
#  InventoryWindow: populate, filters, drift, hygiene, exports, restore
# =============================================================================
import pytest

import program_inventory.app as appmod
from program_inventory.app import COL_NAME, COL_UPD


def _scan(window, recs):
    window.on_scan_done(recs)


def test_populate_and_counts(window, rec):
    _scan(window, [rec("A", "1"), rec("B", "2")])
    assert window.proxy.rowCount() == 2
    assert window.chip_count.text() == "2 programs"
    assert "baseline" in window.chip_status.text().lower()


def test_search_filter(window, rec):
    _scan(window, [rec("Alpha", "1"), rec("Beta", "2")])
    window.search_edit.setText("alp")
    assert window.proxy.rowCount() == 1
    window.search_edit.setText("")
    assert window.proxy.rowCount() == 2


def test_publisher_filter(window, rec):
    _scan(window, [rec("A", "1", Publisher="One"),
                   rec("B", "2", Publisher="Two")])
    idx = window.pub_combo.findData("One")
    window.pub_combo.setCurrentIndex(idx)
    assert window.proxy.rowCount() == 1


def test_age_filter(window, rec):
    _scan(window, [rec("New", "1", InstallDate="2026-06-01"),
                   rec("Old", "1", InstallDate="2020-01-01")])
    window.age_combo.setCurrentIndex(3)          # last year
    assert window.proxy.rowCount() == 1
    assert window.proxy.index(0, COL_NAME).data() == "New"


def test_drift_chip_after_second_scan(window, rec):
    _scan(window, [rec("A", "1"), rec("B", "2")])
    _scan(window, [rec("A", "2"), rec("C", "1")])
    assert window.chip_drift.text() == "drift +1 / -1 / ~1"


def test_no_drift_chip(window, rec):
    _scan(window, [rec("A", "1")])
    _scan(window, [rec("A", "1")])
    assert window.chip_drift.text() == "no drift"


def test_detail_pane_content(window, rec):
    _scan(window, [rec("A", "1")])
    window.table.selectRow(0)
    txt = window.detail.toPlainText()
    assert "UNINSTALL" in txt and "REGISTRY" in txt


def _winget(window, rows):
    """Drive the update controller the way the worker would."""
    window.update_ctl._programs = window.programs
    window.update_ctl._on_rows(rows)


def test_updates_matching_and_toggle(window, rec):
    _scan(window, [rec("Firefox", "127.0"), rec("Stable", "1.0")])
    _winget(window, [
        {"Name": "Firefox", "Id": "Moz.Firefox",
         "Version": "127.0", "Available": "128.0", "Source": "winget"},
        {"Name": "Unrelated", "Id": "X.Y",
         "Version": "1", "Available": "2", "Source": "winget"},
    ])
    assert window.chip_updates.text() == "1 updates (1 unmatched)"
    for r in range(window.proxy.rowCount()):
        if window.proxy.index(r, COL_NAME).data() == "Firefox":
            assert window.proxy.index(r, COL_UPD).data() == "128.0"
    window.upd_toggle.setChecked(True)
    assert window.proxy.rowCount() == 1
    window.upd_toggle.setChecked(False)


def test_probable_match_is_marked_in_table(window, rec):
    _scan(window, [rec("Some Very Long Application Name Here", "1.0")])
    _winget(window, [
        {"Name": "Some Very Long Application N\u2026", "Id": "X.Y",
         "Version": "1.0", "Available": "2.0", "Source": "winget"},
    ])
    assert "probable" in window.chip_updates.text()
    assert window.proxy.index(0, COL_UPD).data() == "2.0 ?"
    window.table.selectRow(0)
    assert "[probable match]" in window.detail.toPlainText()


def test_zero_matches_is_never_reported_as_up_to_date(window, rec):
    # Regression: winget returned updates, none matched — old code said
    # "up to date", which is false.
    _scan(window, [rec("A", "1")])
    _winget(window, [
        {"Name": "Unrelated", "Id": "X.Y",
         "Version": "1", "Available": "2", "Source": "winget"},
    ])
    assert window.chip_updates.text() == "0 matched (1 unmatched)"
    assert "up to date" not in window.chip_updates.text()


def test_up_to_date_only_when_winget_returns_nothing(window, rec):
    _scan(window, [rec("A", "1")])
    _winget(window, [])
    assert window.chip_updates.text() == "up to date"


def test_fresh_scan_strips_transient_update_state(window, rec):
    _scan(window, [rec("A", "1")])
    dirty = rec("A", "2")
    dirty["_update"] = {"junk": True}
    _scan(window, [dirty])
    assert window.chip_updates.text() == "updates: —"
    assert all("_update" not in p
               for p in window.history.latest_scan()[2])
    assert window.history.verify_chain()[0]


def test_visible_records_respect_filters(window, rec):
    _scan(window, [rec("Alpha", "1"), rec("Beta", "2")])
    window.search_edit.setText("Alpha")
    recs = window._visible_records()
    assert len(recs) == 1 and recs[0]["Name"] == "Alpha"


def test_clear_resets_state(window, rec):
    _scan(window, [rec("A", "1")])
    window.clear_table()
    assert window.proxy.rowCount() == 0
    assert window.chip_updates.text() == "updates: —"


def test_startup_restore(qapp, tmp_path, rec, monkeypatch):
    from program_inventory.history import HistoryStore
    db = tmp_path / "restore.db"
    s = HistoryStore(db)
    s.save_scan([rec("A", "1")])
    s.save_scan([rec("A", "2")])
    s.close()
    monkeypatch.setattr(appmod, "HistoryStore", lambda: HistoryStore(db))
    monkeypatch.setattr(appmod.DiffDialog, "exec", lambda self: 0)
    w = appmod.InventoryWindow()
    assert len(w.programs) == 1
    assert w.chip_drift.text() == "drift +0 / -0 / ~1"
    assert "LOADED FROM HISTORY" in w.chip_status.text()
    w.history.close()


def test_uninstall_success_logs_and_rescans(window, rec, monkeypatch):
    from program_inventory.uninstall import outcome_from_exit
    _scan(window, [rec("A", "1")])
    rescan = {}
    monkeypatch.setattr(window, "start_scan",
                        lambda: rescan.setdefault("hit", True))
    window.on_uninstall_completed("A", "unins.exe", outcome_from_exit(3010))
    assert rescan.get("hit")
    ts, kind, cmd, code, outcome = window.history.actions_for_program("A")[0]
    assert code == 3010 and outcome == "success"


def test_uninstall_failed_logged_no_rescan(window, rec, monkeypatch):
    from program_inventory.uninstall import outcome_from_exit
    _scan(window, [rec("A", "1")])
    monkeypatch.setattr(appmod.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(window, "start_scan",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("must not rescan")))
    window.on_uninstall_completed("A", "unins.exe", outcome_from_exit(1602))
    assert "CANCELLED" in window.chip_status.text().upper()
    assert window.history.actions_for_program("A")[0][4] == "failed"


def test_uninstall_unknown_outcome_no_rescan(window, rec, monkeypatch):
    # Regression: launched-but-untrackable used to log exit 0 and rescan.
    monkeypatch.setattr(appmod.QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(window, "start_scan",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("must not rescan on unknown")))
    window.on_uninstall_completed(
        "A", "unins.exe",
        {"outcome": "unknown", "exit_code": None, "detail": "not observable"})
    assert "UNKNOWN" in window.chip_status.text()
    ts, kind, cmd, code, outcome = window.history.actions_for_program("A")[0]
    assert code is None and outcome == "unknown"


def test_uninstall_timeout_message_honest(window, rec, monkeypatch):
    captured = {}
    monkeypatch.setattr(
        appmod.QMessageBox, "information",
        staticmethod(lambda parent, title, text: captured.setdefault(
            "text", text)))
    monkeypatch.setattr(window, "start_scan",
                        lambda: (_ for _ in ()).throw(
                            AssertionError("must not rescan on timeout")))
    window.on_uninstall_completed(
        "A", "unins.exe",
        {"outcome": "timeout", "exit_code": None,
         "detail": "Stopped waiting after 15 minutes — the uninstaller"
                   " may still be running. Rescan once it finishes."})
    assert "may still be running" in captured["text"]
    assert "MAY STILL BE" in window.chip_status.text()


def test_program_history_dialog_includes_actions(window, rec, qapp):
    from program_inventory.dialogs import ProgramHistoryDialog
    from program_inventory.qt_shim import QPlainTextEdit
    _scan(window, [rec("A", "1")])
    _scan(window, [rec("A", "2")])
    window.history.log_action("uninstall", "A", "unins.exe", 0)
    dlg = ProgramHistoryDialog(window.history, "A")
    txt = dlg.findChild(QPlainTextEdit).toPlainText()
    assert "upgraded" in txt and "Logged actions" in txt and "exit 0" in txt


def test_timeline_dialog_lists_scans(window, rec, qapp):
    from program_inventory.dialogs import TimelineDialog
    _scan(window, [rec("A", "1")])
    _scan(window, [rec("A", "2")])
    dlg = TimelineDialog(window.history, window.programs)
    assert dlg.model.rowCount() == 2
    dlg.table.selectRow(1)
    assert dlg._selected_scan_id() == 1


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_filter_api_detection_keys_on_endfilterchange(window, rec):
    # Regression: Qt 6.9 has beginFilterChange but NOT endFilterChange —
    # detection on the wrong symbol crashed at startup on PySide6 6.9.1.
    # Simulate a 6.9-shaped proxy: hide endFilterChange, assert the legacy
    # invalidateFilter path is taken and filtering still works. On Qt 6.10
    # (where this suite may run) the legacy call is deprecated — that
    # warning is the simulation working, so it's ignored for this test.
    proxy = window.proxy

    class Qt69Proxy:
        """Attribute view of the real proxy minus endFilterChange."""
        def __getattr__(self, name):
            if name == "endFilterChange":
                raise AttributeError(name)
            return getattr(proxy, name)

        def __setattr__(self, name, value):
            setattr(proxy, name, value)

    _scan(window, [rec("Alpha", "1"), rec("Beta", "2")])
    shim = Qt69Proxy()
    type(proxy).set_filters(shim, "alpha", "", 0, False)
    assert proxy.rowCount() == 1
    type(proxy).set_filters(shim, "", "", 0, False)
    assert proxy.rowCount() == 2
