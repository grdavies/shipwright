---
description: Gap-check phase plan vs diff; bounded closers for in-scope gaps. Does not merge or ship alone.
alwaysApply: false
---

# `/sw-gaps`

Standalone gap-check (same skill as default-on step in `/sw-ship`).

## Flags

- `--report-only` — mapping + report only; no closer dispatch.

## Procedure

Load `skills/gap-check/SKILL.md` and run the full procedure unless `--report-only`.

Hand off: in-scope closed → `/sw-verify`; out-of-scope → user / feedback intake (`005`).

**Communication intensity:** full

**Model tier:** mid — resolve via `python3 scripts/resolve-model-tier.py --command sw-gaps`.

## Guardrails

- Read-only mapping before any edit.
- `--report-only` never mutates.
