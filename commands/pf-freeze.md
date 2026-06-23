---
description: Stamp frozen: true on an artifact, register in INDEX, and enforce immutability. Does not unfreeze or edit frozen parents.
alwaysApply: false
---

# `/pf-freeze`

Irreversible handoff freeze. Local hooks warn early; CI `check-frozen.sh` is authoritative.

## Scope

- Input: path to brainstorm, PRD, task list, or amendment draft.
- Output: `frozen: true` + `frozen_at` frontmatter; `prds/INDEX.md` entry for PRDs/tasks.
- Does **not** unfreeze, edit parents, or generate tasks.

## Procedure

1. Verify artifact exists and does **not** already have `frozen: true`.
2. Stamp frontmatter:
   ```yaml
   frozen: true
   frozen_at: YYYY-MM-DD
   ```
3. For PRDs/task lists: add or refresh entry in `prds/INDEX.md` (path, amendments, status `not-started`).
4. Report freeze complete; next step `/pf-tasks` for PRDs.

## Enforcement layers

| Layer | Role | Bypassable |
|-------|------|------------|
| `frozen: true` flag | machine-readable state | — |
| `rules/pf-freeze-guardrail.mdc` | agent instruction | — |
| `hooks/pre-commit-frozen.sh` | local commit block | yes (`--no-verify`) |
| `scripts/check-frozen.sh` | CI required-check | **no** |

Bootstrap local hook: `bash scripts/install-hooks.sh`.

## Guardrails

- No unfreeze path exists.
- Post-freeze parent edits are forbidden — use `/pf-amend`.
- Credential hygiene: hook/CI output must not contain secrets.
