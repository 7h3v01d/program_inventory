# =============================================================================
#  Program Inventory — registry scan across hives and WOW64 views
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================

import datetime

from .constants import IS_WINDOWS, NOISE_TERMS
from .diffengine import make_entry_id
from .qt_shim import QThread, Signal

if IS_WINDOWS:
    import winreg


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
                            "EntryId": make_entry_id(hive_name, arch, sub_name),
                            "KeyName": sub_name,
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

    # No display-name deduplication: every registry entry is a distinct
    # installation record with its own EntryId. Per-user vs per-machine and
    # 32/64-bit siblings are real, separate entries and are shown as such.
    programs.sort(key=lambda p: (p["Name"].lower(), p["Arch"]))
    return programs



class ScanWorker(QThread):
    """QThread subclass (project convention) — never moveToThread."""
    scan_done = Signal(list)
    scan_failed = Signal(str)

    def run(self):
        try:
            self.scan_done.emit(scan_installed_programs())
        except Exception as exc:  # noqa: BLE001 — surface everything to UI
            self.scan_failed.emit(str(exc))


