"""Provider-neutral metadata contracts for independently maintained packs.

A *pack* is one registration architecture: the endpoints it talks to, the
entrypoints it exposes, the capabilities it claims, the failure vocabulary it
raises, and the lifecycle hooks an operator runs to verify, diagnose, migrate or
upgrade it. The core never imports a pack's implementation through this module —
every reference is a string that :mod:`sms_tool.packs.registry` resolves lazily.

Two properties make the packs package the place to put this:

* **It is a leaf.** Module-scope imports here are standard library only, because
  a pack depends *on* the contract and inverting that would create the cycle the
  boundary rules forbid. ``scripts/pack_boundary_ratchet.py`` enforces it.
* **Namespaces are derived, not declared.** A pack cannot collide with another
  pack's config keys, storage directory or telemetry prefix because all three are
  computed from the pack id (:class:`PackNamespaces`). There is nothing to get
  wrong and no validation surface to drift.

The manifest schema is versioned. ``provider-pack.v1`` (ADR-0014) is still
accepted and normalised onto the same immutable object, so a pack written before
the platform existed keeps working rather than being rejected by a newer core.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol
from urllib.parse import urlparse

#: Manifest API this core implements. A pack declares the one it was written
#: against; the loader refuses anything it does not know rather than guessing.
CORE_API_VERSION = "1"
SUPPORTED_API_VERSIONS: frozenset[str] = frozenset({CORE_API_VERSION})

#: ``disabled`` packs stay discoverable (so ``--pack-info`` can explain them) but
#: are never resolved by a workflow.
PACK_STATUSES: frozenset[str] = frozenset({"active", "experimental", "deprecated", "disabled"})

#: Operator-facing lifecycle channels. A pack may implement any subset; the
#: management surface reports which ones exist instead of assuming all four.
LIFECYCLE_HOOKS: tuple[str, ...] = ("verify", "doctor", "migrate", "upgrade")

#: The closed capability vocabulary. A pack may only claim what the core knows
#: how to dispatch; anything genuinely new needs a core release, which is what
#: keeps ``capabilities`` from becoming a free-text field nobody can query.
CAPABILITY_VOCABULARY: frozenset[str] = frozenset(
    {
        "account.export",
        "account.health",
        "account.login",
        "account.registration.email",
        "account.registration.phone",
        "mailbox.otp",
        "payment.batch",
        "payment.link",
        "session.access_token",
    }
)

#: Escape hatch for a pack experimenting with its own capability names. The
#: prefix keeps vendor extensions out of the core vocabulary while still letting
#: ``--pack-list`` show them.
EXTENSION_CAPABILITY_PREFIX = "x-"

_PACK_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_ENTRYPOINT = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


class PackManifestError(ValueError):
    """A provider-pack manifest is malformed or internally inconsistent."""


@dataclass(frozen=True)
class PackNamespaces:
    """Per-pack key spaces, derived from the id so two packs cannot collide.

    ``config`` is the key root a pack's settings live under, ``storage`` the
    runtime directory it may write to, and ``telemetry`` the prefix its events
    and logs carry. Deriving all three is the reserved-channel mechanism: a new
    pack gets an isolated namespace for free and cannot accidentally read or
    overwrite another pack's state.
    """

    config: str
    storage: str
    telemetry: str

    @classmethod
    def for_pack(cls, pack_id: str) -> PackNamespaces:
        return cls(
            config=f"packs.{pack_id}",
            storage=f"packs/{pack_id}",
            telemetry=f"pack.{pack_id}",
        )


@dataclass(frozen=True)
class RiskSignal:
    """Provider-neutral classification metadata; does not implement retry policy.

    Retry and bypass decisions stay with ``registration/policy`` and
    ``failure_registry``. A pack only says *what it can observe* (this response
    means the account was deactivated), never what the core should do about it.
    """

    code: str
    category: str
    retryable: bool
    terminal: bool

    @classmethod
    def from_mapping(cls, raw: object) -> RiskSignal:
        if not isinstance(raw, Mapping):
            raise PackManifestError("risk signal must be an object")
        code = _required_text(raw, "code")
        category = _required_text(raw, "category")
        if not _IDENTIFIER.fullmatch(code) or not _IDENTIFIER.fullmatch(category):
            raise PackManifestError("risk signal code and category must be identifiers")
        retryable = raw.get("retryable")
        terminal = raw.get("terminal")
        if not isinstance(retryable, bool) or not isinstance(terminal, bool):
            raise PackManifestError(f"risk signal {code!r} requires boolean retryable and terminal fields")
        if retryable and terminal:
            raise PackManifestError(f"risk signal {code!r} cannot be both retryable and terminal")
        return cls(code=code, category=category, retryable=retryable, terminal=terminal)


@dataclass(frozen=True)
class PackManifest:
    """Validated, immutable declaration of a provider pack's public surface."""

    schema: str
    id: str
    display_name: str
    version: str
    api_version: str
    status: str
    capabilities: frozenset[str]
    endpoints: Mapping[str, str]
    entrypoints: Mapping[str, str]
    hooks: Mapping[str, str]
    risk_signals: tuple[RiskSignal, ...]
    namespaces: PackNamespaces

    @classmethod
    def from_mapping(cls, raw: object) -> PackManifest:
        if not isinstance(raw, Mapping):
            raise PackManifestError("manifest must be a JSON object")

        schema = _required_text(raw, "schema")
        if schema not in {"provider-pack.v1", "provider-pack.v2"}:
            raise PackManifestError(f"unsupported manifest schema: {schema!r}")

        pack_id = _required_text(raw, "id")
        if not _PACK_ID.fullmatch(pack_id):
            raise PackManifestError("id must be a lowercase dotted or dashed identifier")

        display_name = _required_text(raw, "display_name")
        version = _required_text(raw, "version")
        if not _VERSION.fullmatch(version):
            raise PackManifestError("version must use semantic version form MAJOR.MINOR.PATCH")

        capabilities = _parse_capabilities(raw.get("capabilities"))
        api_version = _parse_api_version(raw.get("api_version"), schema)
        status = _parse_status(raw.get("status"), schema)
        endpoints = _parse_endpoints(raw.get("endpoints"))
        entrypoints = _parse_entrypoints(raw.get("entrypoints"), "entrypoints")
        hooks = _parse_entrypoints(raw.get("hooks") or {}, "hooks", allowed_keys=LIFECYCLE_HOOKS)
        risk_signals = _parse_risk_signals(raw.get("risk_signals", []))

        return cls(
            schema=schema,
            id=pack_id,
            display_name=display_name,
            version=version,
            api_version=api_version,
            status=status,
            capabilities=capabilities,
            endpoints=MappingProxyType(endpoints),
            entrypoints=MappingProxyType(entrypoints),
            hooks=MappingProxyType(hooks),
            risk_signals=risk_signals,
            namespaces=PackNamespaces.for_pack(pack_id),
        )

    @property
    def enabled(self) -> bool:
        """Whether a workflow may resolve this pack. ``disabled`` is the off switch."""
        return self.status != "disabled"

    def summary(self) -> dict[str, Any]:
        """Credential-free row for the management surface."""
        return {
            "id": self.id,
            "display_name": self.display_name,
            "version": self.version,
            "api_version": self.api_version,
            "status": self.status,
            "enabled": self.enabled,
            "capabilities": sorted(self.capabilities),
            "entrypoints": sorted(self.entrypoints),
            "hooks": sorted(self.hooks),
            "risk_signals": len(self.risk_signals),
            "namespaces": {
                "config": self.namespaces.config,
                "storage": self.namespaces.storage,
                "telemetry": self.namespaces.telemetry,
            },
        }


class ProviderPack(Protocol):
    """Runtime seam consumed by pack-aware application workflows."""

    @property
    def manifest(self) -> PackManifest: ...

    def resolve_entrypoint(self, name: str) -> Any: ...


def _required_text(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PackManifestError(f"{key} must be a non-empty string")
    return value.strip()


def _identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise PackManifestError(f"{label} must be a lowercase identifier")
    return value


def _parse_capabilities(raw: object) -> frozenset[str]:
    if not isinstance(raw, list) or not raw:
        raise PackManifestError("capabilities must be a non-empty array")
    names = [_identifier(value, "capability") for value in raw]
    if len(names) != len(set(names)):
        raise PackManifestError("capabilities must not contain duplicates")
    unknown = [
        name for name in names if name not in CAPABILITY_VOCABULARY and not name.startswith(EXTENSION_CAPABILITY_PREFIX)
    ]
    if unknown:
        raise PackManifestError(
            "unknown capability name(s) "
            + ", ".join(sorted(unknown))
            + f"; the core dispatch vocabulary is fixed, and a genuinely new capability needs a core release"
        )
    return frozenset(names)


def _parse_api_version(raw: object, schema: str) -> str:
    if raw is None:
        # v1 manifests predate the field; they were written against API 1.
        if schema == "provider-pack.v1":
            return CORE_API_VERSION
        raise PackManifestError("api_version is required for provider-pack.v2")
    if not isinstance(raw, str) or raw not in SUPPORTED_API_VERSIONS:
        raise PackManifestError(
            f"api_version {raw!r} is not supported; this core implements {sorted(SUPPORTED_API_VERSIONS)}"
        )
    return raw


def _parse_status(raw: object, schema: str) -> str:
    if raw is None:
        if schema == "provider-pack.v1":
            return "active"
        raise PackManifestError("status is required for provider-pack.v2")
    if not isinstance(raw, str) or raw not in PACK_STATUSES:
        raise PackManifestError(f"status {raw!r} must be one of {sorted(PACK_STATUSES)}")
    return raw


def _parse_endpoints(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping) or not raw:
        raise PackManifestError("endpoints must be a non-empty object")
    endpoints: dict[str, str] = {}
    for name, value in raw.items():
        endpoint_name = _identifier(name, "endpoint name")
        if not isinstance(value, str):
            raise PackManifestError(f"endpoint {endpoint_name!r} must be a URL string")
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise PackManifestError(f"endpoint {endpoint_name!r} must be an HTTPS URL without credentials")
        endpoints[endpoint_name] = value
    return endpoints


def _parse_entrypoints(
    raw: object,
    label: str,
    *,
    allowed_keys: tuple[str, ...] | None = None,
) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise PackManifestError(f"{label} must be an object")
    if not raw and allowed_keys is None:
        raise PackManifestError(f"{label} must be a non-empty object")
    parsed: dict[str, str] = {}
    for name, value in raw.items():
        entry_name = _identifier(name, f"{label} name")
        if allowed_keys is not None and entry_name not in allowed_keys:
            raise PackManifestError(f"{label} key {entry_name!r} must be one of {list(allowed_keys)}")
        if not isinstance(value, str) or not _ENTRYPOINT.fullmatch(value):
            raise PackManifestError(f"{label} {entry_name!r} must use module.path:attribute form")
        parsed[entry_name] = value
    return parsed


def _parse_risk_signals(raw: object) -> tuple[RiskSignal, ...]:
    if not isinstance(raw, list):
        raise PackManifestError("risk_signals must be an array")
    signals = tuple(RiskSignal.from_mapping(item) for item in raw)
    codes = [signal.code for signal in signals]
    if len(codes) != len(set(codes)):
        raise PackManifestError("risk signal codes must be unique within a pack")
    return signals
