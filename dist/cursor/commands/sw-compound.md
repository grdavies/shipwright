---
description: "[INTERNAL] Compound write step — use /sw-retrospective instead. Distill retro/feedback into durable memories with relationship edges."
alwaysApply: false
internal: true
---

# `/sw-compound` (internal)

**Not a user-facing top-level command (R3).** Use `/sw-retrospective` for post-delivery compounding.

This file documents the internal compound-write step invoked by `/sw-retrospective` between `/sw-retro` and
`/sw-memory-sync`. Load `skills/compound/SKILL.md`. Route all writes through `memory-preflight` +
`scripts/memory-redact.sh`.

**Communication intensity:** full

**Model tier:** mid — resolve via `bash scripts/resolve-model-tier.sh --command sw-compound`.

## Guardrails

- No rule-class writes without user confirmation + audit allowlist.
- Search-before-store; redact before persist.
