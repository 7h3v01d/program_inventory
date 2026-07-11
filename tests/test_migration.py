# =============================================================================
#  Schema v1 -> v2 migration, verification across the algo boundary,
#  summary recompute, corruption recovery
# =============================================================================
import json
import sqlite3

from program_inventory.history import HistoryStore


def _build_v1_db(path, rec):
    """Craft a genuine v1 database: v1 schema, v1 canonical hashing."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE scans(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, host TEXT, count INTEGER,
            added INTEGER, removed INTEGER, changed INTEGER,
            prev_hash TEXT NOT NULL, hash TEXT NOT NULL);
        CREATE TABLE entries(
            scan_id INTEGER NOT NULL, name TEXT NOT NULL,
            version TEXT, data TEXT NOT NULL);
        CREATE TABLE events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL, ts TEXT NOT NULL,
            kind TEXT NOT NULL, name TEXT NOT NULL,
            old_version TEXT, new_version TEXT);
        CREATE TABLE actions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
            command TEXT, exit_code INTEGER);
    """)
    prev_hash = "GENESIS"
    scans = [
        ("2026-01-01T10:00:00", [rec("A", "1"), rec("B", "1")], (0, 0, 0)),
        ("2026-02-01T10:00:00", [rec("A", "2")], (0, 1, 1)),
    ]
    for ts, progs, (a, r, c) in scans:
        rows = [(p["Name"], p.get("Version", ""),
                 json.dumps({k: v for k, v in p.items() if k != "EntryId"
                             and k != "KeyName"}, ensure_ascii=False))
                for p in progs]
        canonical = HistoryStore._canonical_v1(rows)
        h = HistoryStore._scan_hash(prev_hash, ts, "OLDHOST", canonical)
        cur = con.execute(
            "INSERT INTO scans(ts, host, count, added, removed, changed,"
            " prev_hash, hash) VALUES(?,?,?,?,?,?,?,?)",
            (ts, "OLDHOST", len(progs), a, r, c, prev_hash, h))
        con.executemany(
            "INSERT INTO entries(scan_id, name, version, data)"
            " VALUES(?,?,?,?)",
            [(cur.lastrowid, n, v, d) for n, v, d in rows])
        prev_hash = h
    con.execute("INSERT INTO actions(ts, kind, name, command, exit_code)"
                " VALUES('2026-01-15T10:00:00','uninstall','B','u.exe',0)")
    con.commit()
    con.close()


def test_v1_database_migrates_and_still_verifies(tmp_path, rec):
    db = tmp_path / "history.db"
    _build_v1_db(db, rec)
    store = HistoryStore(db)
    assert store.migrated_from == 1
    assert db.with_suffix(".bak-v1").exists()          # backup taken first
    ok, msg = store.verify_chain()
    assert ok, msg                                     # legacy hashes intact
    # legacy entries got backfilled ids from their RegistryPath blobs
    eids = [e for (e,) in store.con.execute(
        "SELECT entry_id FROM entries").fetchall()]
    assert all(eids)
    # actions gained the outcome column
    assert store.actions_for_program("B")[0][4] == ""
    store.close()


def test_new_scans_after_migration_use_v2(tmp_path, rec):
    db = tmp_path / "history.db"
    _build_v1_db(db, rec)
    store = HistoryStore(db)
    store.save_scan([rec("A", "3")])                   # crosses the boundary
    algos = [a for (a,) in store.con.execute(
        "SELECT algo FROM scans ORDER BY id").fetchall()]
    assert algos == [1, 1, 2]
    ok, msg = store.verify_chain()
    assert ok, msg                                     # chain unbroken across algos
    store.close()


def test_verify_flags_tampered_summary_counts(store, rec):
    store.save_scan([rec("A", "1")])
    store.save_scan([rec("A", "2"), rec("B", "1")])
    ok, _ = store.verify_chain()
    assert ok
    # Forge the summary: claim nothing changed. Hash chain still verifies
    # (counts aren't hashed) — the recompute must catch it.
    store.con.execute(
        "UPDATE scans SET added=0, changed=0 WHERE id=2")
    store.con.commit()
    ok, msg = store.verify_chain()
    assert not ok
    assert "summary" in msg.lower() and "scan #2" in msg


def test_corrupt_database_set_aside_not_deleted(tmp_path):
    db = tmp_path / "history.db"
    db.write_bytes(b"this is not a sqlite database at all............")
    store = HistoryStore(db)
    assert store.recovered_from_corruption
    corpses = list(tmp_path.glob("history.corrupt-*"))
    assert len(corpses) == 1                           # set aside, not deleted
    assert corpses[0].read_bytes().startswith(b"this is not")
    assert store.verify_chain()[0]                     # fresh db works
    store.close()


def test_fresh_database_is_v2(store):
    assert store.con.execute("PRAGMA user_version").fetchone()[0] == 2
    assert store.migrated_from is None
