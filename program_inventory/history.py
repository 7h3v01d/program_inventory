# =============================================================================
#  Program Inventory — SQLite scan timeline with chain-hashed audit log
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================
#  Schema v2 (PRAGMA user_version = 2):
#    - entries carry a stable EntryId (hive|view|subkey hash)
#    - scans carry an `algo` column: hashes on legacy scans stay verifiable
#      under the v1 canonical form, new scans hash under v2 (which covers
#      EntryId). The prev_hash chain runs unbroken across the boundary.
#    - scans carry a `modified` count alongside added/removed/changed
#    - actions carry an `outcome` column (success/failed/unknown/declined/
#      timeout/error)
#  verify_chain() checks BOTH: hash-chain integrity AND that the stored
#  summary counts match a recomputed diff of the stored entries — summary
#  data is derivative and is never trusted independently.
#  Migration from v1 databases backs the file up first; a corrupt database
#  is set aside (renamed) and a fresh one started, never silently deleted.
# =============================================================================
import datetime
import hashlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

from .diffengine import diff_scans, diff_counts, make_entry_id

SCHEMA_VERSION = 2

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS scans(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL, host TEXT, count INTEGER,
        added INTEGER, removed INTEGER, changed INTEGER,
        modified INTEGER DEFAULT 0,
        algo INTEGER DEFAULT 2,
        prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS entries(
        scan_id INTEGER NOT NULL, entry_id TEXT DEFAULT '',
        name TEXT NOT NULL, version TEXT, data TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS events(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scan_id INTEGER NOT NULL, ts TEXT NOT NULL,
        kind TEXT NOT NULL, entry_id TEXT DEFAULT '', name TEXT NOT NULL,
        old_version TEXT, new_version TEXT);
    CREATE TABLE IF NOT EXISTS actions(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
        command TEXT, exit_code INTEGER, outcome TEXT DEFAULT '');
    CREATE INDEX IF NOT EXISTS idx_entries_scan ON entries(scan_id);
    CREATE INDEX IF NOT EXISTS idx_events_name ON events(name);
    CREATE INDEX IF NOT EXISTS idx_actions_name ON actions(name);
"""


class HistoryStore:
    """Every scan is persisted automatically. Each scan row carries a SHA-256
    hash chained to the previous scan's hash, so history tampering is
    detectable via verify_chain(). All access is main-thread only."""

    def __init__(self, db_path: Path | None = None):
        self.path = db_path or Path.home() / ".program_inventory" / "history.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.recovered_from_corruption = False
        self.migrated_from: int | None = None
        try:
            self.con = self._open()
        except sqlite3.DatabaseError:
            # Corrupt file: set it aside (never delete), start fresh.
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            self.path.rename(self.path.with_suffix(f".corrupt-{stamp}"))
            self.recovered_from_corruption = True
            self.con = self._open()

    def _open(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.path))
        try:
            con.execute("PRAGMA journal_mode=WAL")
        except sqlite3.DatabaseError:
            # Release the OS file handle before the caller tries to rename
            # this file aside — on Windows a rename fails while any handle
            # to the file is still open.
            con.close()
            raise
        version = con.execute("PRAGMA user_version").fetchone()[0]
        has_scans = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='scans'"
        ).fetchone() is not None
        if has_scans and version < SCHEMA_VERSION:
            self._migrate(con, version)
        con.executescript(_SCHEMA)
        con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        con.commit()
        return con

    # --- migration ------------------------------------------------------------
    def _migrate(self, con: sqlite3.Connection, from_version: int):
        """v1 -> v2. The database file is backed up first. Legacy scans keep
        algo=1 so their original hashes remain verifiable; entry ids are
        backfilled best-effort from each record's stored RegistryPath (this
        does not affect v1 hashes, whose canonical form ignores entry_id)."""
        backup = self.path.with_suffix(f".bak-v{from_version or 1}")
        if not backup.exists():
            shutil.copy2(self.path, backup)
        with con:
            cols = {r[1] for r in con.execute("PRAGMA table_info(scans)")}
            if "algo" not in cols:
                con.execute("ALTER TABLE scans ADD COLUMN algo INTEGER DEFAULT 1")
            if "modified" not in cols:
                con.execute(
                    "ALTER TABLE scans ADD COLUMN modified INTEGER DEFAULT 0")
            ecols = {r[1] for r in con.execute("PRAGMA table_info(entries)")}
            if "entry_id" not in ecols:
                con.execute(
                    "ALTER TABLE entries ADD COLUMN entry_id TEXT DEFAULT ''")
            vcols = {r[1] for r in con.execute("PRAGMA table_info(events)")}
            if "entry_id" not in vcols:
                con.execute(
                    "ALTER TABLE events ADD COLUMN entry_id TEXT DEFAULT ''")
            acols = {r[1] for r in con.execute("PRAGMA table_info(actions)")}
            if "outcome" not in acols:
                con.execute(
                    "ALTER TABLE actions ADD COLUMN outcome TEXT DEFAULT ''")
            # Backfill entry ids from stored record blobs where derivable.
            for rowid, data in con.execute(
                    "SELECT rowid, data FROM entries").fetchall():
                eid = self._derive_entry_id(data)
                if eid:
                    con.execute("UPDATE entries SET entry_id=? WHERE rowid=?",
                                (eid, rowid))
            con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.migrated_from = from_version or 1

    @staticmethod
    def _derive_entry_id(data_json: str) -> str:
        try:
            rec = json.loads(data_json)
        except json.JSONDecodeError:
            return ""
        if rec.get("EntryId"):
            return rec["EntryId"]
        reg = rec.get("RegistryPath", "")
        if not reg:
            return ""
        reg = reg.split("  [")[0]                 # strip display suffix
        parts = reg.split("\\")
        if len(parts) < 2:
            return ""
        hive, key_name = parts[0], parts[-1]
        return make_entry_id(hive, rec.get("Arch", ""), key_name)

    # --- hashing ---------------------------------------------------------
    @staticmethod
    def _canonical_v1(rows: list[tuple]) -> str:
        """(name, version, data) rows — original v1 canonical form."""
        items = sorted(
            (n, v or "", hashlib.sha256(d.encode("utf-8")).hexdigest())
            for n, v, d in rows)
        return json.dumps(items, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _canonical_v2(rows: list[tuple]) -> str:
        """(entry_id, name, version, data) rows — v2 covers identity too."""
        items = sorted(
            (e or "", n, v or "", hashlib.sha256(d.encode("utf-8")).hexdigest())
            for e, n, v, d in rows)
        return json.dumps(items, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _scan_hash(prev_hash: str, ts: str, host: str, canonical: str) -> str:
        return hashlib.sha256(
            f"{prev_hash}|{ts}|{host}|{canonical}".encode("utf-8")).hexdigest()

    # --- write ------------------------------------------------------------
    def save_scan(self, programs: list[dict]) -> dict:
        """Persist a scan inside one explicit transaction, diff against the
        previous scan with the identity-aware engine, record events.
        Returns {'scan_id', 'baseline', 'added', 'removed', 'changed',
        'modified'} — added/removed are record lists, changed/modified are
        (old, new) record pairs."""
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        host = os.environ.get("COMPUTERNAME", "")
        prev = self.con.execute(
            "SELECT id, hash FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        prev_id, prev_hash = (prev if prev else (None, "GENESIS"))

        baseline = prev_id is None
        if baseline:
            diff = {"added": [], "removed": [], "changed": [], "modified": []}
        else:
            diff = diff_scans(self.entries_for(prev_id), programs)
        a, r, c, m = diff_counts(diff)

        entry_rows = [(p.get("EntryId", ""), p["Name"], p.get("Version", ""),
                       json.dumps({k: v for k, v in p.items()
                                   if not k.startswith("_")},
                                  ensure_ascii=False))
                      for p in programs]
        canonical = self._canonical_v2(entry_rows)
        h = self._scan_hash(prev_hash, ts, host, canonical)

        with self.con:                      # explicit transaction — all or nothing
            cur = self.con.execute(
                "INSERT INTO scans(ts, host, count, added, removed, changed,"
                " modified, algo, prev_hash, hash) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (ts, host, len(programs), a, r, c, m,
                 SCHEMA_VERSION, prev_hash, h))
            scan_id = cur.lastrowid
            self.con.executemany(
                "INSERT INTO entries(scan_id, entry_id, name, version, data)"
                " VALUES(?,?,?,?,?)",
                [(scan_id, e, n, v, d) for e, n, v, d in entry_rows])
            ev = (
                [(scan_id, ts, "added", p.get("EntryId", ""), p["Name"],
                  None, p.get("Version", "")) for p in diff["added"]]
                + [(scan_id, ts, "removed", p.get("EntryId", ""), p["Name"],
                    p.get("Version", ""), None) for p in diff["removed"]]
                + [(scan_id, ts, "changed", n.get("EntryId", ""), n["Name"],
                    o.get("Version", ""), n.get("Version", ""))
                   for o, n in diff["changed"]]
                + [(scan_id, ts, "modified", n.get("EntryId", ""), n["Name"],
                    o.get("Version", ""), n.get("Version", ""))
                   for o, n in diff["modified"]]
            )
            if ev:
                self.con.executemany(
                    "INSERT INTO events(scan_id, ts, kind, entry_id, name,"
                    " old_version, new_version) VALUES(?,?,?,?,?,?,?)", ev)
        return {"scan_id": scan_id, "baseline": baseline, **diff}

    # --- read --------------------------------------------------------------
    def latest_scan(self) -> tuple[int, str, list[dict]] | None:
        row = self.con.execute(
            "SELECT id, ts FROM scans ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        return row[0], row[1], self.entries_for(row[0])

    def entries_for(self, scan_id: int) -> list[dict]:
        rows = self.con.execute(
            "SELECT entry_id, data FROM entries WHERE scan_id=?"
            " ORDER BY name COLLATE NOCASE", (scan_id,)).fetchall()
        out = []
        for eid, data in rows:
            rec = json.loads(data)
            if eid and not rec.get("EntryId"):
                rec["EntryId"] = eid          # migrated legacy records
            out.append(rec)
        return out

    def scans(self) -> list[tuple]:
        """(id, ts, host, count, added, removed, changed, modified, hash)
        newest first."""
        return self.con.execute(
            "SELECT id, ts, host, count, added, removed, changed, modified,"
            " hash FROM scans ORDER BY id DESC").fetchall()

    def scan_summary(self, scan_id: int) -> tuple | None:
        return self.con.execute(
            "SELECT added, removed, changed, modified FROM scans WHERE id=?",
            (scan_id,)).fetchone()

    def events_for_program(self, name: str) -> list[tuple]:
        return self.con.execute(
            "SELECT ts, kind, old_version, new_version FROM events"
            " WHERE name=? ORDER BY id", (name,)).fetchall()

    def first_seen(self, name: str) -> str | None:
        row = self.con.execute(
            "SELECT s.ts FROM entries e JOIN scans s ON s.id=e.scan_id"
            " WHERE e.name=? ORDER BY e.scan_id LIMIT 1", (name,)).fetchone()
        return row[0] if row else None

    # --- actions ---------------------------------------------------------------
    def log_action(self, kind: str, name: str, command: str,
                   exit_code: int | None, outcome: str = ""):
        """Informational action log (uninstall runs etc.). The resulting
        inventory change itself is captured by the chain-hashed scan diff."""
        with self.con:
            self.con.execute(
                "INSERT INTO actions(ts, kind, name, command, exit_code,"
                " outcome) VALUES(?,?,?,?,?,?)",
                (datetime.datetime.now().isoformat(timespec="seconds"),
                 kind, name, command, exit_code, outcome))

    def actions_for_program(self, name: str) -> list[tuple]:
        return self.con.execute(
            "SELECT ts, kind, command, exit_code, outcome FROM actions"
            " WHERE name=? ORDER BY id", (name,)).fetchall()

    # --- integrity / maintenance --------------------------------------------
    def verify_chain(self) -> tuple[bool, str]:
        """Two checks per scan: (1) the hash chain, and (2) that stored
        summary counts match a diff recomputed from the stored entries —
        summary data is derivative and never trusted independently."""
        rows = self.con.execute(
            "SELECT id, ts, host, algo, prev_hash, hash, added, removed,"
            " changed, modified FROM scans ORDER BY id").fetchall()
        if not rows:
            return True, "Audit chain empty — nothing to verify."

        expected_prev = "GENESIS"
        problems: list[str] = []
        prev_entries: list[dict] | None = None
        for (sid, ts, host, algo, prev_hash, stored,
             s_add, s_rem, s_chg, s_mod) in rows:
            if prev_hash != expected_prev:
                return False, f"BREAK at scan #{sid}: prev_hash linkage mismatch."
            if algo >= 2:
                raw = self.con.execute(
                    "SELECT entry_id, name, version, data FROM entries"
                    " WHERE scan_id=?", (sid,)).fetchall()
                canonical = self._canonical_v2(raw)
            else:
                raw = self.con.execute(
                    "SELECT name, version, data FROM entries WHERE scan_id=?",
                    (sid,)).fetchall()
                canonical = self._canonical_v1(raw)
            if self._scan_hash(prev_hash, ts, host or "", canonical) != stored:
                return False, (f"BREAK at scan #{sid}: recomputed hash"
                               " != stored hash.")
            expected_prev = stored

            # Summary recompute — legacy (algo 1) scans were saved with the
            # name-keyed diff and no 'modified' concept, so only algo>=2
            # scans are held to the identity-aware recompute.
            entries = self.entries_for(sid)
            if prev_entries is not None and algo >= 2:
                a, r, c, m = diff_counts(diff_scans(prev_entries, entries))
                if (a, r, c, m) != (s_add, s_rem, s_chg, s_mod):
                    problems.append(
                        f"scan #{sid}: stored summary +{s_add}/-{s_rem}/"
                        f"~{s_chg}/±{s_mod} != recomputed +{a}/-{r}/~{c}/±{m}")
            prev_entries = entries

        if problems:
            return False, ("Hash chain intact, but stored summary counts do"
                           " not match recomputed diffs:\n  "
                           + "\n  ".join(problems))
        return True, (f"Audit chain intact — {len(rows)} scans verified,"
                      " summaries consistent.")

    def purge(self):
        with self.con:
            self.con.executescript(
                "DELETE FROM events; DELETE FROM entries; DELETE FROM scans;"
                " DELETE FROM actions;")
        self.con.execute("VACUUM")

    def close(self):
        self.con.close()
