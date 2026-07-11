# =============================================================================
#  Scan helpers (registry access itself requires real Windows)
# =============================================================================
import sys

import pytest

from program_inventory.scan import _parse_install_date, scan_installed_programs


@pytest.mark.parametrize("raw,expected", [
    ("20240315", "2024-03-15"),
    ("2024-03-15", "2024-03-15"),
    ("03/15/2024", "2024-03-15"),
    ("", ""),
    ("garbage", "garbage"),      # unknown format passes through untouched
])
def test_parse_install_date(raw, expected):
    assert _parse_install_date(raw) == expected


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows guard test")
def test_scan_raises_off_windows():
    with pytest.raises(RuntimeError):
        scan_installed_programs()
