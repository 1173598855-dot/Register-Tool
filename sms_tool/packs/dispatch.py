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

import os
from collections.abc import Mapping
from typing import Any

from .contracts import CAPABILITY_VOCABULARY
from .loader import load_registry
from .registry import PackRegistry

#: Process-level default pack, for the case where several installed packs claim
#: the same capability. It lives in the environment rather than in a config shard
#: on purpose: it selects *which implementation runs in this process*, which is
#: the same class of value as ``GPT_REGISTER_CONFIG_DIR`` and ``GPT_PACK_PATH``,
#: and adding a config key would pull in the shard-ownership manifest and the C#
#: ``ConfigStore`` parity gate for a per-process choice. The CLI flag
#: ``--pack <id>`` overrides it.
DEFAULT_PACK_ENV = "GPT_PACK_ID"


class CapabilityDispatchError(RuntimeError):
    """No pack can serve a capability that a workflow asked for."""


def default_pack_id(environ: Mapping[str, str] | None = None) -> str | None:
    """The process-wide default pack id, or ``None`` when it is not set."""
    source = os.environ if environ is None else environ
    value = str(source.get(DEFAULT_PACK_ENV, "") or "").strip()
    return value or None


def resolve_capability_entrypoint(
    capability: str,
    entrypoint: str,
    *,
    pack_id: str | None = None,
    registry: PackRegistry | None = None,
    environ: Mapping[str, str] | None = None,
) -> Any:
    """Resolve ``entrypoint`` on the enabled pack that claims ``capability``.

    Both ``registry`` and ``environ`` are injectable so a caller (and a test) can
    dispatch against a registry and a default it controls itself.
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

    selected = _select(capability, candidates, pack_id, environ)
    return selected.resolve_entrypoint(entrypoint)


def capability_owner(
    capability: str,
    *,
    pack_id: str | None = None,
    registry: PackRegistry | None = None,
    environ: Mapping[str, str] | None = None,
) -> str:
    """The id of the enabled pack that would run ``capability`` (credential-free).

    Same selection rules as :func:`resolve_capability_entrypoint`; used by the
    management surface and by tests that need to assert *which* pack would run.
    """
    resolved_registry = load_registry() if registry is None else registry
    candidates = resolved_registry.choose(capability)
    if not candidates:
        raise CapabilityDispatchError(f"no enabled provider pack claims {capability!r}")
    return _select(capability, candidates, pack_id, environ).manifest.id


def _select(
    capability: str,
    candidates: tuple[Any, ...],
    pack_id: str | None,
    environ: Mapping[str, str] | None = None,
) -> Any:
    """Pick the claimant: explicit flag, then the process default, then the only one.

    A single claimant needs no selector; anything else is a routing decision, so
    it is never made silently by id order.
    """
    if pack_id is None:
        pack_id = default_pack_id(environ)
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
        f"{len(candidates)} packs claim {capability!r} ({names}); "
        f"pass --pack <id>, set {DEFAULT_PACK_ENV}, or name the pack explicitly in code"
    )
