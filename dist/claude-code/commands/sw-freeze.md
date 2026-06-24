---
description: Stamp frozen: true on an artifact, register in INDEX, and enforce immutability. Does not unfreeze or edit frozen parents.
alwaysApply: false
---

# `/sw-freeze`

Irreversible handoff freeze. Local hooks warn early; CI `check-frozen.sh` is authoritative.

## Scope

- Input: path to brainstorm, PRD, decision record, task list, or amendment draft.
- Output: `frozen: true` + `frozen_at` frontmatter; `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` entry.
- Does **not** unfreeze, edit parents, or generate tasks (decision records never generate tasks).

## Procedure

1. Verify artifact exists and does **not** already have `frozen: true`.
2. **Spec-rigor gate** (`skills/spec-rigor/SKILL.md`) — halt on `fail` (exit `20`):
   - **PRD / brainstorm / amendment:** `bash scripts/spec-rigor-check.sh --artifact prd --path <file> --tier <full|standard>`
     (tier from triage or `--tier`; default `standard` when unknown).
   - **Decision record / decision amendment:** `bash scripts/spec-rigor-check.sh --artifact decision --path <file> --tier <full|standard>`
     (route by path under `docs/decisions/` or explicit `--artifact decision`).
   - **Task list:** `bash scripts/spec-rigor-check.sh --artifact tasks --path <file> --prd <frozen-prd>` then
     `bash scripts/traceability-check.sh --prd <frozen-prd> --tasks <file>` — both must pass before freeze.
   - `warn` (exit `10`) may proceed with logged findings.
3. Stamp frontmatter:
   ```yaml
   frozen: true
   frozen_at: YYYY-MM-DD
   ```
4. Register in the appropriate living index:
   - **PRDs / task lists:** add or refresh entry in `docs/prds/INDEX.md` (path, amendments, status `not-started`).
   - **Decision records:** add or refresh entry in `docs/decisions/INDEX.md` (path, amendments, status `not-started`).
     **No task list generation and no `COMPLETION-LOG` row** for decisions.
5. Report freeze complete; next step `/sw-tasks` for PRDs only.

## Enforcement layers

| Layer | Role | Bypassable |
|-------|------|------------|
| `frozen: true` flag | machine-readable state | — |
| `rules/sw-freeze-guardrail.mdc` | agent instruction | — |
| `hooks/pre-commit-frozen.sh` | local commit block | yes (`--no-verify`) |
| `scripts/check-frozen.sh` | CI required-check | **no** |

Bootstrap local hook: `bash scripts/install-hooks.sh`.

## Guardrails

- No unfreeze path exists.
- Post-freeze parent edits are forbidden — use `/sw-amend`.
- Credential hygiene: hook/CI output must not contain secrets.
