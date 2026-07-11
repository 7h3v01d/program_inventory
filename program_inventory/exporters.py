# =============================================================================
#  Program Inventory — export writers and snapshot IO
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================
#  Pure functions: (records, path) in, files out. No Qt.
# =============================================================================
import csv
import datetime
import json
import os
from pathlib import Path

CSV_FIELDS = ["Name", "Version", "Publisher", "InstallDate", "SizeMB",
              "Arch", "Source", "InstallLocation", "UninstallString",
              "EntryId"]

SNAPSHOT_VERSION = 2


def _clean(rec: dict) -> dict:
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def write_csv(records: list[dict], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(_clean(r) for r in records)


def write_json(records: list[dict], path: str):
    payload = {
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "host": os.environ.get("COMPUTERNAME", ""),
        "count": len(records),
        "programs": [_clean(r) for r in records],
    }
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def write_txt(records: list[dict], path: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"PROGRAM INVENTORY — {now} — {len(records)} programs", "=" * 100]
    for p in records:
        lines += [
            f"Name      : {p['Name']}",
            f"Version   : {p.get('Version') or 'N/A'}",
            f"Publisher : {p.get('Publisher') or 'N/A'}",
            f"Installed : {p.get('InstallDate') or 'N/A'}",
            f"Size      : "
            f"{'N/A' if p.get('SizeMB') is None else str(p['SizeMB']) + ' MB'}",
            f"Arch      : {p.get('Arch', '')} ({p.get('Source', '')})",
            f"Location  : {p.get('InstallLocation') or 'N/A'}",
            "-" * 100,
        ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_md(records: list[dict], path: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    esc = lambda s: str(s).replace("|", "\\|")          # noqa: E731
    lines = [f"# Program Inventory — {now}", "",
             f"{len(records)} programs.", "",
             "| Name | Version | Publisher | Installed | Size (MB) | Arch |",
             "|---|---|---|---|---|---|"]
    for p in records:
        lines.append(
            f"| {esc(p['Name'])} | {esc(p.get('Version', ''))} "
            f"| {esc(p.get('Publisher', ''))} | {p.get('InstallDate', '')} "
            f"| {'' if p.get('SizeMB') is None else p['SizeMB']} "
            f"| {p.get('Arch', '')} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_snapshot(programs: list[dict], path: str):
    """Portable snapshot: enough of each record to run an identity-aware
    diff on another machine or at a later date."""
    payload = {
        "snapshot_version": SNAPSHOT_VERSION,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "host": os.environ.get("COMPUTERNAME", ""),
        "programs": [{
            "EntryId": p.get("EntryId", ""),
            "Name": p["Name"],
            "Version": p.get("Version", ""),
            "Publisher": p.get("Publisher", ""),
            "Arch": p.get("Arch", ""),
        } for p in programs],
    }
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def load_snapshot(path: str) -> tuple[dict, list[dict]]:
    """Returns (metadata, records). Accepts v2 snapshots (record list) and
    v1 snapshots ({name: version} map — converted to EntryId-less records
    so the diff engine's name-fallback tier applies)."""
    snap = json.loads(Path(path).read_text(encoding="utf-8"))
    progs = snap["programs"]
    if isinstance(progs, dict):             # v1 format
        records = [{"Name": n, "Version": v} for n, v in progs.items()]
    else:
        records = progs
    meta = {"generated": snap.get("generated", "?"),
            "host": snap.get("host", "?"),
            "snapshot_version": snap.get("snapshot_version", 1)}
    return meta, records
