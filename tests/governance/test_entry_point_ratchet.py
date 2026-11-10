"""Tests for ``scripts/entry_point_ratchet.py``.

The gate exists because entry points accumulate at the repository root one
convenience script at a time, and nothing measured that surface. A gate that only
ever passes on the real tree would not stop that, so every rule is proved to fail
on a mutated miniature repository:

* a new root ``*.py`` with no declaration, and a declaration for code that is gone;
* an undeclared ``services/`` project and an undeclared ``SmsWorkbench*`` project;
* a packaged artifact at the root;
* an entry missing its kind, status, owner or purpose.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import entry_point_ratchet as gate  # noqa: E402

SCRIPT = ROOT / "scripts" / "entry_point_ratchet.py"


def entry(entry_id: str, roots: list[str], **overrides: object) -> dict:
    payload = {
        "id": entry_id,
        "kind": "tool",
        "status": "internal",
        "owner": roots[0],
        "purpose": "a declared entry used by the fixture",
        "roots": list(roots),
    }
    payload.update(overrides)
    return payload


def mini_manifest(*entries: dict) -> dict:
    return {
        "schema": "entry_points.v1",
        "kinds": sorted(gate.KINDS),
        "statuses": sorted(gate.STATUSES),
        "entries": list(entries),
    }


def mini_repo(tmp_path: Path) -> Path:
    (tmp_path / "run.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (tmp_path / "services" / "demo").mkdir(parents=True)
    (tmp_path / "SmsWorkbench").mkdir()
    return tmp_path


@pytest.fixture
def clean(tmp_path: Path) -> tuple[Path, dict]:
    """A miniature repository whose entry surface is fully declared."""
    root = mini_repo(tmp_path)
    payload = mini_manifest(
        entry("cli", ["run.py"], kind="cli", status="authoritative"),
        entry("demo", ["services/demo/"], kind="service"),
        entry("desktop", ["SmsWorkbench/"], kind="desktop", status="authoritative"),
    )
    return root, payload


def test_the_real_tree_is_fully_declared() -> None:
    assert gate.check() == []


def test_script_exits_zero_on_the_real_tree() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "entry-point ratchet OK" in proc.stdout


def test_the_fixture_itself_is_clean(clean: tuple[Path, dict]) -> None:
    root, payload = clean

    assert gate.check(payload, root) == []


def test_an_undeclared_root_script_fails(clean: tuple[Path, dict]) -> None:
    root, payload = clean
    (root / "sneaky.py").write_text("x = 1\n", encoding="utf-8")

    failures = gate.check(payload, root)

    assert any("sneaky.py" in item and "no declaration" in item for item in failures), failures


def test_a_declaration_for_deleted_code_fails(clean: tuple[Path, dict]) -> None:
    root, payload = clean
    (root / "run.py").unlink()

    failures = gate.check(payload, root)

    assert any("does not exist" in item for item in failures), failures


def test_an_undeclared_service_fails(clean: tuple[Path, dict]) -> None:
    root, payload = clean
    (root / "services" / "other").mkdir()

    failures = gate.check(payload, root)

    assert any("services/other/" in item for item in failures), failures


def test_an_undeclared_desktop_project_fails(clean: tuple[Path, dict]) -> None:
    root, payload = clean
    (root / "SmsWorkbench.Contracts").mkdir()

    failures = gate.check(payload, root)

    assert any("SmsWorkbench.Contracts/" in item for item in failures), failures


@pytest.mark.parametrize("name", ["setup.exe", "release.zip", "bundle.msi", "pack.7z"])
def test_a_packaged_artifact_at_the_root_fails(clean: tuple[Path, dict], name: str) -> None:
    root, payload = clean
    (root / name).write_bytes(b"binary")

    failures = gate.check(payload, root)

    assert any(name in item and "dist/" in item for item in failures), failures


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"kind": "wizard"}, "kind must be one of"),
        ({"status": "beta"}, "status must be one of"),
        ({"owner": "  "}, "owner must name"),
        ({"purpose": "todo"}, "purpose must say"),
        ({"roots": []}, "roots must be a non-empty array"),
    ],
)
def test_an_incomplete_entry_fails(clean: tuple[Path, dict], overrides: dict, expected: str) -> None:
    root, _payload = clean
    broken = entry("cli", ["run.py"], kind="cli", status="authoritative")
    broken.update(overrides)
    payload = mini_manifest(
        broken,
        entry("demo", ["services/demo/"], kind="service"),
        entry("desktop", ["SmsWorkbench/"], kind="desktop", status="authoritative"),
    )

    failures = gate.check(payload, root)

    assert any(expected in item for item in failures), failures


def test_a_duplicate_entry_id_fails(clean: tuple[Path, dict]) -> None:
    root, _payload = clean
    payload = mini_manifest(
        entry("cli", ["run.py"], kind="cli", status="authoritative"),
        entry("cli", ["services/demo/"], kind="service"),
        entry("desktop", ["SmsWorkbench/"], kind="desktop", status="authoritative"),
    )

    failures = gate.check(payload, root)

    assert any("duplicate entry id" in item for item in failures), failures


def test_the_vocabulary_must_be_complete(clean: tuple[Path, dict]) -> None:
    """The manifest declares the vocabulary, so it cannot silently shrink."""
    root, payload = clean
    payload = dict(payload, kinds=["cli"])

    failures = gate.check(payload, root)

    assert any("kinds must list exactly" in item for item in failures), failures


# --------------------------------------------------------------------------
# scripts/ grouping: one drawer per blast radius
# --------------------------------------------------------------------------


def scripts_repo(tmp_path: Path) -> Path:
    """The mini repo plus a ``scripts/`` directory with two files."""
    root = mini_repo(tmp_path)
    (root / "scripts").mkdir()
    (root / "scripts" / "a_ratchet.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    (root / "scripts" / "b_operator.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    return root


def grouped(*entries: dict, groups: dict | None = None) -> dict:
    payload = mini_manifest(
        entry("cli", ["run.py"], kind="cli", status="authoritative"),
        entry("demo", ["services/demo/"], kind="service"),
        entry("desktop", ["SmsWorkbench/"], kind="desktop", status="authoritative"),
        *entries,
    )
    payload["script_groups"] = (
        groups
        if groups is not None
        else {
            "gate": {"purpose": "read-only checks that fail the build", "files": ["a_ratchet.py"]},
            "operator": {"purpose": "helpers that touch live credentials", "files": ["b_operator.py"]},
        }
    )
    return payload


def test_a_fully_grouped_scripts_tree_passes(tmp_path: Path) -> None:
    root = scripts_repo(tmp_path)
    payload = grouped(entry("scripts", ["scripts/"], kind="tool"))

    assert gate.check(payload, root) == []


def test_an_ungrouped_script_fails(tmp_path: Path) -> None:
    root = scripts_repo(tmp_path)
    (root / "scripts" / "c_new.py").write_text("x = 1\n", encoding="utf-8")

    failures = gate.check(grouped(entry("scripts", ["scripts/"], kind="tool")), root)

    assert any("c_new.py" in item and "no group" in item for item in failures), failures


def test_a_group_naming_a_missing_script_fails(tmp_path: Path) -> None:
    root = scripts_repo(tmp_path)
    groups = {
        "gate": {"purpose": "read-only checks that fail the build", "files": ["a_ratchet.py", "ghost.py"]},
        "operator": {"purpose": "helpers that touch live credentials", "files": ["b_operator.py"]},
    }

    failures = gate.check(grouped(entry("scripts", ["scripts/"], kind="tool"), groups=groups), root)

    assert any("scripts/ghost.py" in item and "missing" in item for item in failures), failures


def test_a_script_claimed_by_two_groups_fails(tmp_path: Path) -> None:
    root = scripts_repo(tmp_path)
    groups = {
        "gate": {"purpose": "read-only checks that fail the build", "files": ["a_ratchet.py", "b_operator.py"]},
        "operator": {"purpose": "helpers that touch live credentials", "files": ["b_operator.py"]},
    }

    failures = gate.check(grouped(entry("scripts", ["scripts/"], kind="tool"), groups=groups), root)

    assert any("claimed by both" in item for item in failures), failures


def test_a_group_without_a_purpose_fails(tmp_path: Path) -> None:
    root = scripts_repo(tmp_path)
    groups = {
        "gate": {"purpose": "todo", "files": ["a_ratchet.py"]},
        "operator": {"purpose": "helpers that touch live credentials", "files": ["b_operator.py"]},
    }

    failures = gate.check(grouped(entry("scripts", ["scripts/"], kind="tool"), groups=groups), root)

    assert any("purpose must say what the group is for" in item for item in failures), failures
