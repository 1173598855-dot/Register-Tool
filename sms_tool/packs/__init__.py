"""Provider-pack platform: contracts, discovery, registry and management.

This package is the seam that lets one repository host several registration
architectures without any of them reaching into the others. A pack declares its
endpoints, entrypoints, capabilities, risk vocabulary and lifecycle hooks in a
manifest; the core resolves those references lazily and gives every pack its own
config, storage and telemetry namespace.

The package is **standard-library only** at module scope by design: a pack
depends on the contract, so importing the application from here would invert the
dependency the boundary rules exist to keep. ``scripts/pack_boundary_ratchet.py``
enforces that, and ``docs/current/provider-packs.md`` documents the operator
surface.

Typical use::

    from sms_tool.packs import load_registry, capability_matrix

    registry = load_registry()
    registry.choose("account.registration.email")
    capability_matrix(registry)
"""

from .admin import capability_matrix, pack_detail, pack_rows, verify_pack, verify_registry
from .dispatch import CapabilityDispatchError, capability_owner, resolve_capability_entrypoint
from .contracts import (
    CAPABILITY_VOCABULARY,
    CORE_API_VERSION,
    EXTENSION_CAPABILITY_PREFIX,
    LIFECYCLE_HOOKS,
    PACK_STATUSES,
    SUPPORTED_API_VERSIONS,
    PackManifest,
    PackManifestError,
    PackNamespaces,
    ProviderPack,
    RiskSignal,
)
from .loader import (
    BUILTIN_PACK_DIR,
    EXTERNAL_PACK_PATH_ENV,
    MANIFEST_FILENAME,
    discover_manifest_paths,
    external_pack_roots,
    load_builtin_registry,
    load_manifest,
    load_registry,
)
from .registry import LegacyProviderPack, PackRegistry

__all__ = [
    "BUILTIN_PACK_DIR",
    "CAPABILITY_VOCABULARY",
    "CORE_API_VERSION",
    "CapabilityDispatchError",
    "EXTERNAL_PACK_PATH_ENV",
    "EXTENSION_CAPABILITY_PREFIX",
    "LIFECYCLE_HOOKS",
    "LegacyProviderPack",
    "MANIFEST_FILENAME",
    "PACK_STATUSES",
    "PackManifest",
    "PackManifestError",
    "PackNamespaces",
    "PackRegistry",
    "ProviderPack",
    "RiskSignal",
    "SUPPORTED_API_VERSIONS",
    "capability_matrix",
    "capability_owner",
    "discover_manifest_paths",
    "external_pack_roots",
    "load_builtin_registry",
    "load_manifest",
    "load_registry",
    "pack_detail",
    "pack_rows",
    "resolve_capability_entrypoint",
    "verify_pack",
    "verify_registry",
]
