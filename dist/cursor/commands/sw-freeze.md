---
description: Stamp frozen: true on an artifact, register in INDEX, and enforce immutability. Does not unfreeze or edit frozen parents.
alwaysApply: false
---

# `/sw-freeze`

Irreversible handoff freeze. Local hooks warn early; CI `check-frozen.py` is authoritative.

## Scope

- Input: path to brainstorm, PRD, decision record, task list, or amendment draft.
- Output: `frozen: true` + `frozen_at` frontmatter; `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` entry.
- Does **not** unfreeze, edit parents, or generate tasks (decision records never generate tasks).

## Procedure

1. Verify artifact exists and does **not** already have `frozen: true`.
2. **Spec-rigor gate** (`skills/spec-rigor/SKILL.md`) — halt on `fail` (exit `20`):
   - **PRD / brainstorm / amendment:** `python3 scripts/spec-rigor-check.py --artifact prd --path <file> --tier <full|standard>`
     (tier from triage or `--tier`; default `standard` when unknown).
   - **PRD Full-tier linkage (R55):** before stamping, run
     `python3 scripts/doc-link-check.py --path <file> --tier full` — halt on exit `20` when `brainstorm:` is
     missing or dangling.
   - **Decision record / decision amendment:** `python3 scripts/spec-rigor-check.py --artifact decision --path <file> --tier <full|standard>`
     (route by path under `docs/decisions/` or explicit `--artifact decision`).
   - **Decision snapshot (PRD 015):** after stamping `frozen: true` on a decision record, refresh the
     committed redacted snapshot (offline-safe — no provider calls):
     `python3 scripts/memory-decision-snapshot.py write --path <file>` stamps `authoritative: repo|memory`
     via `memory-sot.py` and pipes body through `memory-redact.py`. Provider write of the authoritative
     record (memory-SoT) is best-effort post-freeze with an audit breadcrumb in
     `docs/decisions/.memory-freeze-audit.log` — never a CI gate.
   - **Task list:** `python3 scripts/spec-rigor-check.py --artifact tasks --path <file> --prd <frozen-prd>` then
     `python3 scripts/traceability-check.py --prd <frozen-prd> --tasks <file>` — both must pass before freeze.
   - `warn` (exit `10`) may proceed with logged findings.
2b. **Brainstorm forward ref (R53):** when freezing a **Full-tier PRD**, if the source brainstorm is not frozen,
    run `python3 scripts/doc_link.py write-forwardref --brainstorm <source> --prd <prd-path>` so the
    brainstorm `prd:` field points at this PRD (skip when brainstorm is frozen).
3. Stamp frontmatter:
   ```yaml
   frozen: true
   frozen_at: YYYY-MM-DD
   ```
4. **Gap schedule flip (R52):** when frontmatter lists `absorbs: [GAP-NNN, …]`, run
   `python3 scripts/gap-backlog.py flip --schedule --from-artifact <path>` after stamping.
   Optional structural normalize: `python3 scripts/doc-format-normalize.py --write --inplace <path>` when `--normalize`.
5. Register in the appropriate living index:
   - **PRDs / task lists:** add or refresh entry in `docs/prds/INDEX.md` (path, amendments, status `not-started`).
   - **Decision records:** add or refresh entry in `docs/decisions/INDEX.md` (path, amendments, status `not-started`).
     **No task list generation and no `COMPLETION-LOG` row** for decisions.
6. **Freeze-time commit (PRD 013 R1–R5):** after stamping and index registration, invoke the shared
   spec-seed helper via the verdict-independent wrapper (R4 — warn-not-block; stamp is never rolled back):

   ```bash
   python3 scripts/check-frozen.py freeze-commit --artifact <artifact-path>
   ```

   The helper commits the frozen artifact onto the resolved `<type>/<slug>` (creating the branch from the
   default branch when absent) using non-switching plumbing — the operator's current checkout is restored.
   Docs-only; excludes `docs/brainstorms/**` and untracked/ignored paths; never `main`. A branch or commit
   failure logs a warning and returns success to the freeze verdict.
7. Report freeze complete; next step `/sw-tasks` for PRDs only.

## Enforcement layers

| Layer | Role | Bypassable |
|-------|------|------------|
| `frozen: true` flag | machine-readable state | — |
| `rules/sw-freeze-guardrail.mdc` | agent instruction | — |
| `core/hooks/pre-commit-frozen.py` | local commit block | yes (`--no-verify`) |
| `core/hooks/pre-commit-completed-unit.py` | complete-unit folder immutability (R9/R12) | yes (`--no-verify`) |
| `scripts/check-frozen.py` | CI required-check | **no** |


**Completed-unit immutability (PRD 032 R9/R12):** `core/hooks/pre-commit-completed-unit.py` chains from
`hooks/pre-commit` after the frozen-artifact check. It rejects any staged mutation under a planning unit
folder whose consumer status is `complete` (body, `amendments/` subtree, or ancillary paths). Evaluation
binds to a reconcile-generation token (inline reconcile + derived-status re-read) to close TOCTOU races.
When the reconciler `derived` region is empty (half-applied train), the hook runs in **graceful-degraded
structural-status mode** and emits a warning instead of blocking every write.

`check-frozen.py` and the freeze snapshot path operate on the committed git record only — the provider
is never consulted during freeze or CI (PRD 015 R5).

Bootstrap local hook: `python3 scripts/install-hooks.py`.

**Communication intensity:** normal

**Model tier:** cheap — resolve via `python3 scripts/resolve-model-tier.py --command sw-freeze`.

## Guardrails

- No unfreeze path exists.
- Post-freeze parent edits are forbidden — use `/sw-amend`.
- Credential hygiene: hook/CI output must not contain secrets.
