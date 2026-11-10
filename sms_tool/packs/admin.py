"""Read-only management surface over the pack registry.

This is what ``--pack-list``, ``--pack-info`` and ``--pack-verify`` call. It is
deliberately pure: every function takes a registry (or a pack) and returns plain
data, so the desktop host can render the same rows over IPC without the WPF layer
learning the manifest shape, and tests can drive it without a CLI.

``verify`` is the one operation that imports: answering "does this entrypoint
actually resolve" cannot be done from the manifest. It reports per-reference
results instead of raising, because a half-broken pack is exactly the state an
operator runs ``--pack-verify`` to discover.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import LIFECYCLE_HOOKS, PackManifestError, ProviderPack
from .registry import LegacyProviderPack, PackRegistry

#: Exceptions a failed resolution can raise. Anything outside this tuple is a
#: pack defect that should surface loudly instead of being reported as a tidy
#: per-entrypoint row.
RESOLUTION_ERRORS: tuple[type[BaseException], ...] = (
    AttributeError,
    ImportError,
    KeyError,
    PackManifestError,
    TypeError,
    ValueError,
)


def pack_rows(registry: PackRegistry) -> list[dict[str, Any]]:
    """One credential-free row per pack, sorted by id."""
    return [pack.manifest.summary() for pack in registry.list()]


def pack_configured_toggles(config: Any, pack_id: str) -> dict[str, Any]:
    """The leaves under this pack's own config namespace (``packs.<id>``).

    Every level is read through a ``Mapping`` guard, not a ``dict`` check: the
    sharded production config freezes each section into a ``mappingproxy``
    (``sms_tool/config.py::_freeze``), which is a ``Mapping`` but not a ``dict``, so a
    ``dict`` guard would report "nothing configured" in every real run while plain
    dict test fixtures stayed green -- the 2026-10-07 P1-D class.

    The pack id is used as **one key**, not as a dotted path: ids contain dots
    (``openai.chatgpt``), so splitting on ``.`` could not tell a section from a key.
    """
    packs_section = config.get("packs") if isinstance(config, Mapping) else None
    if not isinstance(packs_section, Mapping):
        return {}
    section = packs_section.get(pack_id)
    if not isinstance(section, Mapping):
        return {}
    return dict(sorted(section.items()))


def pack_detail(
    registry: PackRegistry, pack_id: str, *, config: Any = None, configured_toggles: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Full manifest view for one pack, including the references it declares.

    ``config`` makes the view truthful about what this architecture currently
    *configures*: ``--pack-info`` is how an operator sees a pack's own switches
    without running a registration, and ``packs.<id>`` is the namespace this
    function already reports (``detail["namespaces"]["config"]``). Pass ``None``
    when the caller is not looking at config at all -- that is different from a pack
    that configures nothing, which reports ``{}`` and is why the key is omitted
    rather than faked.

    ``configured_toggles`` is the direct-injection form, for a caller that resolved
    the section itself.
    """
    manifest = registry.get(pack_id).manifest
    detail = manifest.summary()
    detail.update(
        {
            "schema": manifest.schema,
            "endpoints": dict(sorted(manifest.endpoints.items())),
            "entrypoint_references": dict(sorted(manifest.entrypoints.items())),
            "hook_references": dict(sorted(manifest.hooks.items())),
            "risk_signals": [
                {
                    "code": signal.code,
                    "category": signal.category,
                    "retryable": signal.retryable,
                    "terminal": signal.terminal,
                }
                for signal in manifest.risk_signals
            ],
            "missing_hooks": [hook for hook in LIFECYCLE_HOOKS if hook not in manifest.hooks],
        }
    )
    if configured_toggles is not None:
        detail["configured_toggles"] = dict(sorted(configured_toggles.items()))
    elif config is not None:
        detail["configured_toggles"] = pack_configured_toggles(config, pack_id)
    return detail


def capability_matrix(registry: PackRegistry, *, only_enabled: bool = True) -> dict[str, list[str]]:
    """Capability -> the pack ids that claim it. Empty capabilities are omitted."""
    matrix: dict[str, list[str]] = {}
    for pack in registry.list():
        if only_enabled and not pack.manifest.enabled:
            continue
        for capability in sorted(pack.manifest.capabilities):
            matrix.setdefault(capability, []).append(pack.manifest.id)
    return dict(sorted(matrix.items()))


def verify_pack(pack: ProviderPack) -> dict[str, Any]:
    """Resolve every declared entrypoint and lifecycle hook.

    A ``LegacyProviderPack`` resolves by import. Any other implementation is
    assumed to resolve its own references; the row is reported as ``declared`` so
    the operator can tell "checked" from "not checkable from here".
    """
    rows: list[dict[str, Any]] = []
    failures: list[str] = []
    resolvable = isinstance(pack, LegacyProviderPack)

    for kind, references in (("entrypoint", pack.manifest.entrypoints), ("hook", pack.manifest.hooks)):
        for name in sorted(references):
            if not resolvable:
                rows.append({"kind": kind, "name": name, "reference": references[name], "status": "declared"})
                continue
            outcome = _resolve_row(pack, kind, name)
            rows.append(outcome)
            if outcome["status"] == "failed":
                failures.append(f"{kind} {name}: {outcome['error']}")

    return {
        "ok": not failures,
        "id": pack.manifest.id,
        "version": pack.manifest.version,
        "api_version": pack.manifest.api_version,
        "status": pack.manifest.status,
        "checked": resolvable,
        "references": rows,
        "failures": failures,
    }


def verify_registry(registry: PackRegistry, ids: Iterable[str] | None = None) -> dict[str, Any]:
    """Verify every pack (or the given subset) and roll the results up."""
    selected = tuple(registry.ids() if ids is None else ids)
    reports = [verify_pack(registry.get(pack_id)) for pack_id in selected]
    failed = [report["id"] for report in reports if not report["ok"]]
    return {"ok": not failed, "packs": len(reports), "failed": failed, "reports": reports}


def _resolve_row(pack: ProviderPack, kind: str, name: str) -> dict[str, Any]:
    reference = pack.manifest.entrypoints[name] if kind == "entrypoint" else pack.manifest.hooks[name]
    try:
        if kind == "entrypoint":
            target = pack.resolve_entrypoint(name)  # type: ignore[attr-defined]
        else:
            target = pack.resolve_hook(name)  # type: ignore[attr-defined]
    except RESOLUTION_ERRORS as exc:
        return {
            "kind": kind,
            "name": name,
            "reference": reference,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "kind": kind,
        "name": name,
        "reference": reference,
        "status": "ok",
        "resolved": getattr(target, "__qualname__", type(target).__name__),
    }
