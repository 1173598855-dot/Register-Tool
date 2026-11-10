"""Scaffold a new registration architecture as an independent provider pack.

One command produces everything that architecture needs in order to be
maintained, managed and upgraded on its own:

```text
sms_tool/platforms/<short>/__init__.py      implementation namespace
sms_tool/platforms/<short>/flow.py           the entry points the manifest names
sms_tool/packs/builtin/<short>/manifest.json endpoints, capabilities, hooks
tests/packs/test_<short>_pack.py            its own contract test
docs/packs/<id>.md                          its own operator/maintenance notes
```

Nothing in the core changes, and one pack cannot import another: the manifest
references implementation by ``module.path:attribute`` and
``scripts/pack_boundary_ratchet.py`` keeps the data directory data-only.

Usage::

    python scripts/pack_new.py --id acme.portal --display-name "Acme Portal"
    python scripts/pack_new.py --id acme.portal --dry-run
    python scripts/pack_new.py --id acme.portal --force   # overwrite a scaffold

The generated pack starts as ``experimental`` in its manifest; promoting it to
``active`` is a deliberate edit, not a default.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_CAPABILITIES = ("account.registration.email", "mailbox.otp")
DEFAULT_VERSION = "0.1.0"
PLACEHOLDER_TLD = "invalid"

_FLOW_TEMPLATE = '''"""{display} registration flow (scaffold).

The provider pack ``{pack_id}`` references these functions by
``module.path:attribute``; renaming one is a manifest edit too.
"""

from __future__ import annotations

from typing import Any

PACK_ID = "{pack_id}"


def preflight(*, proxy: str | None = None) -> dict[str, Any]:
    """Read-only reachability check the ``verify`` hook runs.

    Return the shared probe shape (``{{"ok": bool, ...}}``) and never persist,
    purchase or mutate anything: the hook is an operator diagnostic.
    """
    raise NotImplementedError(f"implement {{PACK_ID}}.preflight")


def register_email(mailbox: str, *, proxy: str | None = None) -> dict[str, Any]:
    """Register one account for ``{pack_id}``.

    Must return the shared registration result shape and must not import another
    platform module; shared behaviour belongs in a core seam, not in a sibling
    platform.
    """
    raise NotImplementedError(f"implement {{PACK_ID}}.register_email")
'''

_DOC_TEMPLATE = """# {display} ({pack_id})

- **Manifest**: `sms_tool/packs/builtin/{short}/manifest.json`
- **Implementation**: `sms_tool/platforms/{short}/flow.py`
- **Contract test**: `tests/packs/test_{short}_pack.py`
- **Status**: experimental (scaffolded)

## Capabilities

{capabilities}

## Endpoints

{endpoints}

## Maintenance entry points

```powershell
python -m sms_tool --pack-info {pack_id}
python -m sms_tool --pack-verify {pack_id}
python -m pytest -q tests/packs/test_{short}_pack.py
```

## Reserved namespaces

| Space | Value |
| --- | --- |
| config | `packs.{pack_id}` |
| storage | `runtime/packs/{pack_id}/` |
| telemetry | `pack.{pack_id}` |

The three are derived from the pack id, so this architecture cannot collide with
another pack's settings, files or log prefix.

## Upgrade checklist

1. Change `version` in the manifest (semver) and keep `api_version` at a value
   this core supports.
2. Run `--pack-verify {pack_id}`; every declared entrypoint and hook must resolve.
3. Run the pack's own test module.
4. Record the change in `docs/releases/` with the other work in that release.
"""

_TEST_TEMPLATE = '''"""Contract test for the {pack_id} provider pack.

This file is the pack's own maintenance entry: it fails when the manifest stops
describing code that exists, which is the failure mode a silently renamed
function would otherwise produce at registration time.
"""

from __future__ import annotations

from sms_tool.packs import admin, loader


def test_the_pack_is_discoverable() -> None:
    registry = loader.load_registry()

    assert "{pack_id}" in registry.ids()


def test_every_declared_reference_resolves() -> None:
    registry = loader.load_registry()

    report = admin.verify_pack(registry.get("{pack_id}"))

    assert report["ok"], report["failures"]


def test_the_pack_declares_its_namespaces() -> None:
    manifest = loader.load_registry().get("{pack_id}").manifest

    assert manifest.namespaces.config == "packs.{pack_id}"
    assert manifest.namespaces.storage == "packs/{pack_id}"
    assert manifest.namespaces.telemetry == "pack.{pack_id}"
'''


@dataclass
class Scaffold:
    """The files a new pack needs, rendered but not yet written."""

    pack_id: str
    short: str
    display: str
    capabilities: tuple[str, ...] = DEFAULT_CAPABILITIES
    endpoints: dict[str, str] = field(default_factory=dict)
    files: dict[Path, str] = field(default_factory=dict)

    def manifest(self) -> dict[str, object]:
        return {
            "schema": "provider-pack.v2",
            "id": self.pack_id,
            "display_name": self.display,
            "version": DEFAULT_VERSION,
            "api_version": "1",
            "status": "experimental",
            "capabilities": list(self.capabilities),
            "endpoints": dict(sorted(self.endpoints.items())),
            "entrypoints": {
                "register_email": f"sms_tool.platforms.{self.short}.flow:register_email",
            },
            "hooks": {
                "verify": f"sms_tool.platforms.{self.short}.flow:preflight",
            },
            "risk_signals": [],
        }


def build_scaffold(
    pack_id: str,
    display: str,
    capabilities: tuple[str, ...] = DEFAULT_CAPABILITIES,
    endpoints: dict[str, str] | None = None,
) -> Scaffold:
    """Render every file for one new pack. Pure: nothing touches the disk."""
    short = module_name(pack_id)
    resolved_endpoints = dict(endpoints or {"base": f"https://{short.replace('_', '-')}.{PLACEHOLDER_TLD}"})
    manifest = Scaffold(pack_id=pack_id, short=short, display=display, capabilities=capabilities)
    manifest.endpoints = resolved_endpoints

    implementation_dir = ROOT / "sms_tool" / "platforms" / short
    files: dict[Path, str] = {
        implementation_dir / "__init__.py": f'"""Registration architecture implementation: {display}."""\n',
        implementation_dir / "flow.py": _FLOW_TEMPLATE.format(display=display, pack_id=pack_id),
        ROOT / "sms_tool" / "packs" / "builtin" / short / "manifest.json": json.dumps(
            manifest.manifest(), indent=2, ensure_ascii=False
        )
        + "\n",
        ROOT / "tests" / "packs" / f"test_{short}_pack.py": _TEST_TEMPLATE.format(pack_id=pack_id),
        ROOT / "docs" / "packs" / f"{pack_id}.md": _DOC_TEMPLATE.format(
            display=display,
            pack_id=pack_id,
            short=short,
            capabilities="\n".join(f"- `{name}`" for name in capabilities),
            endpoints="\n".join(f"- `{key}`: `{value}`" for key, value in sorted(resolved_endpoints.items())),
        ),
    }
    manifest.files = files
    return manifest


def module_name(pack_id: str) -> str:
    """Directory/module name for a pack id: ``acme.portal`` -> ``acme_portal``."""
    return re.sub(r"[^a-z0-9]+", "_", pack_id).strip("_")


def write_scaffold(scaffold: Scaffold, *, force: bool = False) -> list[Path]:
    """Write the scaffold, refusing to clobber an existing file unless forced."""
    existing = [path for path in scaffold.files if path.exists()]
    if existing and not force:
        raise FileExistsError("already exists: " + ", ".join(str(path.relative_to(ROOT)) for path in existing))
    for path, content in scaffold.files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    return sorted(scaffold.files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scaffold a provider pack (one registration architecture).")
    parser.add_argument("--id", required=True, help="pack id, e.g. acme.portal (lowercase, dotted)")
    parser.add_argument("--display-name", default=None, help="human name shown by --pack-list")
    parser.add_argument(
        "--capability",
        action="append",
        dest="capabilities",
        default=None,
        help=f"capability to claim (repeatable); default {list(DEFAULT_CAPABILITIES)}",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        default=None,
        metavar="NAME=URL",
        help="endpoint root, e.g. auth=https://auth.acme.test (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the files that would be written")
    parser.add_argument("--force", action="store_true", help="overwrite an existing scaffold")
    args = parser.parse_args(argv)

    from sms_tool.packs import PackManifestError

    try:
        endpoints = _parse_endpoints(args.endpoints or [])
        scaffold = build_scaffold(
            args.id,
            args.display_name or args.id,
            tuple(args.capabilities) if args.capabilities else DEFAULT_CAPABILITIES,
            endpoints,
        )
        # Validate before writing: a scaffold that the loader would reject is
        # worse than no scaffold, because it fails at the next `--pack-list`.
        from sms_tool.packs.contracts import PackManifest

        PackManifest.from_mapping(scaffold.manifest())
    except PackManifestError as exc:
        print(f"cannot scaffold {args.id!r}: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"cannot scaffold {args.id!r}: {exc}", file=sys.stderr)
        return 2

    if args.dry_run:
        for path, content in scaffold.files.items():
            print(f"--- {path.relative_to(ROOT).as_posix()} ---")
            print(content)
        return 0

    try:
        written = write_scaffold(scaffold, force=args.force)
    except FileExistsError as exc:
        print(f"refusing to overwrite: {exc}", file=sys.stderr)
        print("re-run with --force to overwrite, or pick another --id", file=sys.stderr)
        return 2

    for path in written:
        print(f"wrote {path.relative_to(ROOT).as_posix()}")
    print(f"\nnext: python -m sms_tool --pack-verify {scaffold.pack_id}")
    print("      python -m pytest -q tests/packs")
    return 0


def _parse_endpoints(raw: list[str]) -> dict[str, str]:
    endpoints: dict[str, str] = {}
    for item in raw:
        name, _, value = item.partition("=")
        if not name.strip() or not value.strip():
            raise ValueError(f"--endpoint expects NAME=URL, got {item!r}")
        endpoints[name.strip()] = value.strip()
    return endpoints


if __name__ == "__main__":
    raise SystemExit(main())
