"""Tests for the pack-scoped config reader (Phase 2.6).

Why this exists
---------------
``scripts/experiment_ledger.json`` can declare ``packs.<id>.toggles``, and the
ratchet validates their shape -- but nothing proved that a pack's own config
namespace is read at all. That is exactly why ``experiment_ratchet`` rejects a
``retired`` pack toggle instead of believing it: an unread key has nothing to
retire.

The reader lives in ``sms_tool/packs/admin.py`` because that module already owns
the ``packs.<id>`` namespace knowledge (it reports it as
``detail["namespaces"]["config"]``) and needs nothing but the standard library to
read it -- which is what the pack boundary allows. Putting it in
``sms_tool/kernel/flags.py`` instead would have added an edge to the frozen
``sms_tool -> sms_tool/kernel`` pair for a value only ``--pack-info`` needs.

Two shapes are pinned here because both were live defects elsewhere in this repo:
a ``dict`` check instead of a ``Mapping`` check reads "nothing configured" in
production (the frozen shards are ``mappingproxy``), and a dotted path cannot
express a pack id, which itself contains dots.
"""

from __future__ import annotations

import json
import types
from typing import Any

import pytest

from sms_tool import cli
from sms_tool.packs import LegacyProviderPack, PackManifest, PackRegistry, admin

MANIFEST = {
    "schema": "provider-pack.v2",
    "id": "openai.chatgpt",
    "display_name": "Toggle Demo",
    "version": "1.0.0",
    "api_version": "1",
    "status": "active",
    "capabilities": ["account.health"],
    "endpoints": {"api": "https://toggle.test"},
    "entrypoints": {"health": "sms_tool.accounts.account_liveness:probe_account_liveness"},
    "hooks": {},
    "risk_signals": [],
}


def registry() -> PackRegistry:
    return PackRegistry([LegacyProviderPack(PackManifest.from_mapping(MANIFEST))])


# ---------------------------------------------------------------------------
# the reader
# ---------------------------------------------------------------------------


def test_the_reader_returns_the_packs_own_section() -> None:
    config = {"packs": {"openai.chatgpt": {"new_flow": True, "a": "off"}}}

    assert admin.pack_configured_toggles(config, "openai.chatgpt") == {"a": "off", "new_flow": True}


def test_a_dotted_pack_id_is_one_key() -> None:
    """The id is looked up whole: splitting on dots would find the wrong section."""
    config = {"packs": {"openai.chatgpt": {"new_flow": True}}, "openai": {"chatgpt": {"new_flow": "wrong"}}}

    assert admin.pack_configured_toggles(config, "openai.chatgpt") == {"new_flow": True}


def test_an_unconfigured_pack_reads_as_empty() -> None:
    assert admin.pack_configured_toggles({"packs": {}}, "openai.chatgpt") == {}
    assert admin.pack_configured_toggles({}, "openai.chatgpt") == {}


def test_a_differently_shaped_section_reads_as_empty() -> None:
    assert admin.pack_configured_toggles({"packs": "not-a-mapping"}, "openai.chatgpt") == {}
    assert admin.pack_configured_toggles(None, "openai.chatgpt") == {}


def test_a_frozen_mappingproxy_is_readable() -> None:
    """The production config freezes every section, and that is not a dict."""
    frozen = types.MappingProxyType({"openai.chatgpt": types.MappingProxyType({"new_flow": "off"})})

    assert admin.pack_configured_toggles({"packs": frozen}, "openai.chatgpt") == {"new_flow": "off"}


# ---------------------------------------------------------------------------
# the management surface
# ---------------------------------------------------------------------------


def test_the_pack_detail_reports_the_configured_section() -> None:
    detail = admin.pack_detail(registry(), "openai.chatgpt", config={"packs": {"openai.chatgpt": {"new_flow": True}}})

    assert detail["configured_toggles"] == {"new_flow": True}


def test_pack_detail_omits_the_key_when_the_caller_did_not_look() -> None:
    """``None`` means "not asked"; ``{}`` means "asked, and this pack configures nothing"."""
    assert "configured_toggles" not in admin.pack_detail(registry(), "openai.chatgpt")
    assert admin.pack_detail(registry(), "openai.chatgpt", config={})["configured_toggles"] == {}


# ---------------------------------------------------------------------------
# the command layer
# ---------------------------------------------------------------------------


def test_pack_info_passes_the_live_config(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Wiring proof: without this the reader would have no production caller."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli.pack_loader, "load_registry", registry)
    monkeypatch.setattr(cli, "CFG", {"packs": {"openai.chatgpt": {"new_flow": True}}})
    monkeypatch.setattr(
        cli.pack_admin,
        "pack_detail",
        lambda reg, pack_id, *, config=None: seen.update(pack_id=pack_id, config=config) or {"ok": True},
    )

    args = types.SimpleNamespace(pack_list=False, pack_info="openai.chatgpt", pack_verify=None, json_output=True)
    assert cli._pack_management_command(args) == 0

    assert seen["pack_id"] == "openai.chatgpt"
    assert seen["config"] == {"packs": {"openai.chatgpt": {"new_flow": True}}}
    assert json.loads(capsys.readouterr().out.strip())["ok"] is True
