"""Contract test for the bundled ChatGPT provider pack.

This file is the ChatGPT architecture's own maintenance entry. It fails when the
manifest stops describing code that exists, which is the failure mode a silently
renamed function would otherwise produce only at registration time — the pack is
resolved lazily, so nothing else in the suite imports its entrypoints.
"""

from __future__ import annotations

from sms_tool.packs import admin, loader


def registry():
    return loader.load_registry()


def test_the_chatgpt_pack_is_discoverable() -> None:
    assert "openai.chatgpt" in registry().ids()


def test_every_declared_entrypoint_and_hook_resolves() -> None:
    report = admin.verify_pack(registry().get("openai.chatgpt"))

    assert report["ok"], report["failures"]
    assert report["checked"] is True


def test_the_pack_claims_the_capabilities_the_core_dispatches() -> None:
    capabilities = registry().get("openai.chatgpt").manifest.capabilities

    assert {"account.registration.email", "account.health", "session.access_token"} <= capabilities


def test_the_pack_owns_an_isolated_namespace() -> None:
    namespaces = registry().get("openai.chatgpt").manifest.namespaces

    assert namespaces.config == "packs.openai.chatgpt"
    assert namespaces.storage == "packs/openai.chatgpt"
    assert namespaces.telemetry == "pack.openai.chatgpt"


def test_the_verify_hook_is_declared_and_the_rest_are_still_reserved() -> None:
    detail = admin.pack_detail(registry(), "openai.chatgpt")

    assert "verify" in detail["hooks"]
    # Operator channels the platform reserves but this pack does not implement
    # yet. Pinned so adding one is a visible, reviewed decision.
    assert detail["missing_hooks"] == ["doctor", "migrate", "upgrade"]


def test_the_pack_is_active_so_workflows_may_resolve_it() -> None:
    manifest = registry().get("openai.chatgpt").manifest

    assert manifest.status == "active"
    assert manifest.enabled is True
    assert manifest.api_version == "1"
