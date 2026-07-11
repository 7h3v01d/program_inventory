# =============================================================================
#  Governed uninstall: command splitting, elevation fallback, dialog gating
# =============================================================================
import subprocess

import pytest

import program_inventory.uninstall as un
from program_inventory.uninstall import (
    split_command_line, UninstallWorker, UninstallDialog, MSI_EXIT)


@pytest.fixture
def spaced_exe(tmp_path):
    d = tmp_path / "Program Files" / "7-Zip"
    d.mkdir(parents=True)
    exe = d / "Uninstall.exe"
    exe.write_bytes(b"MZ")
    return exe


class TestSplitCommandLine:
    def test_unquoted_path_with_spaces(self, spaced_exe):
        assert split_command_line(str(spaced_exe)) == (str(spaced_exe), "")

    def test_unquoted_path_with_spaces_and_args(self, spaced_exe):
        exe, params = split_command_line(f"{spaced_exe} /S /extra")
        assert exe == str(spaced_exe) and params == "/S /extra"

    def test_quoted_path_with_args(self, spaced_exe):
        exe, params = split_command_line(f'"{spaced_exe}" /SILENT')
        assert exe == str(spaced_exe) and params == "/SILENT"

    def test_quoted_path_no_args(self, spaced_exe):
        assert split_command_line(f'"{spaced_exe}"') == (str(spaced_exe), "")

    def test_bare_exe_with_msi_args(self):
        exe, params = split_command_line("MsiExec.exe /X{ABC-123}")
        assert exe == "MsiExec.exe" and params == "/X{ABC-123}"

    def test_unterminated_quote(self):
        exe, _ = split_command_line('"C:\\x\\unins.exe')
        assert exe == "C:\\x\\unins.exe"


class TestWorkerElevationFallback:
    def _run(self, worker):
        results = []
        worker.finished_code.connect(lambda c: results.append(("code", c)))
        worker.failed.connect(lambda m: results.append(("fail", m)))
        worker.run()                      # thread body, synchronous
        return results

    def test_740_falls_back_to_elevated(self, qapp, spaced_exe, monkeypatch):
        err = OSError("elevation required")
        err.winerror = 740
        monkeypatch.setattr(un.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(err))
        calls = {}
        monkeypatch.setattr(un, "run_elevated",
                            lambda e, p, t: calls.setdefault("args", (e, p, t)) and 0 or 0)
        results = self._run(UninstallWorker(f'"{spaced_exe}" /S', silent=False))
        assert results == [("code", 0)]
        assert calls["args"] == (str(spaced_exe), "/S", UninstallWorker.TIMEOUT_S)

    def test_uac_declined_reports_failure(self, qapp, spaced_exe, monkeypatch):
        err = OSError()
        err.winerror = 740
        monkeypatch.setattr(un.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(err))
        monkeypatch.setattr(un, "run_elevated",
                            lambda *a: (_ for _ in ()).throw(
                                PermissionError("UAC elevation prompt was declined.")))
        results = self._run(UninstallWorker(str(spaced_exe), silent=False))
        assert results == [("fail", "UAC elevation prompt was declined.")]

    def test_non_740_error_never_elevates(self, qapp, monkeypatch):
        err = OSError("no such file")
        err.winerror = 2
        monkeypatch.setattr(un.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(err))
        monkeypatch.setattr(un, "run_elevated",
                            lambda *a: (_ for _ in ()).throw(
                                AssertionError("must not elevate")))
        results = self._run(UninstallWorker("missing.exe", silent=False))
        assert results[0][0] == "fail" and "no such file" in results[0][1]

    def test_timeout_reported(self, qapp, monkeypatch):
        monkeypatch.setattr(
            un.subprocess, "run",
            lambda *a, **k: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("x", 900)))
        results = self._run(UninstallWorker("x.exe", silent=False))
        assert results[0][0] == "fail" and "timed out" in results[0][1]


class TestUninstallDialog:
    def test_disarmed_until_exact_name(self, qapp, rec):
        dlg = UninstallDialog(rec("Alpha Tool", "1.0"))
        assert not dlg.go_btn.isEnabled()
        dlg.confirm_edit.setText("alpha tool")          # wrong case
        assert not dlg.go_btn.isEnabled()
        dlg.confirm_edit.setText("Alpha Tool")
        assert dlg.go_btn.isEnabled()

    def test_silent_mode_only_with_quiet_string(self, qapp, rec):
        assert UninstallDialog(rec("A", "1")).silent_combo.count() == 1
        assert UninstallDialog(
            rec("A", "1", quiet="u.exe /S")).silent_combo.count() == 2

    def test_chosen_command_matches_mode(self, qapp, rec):
        dlg = UninstallDialog(rec("A", "1", quiet="u.exe /S"))
        dlg.confirm_edit.setText("A")
        dlg.silent_combo.setCurrentIndex(1)
        dlg._accept()
        assert dlg.silent and dlg.chosen_command == "u.exe /S"


def test_msi_exit_map_success_semantics():
    assert MSI_EXIT[0][1] and MSI_EXIT[3010][1]
    assert not MSI_EXIT[1602][1] and not MSI_EXIT[1603][1]
