# =============================================================================
#  Export writers and snapshot IO
# =============================================================================
import csv
import json

from program_inventory import exporters
from program_inventory.diffengine import diff_scans, diff_counts


def test_csv_roundtrip_excludes_transient(tmp_path, rec):
    r = rec("A", "1")
    r["_update"] = {"junk": True}
    path = tmp_path / "out.csv"
    exporters.write_csv([r], str(path))
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows[0]["Name"] == "A" and rows[0]["EntryId"]
    assert "_update" not in rows[0]


def test_json_export_clean(tmp_path, rec):
    r = rec("A", "1")
    r["_update"] = {"junk": True}
    path = tmp_path / "out.json"
    exporters.write_json([r], str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["count"] == 1
    assert "_update" not in data["programs"][0]


def test_txt_and_md_render(tmp_path, rec):
    t, m = tmp_path / "o.txt", tmp_path / "o.md"
    exporters.write_txt([rec("A|B", "1")], str(t))
    exporters.write_md([rec("A|B", "1")], str(m))
    assert "A|B" in t.read_text(encoding="utf-8")
    assert "A\\|B" in m.read_text(encoding="utf-8")    # pipes escaped in md


def test_snapshot_v2_roundtrip_diffs_by_identity(tmp_path, rec):
    path = tmp_path / "snap.json"
    exporters.write_snapshot([rec("A", "1", key="{G1}")], str(path))
    meta, old = exporters.load_snapshot(str(path))
    assert meta["snapshot_version"] == 2
    d = diff_scans(old, [rec("A", "2", key="{G1}")])
    assert diff_counts(d)[2] == 1                      # same id -> changed


def test_v1_snapshot_still_loads(tmp_path, rec):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({
        "snapshot_version": 1, "generated": "2026-01-01T00:00:00",
        "host": "X", "programs": {"A": "1", "B": "2"}}), encoding="utf-8")
    meta, old = exporters.load_snapshot(str(path))
    assert meta["snapshot_version"] == 1
    d = diff_scans(old, [rec("A", "2")])
    a, r, c, m = diff_counts(d)
    assert (r, c) == (1, 1)                            # B gone, A upgraded
