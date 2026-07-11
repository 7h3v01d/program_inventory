# =============================================================================
#  Governed uninstall: command splitting, elevation fallback, dialog gating
# =============================================================================
import subprocess

import pytest

import program_inventory.uninstall as un
from program_inventory.uninstall import (
    split_command_line, UninstallWorker, UninstallDialog, MSI_EXIT,
    LaunchedUnknown, OUTCOME_SUCCESS, OUTCOME_FAILED, OUTCOME_DECLINED,
    OUTCOME_TIMEOUT, OUTCOME_UNKNOWN, OUTCOME_ERROR)


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


class TestWorkerOutcomes:
    """The worker emits ONE result dict — outcome is what was OBSERVED."""

    def _run(self, worker):
        results = []
        worker.completed.connect(results.append)
        worker.run()                      # thread body, synchronous
        assert len(results) == 1
        return results[0]

    def _raise_740(self, monkeypatch):
        err = OSError("elevation required")
        err.winerror = 740
        monkeypatch.setattr(un.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(err))

    def test_740_falls_back_to_elevated_success(self, qapp, spaced_exe,
                                                monkeypatch):
        self._raise_740(monkeypatch)
        calls = {}
        monkeypatch.setattr(
            un, "run_elevated",
            lambda e, p, t: calls.setdefault("args", (e, p, t)) and 0 or 0)
        r = self._run(UninstallWorker(f'"{spaced_exe}" /S', silent=False))
        assert r["outcome"] == OUTCOME_SUCCESS and r["exit_code"] == 0
        assert calls["args"] == (str(spaced_exe), "/S",
                                 UninstallWorker.TIMEOUT_S)

    def test_elevated_failure_exit_code(self, qapp, spaced_exe, monkeypatch):
        self._raise_740(monkeypatch)
        monkeypatch.setattr(un, "run_elevated", lambda e, p, t: 1603)
        r = self._run(UninstallWorker(str(spaced_exe), silent=False))
        assert r["outcome"] == OUTCOME_FAILED and r["exit_code"] == 1603
        assert "fatal" in r["detail"]

    def test_uac_declined_is_declined_not_failed(self, qapp, spaced_exe,
                                                 monkeypatch):
        self._raise_740(monkeypatch)
        monkeypatch.setattr(
            un, "run_elevated",
            lambda *a: (_ for _ in ()).throw(
                PermissionError("UAC elevation prompt was declined.")))
        r = self._run(UninstallWorker(str(spaced_exe), silent=False))
        assert r["outcome"] == OUTCOME_DECLINED and r["exit_code"] is None

    def test_no_process_handle_is_unknown_not_success(self, qapp, spaced_exe,
                                                      monkeypatch):
        # Regression: this used to be treated as exit code 0.
        self._raise_740(monkeypatch)
        monkeypatch.setattr(
            un, "run_elevated",
            lambda *a: (_ for _ in ()).throw(
                LaunchedUnknown(un.UNKNOWN_DETAIL)))
        r = self._run(UninstallWorker(str(spaced_exe), silent=False))
        assert r["outcome"] == OUTCOME_UNKNOWN and r["exit_code"] is None
        assert "not observable" in r["detail"]

    def test_elevated_timeout_says_may_still_be_running(self, qapp,
                                                        spaced_exe,
                                                        monkeypatch):
        self._raise_740(monkeypatch)
        monkeypatch.setattr(un, "run_elevated",
                            lambda *a: (_ for _ in ()).throw(TimeoutError()))
        r = self._run(UninstallWorker(str(spaced_exe), silent=False))
        assert r["outcome"] == OUTCOME_TIMEOUT
        assert "may still be running" in r["detail"]

    def test_normal_timeout_says_may_still_be_running(self, qapp,
                                                      monkeypatch):
        monkeypatch.setattr(
            un.subprocess, "run",
            lambda *a, **k: (_ for _ in ()).throw(
                subprocess.TimeoutExpired("x", 900)))
        r = self._run(UninstallWorker("x.exe", silent=False))
        assert r["outcome"] == OUTCOME_TIMEOUT
        assert "may still be running" in r["detail"]

    def test_non_740_error_never_elevates(self, qapp, monkeypatch):
        err = OSError("no such file")
        err.winerror = 2
        monkeypatch.setattr(un.subprocess, "run",
                            lambda *a, **k: (_ for _ in ()).throw(err))
        monkeypatch.setattr(un, "run_elevated",
                            lambda *a: (_ for _ in ()).throw(
                                AssertionError("must not elevate")))
        r = self._run(UninstallWorker("missing.exe", silent=False))
        assert r["outcome"] == OUTCOME_ERROR and "no such file" in r["detail"]


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
