# =============================================================================
#  HistoryStore: persistence, diff events, chain integrity, actions
# =============================================================================
import json


def test_first_scan_is_baseline(store, rec):
    r = store.save_scan([rec("A", "1"), rec("B", "2")])
    assert r["baseline"] and r["scan_id"] == 1
    assert r["added"] == [] and r["removed"] == [] and r["changed"] == []


def test_second_scan_diffs_against_first(store, rec):
    store.save_scan([rec("A", "1"), rec("B", "2")])
    r = store.save_scan([rec("A", "2"), rec("C", "1")])
    assert not r["baseline"]
    assert r["added"] == ["C"]
    assert r["removed"] == ["B"]
    assert r["changed"] == [("A", "1", "2")]


def test_latest_scan_roundtrip(store, rec):
    store.save_scan([rec("A", "1")])
    store.save_scan([rec("A", "1"), rec("B", "3")])
    sid, ts, entries = store.latest_scan()
    assert sid == 2 and len(entries) == 2
    assert {p["Name"] for p in entries} == {"A", "B"}
    assert entries[0]["Publisher"] == "Acme"        # full record preserved


def test_latest_scan_empty_db(store):
    assert store.latest_scan() is None


def test_scans_listing_counts(store, rec):
    store.save_scan([rec("A", "1")])
    store.save_scan([rec("A", "2"), rec("B", "1")])
    rows = store.scans()
    assert rows[0][0] == 2                    # newest first
    assert rows[0][4:7] == (1, 0, 1)          # +1 added, -0, ~1 changed


def test_events_and_first_seen(store, rec):
    store.save_scan([rec("A", "1")])
    store.save_scan([rec("A", "2")])
    store.save_scan([])
    ev = store.events_for_program("A")
    assert [e[1] for e in ev] == ["changed", "removed"]
    assert store.first_seen("A") is not None
    assert store.first_seen("Never") is None


def test_chain_verifies_when_untouched(store, rec):
    store.save_scan([rec("A", "1")])
    store.save_scan([rec("A", "2")])
    ok, msg = store.verify_chain()
    assert ok and "2 scans" in msg


def test_chain_detects_version_column_tamper(store, rec):
    store.save_scan([rec("A", "1")])
    store.con.execute("UPDATE entries SET version='9' WHERE name='A'")
    store.con.commit()
    assert not store.verify_chain()[0]


def test_chain_detects_name_tamper(store, rec):
    store.save_scan([rec("A", "1")])
    store.con.execute("UPDATE entries SET name='Evil' WHERE name='A'")
    store.con.commit()
    assert not store.verify_chain()[0]


def test_chain_detects_data_blob_tamper(store, rec):
    store.save_scan([rec("A", "1")])
    row = store.con.execute("SELECT data FROM entries").fetchone()[0]
    d = json.loads(row)
    d["UninstallString"] = "evil.exe"
    store.con.execute("UPDATE entries SET data=?",
                      (json.dumps(d, ensure_ascii=False),))
    store.con.commit()
    assert not store.verify_chain()[0]


def test_chain_detects_linkage_tamper(store, rec):
    store.save_scan([rec("A", "1")])
    store.save_scan([rec("A", "2")])
    store.con.execute("UPDATE scans SET prev_hash='forged' WHERE id=2")
    store.con.commit()
    ok, msg = store.verify_chain()
    assert not ok and "linkage" in msg


def test_empty_chain_verifies(store):
    ok, msg = store.verify_chain()
    assert ok and "empty" in msg.lower()


def test_action_log_and_query(store):
    store.log_action("uninstall", "A", "unins.exe", 0)
    store.log_action("uninstall", "A", "unins.exe", None)
    acts = store.actions_for_program("A")
    assert len(acts) == 2
    assert acts[0][3] == 0 and acts[1][3] is None


def test_purge_clears_everything(store, rec):
    store.save_scan([rec("A", "1")])
    store.log_action("uninstall", "A", "x", 0)
    store.purge()
    assert store.scans() == []
    assert store.latest_scan() is None
    assert store.actions_for_program("A") == []
