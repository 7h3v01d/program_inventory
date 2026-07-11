# =============================================================================
#  Program Inventory — test fixtures
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from program_inventory.qt_shim import QApplication          # noqa: E402
from program_inventory.history import HistoryStore          # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    from program_inventory.theme import QSS
    app.setStyleSheet(QSS)
    return app


@pytest.fixture
def store(tmp_path):
    s = HistoryStore(tmp_path / "history.db")
    yield s
    s.close()


@pytest.fixture
def rec():
    from program_inventory.diffengine import make_entry_id

    def make(name, ver, quiet="", key=None, **kw):
        key = key or name                    # registry subkey defaults to name
        base = {
            "EntryId": make_entry_id("HKLM", "64-bit", key),
            "KeyName": key,
            "Name": name, "Version": ver, "Publisher": "Acme",
            "InstallDate": "2026-06-01", "SizeMB": 10.0, "Arch": "64-bit",
            "Source": "HKLM", "InstallLocation": "",
            "UninstallString": "C:\\x\\unins.exe",
            "QuietUninstallString": quiet, "URLInfoAbout": "",
            "RegistryPath": "HKLM\\SOFTWARE\\...\\Uninstall\\" + key,
        }
        base.update(kw)
        return base
    return make


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    import program_inventory.app as appmod
    monkeypatch.setattr(appmod, "HistoryStore",
                        lambda: HistoryStore(tmp_path / "h.db"))
    # never block on modal diff popups in tests
    monkeypatch.setattr(appmod.DiffDialog, "exec", lambda self: 0)
    w = appmod.InventoryWindow()
    yield w
    w.history.close()
