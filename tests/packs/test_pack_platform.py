"""Contract tests for the provider-pack platform.

A pack is one registration architecture: its manifest declares the endpoints,
entrypoints, capabilities, risk vocabulary and lifecycle hooks the core may use,
and the core resolves those references lazily. These tests pin the parts that
make that safe:

* the manifest is validated on the way in, so a wrong capability name or a
  plaintext-credential endpoint fails at load time rather than at registration
  time;
* ``provider-pack.v1`` manifests keep working (ADR-0014 wrote them), so the
  platform addition does not invalidate an existing pack;
* every pack gets its own config/storage/telemetry namespace, derived from the
  id, so two architectures cannot collide;
* discovery accepts an operator-controlled external root, and a duplicate id or
  an unsupported ``api_version`` is a hard failure rather than a silent skip.
"""

from __future__ import annotations

import json
import types
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any, cast

import pytest

from sms_tool.packs import (
    CAPABILITY_VOCABULARY,
    CORE_API_VERSION,
    LIFECYCLE_HOOKS,
    LegacyProviderPack,
    PackManifest,
    PackManifestError,
    PackRegistry,
    admin,
    loader,
)

V2_FIELDS: dict[str, Any] = {
    "schema": "provider-pack.v2",
    "id": "test.example",
    "display_name": "Example",
    "version": "1.0.0",
    "api_version": CORE_API_VERSION,
    "status": "active",
    "capabilities": ["account.health"],
    "endpoints": {"api": "https://example.test"},
    "entrypoints": {"health": "test_provider:health"},
    "hooks": {},
    "risk_signals": [],
}


def manifest_payload(**overrides: Any) -> dict[str, Any]:
    payload = dict(V2_FIELDS)
    payload.update(overrides)
    return payload


def v1_payload() -> dict[str, Any]:
    """A manifest as ADR-0014 wrote it: no api_version, no status, no hooks."""
    return {
        "schema": "provider-pack.v1",
        "id": "test.legacy",
        "display_name": "Legacy",
        "version": "1.0.0",
        "capabilities": ["account.health"],
        "endpoints": {"api": "https://legacy.test"},
        "entrypoints": {"health": "test_provider:health"},
        "risk_signals": [],
    }


# ---------------------------------------------------------------------------
# Manifest validation
# ---------------------------------------------------------------------------


def test_v1_manifest_is_normalised_onto_the_current_contract() -> None:
    manifest = PackManifest.from_mapping(v1_payload())

    assert manifest.api_version == CORE_API_VERSION
    assert manifest.status == "active"
    assert dict(manifest.hooks) == {}
    assert manifest.enabled is True


def test_v2_requires_api_version_and_status() -> None:
    with pytest.raises(PackManifestError, match="api_version is required"):
        PackManifest.from_mapping({key: value for key, value in manifest_payload().items() if key != "api_version"})
    with pytest.raises(PackManifestError, match="status is required"):
        PackManifest.from_mapping({key: value for key, value in manifest_payload().items() if key != "status"})


def test_an_unsupported_api_version_is_rejected() -> None:
    with pytest.raises(PackManifestError, match="not supported"):
        PackManifest.from_mapping(manifest_payload(api_version="99"))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "Bad ID", "lowercase dotted or dashed"),
        ("version", "latest", "semantic version"),
        ("endpoints", {"api": "http://example.test"}, "HTTPS URL"),
        ("endpoints", {"api": "https://user:pass@example.test"}, "without credentials"),
        ("entrypoints", {"health": "not-a-reference"}, "module.path:attribute"),
        ("status", "retired", "must be one of"),
    ],
)
def test_invalid_contract_fields_are_rejected(field: str, value: object, message: str) -> None:
    with pytest.raises(PackManifestError, match=message):
        PackManifest.from_mapping(manifest_payload(**{field: value}))


def test_capabilities_must_come_from_the_core_vocabulary() -> None:
    with pytest.raises(PackManifestError, match="unknown capability name"):
        PackManifest.from_mapping(manifest_payload(capabilities=["account.registration.telepathy"]))


def test_a_prefixed_namespaced_capability_is_allowed_as_an_extension() -> None:
    manifest = PackManifest.from_mapping(manifest_payload(capabilities=["x-acme.widgets"]))

    assert "x-acme.widgets" in manifest.capabilities
    assert "x-acme.widgets" not in CAPABILITY_VOCABULARY


def test_hooks_are_limited_to_the_lifecycle_channels() -> None:
    with pytest.raises(PackManifestError, match="must be one of"):
        PackManifest.from_mapping(manifest_payload(hooks={"teleport": "test_provider:health"}))

    manifest = PackManifest.from_mapping(manifest_payload(hooks={"verify": "test_provider:health"}))
    assert dict(manifest.hooks) == {"verify": "test_provider:health"}
    assert set(LIFECYCLE_HOOKS) >= set(manifest.hooks)


def test_risk_signals_cannot_contradict_or_repeat() -> None:
    contradictory = [{"code": "blocked", "category": "network", "retryable": True, "terminal": True}]
    with pytest.raises(PackManifestError, match="both retryable and terminal"):
        PackManifest.from_mapping(manifest_payload(risk_signals=contradictory))

    duplicated = [
        {"code": "blocked", "category": "network", "retryable": True, "terminal": False},
        {"code": "blocked", "category": "account", "retryable": False, "terminal": True},
    ]
    with pytest.raises(PackManifestError, match="codes must be unique"):
        PackManifest.from_mapping(manifest_payload(risk_signals=duplicated))


def test_manifest_collections_are_immutable() -> None:
    manifest = PackManifest.from_mapping(manifest_payload())

    with pytest.raises(AttributeError):
        getattr(manifest.capabilities, "add")("account.health")
    with pytest.raises(TypeError):
        cast(MutableMapping[str, str], manifest.endpoints)["api"] = "https://other.test"


def test_namespaces_are_derived_from_the_id_so_packs_cannot_collide() -> None:
    first = PackManifest.from_mapping(manifest_payload(id="a.one"))
    second = PackManifest.from_mapping(manifest_payload(id="b.two"))

    assert first.namespaces.config == "packs.a.one"
    assert first.namespaces.storage == "packs/a.one"
    assert first.namespaces.telemetry == "pack.a.one"
    assert {first.namespaces.config, first.namespaces.storage, first.namespaces.telemetry}.isdisjoint(
        {second.namespaces.config, second.namespaces.storage, second.namespaces.telemetry}
    )


def test_a_disabled_pack_reports_itself_as_not_enabled() -> None:
    manifest = PackManifest.from_mapping(manifest_payload(status="disabled"))

    assert manifest.enabled is False


# ---------------------------------------------------------------------------
# Registry and lazy resolution
# ---------------------------------------------------------------------------


def test_legacy_adapter_imports_only_when_a_reference_is_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    fake_module = types.ModuleType("test_provider")
    setattr(fake_module, "health", lambda: calls.append("called") or "healthy")
    monkeypatch.setitem(__import__("sys").modules, "test_provider", fake_module)
    pack = LegacyProviderPack(PackManifest.from_mapping(manifest_payload()))

    assert calls == []
    assert pack.resolve_entrypoint("health")() == "healthy"
    assert calls == ["called"]


def test_resolving_an_undeclared_entrypoint_or_hook_names_the_pack() -> None:
    pack = LegacyProviderPack(PackManifest.from_mapping(manifest_payload()))

    with pytest.raises(KeyError, match="has no entrypoint"):
        pack.resolve_entrypoint("register")
    with pytest.raises(KeyError, match="does not implement the 'migrate' hook"):
        pack.resolve_hook("migrate")


def test_registry_rejects_duplicate_ids_and_reports_unknown_ids() -> None:
    pack = LegacyProviderPack(PackManifest.from_mapping(manifest_payload()))
    registry = PackRegistry([pack])

    with pytest.raises(PackManifestError, match="duplicate provider pack id"):
        registry.register(pack)
    with pytest.raises(KeyError, match="unknown provider pack"):
        registry.get("missing.pack")


def test_choose_filters_by_capability_and_skips_disabled_packs() -> None:
    active = LegacyProviderPack(PackManifest.from_mapping(manifest_payload(id="a.active")))
    disabled = LegacyProviderPack(PackManifest.from_mapping(manifest_payload(id="b.disabled", status="disabled")))
    registry = PackRegistry([active, disabled])

    assert [pack.manifest.id for pack in registry.choose("account.health")] == ["a.active"]
    assert len(registry.choose("account.health", only_enabled=False)) == 2
    assert registry.choose("payment.link") == ()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def write_pack(root: Path, directory: str, payload: dict[str, Any]) -> Path:
    pack_dir = root / directory
    pack_dir.mkdir(parents=True, exist_ok=True)
    target = pack_dir / loader.MANIFEST_FILENAME
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_external_pack_roots_split_on_the_platform_separator() -> None:
    import os

    roots = loader.external_pack_roots({"GPT_PACK_PATH": f"a{os.pathsep}b{os.pathsep}"})

    assert [path.name for path in roots] == ["a", "b"]


def test_discovery_ignores_directories_without_a_manifest(tmp_path: Path) -> None:
    write_pack(tmp_path, "one", manifest_payload(id="one.pack"))
    (tmp_path / "scratch").mkdir()

    registry = loader.load_registry(roots=(tmp_path,))

    # The builtin packs are always searched, so this asserts the extra root is
    # picked up *in addition* rather than instead.
    assert "one.pack" in registry.ids()
    assert "openai.chatgpt" in registry.ids()


def test_discovery_loads_several_roots_and_names_the_duplicate(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_pack(first, "one", manifest_payload(id="one.pack"))
    write_pack(second, "one", manifest_payload(id="one.pack"))

    with pytest.raises(PackManifestError, match="duplicate provider pack id"):
        loader.load_registry(roots=(first, second))


def test_loader_refuses_an_unsupported_api_version(tmp_path: Path) -> None:
    write_pack(tmp_path, "future", manifest_payload(id="future.pack", api_version="99"))

    with pytest.raises(PackManifestError, match="not supported"):
        loader.load_registry(roots=(tmp_path,))


def test_a_malformed_manifest_names_the_file(tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / loader.MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")

    with pytest.raises(PackManifestError, match="cannot read provider manifest"):
        loader.load_registry(roots=(tmp_path,))


# ---------------------------------------------------------------------------
# Management surface
# ---------------------------------------------------------------------------


def test_admin_rows_detail_and_capability_matrix_are_credential_free() -> None:
    registry = PackRegistry(
        [
            LegacyProviderPack(PackManifest.from_mapping(manifest_payload(id="a.one"))),
            LegacyProviderPack(
                PackManifest.from_mapping(manifest_payload(id="b.two", capabilities=["account.health", "payment.link"]))
            ),
        ]
    )

    rows = admin.pack_rows(registry)
    detail = admin.pack_detail(registry, "a.one")
    matrix = admin.capability_matrix(registry)

    assert [row["id"] for row in rows] == ["a.one", "b.two"]
    assert detail["namespaces"]["config"] == "packs.a.one"
    assert detail["entrypoint_references"] == {"health": "test_provider:health"}
    assert matrix["payment.link"] == ["b.two"]
    assert "cookies" not in json.dumps(rows).lower()


def test_verify_reports_a_broken_reference_instead_of_raising() -> None:
    pack = LegacyProviderPack(PackManifest.from_mapping(manifest_payload(entrypoints={"health": "json:absent"})))

    report = admin.verify_pack(pack)

    assert report["ok"] is False
    assert report["checked"] is True
    assert report["failures"] and "AttributeError" in report["failures"][0]
    assert report["references"][0]["status"] == "failed"


def test_verify_registry_rolls_up_failures() -> None:
    registry = PackRegistry(
        [
            LegacyProviderPack(
                PackManifest.from_mapping(manifest_payload(id="good.pack", entrypoints={"health": "json:dumps"}))
            ),
            LegacyProviderPack(
                PackManifest.from_mapping(manifest_payload(id="bad.pack", entrypoints={"health": "json:absent"}))
            ),
        ]
    )

    report = admin.verify_registry(registry)

    assert report["ok"] is False
    assert report["failed"] == ["bad.pack"]
    assert report["packs"] == 2
