"""Tests for ``scripts/pack_new.py`` — the new-architecture scaffold.

The generator is the one command an operator runs to start a new registration
architecture, so it is pinned in both directions: the rendered manifest must
validate against the real contract (a scaffold the loader would reject is worse
than none), and the files it writes must land where the platform looks for them.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import pack_new  # noqa: E402

from sms_tool.packs.contracts import PackManifest  # noqa: E402


def test_module_name_turns_a_pack_id_into_a_directory_name() -> None:
    assert pack_new.module_name("acme.portal") == "acme_portal"
    assert pack_new.module_name("acme-multi-word.portal") == "acme_multi_word_portal"


def test_the_rendered_manifest_validates_against_the_real_contract() -> None:
    scaffold = pack_new.build_scaffold("acme.portal", "Acme Portal")

    manifest = PackManifest.from_mapping(scaffold.manifest())

    assert manifest.id == "acme.portal"
    assert manifest.status == "experimental"
    assert manifest.api_version == "1"
    assert manifest.capabilities == frozenset(pack_new.DEFAULT_CAPABILITIES)
    assert manifest.entrypoints == {"register_email": "sms_tool.platforms.acme_portal.flow:register_email"}
    assert manifest.hooks == {"verify": "sms_tool.platforms.acme_portal.flow:preflight"}


def test_the_placeholder_endpoint_is_unroutable() -> None:
    """A scaffold must never point at a host that could answer for real."""
    scaffold = pack_new.build_scaffold("acme.portal", "Acme Portal")

    assert scaffold.endpoints == {"base": "https://acme-portal.invalid"}


def test_the_generated_flow_is_syntactically_valid_and_raises_not_implemented() -> None:
    scaffold = pack_new.build_scaffold("acme.portal", "Acme Portal")
    source = next(content for path, content in scaffold.files.items() if path.name == "flow.py")

    ast.parse(source)
    assert "NotImplementedError" in source
    assert "acme.portal" in source


def test_the_scaffold_covers_every_maintenance_surface() -> None:
    scaffold = pack_new.build_scaffold("acme.portal", "Acme Portal")

    names = {path.as_posix().replace(str(ROOT).replace("\\", "/"), "") for path in scaffold.files}

    assert any(name.endswith("sms_tool/platforms/acme_portal/flow.py") for name in names)
    assert any(name.endswith("sms_tool/packs/builtin/acme_portal/manifest.json") for name in names)
    assert any(name.endswith("tests/packs/test_acme_portal_pack.py") for name in names)
    assert any(name.endswith("docs/packs/acme.portal.md") for name in names)


def test_endpoint_parsing_rejects_a_value_without_a_url() -> None:
    assert pack_new._parse_endpoints(["auth=https://auth.acme.test"]) == {"auth": "https://auth.acme.test"}
    with pytest.raises(ValueError, match="expects NAME=URL"):
        pack_new._parse_endpoints(["auth"])


def test_writing_refuses_to_clobber_and_force_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pack_new, "ROOT", tmp_path)
    scaffold = pack_new.build_scaffold("acme.portal", "Acme Portal")

    written = pack_new.write_scaffold(scaffold)

    assert written
    assert all(path.exists() for path in written)

    with pytest.raises(FileExistsError, match="already exists"):
        pack_new.write_scaffold(scaffold)

    assert pack_new.write_scaffold(scaffold, force=True)


def test_a_rejected_manifest_never_reaches_the_disk(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``main`` validates before writing; an unknown capability must exit 2."""
    monkeypatch.setattr(pack_new, "ROOT", tmp_path)

    exit_code = pack_new.main(["--id", "acme.portal", "--capability", "account.registration.telepathy"])

    assert exit_code == 2
    assert not (tmp_path / "sms_tool").exists()
