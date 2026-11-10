"""Ratchet: every way into this repository is declared, and the root stays small.

Why this exists
---------------
Entry points accumulate the same way root modules did: one convenience script at
a time. ``scripts/root_module_ratchet.py`` froze the *package* root after it grew
to 155 files; nothing measured the *repository* root, where a one-off
``run_something.py`` costs nothing on the day it is written and is still there a
year later. The 57 MB runtime installer sitting untracked at the root is the same
defect in a different shape: a build artifact where a source tree should be.

So this gate makes the entry surface a declared inventory:

* every root-level ``*.py`` file is claimed by exactly one entry;
* every ``services/<dir>/`` and every ``SmsWorkbench*`` project directory is
  claimed;
* every declared root still exists, so a row for deleted code fails instead of
  describing nothing;
* no packaged artifact (``*.exe``/``*.msi``/``*.zip``/``*.7z``) sits at the
  repository root -- releases are built into ``dist/``;
* each entry declares a ``kind``, a ``status``, an ``owner`` and a ``purpose``.

The claims live in ``scripts/entry_point_manifest.json``; the human table is
``docs/current/entry-points.md``. Both must agree, so a new entry point cannot
land with a row in only one of them.

Standard library only: it runs as a pytest test and would run in CI unchanged.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).resolve().parent / "entry_point_manifest.json"

KINDS = frozenset({"cli", "compat", "desktop", "operator", "service", "tool"})
STATUSES = frozenset({"authoritative", "compat", "internal", "deprecated"})

#: Extensions that mean "this is a build output, not source".
ARTIFACT_SUFFIXES = (".exe", ".msi", ".zip", ".7z")

#: A purpose shorter than this is a placeholder, not a classification.
MIN_PURPOSE = 12


def load_manifest(path: Path | None = None) -> dict:
    """Read the manifest, or raise ``ValueError`` with the reason."""
    source = MANIFEST if path is None else path
    try:
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source.name}: cannot read ({exc})") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{source.name}: must be a JSON object")
    return payload


def root_python_files(root: Path = ROOT) -> list[str]:
    """Repository-root ``*.py`` files, POSIX-relative."""
    return sorted(path.relative_to(root).as_posix() for path in root.glob("*.py") if path.is_file())


def service_dirs(root: Path = ROOT) -> list[str]:
    """``services/<name>/`` directories, with a trailing slash."""
    services = root / "services"
    if not services.is_dir():
        return []
    return sorted(f"services/{child.name}/" for child in services.iterdir() if child.is_dir())


def desktop_projects(root: Path = ROOT) -> list[str]:
    """``SmsWorkbench*`` project directories, with a trailing slash."""
    return sorted(
        f"{child.name}/" for child in root.iterdir() if child.is_dir() and child.name.startswith("SmsWorkbench")
    )


def artifacts_at_root(root: Path = ROOT) -> list[str]:
    """Packaged build outputs sitting at the repository root."""
    return sorted(path.name for path in root.iterdir() if path.is_file() and path.suffix.lower() in ARTIFACT_SUFFIXES)


def _claimed_roots(entries: list) -> dict[str, str]:
    """Map every declared root path to the entry id that claims it."""
    claims: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        entry_id = str(entry.get("id") or "")
        for declared in entry.get("roots") or []:
            if isinstance(declared, str) and declared.strip():
                claims.setdefault(declared.strip(), entry_id)
    return claims


def check(manifest: dict | None = None, root: Path = ROOT) -> list[str]:
    """Return every violation; an empty list means the entry surface is declared."""
    payload = load_manifest() if manifest is None else manifest
    failures: list[str] = []

    if payload.get("schema") != "entry_points.v1":
        failures.append("entry_point_manifest.json: schema must be entry_points.v1")
    for field, vocabulary in (("kinds", KINDS), ("statuses", STATUSES)):
        declared = payload.get(field)
        if not isinstance(declared, list) or set(declared) != vocabulary:
            failures.append(f"entry_point_manifest.json: {field} must list exactly {sorted(vocabulary)}")

    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return failures + ["entry_point_manifest.json: entries must be a non-empty array"]

    seen_ids: set[str] = set()
    claims: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            failures.append("entry_point_manifest.json: every entry must be an object")
            continue
        entry_id = str(entry.get("id") or "").strip()
        if not entry_id:
            failures.append("entry_point_manifest.json: an entry has no id")
            continue
        if entry_id in seen_ids:
            failures.append(f"{entry_id}: duplicate entry id")
        seen_ids.add(entry_id)
        failures.extend(_check_entry(entry_id, entry))
        for declared in entry.get("roots") or []:
            if isinstance(declared, str) and declared.strip():
                claims.setdefault(declared.strip(), entry_id)

    failures.extend(_check_coverage(claims, root))
    failures.extend(_check_script_groups(payload, root))
    failures.extend(
        f"{name}: packaged artifact at the repository root -- releases are built into dist/"
        for name in artifacts_at_root(root)
    )
    return failures


def _check_entry(entry_id: str, entry: dict) -> list[str]:
    failures: list[str] = []
    kind = entry.get("kind")
    status = entry.get("status")
    if kind not in KINDS:
        failures.append(f"{entry_id}: kind must be one of {sorted(KINDS)}")
    if status not in STATUSES:
        failures.append(f"{entry_id}: status must be one of {sorted(STATUSES)}")
    if not str(entry.get("owner") or "").strip():
        failures.append(f"{entry_id}: owner must name the file or directory that implements it")
    if len(str(entry.get("purpose") or "").strip()) < MIN_PURPOSE:
        failures.append(f"{entry_id}: purpose must say what the entry is for, not a placeholder")
    roots = entry.get("roots")
    if not isinstance(roots, list) or not roots:
        failures.append(f"{entry_id}: roots must be a non-empty array")
    return failures


def script_files(root: Path = ROOT) -> list[str]:
    """``scripts/*.py`` file names."""
    return sorted(path.name for path in (root / "scripts").glob("*.py"))


def _check_script_groups(payload: dict, root: Path) -> list[str]:
    """Every ``scripts/*.py`` belongs to exactly one declared group.

    ``scripts/`` is one entry point in this inventory, but it holds 65 files with
    very different blast radii: a read-only ratchet, a tool that rewrites source,
    and an operator helper that touches live credentials. Grouping them makes the
    difference explicit and stops the directory from becoming an unclassified
    drawer -- the same defect this gate exists to prevent one level up.
    """
    actual = script_files(root)
    groups = payload.get("script_groups")
    if not actual and groups is None:
        return []
    if not isinstance(groups, dict) or not groups:
        return ["entry_point_manifest.json: script_groups must declare every scripts/*.py"]

    failures: list[str] = []
    claims: dict[str, str] = {}
    for name, group in sorted(groups.items()):
        if not isinstance(group, dict):
            failures.append(f"script_groups.{name}: must be an object")
            continue
        if len(str(group.get("purpose") or "").strip()) < MIN_PURPOSE:
            failures.append(f"script_groups.{name}: purpose must say what the group is for")
        files = group.get("files")
        if not isinstance(files, list) or not files:
            failures.append(f"script_groups.{name}: files must be a non-empty array")
            continue
        for declared in files:
            label = str(declared or "").strip()
            if not label:
                failures.append(f"script_groups.{name}: contains an empty file name")
                continue
            if label in claims:
                failures.append(f"scripts/{label}: claimed by both {claims[label]} and {name}")
                continue
            claims[label] = name
            if not (root / "scripts" / label).is_file():
                failures.append(f"scripts/{label}: declared in {name} but missing")
    for name in actual:
        if name not in claims:
            failures.append(f"scripts/{name}: no group -- add it to script_groups in the manifest")
    return failures


def _check_coverage(claims: dict[str, str], root: Path) -> list[str]:
    """Both directions: nothing undeclared, and nothing declared that is gone."""
    failures: list[str] = []
    for declared, entry_id in sorted(claims.items()):
        if not (root / declared).exists():
            failures.append(f"{entry_id}: declares {declared!r}, which does not exist")

    required: list[str] = root_python_files(root) + service_dirs(root) + desktop_projects(root)
    for path in required:
        if path not in claims:
            failures.append(
                f"{path}: a new entry point with no declaration -- add a row to "
                "scripts/entry_point_manifest.json and docs/current/entry-points.md"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ratchet on the repository entry-point inventory.")
    parser.add_argument("--detail", action="store_true", help="print the declared entry surface")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    try:
        payload = load_manifest()
    except ValueError as exc:
        print(f"entry-point ratchet: {exc}", file=sys.stderr)
        return 1

    if args.detail:
        for entry in payload.get("entries") or []:
            print(f"{entry.get('id'):<18} {entry.get('kind'):<10} {entry.get('status'):<14} {entry.get('owner')}")

    failures = check(payload, args.root)
    if failures:
        print("entry-point ratchet FAILED:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    entries = payload.get("entries") or []
    print(f"entry-point ratchet OK ({len(entries)} declared entry point(s), root free of build artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
