"""Tests for capability dispatch — the first capability that really routes.

Until this module existed the pack layer was declarative only: ``registry.choose``
had no production caller, so a manifest that pointed at the wrong function would
have gone unnoticed. These tests pin the two properties that make the routing
real rather than cosmetic:

* **anti-drift**: the callable the manifest resolves *is* the object the workflow
  used to import directly, so repointing a manifest breaks a test instead of
  silently running different code;
* **no silent fallback**: a missing, disabled or ambiguous claimant is an explicit
  error, because a fallback would make a broken pack indistinguishable from a
  working one.

Plus the wiring itself: the CLI must actually pass the dispatched probe into the
command, otherwise the seam is decoration.
"""

from __future__ import annotations

import types
from typing import Any

import pytest

from sms_tool import cli
from sms_tool.commands import accounts as account_commands
from sms_tool.packs import dispatch
from sms_tool.packs.contracts import PackManifest
from sms_tool.packs.registry import LegacyProviderPack, PackRegistry

CAPABILITY = "account.health"
ENTRYPOINT = "account_liveness"


def manifest(pack_id: str = "test.health", *, status: str = "active") -> PackManifest:
    return PackManifest.from_mapping(
        {
            "schema": "provider-pack.v2",
            "id": pack_id,
            "display_name": "Test Health",
            "version": "1.0.0",
            "api_version": "1",
            "status": status,
            "capabilities": [CAPABILITY],
            "endpoints": {"api": "https://health.test"},
            "entrypoints": {ENTRYPOINT: "sms_tool.accounts.account_liveness:probe_account_liveness"},
            "hooks": {},
            "risk_signals": [],
        }
    )


def registry_of(*packs: PackManifest) -> PackRegistry:
    return PackRegistry([LegacyProviderPack(pack) for pack in packs])


def quota_args(**overrides: Any) -> types.SimpleNamespace:
    base = {"email": "a@example.com", "proxy": None, "refresh_timeout": 30, "desktop_ipc": False}
    base.update(overrides)
    return types.SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_the_dispatched_probe_is_the_object_the_workflow_imports() -> None:
    """Anti-drift: the manifest may not point somewhere else without failing here."""
    from sms_tool.accounts import account_liveness

    resolved = dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, registry=registry_of(manifest()))

    assert resolved is account_liveness.probe_account_liveness


def test_the_real_tree_dispatches_to_the_chatgpt_pack() -> None:
    assert dispatch.capability_owner(CAPABILITY) == "openai.chatgpt"

    resolved = dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT)

    from sms_tool.accounts import account_liveness

    assert resolved is account_liveness.probe_account_liveness


def test_an_unknown_capability_names_the_vocabulary() -> None:
    with pytest.raises(dispatch.CapabilityDispatchError, match="unknown capability"):
        dispatch.resolve_capability_entrypoint("account.telepathy", ENTRYPOINT, registry=registry_of(manifest()))


def test_no_claimant_is_an_explicit_error_not_a_fallback() -> None:
    """The whole point: a pack that stops claiming a capability must fail loudly."""
    with pytest.raises(dispatch.CapabilityDispatchError, match="no enabled provider pack claims"):
        dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, registry=PackRegistry())


def test_a_disabled_pack_is_not_dispatchable() -> None:
    registry = registry_of(manifest(status="disabled"))

    with pytest.raises(dispatch.CapabilityDispatchError, match="no enabled provider pack claims"):
        dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, registry=registry)


def test_two_claimants_require_an_explicit_pack_id() -> None:
    """Picking by id order would be a routing decision nobody made."""
    registry = registry_of(manifest("a.first"), manifest("b.second"))

    with pytest.raises(dispatch.CapabilityDispatchError, match="pass pack_id to choose one explicitly"):
        dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, registry=registry)

    resolved = dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, pack_id="b.second", registry=registry)
    assert resolved.__name__ == "probe_account_liveness"


def test_an_explicit_pack_id_that_does_not_claim_is_rejected() -> None:
    registry = registry_of(manifest("a.first"), manifest("b.second"))

    with pytest.raises(dispatch.CapabilityDispatchError, match="does not claim"):
        dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, pack_id="c.third", registry=registry)


# ---------------------------------------------------------------------------
# The command seam
# ---------------------------------------------------------------------------


@pytest.fixture
def quota_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Isolate ``quota_usage`` from storage and the IPC channel."""
    captured: dict[str, Any] = {"emitted": None}

    monkeypatch.setattr("sms_tool.storage.get_account_payload", lambda email: {"email": email})
    monkeypatch.setattr(account_commands, "emit_result", lambda payload, **kwargs: captured.update(emitted=payload))
    return captured


def test_quota_usage_runs_the_injected_probe(quota_env: dict[str, Any]) -> None:
    calls: list[dict[str, Any]] = []

    def sentinel(account: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        calls.append({"account": account, **kwargs})
        return {"ok": True, "status": "active", "quota_status": "可用", "wham_usage": None, "status_code": 200}

    account_commands.quota_usage(quota_args(), probe_fn=sentinel)

    assert calls and calls[0]["account"] == {"email": "a@example.com"}
    assert calls[0]["proxy"] is None
    assert quota_env["emitted"]["ok"] is True


def test_quota_usage_defaults_to_the_direct_import(quota_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Every existing caller and test keeps the old behaviour when nothing is injected."""
    from sms_tool.accounts import account_liveness

    seen: list[str] = []

    def fake_probe(account: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        seen.append("direct")
        return {"ok": True, "status": "active", "quota_status": "可用"}

    monkeypatch.setattr(account_liveness, "probe_account_liveness", fake_probe)

    account_commands.quota_usage(quota_args())

    assert seen == ["direct"]


def test_the_cli_routes_quota_usage_through_the_registry(
    quota_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wiring proof: without this, the dispatch would have no production caller."""
    marker = object()
    forwarded: dict[str, Any] = {}

    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", lambda capability, entrypoint: marker)
    monkeypatch.setattr(
        account_commands,
        "quota_usage",
        lambda args, *, probe_fn=None: forwarded.update(probe_fn=probe_fn),
    )

    cli._quota_usage(quota_args())

    assert forwarded["probe_fn"] is marker


def test_the_cli_reports_a_missing_capability_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(capability: str, entrypoint: str) -> Any:
        raise dispatch.CapabilityDispatchError("no enabled provider pack claims 'account.health'")

    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", unavailable)

    with pytest.raises(SystemExit) as excinfo:
        cli._quota_usage(quota_args())

    assert excinfo.value.code == 2
