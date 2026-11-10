"""Tests for ``scripts/pack_boundary_ratchet.py``.

The ratchet has no baseline on purpose: the correct count for every rule is
zero. That makes it cheap to check, and it makes this file load-bearing — a gate
that cannot fail is not a gate, so each rule is proved with a mutation of a
throwaway tree as well as asserted clean on the real one.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import pack_boundary_ratchet as gate  # noqa: E402

SCRIPT = ROOT / "scripts" / "pack_boundary_ratchet.py"

PACK_MANIFEST: dict[str, object] = {
    "schema": "provider-pack.v2",
    "id": "demo",
    "display_name": "Demo",
    "version": "1.0.0",
    "api_version": "1",
    "status": "active",
    "capabilities": ["account.health"],
    "endpoints": {"api": "https://demo.test"},
    "entrypoints": {"health": "sms_tool.platforms.demo.flow:preflight"},
    "hooks": {},
    "risk_signals": [],
}


def fake_repo(tmp_path: Path, manifest: dict[str, object] | None = None, directory: str = "demo") -> Path:
    """A minimal tree with one pack module, one builtin pack and one core module."""
    packs = tmp_path / "sms_tool" / "packs"
    packs.mkdir(parents=True)
    (packs / "demo.py").write_text("import json\n\n\ndef helper() -> None:\n    return None\n", encoding="utf-8")
    builtin = packs / "builtin" / directory
    builtin.mkdir(parents=True)
    (builtin / "manifest.json").write_text(json.dumps(manifest or PACK_MANIFEST), encoding="utf-8")
    (tmp_path / "sms_tool" / "core.py").write_text("import os\n", encoding="utf-8")
    return tmp_path


def test_the_real_tree_passes_every_rule() -> None:
    assert gate.all_violations() == {
        "leaf contract": [],
        "core imports a builtin pack": [],
        "builtin pack layout": [],
        "manifest contract": [],
    }


def test_script_exits_zero_on_the_real_tree() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "pack-boundary ratchet OK" in proc.stdout


def test_a_clean_fixture_tree_passes(tmp_path: Path) -> None:
    root = fake_repo(tmp_path)

    assert gate.all_violations(root) == {
        "leaf contract": [],
        "core imports a builtin pack": [],
        "builtin pack layout": [],
        "manifest contract": [],
    }


def test_leaf_contract_flags_an_absolute_application_import(tmp_path: Path) -> None:
    root = fake_repo(tmp_path)
    (root / "sms_tool" / "packs" / "demo.py").write_text("import sms_tool.config\n", encoding="utf-8")

    violations = gate.leaf_violations(root)

    assert violations and "may only import stdlib" in violations[0]


def test_leaf_contract_flags_a_relative_import_out_of_the_package(tmp_path: Path) -> None:
    root = fake_repo(tmp_path)
    (root / "sms_tool" / "packs" / "demo.py").write_text("from ..config import CFG\n", encoding="utf-8")

    violations = gate.leaf_violations(root)

    assert violations and "escapes the packs package" in violations[0]


def test_leaf_contract_allows_a_relative_import_inside_the_package(tmp_path: Path) -> None:
    root = fake_repo(tmp_path)
    (root / "sms_tool" / "packs" / "demo.py").write_text("from .contracts import PackManifest\n", encoding="utf-8")

    assert gate.leaf_violations(root) == []


def test_leaf_contract_ignores_function_local_imports(tmp_path: Path) -> None:
    """A delayed import is ``delayed_import_ratchet``'s business, not this rule's."""
    root = fake_repo(tmp_path)
    (root / "sms_tool" / "packs" / "demo.py").write_text(
        "def helper() -> None:\n    from ..config import CFG\n\n    return None\n", encoding="utf-8"
    )

    assert gate.leaf_violations(root) == []


def test_leaf_contract_flags_a_relative_import_that_escapes_the_package(tmp_path: Path) -> None:
    root = fake_repo(tmp_path)
    (root / "sms_tool" / "packs" / "demo.py").write_text("from ...kernel import paths\n", encoding="utf-8")

    violations = gate.leaf_violations(root)

    assert violations and "escapes the packs package" in violations[0]


def test_a_core_module_importing_a_builtin_pack_is_a_violation(tmp_path: Path) -> None:
    root = fake_repo(tmp_path)
    (root / "sms_tool" / "core.py").write_text("from sms_tool.packs.builtin.demo import x\n", encoding="utf-8")

    violations = gate.core_import_violations(root)

    assert violations and "builtin packs are data only" in violations[0]


def test_a_python_file_inside_a_builtin_pack_is_a_violation(tmp_path: Path) -> None:
    root = fake_repo(tmp_path)
    (root / "sms_tool" / "packs" / "builtin" / "demo" / "impl.py").write_text("x = 1\n", encoding="utf-8")

    violations = gate.builtin_layout_violations(root)

    assert violations and "builtin packs are data only" in violations[0]


def test_the_manifest_directory_name_must_match_the_pack_id(tmp_path: Path) -> None:
    root = fake_repo(tmp_path, directory="wrong-name")

    violations = gate.manifest_violations(root)

    assert any("directory name must be the pack id" in item for item in violations)


def test_a_pack_without_entrypoints_is_rejected_by_the_contract(tmp_path: Path) -> None:
    payload = dict(PACK_MANIFEST, entrypoints={})
    root = fake_repo(tmp_path, manifest=payload)

    violations = gate.manifest_violations(root)

    assert any("manifest.json" in item and "non-empty" in item for item in violations)


def test_an_entrypoint_pointing_into_a_builtin_pack_is_a_violation(tmp_path: Path) -> None:
    payload = dict(PACK_MANIFEST, entrypoints={"health": "sms_tool.packs.builtin.demo:preflight"})
    root = fake_repo(tmp_path, manifest=payload)

    violations = gate.manifest_violations(root)

    assert any("points into a builtin pack" in item for item in violations)


def test_duplicate_pack_ids_across_directories_are_a_violation(tmp_path: Path) -> None:
    root = fake_repo(tmp_path)
    duplicate = root / "sms_tool" / "packs" / "builtin" / "demo"
    second = root / "sms_tool" / "packs" / "builtin" / "pack"
    second.mkdir()
    (second / "manifest.json").write_text((duplicate / "manifest.json").read_text(encoding="utf-8"), encoding="utf-8")

    violations = gate.manifest_violations(root)

    assert any("duplicate pack id" in item for item in violations)
