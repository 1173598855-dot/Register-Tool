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

    with pytest.raises(dispatch.CapabilityDispatchError, match="pass --pack"):
        dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, registry=registry)

    resolved = dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, pack_id="b.second", registry=registry)
    assert resolved.__name__ == "probe_account_liveness"


def test_an_explicit_pack_id_that_does_not_claim_is_rejected() -> None:
    registry = registry_of(manifest("a.first"), manifest("b.second"))

    with pytest.raises(dispatch.CapabilityDispatchError, match="does not claim"):
        dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, pack_id="c.third", registry=registry)


# ---------------------------------------------------------------------------
# The selector: flag, then process default, then the only claimant
# ---------------------------------------------------------------------------


def test_the_process_default_selects_among_claimants() -> None:
    registry = registry_of(manifest("a.first"), manifest("b.second"))

    resolved = dispatch.resolve_capability_entrypoint(
        CAPABILITY, ENTRYPOINT, registry=registry, environ={"GPT_PACK_ID": "b.second"}
    )

    assert resolved.__name__ == "probe_account_liveness"


def test_an_explicit_flag_beats_the_process_default() -> None:
    registry = registry_of(manifest("a.first"), manifest("b.second"))

    owner = dispatch.capability_owner(
        CAPABILITY, pack_id="a.first", registry=registry, environ={"GPT_PACK_ID": "b.second"}
    )

    assert owner == "a.first"


def test_the_process_default_must_claim_the_capability() -> None:
    registry = registry_of(manifest("a.first"), manifest("b.second"))

    with pytest.raises(dispatch.CapabilityDispatchError, match="does not claim"):
        dispatch.resolve_capability_entrypoint(
            CAPABILITY, ENTRYPOINT, registry=registry, environ={"GPT_PACK_ID": "c.third"}
        )


def test_a_blank_process_default_is_treated_as_unset() -> None:
    registry = registry_of(manifest("a.first"), manifest("b.second"))

    with pytest.raises(dispatch.CapabilityDispatchError, match="2 packs claim"):
        dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, registry=registry, environ={"GPT_PACK_ID": "  "})


def test_the_ambiguity_message_names_both_remedies() -> None:
    registry = registry_of(manifest("a.first"), manifest("b.second"))

    with pytest.raises(dispatch.CapabilityDispatchError) as excinfo:
        dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, registry=registry, environ={})

    message = str(excinfo.value)
    assert "--pack" in message
    assert "GPT_PACK_ID" in message


def test_a_single_claimant_needs_no_selector() -> None:
    registry = registry_of(manifest("only.one"))

    resolved = dispatch.resolve_capability_entrypoint(CAPABILITY, ENTRYPOINT, registry=registry, environ={})

    assert resolved.__name__ == "probe_account_liveness"


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

    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", lambda capability, entrypoint, **kwargs: marker)
    monkeypatch.setattr(
        account_commands,
        "quota_usage",
        lambda args, *, probe_fn=None: forwarded.update(probe_fn=probe_fn),
    )

    cli._quota_usage(quota_args())

    assert forwarded["probe_fn"] is marker


def test_the_cli_reports_a_missing_capability_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(capability: str, entrypoint: str, **kwargs: Any) -> Any:
        raise dispatch.CapabilityDispatchError("no enabled provider pack claims 'account.health'")

    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", unavailable)

    with pytest.raises(SystemExit) as excinfo:
        cli._quota_usage(quota_args())

    assert excinfo.value.code == 2


def test_the_cli_reports_a_broken_external_pack_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A discovered-but-unreadable manifest is a preflight failure, not a traceback."""
    from sms_tool.packs.contracts import PackManifestError

    def broken(capability: str, entrypoint: str, **kwargs: Any) -> Any:
        raise PackManifestError("cannot read provider manifest manifest.json: unexpected token")

    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", broken)

    with pytest.raises(SystemExit) as excinfo:
        cli._quota_usage(quota_args())

    assert excinfo.value.code == 2


# ---------------------------------------------------------------------------
# The selector reaches the CLI and the two batch workflows
# ---------------------------------------------------------------------------


def test_the_cli_forwards_the_selected_pack_to_dispatch(
    quota_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = object()
    seen: dict[str, Any] = {}

    def resolve(capability: str, entrypoint: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return marker

    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", resolve)
    monkeypatch.setattr(account_commands, "quota_usage", lambda args, *, probe_fn=None: seen.update(probe=probe_fn))

    cli._quota_usage(quota_args(pack="acme.portal"))

    assert seen["pack_id"] == "acme.portal"
    assert seen["probe"] is marker


def test_scan_accounts_threads_the_probe_into_every_account(monkeypatch: pytest.MonkeyPatch) -> None:
    from sms_tool.accounts import account_scan

    marker = object()
    seen: list[Any] = []

    def fake_scan_one(*args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs.get("probe_fn"))
        return {"index": kwargs.get("index", args[0] if args else 0), "ok": True, "scan_status": "ok"}

    monkeypatch.setattr(account_scan, "_scan_one_with_lane", fake_scan_one)

    account_scan.scan_accounts(["a@example.com"], workers=1, probe_fn=marker)

    assert seen == [marker]


def test_refresh_local_quota_statuses_threads_the_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    from sms_tool.accounts import recovery_batch

    marker = object()
    seen: list[Any] = []

    def fake_with_retries(*args: Any, **kwargs: Any) -> dict[str, Any]:
        seen.append(kwargs.get("probe_fn"))
        return {"ok": True, "status": "active", "quota_status": "可用", "status_code": 200}

    monkeypatch.setattr(recovery_batch, "_probe_liveness_with_retries", fake_with_retries)

    recovery_batch.refresh_local_quota_statuses(emails=["a@example.com"], workers=1, probe_fn=marker)

    # The injected callable is what reaches the retry helper, not the import.
    assert seen and seen[0] is marker


# ---------------------------------------------------------------------------
# Phase 2: the registration entry and the payment-link factory
# ---------------------------------------------------------------------------


def test_the_registration_entrypoint_is_the_object_the_cli_used_to_import() -> None:
    """Anti-drift: the manifest must name the same callable the CLI imported."""
    from sms_tool.registration import orchestrator

    resolved = dispatch.resolve_capability_entrypoint("account.registration.email", "register_email")

    assert resolved is orchestrator.run_email


def test_the_payment_link_entrypoint_resolves_to_the_shipped_generator() -> None:
    import sms_tool.gen_pp_link as gen_pp_link

    resolved = dispatch.resolve_capability_entrypoint("payment.link", "paypal_link")

    assert resolved is gen_pp_link.generate_pp_link


def test_the_cli_injects_the_payment_link_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wiring proof: without this the payment-link seam would have no caller."""
    from sms_tool.commands import payment_links

    marker = object()
    seen: dict[str, Any] = {}

    monkeypatch.setattr(
        payment_links,
        "generate_ba_link",
        lambda args, ctx, *, link_factory=None: seen.update(factory=link_factory),
    )
    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", lambda capability, entrypoint, **kw: marker)

    cli._generate_ba_link(types.SimpleNamespace(pack="acme.portal"))

    assert seen["factory"] is marker


def test_the_cli_reports_a_missing_payment_link_pack_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(capability: str, entrypoint: str, **kwargs: Any) -> Any:
        raise dispatch.CapabilityDispatchError("no enabled provider pack claims the capability")

    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", unavailable)

    with pytest.raises(SystemExit) as excinfo:
        cli._generate_ba_link(types.SimpleNamespace(pack="acme.portal"))

    assert excinfo.value.code == 2


def test_without_a_selected_pack_the_payment_link_seam_is_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No --pack means no injection: the payment lane keeps its own registry."""
    from sms_tool.commands import payment_links

    seen: dict[str, Any] = {}

    monkeypatch.setattr(
        payment_links,
        "generate_ba_link",
        lambda args, ctx, *, link_factory=None: seen.update(factory=link_factory),
    )

    cli._generate_ba_link(types.SimpleNamespace(pack=None))

    assert seen["factory"] is None


# ---------------------------------------------------------------------------
# Phase 2.5: the batch registration entry
# ---------------------------------------------------------------------------


def test_the_batch_entrypoint_resolves_to_the_runner_the_cli_calls() -> None:
    """Anti-drift: the manifest must name the object cli actually invokes."""
    from sms_tool import batch_runner

    resolved = dispatch.resolve_capability_entrypoint("account.registration.email", "register_batch_impl")

    assert resolved is batch_runner.run_batch_impl


def test_the_batch_entrypoint_is_not_the_orchestrator_facade() -> None:
    """The facade and the implementation are two objects; swapping them is silent."""
    from sms_tool import batch_runner
    from sms_tool.registration import orchestrator

    resolved = dispatch.resolve_capability_entrypoint("account.registration.email", "register_batch_impl")

    assert resolved is not orchestrator.run_batch
    assert resolved is batch_runner.run_batch_impl


def test_the_cli_resolves_the_batch_runner_through_the_pack(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = object()
    monkeypatch.setattr(cli, "_capability_entrypoint", lambda capability, entrypoint, pack_id=None: marker)
    monkeypatch.setattr(cli, "run_batch", None)
    monkeypatch.setattr(cli, "filter_registered_mailboxes", None)

    cli._load_batch_deps()

    assert cli.run_batch is marker


def test_a_missing_batch_capability_surfaces_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """The startup resolvers raise; only command paths turn this into exit 2."""

    def unavailable(capability: str, entrypoint: str, **kwargs: Any) -> Any:
        raise dispatch.CapabilityDispatchError("no enabled provider pack claims account.registration.email")

    monkeypatch.setattr(dispatch, "resolve_capability_entrypoint", unavailable)
    monkeypatch.setattr(cli, "run_batch", None)
    monkeypatch.setattr(cli, "filter_registered_mailboxes", None)

    with pytest.raises(dispatch.CapabilityDispatchError):
        cli._load_batch_deps()


# ---------------------------------------------------------------------------
# Phase 2.1 / 2.2: the two registration-lane capabilities
# ---------------------------------------------------------------------------


def test_the_access_token_probe_entrypoint_is_the_registration_object() -> None:
    from sms_tool.registration import orchestrator

    resolved = dispatch.resolve_capability_entrypoint("session.access_token", "access_token_probe")

    assert resolved is orchestrator._probe_registration_access_token


def test_the_mailbox_otp_entrypoint_is_the_router_object() -> None:
    from sms_tool.mailbox import router

    resolved = dispatch.resolve_capability_entrypoint("mailbox.otp", "poll_email_otp")

    assert resolved is router.poll_email_otp


def test_the_operations_bundle_takes_the_probe_from_the_pack() -> None:
    """2.1 wiring: the bundle the stages call holds the manifest's callable.

    It is the same object while one pack exists, but the manifest is what decides.
    A patch on the module attribute is read before the bundle is built, which is why
    ``tests/registration/test_registration_at_probe.py`` still sees its own double.
    """
    from sms_tool.registration import orchestrator

    bundle = orchestrator._email_registration_operations()

    assert bundle._probe_registration_access_token is orchestrator._probe_registration_access_token


def test_the_otp_poll_lazy_export_takes_the_callable_from_the_pack() -> None:
    """2.2 wiring: the registration facade resolves the poll through the manifest."""
    from sms_tool.mailbox import router
    from sms_tool.registration import orchestrator

    orchestrator.__dict__.pop("poll_email_otp", None)  # force the lazy path

    assert getattr(orchestrator, "poll_email_otp") is router.poll_email_otp


def test_an_unknown_entrypoint_name_is_a_named_error() -> None:
    """A capability with no such entrypoint must not silently resolve to something."""
    with pytest.raises(KeyError) as excinfo:
        dispatch.resolve_capability_entrypoint("mailbox.otp", "no_such_entrypoint")

    assert "no entrypoint" in str(excinfo.value)
