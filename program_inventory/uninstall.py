# =============================================================================
#  Program Inventory — governed uninstall: deny-first gate, elevation fallback
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================

import subprocess
from pathlib import Path

from .qt_shim import (QThread, Signal, Slot, QDialog, QVBoxLayout,
                      QHBoxLayout, QLabel, QPlainTextEdit, QComboBox,
                      QLineEdit, QPushButton)


MSI_EXIT = {
    0:    ("success", True),
    1602: ("cancelled by user", False),
    1603: ("fatal error during uninstall", False),
    1618: ("another installation is already in progress", False),
    3010: ("success — reboot required", True),
}

ERROR_ELEVATION_REQUIRED = 740
ERROR_CANCELLED = 1223          # user declined the UAC prompt


def split_command_line(cmd: str) -> tuple[str, str]:
    """Split a registry UninstallString into (executable, parameters).

    Handles three real-world shapes:
      "C:\\Program Files\\App\\unins.exe" /flags   (quoted)
      C:\\Program Files\\7-Zip\\Uninstall.exe      (unquoted, spaces in path)
      MsiExec.exe /X{GUID}                          (bare exe + args)
    For unquoted paths we probe progressively shorter space-joined prefixes
    for an existing file, longest match wins.
    """
    cmd = cmd.strip()
    if cmd.startswith('"'):
        end = cmd.find('"', 1)
        if end > 0:
            return cmd[1:end], cmd[end + 1:].strip()
        return cmd.strip('"'), ""
    parts = cmd.split(" ")
    for i in range(len(parts), 0, -1):
        candidate = " ".join(parts[:i])
        if Path(candidate).is_file():
            return candidate, " ".join(parts[i:]).strip()
    return parts[0], " ".join(parts[1:]).strip()


def run_elevated(exe: str, params: str, timeout_s: int) -> int:
    """Run via ShellExecuteExW with the 'runas' verb (UAC prompt), wait for
    completion, return the process exit code. CreateProcess cannot trigger
    elevation — this path exists for uninstallers whose manifest requires
    admin (WinError 740). Raises PermissionError if the UAC prompt is
    declined and TimeoutError if the wait expires."""
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    SEE_MASK_NOCLOSEPROCESS = 0x00000040
    SEE_MASK_NOASYNC = 0x00000100
    SW_SHOWNORMAL = 1
    WAIT_TIMEOUT = 0x00000102

    shell32 = ctypes.windll.shell32
    kernel32 = ctypes.windll.kernel32

    sei = SHELLEXECUTEINFOW()
    sei.cbSize = ctypes.sizeof(sei)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC
    sei.lpVerb = "runas"
    sei.lpFile = exe
    sei.lpParameters = params or None
    sei.nShow = SW_SHOWNORMAL

    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        err = kernel32.GetLastError()
        if err == ERROR_CANCELLED:
            raise PermissionError("UAC elevation prompt was declined.")
        raise OSError(f"ShellExecuteEx failed (Win32 error {err}).")

    if not sei.hProcess:
        # Process launched but no handle returned — cannot track exit code.
        return 0
    try:
        if kernel32.WaitForSingleObject(
                sei.hProcess, timeout_s * 1000) == WAIT_TIMEOUT:
            raise TimeoutError(f"Uninstaller timed out after {timeout_s} s.")
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
        return int(code.value)
    finally:
        kernel32.CloseHandle(sei.hProcess)


class UninstallWorker(QThread):
    """Runs a registry UninstallString. Tries CreateProcess first (no shell
    layer); if the target's manifest requires admin (WinError 740), retries
    through ShellExecuteEx 'runas' so Windows shows the UAC prompt."""
    finished_code = Signal(int)
    failed = Signal(str)

    TIMEOUT_S = 900

    def __init__(self, command: str, silent: bool):
        super().__init__()
        self.command = command
        self.silent = silent

    def run(self):
        try:
            proc = subprocess.run(
                self.command, timeout=self.TIMEOUT_S,
                creationflags=(0x08000000 if self.silent else 0),
            )
            self.finished_code.emit(proc.returncode)
            return
        except subprocess.TimeoutExpired:
            self.failed.emit("Uninstaller timed out after 15 minutes.")
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) != ERROR_ELEVATION_REQUIRED:
                self.failed.emit(str(exc))
                return
            # fall through to elevated retry
        except ValueError as exc:
            self.failed.emit(str(exc))
            return

        # --- elevation required: ShellExecuteEx 'runas' -------------------
        try:
            exe, params = split_command_line(self.command)
            self.finished_code.emit(run_elevated(exe, params, self.TIMEOUT_S))
        except PermissionError as exc:      # UAC declined
            self.failed.emit(str(exc))
        except (TimeoutError, OSError) as exc:
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

        note = QLabel("Windows may show a UAC elevation prompt if the "
                      "uninstaller requires administrator rights.")
        note.setObjectName("SubHeader")
        note.setWordWrap(True)
        lay.addWidget(note)

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


