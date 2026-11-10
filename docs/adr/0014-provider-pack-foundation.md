# ADR-0014: Additive Provider-Pack Foundation

- Status: Accepted
- Date: 2026-11-10

The workbench is to grow beyond its current ChatGPT-specific product surface.
The first step adds a provider-neutral manifest contract, a registry, and a
lazy adapter that can expose existing functions as named pack entrypoints.
ChatGPT is the first declared pack; its implementation remains in the existing
modules and remains the runtime authority.

This decision is deliberately additive. No CLI, WPF, registration, account,
mailbox, or payment caller is rerouted in this step. Generic workflow execution
and code movement wait until a second concrete pack validates the abstraction.

## Consequences

- Pack metadata has one validated shape: `provider-pack.v1`.
- Capability names are extensible strings rather than a closed enum.
- Endpoint roots must be HTTPS URLs without embedded credentials.
- Entrypoints use explicit `module.path:attribute` references and resolve lazily.
- Risk-signal vocabulary is descriptive metadata, not retry or bypass policy.
- `sms_tool/packs/` is a domain-contract package and is covered by the module,
  layer, documentation, and test ratchets.
- Future product work can build three distinct surfaces over proven shared
  seams: general provider automation, browser/risk research, and payment
  orchestration. They are not collapsed into one runtime pipeline prematurely.
