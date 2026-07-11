# =============================================================================
#  Program Inventory — shared constants
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================

import sys

from .qt_shim import Qt
from . import __version__, APP_NAME as _APP_NAME

IS_WINDOWS = sys.platform == "win32"
APP_NAME = _APP_NAME
APP_VERSION = __version__

COLUMNS = ["Name", "Version", "Update", "Publisher", "Installed", "Size (MB)", "Arch", "Source", "Location"]
(COL_NAME, COL_VER, COL_UPD, COL_PUB, COL_DATE, COL_SIZE, COL_ARCH, COL_SRC,
 COL_LOC) = range(9)
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
DATA_ROLE = Qt.ItemDataRole.UserRole + 2   # full record dict on column 0

NOISE_TERMS = ("windows update", "security update", "hotfix", "edge webview")

