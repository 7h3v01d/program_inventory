# =============================================================================
#  Identity-aware two-tier diff engine
# =============================================================================
from program_inventory.diffengine import (
    make_entry_id, entry_key, diff_scans, diff_counts, format_diff_report)


def R(name, ver, key=None, pub="Acme", **kw):
    key = key or name
    base = {"EntryId": make_entry_id("HKLM", "64-bit", key),
            "Name": name, "Version": ver, "Publisher": pub}
    base.update(kw)
    return base


def test_entry_id_stable_and_distinct():
    assert make_entry_id("HKLM", "64-bit", "K") == make_entry_id("HKLM", "64-bit", "K")
    assert make_entry_id("HKLM", "64-bit", "K") != make_entry_id("HKLM", "32-bit", "K")
    assert make_entry_id("HKLM", "64-bit", "K") != make_entry_id("HKCU", "64-bit", "K")


def test_legacy_records_fall_back_to_name_key():
    assert entry_key({"Name": "App"}) == "name:app"
    assert entry_key(R("App", "1")) != "name:app"


def test_same_id_version_bump_is_changed():
    d = diff_scans([R("App", "1.0")], [R("App", "2.0")])
    assert diff_counts(d) == (0, 0, 1, 0)


def test_same_id_metadata_change_is_modified():
    d = diff_scans([R("App", "1.0", InstallLocation="C:\\a")],
                   [R("App", "1.0", InstallLocation="C:\\b")])
    assert diff_counts(d) == (0, 0, 0, 1)


def test_identical_scans_no_events():
    d = diff_scans([R("App", "1.0")], [R("App", "1.0")])
    assert diff_counts(d) == (0, 0, 0, 0)


def test_tier2_key_rewrite_same_name_is_changed():
    # MSI ProductCode change on upgrade: new registry key, same display name.
    d = diff_scans([R("App", "1.0", key="{OLD-GUID}")],
                   [R("App", "2.0", key="{NEW-GUID}")])
    assert diff_counts(d) == (0, 0, 1, 0)
    o, n = d["changed"][0]
    assert o["Version"] == "1.0" and n["Version"] == "2.0"


def test_tier2_key_move_same_version_is_modified():
    d = diff_scans([R("App", "1.0", key="OldKey")],
                   [R("App", "1.0", key="NewKey")])
    assert diff_counts(d) == (0, 0, 0, 1)


def test_name_and_key_both_change_is_add_remove():
    # Honest reporting: nothing ties the two entries together.
    d = diff_scans([R("Python 3.11.4 (64-bit)", "3.11.4", key="{G1}")],
                   [R("Python 3.11.5 (64-bit)", "3.11.5", key="{G2}")])
    assert diff_counts(d) == (1, 1, 0, 0)


def test_tier2_disambiguates_by_publisher():
    # Two products share a display name; only the same-publisher pair
    # correlates — the other is a genuine remove + add.
    d = diff_scans(
        [R("Updater", "1.0", key="K1", pub="VendorA"),
         R("Updater", "1.0", key="K2", pub="VendorB")],
        [R("Updater", "2.0", key="K3", pub="VendorA")])
    assert diff_counts(d) == (0, 1, 1, 0)
    assert d["removed"][0]["Publisher"] == "VendorB"
    assert d["changed"][0][1]["Publisher"] == "VendorA"


def test_same_name_same_version_different_entries_coexist():
    # Per-user + per-machine siblings: both present, no collapse, no events.
    a = R("Tool", "1.0", key="K-machine")
    b = dict(R("Tool", "1.0", key="K-user"),
             EntryId=make_entry_id("HKCU", "user", "K-user"))
    d = diff_scans([a, b], [a, b])
    assert diff_counts(d) == (0, 0, 0, 0)
    d2 = diff_scans([a, b], [a])            # user copy removed
    assert diff_counts(d2) == (0, 1, 0, 0)


def test_report_contains_all_sections():
    d = diff_scans([R("Gone", "1"), R("Chg", "1")],
                   [R("Chg", "2"), R("New", "1")])
    text = format_diff_report(d, ["header"])
    for token in ("header", "[+] ADDED (1)", "[-] REMOVED (1)",
                  "[~] VERSION CHANGED (1)", "[±] METADATA MODIFIED (0)",
                  "+ New", "- Gone", "~ Chg  1  ->  2"):
        assert token in text, token
