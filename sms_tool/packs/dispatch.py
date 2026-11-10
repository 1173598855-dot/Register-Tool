"""Capability dispatch: map a capability name to the callable a workflow may run.

Why this exists
---------------
A manifest is declarative: it says pack ``openai.chatgpt`` *claims*
``account.health`` and exposes an ``account_liveness`` entrypoint. Nothing runs
until something asks "which pack owns this capability, and what does its
entrypoint resolve to". That question used to have no owner — every caller that
wanted it would have re-implemented "load the registry, filter by capability,
pick a pack, resolve the entrypoint", and each copy could disagree.

This module is that question, in one place.

Failure is explicit, never a fallback
-------------------------------------
There is no "if no pack claims it, import the old function". A silent fallback
would make a broken or disabled pack indistinguishable from a working one -- the
same defect class the registration lane paid for when a broad ``except`` turned a
``KeyError`` into a retried network failure. So:

* no pack claims the capability -> :class:`CapabilityDispatchError`
* more than one pack claims it and no ``pack_id`` was given -> error, because
  picking the first one by id order is a routing decision nobody made
* the named pack claims it but the entrypoint is missing -> :class:`KeyError`
  from the pack adapter, unchanged

Layering
--------
Standard library only at module scope, like the rest of this package. The
*resolution* imports the provider module (that is what a pack is for); the
decision to call it belongs to the caller that owns the workflow.
"""

from __future__ import annotations

from typing import Any

from .contracts import CAPABILITY_VOCABULARY
from .loader import load_registry
from .registry import PackRegistry


class CapabilityDispatchError(RuntimeError):
    """No pack can serve a capability that a workflow asked for."""


def resolve_capability_entrypoint(
    capability: str,
    entrypoint: str,
    *,
    pack_id: str | None = None,
    registry: PackRegistry | None = None,
) -> Any:
    """Resolve ``entrypoint`` on the enabled pack that claims ``capability``.

    ``registry`` is injectable so a caller (and a test) can dispatch against a
    registry it built itself instead of the discovered one.
    """
    if capability not in CAPABILITY_VOCABULARY and not capability.startswith("x-"):
        raise CapabilityDispatchError(
            f"unknown capability {capability!r}; the dispatch vocabulary is {sorted(CAPABILITY_VOCABULARY)}"
        )

    resolved_registry = load_registry() if registry is None else registry
    candidates = resolved_registry.choose(capability)
    if not candidates:
        enabled = ", ".join(resolved_registry.ids()) or "none"
        raise CapabilityDispatchError(
            f"no enabled provider pack claims {capability!r} (packs installed: {enabled}); "
            "check `python -m sms_tool --pack-list`"
        )

    selected = _select(capability, candidates, pack_id)
    return selected.resolve_entrypoint(entrypoint)


def capability_owner(
    capability: str,
    *,
    registry: PackRegistry | None = None,
) -> str:
    """The id of the enabled pack that claims ``capability`` (credential-free).

    Same selection rules as :func:`resolve_capability_entrypoint`; used by the
    management surface and by tests that need to assert *which* pack would run.
    """
    resolved_registry = load_registry() if registry is None else registry
    candidates = resolved_registry.choose(capability)
    if not candidates:
        raise CapabilityDispatchError(f"no enabled provider pack claims {capability!r}")
    return _select(capability, candidates, None).manifest.id


def _select(capability: str, candidates: tuple[Any, ...], pack_id: str | None) -> Any:
    if pack_id is not None:
        for pack in candidates:
            if pack.manifest.id == pack_id:
                return pack
        names = ", ".join(pack.manifest.id for pack in candidates)
        raise CapabilityDispatchError(f"pack {pack_id!r} does not claim {capability!r} (claimants: {names})")
    if len(candidates) == 1:
        return candidates[0]
    names = ", ".join(pack.manifest.id for pack in candidates)
    raise CapabilityDispatchError(
        f"{len(candidates)} packs claim {capability!r} ({names}); pass pack_id to choose one explicitly"
    )
