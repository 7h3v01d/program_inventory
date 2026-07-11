# =============================================================================
#  winget table parser, name matcher, command builder
# =============================================================================
from program_inventory.wingetcheck import (
    parse_winget_upgrade, match_winget_row, winget_upgrade_command)

W = (34, 23, 13, 13)


def wrow(n, i, v, a, s="winget"):
    return n.ljust(W[0]) + i.ljust(W[1]) + v.ljust(W[2]) + a.ljust(W[3]) + s


HEADER = wrow("Name", "Id", "Version", "Available", "Source")
SEP = "-" * len(HEADER)

SAMPLE = "\n".join([
    "   -\x08\\\x08|\x08",                                   # spinner junk
    HEADER, SEP,
    wrow("Mozilla Firefox (x64 en-US)", "Mozilla.Firefox", "127.0", "128.0.1"),
    wrow("7-Zip 24.07 (x64)", "7zip.7zip", "24.07", "24.08"),
    wrow("Some Very Long Application Name\u2026",
         "SomePublisher.SomeVe\u2026", "1.0.0", "2.0.0"),
    "3 upgrades available.",
    "",
    "The following packages have an upgrade available, but require "
    "explicit targeting for upgrade:",
    HEADER, SEP,
    wrow("Pinned Tool", "Pinned.Tool", "5.0", "6.0"),
])


def test_parses_all_data_rows_across_sections():
    rows = parse_winget_upgrade(SAMPLE)
    assert len(rows) == 4
    assert rows[3]["Name"] == "Pinned Tool"


def test_columns_sliced_correctly():
    rows = parse_winget_upgrade(SAMPLE)
    assert rows[0]["Id"] == "Mozilla.Firefox"
    assert rows[0]["Available"] == "128.0.1"
    assert rows[0]["Source"] == "winget"


def test_truncated_fields_preserved():
    rows = parse_winget_upgrade(SAMPLE)
    assert rows[2]["Name"].endswith("\u2026")
    assert rows[2]["Id"].endswith("\u2026")


def test_prose_and_summary_lines_skipped():
    rows = parse_winget_upgrade(SAMPLE)
    names = [r["Name"] for r in rows]
    assert not any("following packages" in n for n in names)
    assert not any("upgrades available" in n for n in names)


def test_empty_and_headerless_output():
    assert parse_winget_upgrade("") == []
    assert parse_winget_upgrade("No installed package found.") == []


def test_match_exact_case_insensitive():
    assert match_winget_row("7-Zip 24.07 (x64)", "7-zip 24.07 (X64)")
    assert not match_winget_row("Other App", "7-Zip 24.07 (x64)")


def test_match_truncated_prefix():
    assert match_winget_row("Some Very Long Application Name Here Really",
                            "Some Very Long Application Name\u2026")


def test_command_uses_id_when_clean():
    assert winget_upgrade_command(
        {"Id": "Mozilla.Firefox", "Name": "Firefox"}
    ) == 'winget upgrade --id "Mozilla.Firefox"'


def test_command_falls_back_to_name_when_id_truncated():
    cmd = winget_upgrade_command(
        {"Id": "SomePublisher.SomeVe\u2026", "Name": "Some App"})
    assert cmd == 'winget upgrade --name "Some App"'
