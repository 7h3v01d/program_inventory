# =============================================================================
#  Program Inventory — identity-aware diff engine
#  Copyright 2026 Leon Priest / 7h3v01d — Apache License 2.0
# =============================================================================
#  Two-tier diff between scans:
#    Tier 1 — match on EntryId (hive|view|registry-subkey hash): tracks the
#             actual installation. Same id + new version = 'changed'; same id
#             + same version but different metadata = 'modified'.
#    Tier 2 — correlate leftover added/removed by (name, publisher): catches
#             upgrades that rewrite the registry key (MSI ProductCode change)
#             while keeping the display name. Both name AND key changing is
#             reported honestly as removed + added.
#  Pure functions, no Qt — importable standalone.
# =============================================================================
import hashlib
import json


def make_entry_id(hive_name: str, arch: str, key_name: str) -> str:
    """Stable installation identity: hive + registry view + subkey name."""
    return hashlib.sha256(
        f"{hive_name}|{arch}|{key_name}".encode("utf-8")).hexdigest()[:16]


def entry_key(rec: dict) -> str:
    """Diff key for a record. Legacy records (pre-v4.1 history) may lack an
    EntryId — fall back to display name so old scans still diff sensibly."""
    return rec.get("EntryId") or f"name:{rec.get('Name', '').lower()}"


def record_fingerprint(rec: dict) -> str:
    """Hash of everything durable in a record (transient _keys excluded)."""
    stable = {k: v for k, v in sorted(rec.items()) if not k.startswith("_")}
    return hashlib.sha256(
        json.dumps(stable, sort_keys=True, ensure_ascii=False,
                   default=str).encode("utf-8")).hexdigest()


def diff_scans(old: list[dict], new: list[dict]) -> dict:
    """Returns {'added': [rec], 'removed': [rec],
                'changed': [(old, new)], 'modified': [(old, new)]}
    'changed'  = same installation (or tier-2 correlated), version differs
    'modified' = same installation and version, other metadata differs"""
    old_by = {entry_key(r): r for r in old}
    new_by = {entry_key(r): r for r in new}

    changed: list[tuple[dict, dict]] = []
    modified: list[tuple[dict, dict]] = []

    # Tier 1 — identity match
    for k in old_by.keys() & new_by.keys():
        o, n = old_by[k], new_by[k]
        if o.get("Version", "") != n.get("Version", ""):
            changed.append((o, n))
        elif record_fingerprint(o) != record_fingerprint(n):
            modified.append((o, n))

    # Tier 2 — correlate leftovers by name; publishers must agree when both
    # sides have one (a blank publisher — e.g. a legacy v1 snapshot — falls
    # back to name-only correlation rather than failing to correlate).
    removed_pool: dict[str, list[dict]] = {}
    for k in old_by.keys() - new_by.keys():
        r = old_by[k]
        removed_pool.setdefault(r.get("Name", "").lower(), []).append(r)

    added: list[dict] = []
    for k in sorted(new_by.keys() - old_by.keys()):
        n = new_by[k]
        pool = removed_pool.get(n.get("Name", "").lower(), [])
        n_pub = n.get("Publisher", "").lower()
        o = next((c for c in pool
                  if c.get("Publisher", "").lower() == n_pub), None)
        if o is None:
            o = next((c for c in pool
                      if not c.get("Publisher") or not n_pub), None)
        if o is not None:
            pool.remove(o)
            if o.get("Version", "") != n.get("Version", ""):
                changed.append((o, n))       # key rewritten by upgrade
            else:
                modified.append((o, n))      # key moved, same version
        else:
            added.append(n)

    removed = [r for pool in removed_pool.values() for r in pool]

    key = lambda r: r.get("Name", "").lower()          # noqa: E731
    pkey = lambda p: p[1].get("Name", "").lower()      # noqa: E731
    return {
        "added": sorted(added, key=key),
        "removed": sorted(removed, key=key),
        "changed": sorted(changed, key=pkey),
        "modified": sorted(modified, key=pkey),
    }


def diff_counts(diff: dict) -> tuple[int, int, int, int]:
    return (len(diff["added"]), len(diff["removed"]),
            len(diff["changed"]), len(diff["modified"]))


def format_diff_report(diff: dict, header_lines: list[str] | None = None) -> str:
    """Single shared renderer for scan popups, snapshot compares, and the
    timeline dialog — one format everywhere."""
    lines = list(header_lines or [])
    if lines:
        lines.append("")
    a, r, c, m = diff_counts(diff)

    lines.append(f"[+] ADDED ({a})")
    lines += [f"    + {n['Name']}  {n.get('Version', '')}"
              for n in diff["added"]] or ["    (none)"]
    lines.append("")
    lines.append(f"[-] REMOVED ({r})")
    lines += [f"    - {o['Name']}  {o.get('Version', '')}"
              for o in diff["removed"]] or ["    (none)"]
    lines.append("")
    lines.append(f"[~] VERSION CHANGED ({c})")
    lines += [f"    ~ {n['Name']}  {o.get('Version', '?')}  ->  "
              f"{n.get('Version', '?')}"
              for o, n in diff["changed"]] or ["    (none)"]
    lines.append("")
    lines.append(f"[±] METADATA MODIFIED ({m})")
    lines += [f"    ± {n['Name']}  {n.get('Version', '')}"
              for _, n in diff["modified"]] or ["    (none)"]
    return "\n".join(lines)
