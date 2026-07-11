# =============================================================================
#  Program Inventory — SQLite scan timeline with chain-hashed audit log
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================

import datetime
import hashlib
import json
import os
import sqlite3
from pathlib import Path


# =============================================================================
#  History store — SQLite timeline with chain-hashed audit log
# =============================================================================
class HistoryStore:
    """Every scan is persisted automatically. Each scan row carries a SHA-256
    hash chained to the previous scan's hash, so history tampering is
    detectable via verify_chain(). All access is main-thread only."""

    def __init__(self, db_path: Path | None = None):
        self.path = db_path or Path.home() / ".program_inventory" / "history.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(str(self.path))
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript("""
            CREATE TABLE IF NOT EXISTS scans(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, host TEXT, count INTEGER,
                added INTEGER, removed INTEGER, changed INTEGER,
                prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entries(
                scan_id INTEGER NOT NULL, name TEXT NOT NULL,
                version TEXT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id INTEGER NOT NULL, ts TEXT NOT NULL,
                kind TEXT NOT NULL, name TEXT NOT NULL,
                old_version TEXT, new_version TEXT);
            CREATE TABLE IF NOT EXISTS actions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
                command TEXT, exit_code INTEGER);
            CREATE INDEX IF NOT EXISTS idx_entries_scan ON entries(scan_id);
            CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
            CREATE INDEX IF NOT EXISTS idx_actions_name ON actions(name);
        """)
        self.con.commit()

    # --- hashing ---------------------------------------------------------
    @staticmethod
    def _canonical(rows: list[tuple[str, str, str]]) -> str:
        """Canonical form over (name, version, data_json) rows. Covers the
        columns diffs read AND the full record blobs, so tampering with any
        of them breaks the chain."""
        items = sorted(
            (n, v or "", hashlib.sha256(d.encode("utf-8")).hexdigest())
            for n, v, d in rows)
        return json.dumps(items, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _scan_hash(prev_hash: str, ts: str, host: str, canonical: str) -> str:
        return hashlib.sha256(
            f"{prev_hash}|{ts}|{host}|{canonical}".encode("utf-8")).hexdigest()

    # --- write ------------------------------------------------------------
    def save_scan(self, programs: list[dict]) -> dict:
        """Persist a scan, diff against the previous one, record events.
        Returns {'scan_id', 'added', 'removed', 'changed', 'baseline'}."""
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        host = os.environ.get("COMPUTERNAME", "")
        prev = self.con.execute(
            "SELECT id, hash FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        prev_id, prev_hash = (prev if prev else (None, "GENESIS"))

        new_map = {p["Name"]: p.get("Version", "") for p in programs}
        added: list[str] = []
        removed: list[str] = []
        changed: list[tuple[str, str, str]] = []
        old_map: dict[str, str] = {}
        if prev_id is not None:
            old_map = dict(self.con.execute(
                "SELECT name, version FROM entries WHERE scan_id=?", (prev_id,)))
            added = sorted(set(new_map) - set(old_map), key=str.lower)
            removed = sorted(set(old_map) - set(new_map), key=str.lower)
            changed = sorted(
                ((n, old_map[n], new_map[n])
                 for n in set(new_map) & set(old_map) if new_map[n] != old_map[n]),
                key=lambda t: t[0].lower())

        entry_rows = [(p["Name"], p.get("Version", ""),
                       json.dumps(p, ensure_ascii=False)) for p in programs]
        canonical = self._canonical(entry_rows)
        h = self._scan_hash(prev_hash, ts, host, canonical)
        cur = self.con.execute(
            "INSERT INTO scans(ts, host, count, added, removed, changed, prev_hash, hash)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (ts, host, len(programs), len(added), len(removed), len(changed),
             prev_hash, h))
        scan_id = cur.lastrowid
        self.con.executemany(
            "INSERT INTO entries(scan_id, name, version, data) VALUES(?,?,?,?)",
            [(scan_id, n, v, d) for n, v, d in entry_rows])
        ev = ([(scan_id, ts, "added", n, None, new_map[n]) for n in added]
              + [(scan_id, ts, "removed", n, old_map[n], None) for n in removed]
              + [(scan_id, ts, "changed", n, o, v) for n, o, v in changed])
        if ev:
            self.con.executemany(
                "INSERT INTO events(scan_id, ts, kind, name, old_version, new_version)"
                " VALUES(?,?,?,?,?,?)", ev)
        self.con.commit()
        return {"scan_id": scan_id, "added": added, "removed": removed,
                "changed": changed, "baseline": prev_id is None}

    # --- read --------------------------------------------------------------
    def latest_scan(self) -> tuple[int, str, list[dict]] | None:
        row = self.con.execute(
            "SELECT id, ts FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return row[0], row[1], self.entries_for(row[0])

    def entries_for(self, scan_id: int) -> list[dict]:
        rows = self.con.execute(
            "SELECT data FROM entries WHERE scan_id=? ORDER BY name COLLATE NOCASE",
            (scan_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def scans(self) -> list[tuple]:
        """(id, ts, host, count, added, removed, changed, hash) newest first."""
        return self.con.execute(
            "SELECT id, ts, host, count, added, removed, changed, hash"
            " FROM scans ORDER BY id DESC").fetchall()

    def events_for_program(self, name: str) -> list[tuple]:
        return self.con.execute(
            "SELECT ts, kind, old_version, new_version FROM events"
            " WHERE name=? ORDER BY id", (name,)).fetchall()

    def first_seen(self, name: str) -> str | None:
        row = self.con.execute(
            "SELECT s.ts FROM entries e JOIN scans s ON s.id=e.scan_id"
            " WHERE e.name=? ORDER BY e.scan_id LIMIT 1", (name,)).fetchone()
        return row[0] if row else None

    def log_action(self, kind: str, name: str, command: str,
                   exit_code: int | None):
        """Informational action log (uninstall runs etc.). The resulting
        inventory change itself is captured by the chain-hashed scan diff."""
        self.con.execute(
            "INSERT INTO actions(ts, kind, name, command, exit_code)"
            " VALUES(?,?,?,?,?)",
            (datetime.datetime.now().isoformat(timespec="seconds"),
             kind, name, command, exit_code))
        self.con.commit()

    def actions_for_program(self, name: str) -> list[tuple]:
        return self.con.execute(
            "SELECT ts, kind, command, exit_code FROM actions"
            " WHERE name=? ORDER BY id", (name,)).fetchall()

    # --- integrity / maintenance --------------------------------------------
    def verify_chain(self) -> tuple[bool, str]:
        rows = self.con.execute(
            "SELECT id, ts, host, prev_hash, hash FROM scans ORDER BY id").fetchall()
        if not rows:
            return True, "Audit chain empty — nothing to verify."
        expected_prev = "GENESIS"
        for sid, ts, host, prev_hash, stored in rows:
            if prev_hash != expected_prev:
                return False, f"BREAK at scan #{sid}: prev_hash linkage mismatch."
            rows_ = self.con.execute(
                "SELECT name, version, data FROM entries WHERE scan_id=?",
                (sid,)).fetchall()
            canonical = self._canonical(rows_)
            if self._scan_hash(prev_hash, ts, host or "", canonical) != stored:
                return False, f"BREAK at scan #{sid}: recomputed hash != stored hash."
            expected_prev = stored
        return True, f"Audit chain intact — {len(rows)} scans verified."

    def purge(self):
        self.con.executescript(
            "DELETE FROM events; DELETE FROM entries; DELETE FROM scans;"
            " DELETE FROM actions;")
        self.con.commit()
        self.con.execute("VACUUM")

    def close(self):
        self.con.close()


