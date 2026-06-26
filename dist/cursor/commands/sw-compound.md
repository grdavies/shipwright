---
description: "[DEPRECATED] Use /sw-retrospective instead. Thin alias for the internal compound write step only."
alwaysApply: false
deprecated: true
replacedBy: sw-retrospective
internal: true
---

# `/sw-compound` (deprecated)

> **Deprecation notice (one release):** `/sw-compound` is deprecated. Use **`/sw-retrospective`**
> for the full post-delivery chain, or invoke the compound write step internally via
> `skills/compound/SKILL.md` inside `/sw-retrospective`. This alias preserves the atomic write-step
> behavior for one release.

## Procedure

1. Print this deprecation notice once at the start of the run.
2. Load `skills/compound/SKILL.md` and run the compound write step (same as the internal step in
   `/sw-retrospective`).
3. Route all writes through `memory-preflight` + `scripts/memory-redact.sh`.

**Communication intensity:** full

**Model tier:** mid — resolve via `bash scripts/resolve-model-tier.sh --command sw-compound`.

## Guardrails

- No rule-class writes without user confirmation + audit allowlist.
- Search-before-store; redact before persist.
