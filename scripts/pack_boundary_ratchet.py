"""Ratchet: the provider-pack boundary must not erode.

Why this exists
---------------
``sms_tool/packs/`` is the seam that lets several registration architectures
live in one repository. A seam only works if both sides stay on their own side,
and both failure directions are silent:

* a pack module importing the application (``from .config import CFG``) makes the
  contract depend on its consumer -- an import cycle that nothing else notices
  until the package fails to load;
* a core module importing a *builtin pack* (``sms_tool.packs.builtin.chatgpt``)
  hard-codes one registration architecture into the platform, which is exactly
  what the platform exists to prevent;
* a ``.py`` file appearing under ``builtin/`` turns a data directory into an
  implementation directory, and from then on "the pack" is code nobody declared
  in a manifest.

So this gate checks five things, and it is a **ratchet in the strict sense**: it
does not carry a baseline. The correct count for every rule is zero, so a new
violation fails immediately and cleaning one up needs no baseline edit.

What it checks
--------------
1. **Leaf contract.** Every module-scope import in ``sms_tool/packs/*.py`` is
   standard library or a relative import that stays inside ``sms_tool.packs``.
   Function-local imports are not checked here: they are frozen by
   ``scripts/delayed_import_ratchet.py`` instead, and a new one fails there.
2. **No core module reaches into a builtin pack.** Builtin packs are data.
3. **Builtin packs are data only.** No ``.py`` file inside
   ``sms_tool/packs/builtin/<dir>/``, and no manifest entrypoint or hook that
   points into ``sms_tool.packs.builtin``.
4. **Every builtin pack has one valid manifest**, whose ``id`` matches its
   directory, with unique ids across the tree.
5. **Every builtin pack has one valid manifest**, whose ``id`` matches its
   directory and is unique across the tree. A pack that resolves nothing fails
   here because the contract rejects an empty ``entrypoints`` map -- a pack with
   no entrypoint is a documentation stub, not a registration architecture.

Standard library only, so it runs from a test, CI, or a bare interpreter.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS_DIR = ROOT / "sms_tool" / "packs"
BUILTIN_DIR = PACKS_DIR / "builtin"
PACKAGE = "sms_tool.packs"

#: The manifest rules import the contract package, and a script run as
#: ``python scripts/pack_boundary_ratchet.py`` only has ``scripts/`` on the path.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: ``sys.stdlib_module_names`` is the vocabulary a leaf module may use. A name
#: added by a future interpreter release is accepted automatically, which is the
#: direction this gate wants.
STDLIB = frozenset(sys.stdlib_module_names) | {"__future__"}


def module_scope_nodes(tree: ast.AST) -> list[ast.stmt]:
    """Import statements that execute at import time (function bodies excluded)."""
    visitor = _ModuleScopeVisitor()
    visitor.visit(tree)
    return list(visitor.imports)


class _ModuleScopeVisitor(ast.NodeVisitor):
    """Collect ``import`` / ``from ... import`` outside function bodies.

    ``NodeVisitor`` already stops at a node whose visitor does not call
    ``generic_visit``, so overriding the two function visitors is enough to skip
    their bodies.
    """

    def __init__(self) -> None:
        self.imports: list[ast.stmt] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """A function body does not run at import time."""

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """A coroutine body does not run at import time either."""

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for child in node.body:
            self.visit(child)

    def visit_Import(self, node: ast.Import) -> None:
        self.imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.imports.append(node)


def leaf_violations(root: Path | None = None) -> list[str]:
    """Rule 1: a pack module may only import the standard library."""
    base = PACKS_DIR if root is None else root / "sms_tool" / "packs"
    failures: list[str] = []
    for path in sorted(base.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            failures.append(f"{path.name}: cannot parse ({type(exc).__name__})")
            continue
        for node in module_scope_nodes(tree):
            failures.extend(_leaf_failures(path.name, node))
    return failures


def _leaf_failures(module_label: str, node: ast.stmt) -> list[str]:
    failures: list[str] = []
    if isinstance(node, ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top not in STDLIB:
                failures.append(f"{module_label}:{node.lineno} imports {alias.name!r}; packs may only import stdlib")
    elif isinstance(node, ast.ImportFrom):
        if node.level:
            resolved = _resolve_relative(node)
            if not (resolved == PACKAGE or resolved.startswith(PACKAGE + ".")):
                failures.append(f"{module_label}:{node.lineno} relative import escapes the packs package ({resolved})")
        elif node.module:
            top = node.module.split(".")[0]
            if top not in STDLIB:
                failures.append(f"{module_label}:{node.lineno} imports {node.module!r}; packs may only import stdlib")
    return failures


def _resolve_relative(node: ast.ImportFrom) -> str:
    """Resolve ``from ..x import y`` inside ``sms_tool.packs`` to an absolute name."""
    package_parts = PACKAGE.split(".")
    if node.level > 1:
        package_parts = package_parts[: len(package_parts) - (node.level - 1)]
    base = ".".join(package_parts)
    return f"{base}.{node.module}" if node.module else base


def core_import_violations(root: Path | None = None) -> list[str]:
    """Rule 2: nothing outside ``sms_tool/packs/`` may import a builtin pack."""
    repo = ROOT if root is None else root
    packs_dir = repo / "sms_tool" / "packs"
    failures: list[str] = []
    for path in sorted((repo / "sms_tool").rglob("*.py")):
        if packs_dir in path.parents or path.parent == packs_dir:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        for node in ast.walk(tree):
            for target in _imported_modules(node):
                if target.startswith(PACKAGE + ".builtin"):
                    rel = path.relative_to(repo).as_posix()
                    failures.append(
                        f"{rel}:{getattr(node, 'lineno', 0)} imports {target!r}; builtin packs are data only"
                    )
    return failures


def _imported_modules(node: ast.AST) -> list[str]:
    """Absolute module names a single import statement names."""
    if isinstance(node, ast.ImportFrom):
        return [node.module] if node.level == 0 and node.module else []
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    return []


def builtin_layout_violations(root: Path | None = None) -> list[str]:
    """Rule 3: a builtin pack directory contains its manifest and nothing else."""
    builtin = BUILTIN_DIR if root is None else root / "sms_tool" / "packs" / "builtin"
    if not builtin.is_dir():
        return [f"missing builtin pack directory: {builtin}"]
    failures: list[str] = []
    for pack_dir in sorted(child for child in builtin.iterdir() if child.is_dir()):
        for entry in sorted(pack_dir.rglob("*")):
            if entry.is_file() and entry.suffix != ".json":
                failures.append(
                    f"{entry.relative_to(builtin).as_posix()}: builtin packs are data only; "
                    "put implementation in a real module and reference it from the manifest"
                )
    return failures


def manifest_violations(root: Path | None = None) -> list[str]:
    """Rules 4 and 5: exactly one valid manifest per directory, unique ids."""
    from sms_tool.packs.contracts import PackManifestError
    from sms_tool.packs.loader import load_manifest

    builtin = BUILTIN_DIR if root is None else root / "sms_tool" / "packs" / "builtin"
    failures: list[str] = []
    seen: dict[str, str] = {}
    for pack_dir in sorted(child for child in builtin.iterdir() if child.is_dir()):
        manifest_path = pack_dir / "manifest.json"
        if not manifest_path.is_file():
            failures.append(f"{pack_dir.name}/: missing manifest.json")
            continue
        try:
            manifest = load_manifest(manifest_path)
        except PackManifestError as exc:
            failures.append(f"{pack_dir.name}/manifest.json: {exc}")
            continue
        if pack_dir.name not in {manifest.id, manifest.id.split(".")[-1]}:
            failures.append(f"{pack_dir.name}/: directory name must be the pack id {manifest.id!r} or its last segment")
        if manifest.id in seen:
            failures.append(f"duplicate pack id {manifest.id!r}: {seen[manifest.id]} and {pack_dir.name}/")
        seen[manifest.id] = f"{pack_dir.name}/"
        for kind, references in (("entrypoint", manifest.entrypoints), ("hook", manifest.hooks)):
            for name, reference in references.items():
                if reference.startswith(PACKAGE + ".builtin"):
                    failures.append(
                        f"{pack_dir.name}/manifest.json: {kind} {name!r} points into a builtin pack; "
                        "the implementation belongs in a real module"
                    )
    return failures


def all_violations(root: Path | None = None) -> dict[str, list[str]]:
    """Every rule, keyed by name, so a caller can report them separately."""
    return {
        "leaf contract": leaf_violations(root),
        "core imports a builtin pack": core_import_violations(root),
        "builtin pack layout": builtin_layout_violations(root),
        "manifest contract": manifest_violations(root),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ratchet on the provider-pack boundary.")
    parser.add_argument("--detail", action="store_true", help="print each rule's result, including the clean ones")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    results = all_violations(args.root)
    total = sum(len(items) for items in results.values())
    if args.detail:
        for rule, items in results.items():
            print(f"{'OK  ' if not items else 'FAIL'} {rule}: {len(items)} violation(s)")
            for item in items:
                print(f"       {item}")
    if total:
        print(f"pack-boundary ratchet: {total} violation(s) across {len(results)} rule(s)", file=sys.stderr)
        return 1
    print(f"pack-boundary ratchet OK ({len(results)} rule(s), 0 violations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
