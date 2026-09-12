# Shipwright install-root documentation

Canonical adopter guides for packaged Shipwright installs. Platform emitters copy this tree to
`<install-root>/documentation/` so consumers read docs from the plugin install root — not from a
Shipwright source checkout.

## Guides

| Guide | Purpose |
| --- | --- |
| [Getting started](getting-started.md) | Packaged install, init, and first workflow |
| [Self-upgrade](self-upgrade.md) | Release assets, missing-asset behavior, and recovery |
| [Configuration](configuration.md) | Profiles, memory, planning, and credentials |
| [Workflows](workflows.md) | End-to-end deliver, doc, debug, and ship loops |
| [Commands](commands.md) | `sw-*` command reference |
| [Decision tree](decision-tree.md) | Which command to run next |
| [Style guide](style-guide.md) | Adopter-facing prose conventions |
| [Glossary](glossary.md) | Coined terms |
| [Testing](testing.md) | Verification and CI expectations |
| [Graph domain terminology](graph-domain-terminology.md) | Planning vs execution graph vocabulary |
| [GitHub issues](github-issues.md) | Issue-store onboarding |
| [Issue store](issue-store.md) | External planning backends |
| [Troubleshooting](troubleshooting.md) | Projection timeouts, rate limits, and resume |
| [Trust anchors](trust-anchors.md) | Dist-only install trust verification |

## Redaction tier semantics

Planning **visibility (redaction) tier** defaults and store placement are documented in
[configuration.md](configuration.md) under `planning.visibilityTier` (`all-private` |
`specs-public` | `all-public`). Memory redaction-on-write and transcript-room non-bypass rules in
that guide remain authoritative for install-root consumers — this tree does not weaken closed-world
defaults or expose credentials.

Public repository paths under `docs/guides/` may carry redirect stubs in later rollout phases;
**this directory is the canonical install-root home** for adopter guide bodies.
