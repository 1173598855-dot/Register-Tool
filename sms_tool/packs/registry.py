"""Explicit provider-pack registry with lazy legacy entrypoint resolution.

Discovery lives in :mod:`sms_tool.packs.loader`; this module only owns the
catalog and the adapter that turns a declared ``module.path:attribute`` string
into a callable. Registering or listing a pack never imports its implementation,
which is what lets the management surface describe an uninstalled or broken pack
without the core paying for it.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .contracts import PackManifest, PackManifestError, ProviderPack


@dataclass(frozen=True)
class LegacyProviderPack:
    """Adapt existing functions to the pack seam without moving or invoking them.

    This is the migration adapter: a pack can describe today's ChatGPT modules
    in a manifest while the implementation keeps living in its current home. The
    indirection is one string resolution, so the eventual move is a manifest edit
    rather than a caller rewrite.
    """

    manifest: PackManifest

    def resolve_entrypoint(self, name: str) -> Any:
        """Import one declared entrypoint only when something asks for it."""
        try:
            reference = self.manifest.entrypoints[name]
        except KeyError as exc:
            raise KeyError(f"pack {self.manifest.id!r} has no entrypoint {name!r}") from exc
        return _resolve_reference(reference, f"entrypoint {name!r} in pack {self.manifest.id!r}")

    def resolve_hook(self, name: str) -> Any:
        """Resolve a lifecycle hook; a pack declares only the ones it implements."""
        try:
            reference = self.manifest.hooks[name]
        except KeyError as exc:
            raise KeyError(f"pack {self.manifest.id!r} does not implement the {name!r} hook") from exc
        return _resolve_reference(reference, f"hook {name!r} in pack {self.manifest.id!r}")


def _resolve_reference(reference: str, label: str) -> Any:
    module_name, attribute_path = reference.split(":", maxsplit=1)
    value: Any = importlib.import_module(module_name)
    for attribute in attribute_path.split("."):
        value = getattr(value, attribute)
    if not callable(value):
        raise PackManifestError(f"{label} is not callable")
    return value


class PackRegistry:
    """In-memory pack catalog. One id, one pack, no silent replacement."""

    def __init__(self, packs: Iterable[ProviderPack] = ()) -> None:
        self._packs: dict[str, ProviderPack] = {}
        for pack in packs:
            self.register(pack)

    def register(self, pack: ProviderPack) -> None:
        pack_id = pack.manifest.id
        if pack_id in self._packs:
            raise PackManifestError(f"duplicate provider pack id: {pack_id}")
        self._packs[pack_id] = pack

    def get(self, pack_id: str) -> ProviderPack:
        try:
            return self._packs[pack_id]
        except KeyError as exc:
            raise KeyError(f"unknown provider pack: {pack_id}") from exc

    def list(self) -> tuple[ProviderPack, ...]:
        return tuple(self._packs[key] for key in sorted(self._packs))

    def ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._packs))

    def choose(self, capability: str, *, only_enabled: bool = True) -> tuple[ProviderPack, ...]:
        """Packs claiming ``capability``, in id order.

        The caller decides what to do with more than one candidate; this only
        answers the vocabulary question so no caller re-implements the filter.
        """
        return tuple(
            pack
            for pack in self.list()
            if capability in pack.manifest.capabilities and (pack.manifest.enabled or not only_enabled)
        )
