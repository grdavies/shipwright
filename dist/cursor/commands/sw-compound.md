---
description: Distill retro/feedback into durable memories with relationship edges. Rule-class promotion requires human gate via /sw-memory-audit.
alwaysApply: false
---

# `/sw-compound`

Compounding step after `/sw-retro` or explicit feedback.

Load `skills/compound/SKILL.md`. Route all writes through `memory-preflight` + `scripts/memory-redact.sh`.

## Guardrails

- No rule-class writes without user confirmation + audit allowlist.
- Search-before-store; redact before persist.
