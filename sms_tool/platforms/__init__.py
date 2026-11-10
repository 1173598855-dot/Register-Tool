"""Reserved namespace for registration-architecture implementations.

``sms_tool/packs/`` holds *contracts and manifests* and is standard-library only
by rule. A pack's actual protocol code cannot live there, and it cannot be a new
module at the package root either (``scripts/root_module_ratchet.py`` freezes that
surface). This package is the reserved home:

```text
sms_tool/platforms/<short_name>/     one registration architecture
sms_tool/platforms/<short_name>/flow.py
```

The pack manifest in ``sms_tool/packs/builtin/<dir>/manifest.json`` points at
these modules by ``module.path:attribute``, so adding an architecture is a new
subpackage plus a manifest -- never an edit to the core, and never an import from
one platform into another.

Scaffold a new one with ``python scripts/pack_new.py --help``; the generated
layout, manifest, doc stub and per-pack test are the maintenance entry points for
that architecture.
"""
