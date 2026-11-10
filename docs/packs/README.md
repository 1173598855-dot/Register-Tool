# Provider Packs (注册架构)

One file per registration architecture. A pack is the unit of maintenance: its
manifest declares the endpoints, entrypoints, capabilities and lifecycle hooks,
and the three namespaces (config / storage / telemetry) are derived from its id,
so two architectures can be developed, upgraded and rolled back independently.

Platform contract and operator surface: [provider-packs.md](../current/provider-packs.md).

## Packs

| Pack | Manifest | Implementation | Contract test | Status |
| --- | --- | --- | --- | --- |
| ChatGPT (`openai.chatgpt`) | `sms_tool/packs/builtin/chatgpt/manifest.json` | existing `sms_tool/registration`, `sms_tool/accounts`, `sms_tool/auth_flow` modules | `tests/packs/test_chatgpt_pack.py` | active |

## Adding one

```powershell
python scripts/pack_new.py --id acme.portal --display-name "Acme Portal"
python -m sms_tool --pack-verify acme.portal
python -m pytest -q tests/packs
```

The generator writes this file's next row, the manifest, the implementation
stub under `sms_tool/platforms/<short>/`, and the pack's own contract test. Then
fill in `flow.py` — no core module changes.

## Rules that keep packs independent

| Rule | Enforced by |
| --- | --- |
| `sms_tool/packs/` imports standard library only | `scripts/pack_boundary_ratchet.py` (leaf contract) |
| No core module imports a builtin pack | same gate |
| A builtin pack directory holds JSON only | same gate |
| Every pack has a valid, uniquely-named manifest with ≥1 entrypoint | same gate |
| A platform module must not import another platform module | `docs/directory-map.md` boundary note + review |
