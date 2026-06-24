---
description: Gap-check phase plan vs diff; bounded closers for in-scope gaps. Does not merge or ship alone.
alwaysApply: false
---

# `/pf-gaps`

Standalone gap-check (same skill as default-on step in `/pf-ship`).

## Flags

- `--report-only` — mapping + report only; no closer dispatch.

## Procedure

Load `skills/gap-check/SKILL.md` and run the full procedure unless `--report-only`.

Hand off: in-scope closed → `/pf-verify`; out-of-scope → user / feedback intake (`005`).

## Guardrails

- Read-only mapping before any edit.
- `--report-only` never mutates.
