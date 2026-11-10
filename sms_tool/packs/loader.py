"""Pack discovery: bundled packs plus an operator-controlled external channel.

Two sources, in this order:

1. ``sms_tool/packs/builtin/<id>/manifest.json`` — packs shipped with the core.
2. Every directory in ``GPT_PACK_PATH`` (``;``-separated on Windows) — the
   reserved channel for a pack that is developed, patched or upgraded outside
   this repository. Nothing else about the core changes to support it.

A directory only becomes a pack if it contains ``manifest.json``; anything else
is ignored so a scratch directory in the search path is not an error. Duplicate
ids and unsupported ``api_version`` values are hard failures: a pack that the
core cannot dispatch must not be half-registered.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path

from .contracts import PackManifest, PackManifestError
from .registry import LegacyProviderPack, PackRegistry

#: Environment variable holding extra pack roots. The separator is the platform's
#: ``os.pathsep`` so the same value works from PowerShell and CI.
EXTERNAL_PACK_PATH_ENV = "GPT_PACK_PATH"

MANIFEST_FILENAME = "manifest.json"

BUILTIN_PACK_DIR = Path(__file__).with_name("builtin")


def load_manifest(path: str | Path) -> PackManifest:
    """Read and validate one JSON manifest.

    Decoded as ``utf-8-sig`` rather than ``utf-8``: a manifest is an
    operator-editable data file, and on Windows both Notepad's "UTF-8 with BOM"
    and PowerShell 5.1's ``Set-Content -Encoding utf8`` prepend an ``EF BB BF``
    that ``utf-8`` rejects with "Unexpected UTF-8 BOM". The JSON is valid and only
    the prefix is not, so refusing it would reject a correctly written pack for a
    reason the message cannot make obvious. BOM-less files decode identically.
    """
    manifest_path = Path(path)
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PackManifestError(f"cannot read provider manifest {manifest_path.name}: {exc}") from exc
    manifest = PackManifest.from_mapping(raw)
    return manifest


def external_pack_roots(environ: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Resolve the external pack roots, ignoring empty entries."""
    source = os.environ if environ is None else environ
    raw = str(source.get(EXTERNAL_PACK_PATH_ENV, "") or "")
    return tuple(Path(part) for part in raw.split(os.pathsep) if part.strip())


def discover_manifest_paths(roots: Iterable[Path] | None = None) -> tuple[Path, ...]:
    """Every ``manifest.json`` under the builtin dir plus the given roots.

    The builtin directory is always searched: a release build must never fail to
    see the packs it ships just because the operator set ``GPT_PACK_PATH``.
    """
    search: list[Path] = [BUILTIN_PACK_DIR]
    search.extend(external_pack_roots() if roots is None else roots)
    found: list[Path] = []
    for root in search:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            candidate = child / MANIFEST_FILENAME
            if child.is_dir() and candidate.is_file():
                found.append(candidate)
    return tuple(found)


def load_registry(roots: Iterable[Path] | None = None) -> PackRegistry:
    """Load every discoverable pack into a registry.

    Manifests are validated before any registry is built, so a broken pack fails
    the whole load with the offending file named instead of silently vanishing.
    """
    packs = [LegacyProviderPack(load_manifest(path)) for path in discover_manifest_paths(roots)]
    seen: dict[str, Path] = {}
    for path, pack in zip(discover_manifest_paths(roots), packs):
        if pack.manifest.id in seen:
            raise PackManifestError(
                f"duplicate provider pack id {pack.manifest.id!r}: {seen[pack.manifest.id]} and {path}"
            )
        seen[pack.manifest.id] = path
    return PackRegistry(packs)


def load_builtin_registry() -> PackRegistry:
    """Bundled packs only — the source a release build ships."""
    return load_registry(roots=())
