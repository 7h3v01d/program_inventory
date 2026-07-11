# =============================================================================
#  Program Inventory — winget update intelligence: parser, matcher, worker
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================

import subprocess

from .constants import IS_WINDOWS
from .qt_shim import QThread, Signal


WINGET_ELLIPSIS = "\u2026"


def parse_winget_upgrade(output: str) -> list[dict]:
    """Parse `winget upgrade` fixed-width table output.

    winget has no JSON output for the upgrade list, so we locate header
    lines ('Name ... Id ... Version ... Available ...'), take the column
    start offsets from the header, and slice each data row. Handles multiple
    table sections (regular + 'require explicit targeting') and skips
    separators/summary lines. Known limitation: rows containing wide CJK
    glyphs can mis-slice because winget pads by display width, not chars.
    """
    rows: list[dict] = []
    offsets: list[tuple[str, int]] | None = None
    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        if (stripped.startswith("Name") and " Id" in line
                and "Version" in line and "Available" in line):
            offsets = sorted(
                ((col, line.index(col)) for col in
                 ("Name", "Id", "Version", "Available", "Source")
                 if col in line),
                key=lambda t: t[1])
            continue
        if offsets is None:
            continue
        if set(stripped) <= {"-"}:          # separator row
            continue
        # Aligned data rows have a space immediately before each column
        # start; prose lines ("The following packages ...") don't.
        if any(start > 0 and len(line) > start and line[start - 1] != " "
               for _, start in offsets):
            continue
        rec: dict = {}
        for j, (col, start) in enumerate(offsets):
            end = offsets[j + 1][1] if j + 1 < len(offsets) else None
            rec[col] = line[start:end].strip()
        if rec.get("Name") and rec.get("Available"):
            rows.append(rec)
    return rows


def match_winget_row(registry_name: str, winget_name: str) -> str | None:
    """Confidence-graded match. 'exact' = full case-insensitive name match;
    'probable' = prefix match against a winget-truncated ('…') name; None =
    no match. Callers must surface the difference — probable matches are a
    heuristic, not an identification."""
    rn, wn = registry_name.lower(), winget_name.lower()
    if wn.endswith(WINGET_ELLIPSIS):
        return "probable" if rn.startswith(wn[:-1]) else None
    return "exact" if rn == wn else None


def winget_upgrade_command(update: dict) -> str:
    """Build a copy-ready upgrade command. If the Id was display-truncated,
    fall back to matching by name (quoted)."""
    wid = update.get("Id", "")
    if wid and WINGET_ELLIPSIS not in wid:
        return f'winget upgrade --id "{wid}"'
    return f'winget upgrade --name "{update.get("Name", "")}"'


class WingetWorker(QThread):
    """QThread subclass (project convention). Shells out to winget."""
    updates_done = Signal(list)
    updates_failed = Signal(str)

    def run(self):
        if not IS_WINDOWS:
            self.updates_failed.emit("winget requires Windows.")
            return
        try:
            proc = subprocess.run(
                ["winget", "upgrade", "--include-unknown",
                 "--disable-interactivity", "--accept-source-agreements"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180,
                creationflags=0x08000000,  # CREATE_NO_WINDOW — no console flash
            )
        except FileNotFoundError:
            self.updates_failed.emit(
                "winget not found — install 'App Installer' from the Microsoft Store.")
            return
        except subprocess.TimeoutExpired:
            self.updates_failed.emit("winget timed out after 180 s.")
            return
        if proc.returncode not in (0,):
            # winget exits non-zero for 'no applicable upgrade' etc. — still
            # try to parse; only fail if we also got nothing usable.
            parsed = parse_winget_upgrade(proc.stdout or "")
            if parsed:
                self.updates_done.emit(parsed)
            else:
                self.updates_failed.emit(
                    f"winget exit code {proc.returncode}:\n"
                    f"{(proc.stderr or proc.stdout or '').strip()[:400]}")
            return
        self.updates_done.emit(parse_winget_upgrade(proc.stdout or ""))


