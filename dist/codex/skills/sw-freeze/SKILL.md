---
name: sw-freeze
description: Stamp frozen: true on an artifact, register in INDEX, and enforce immutability. Does not unfreeze or edit frozen parents.
alwaysApply: false
---

# `/sw-freeze`

Irreversible handoff freeze. Local hooks warn early; CI `check-frozen.py` is authoritative.

## Scope

- Input: path to brainstorm, PRD, decision record, task list, or amendment draft.
- Output: `frozen: true` + `frozen_at` frontmatter; `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` entry.
- Does **not** unfreeze, edit parents, or generate tasks (decision records never generate tasks).

## Freeze receipt and durability (PRD 081 R10/R12)

`/sw-freeze` and `scripts/check_frozen_lib.py freeze_artifact` emit a structured **receipt** alongside
`frozen: true` frontmatter. Orchestrated doc-loop freezes record owner `doc-loop:<run-id>`; standalone
operator freezes record owner `operator` (or explicit `--owner` when wired).

### Receipt fields

| Field | Meaning |
| --- | --- |
| `artifact` | Repo-relative path frozen |
| `owner` | Exclusive freeze owner (`doc-loop:<run-id>`, deliver driver, or `operator`) |
| `lifecycleState` | `frozen` when stamp succeeded |
| `durabilityState` | `verified` \| `failed` — file-store commit or issue-store hash verification |
| `revision` | Content hash at freeze time |
| `freezeRecordDigest` | Canonical digest for tamper detection |
| `commitSha` | File-store seed commit (when durability verified) |
| `storeRevision` | Issue-store revision (when applicable) |
| `driverInvoked` | `true` when `SW_DOC_DRIVER` / `SW_DOC_ORCHESTRATOR` or explicit driver path |

### Durability per store mode

| Store | Durability check | Driver-invoked failure |
| --- | --- | --- |
| **File-store** | `check-frozen.py freeze-commit` onto `<type>/<slug>` (non-switching plumbing) | **`verdict: fail`**, `error: durability-not-verified` — doc-loop halts |
| **Issue-store** | `planning_store.py freeze` + `verify-frozen-hash` at deliver entry | Distillation / hash failure → `sw:freeze-incomplete`; deliver blocked |
| **Direct operator** | Same durability helpers | **`verdict: warn`** on durability failure — stamp not rolled back; operator decides |

Driver-invoked freezes **fail closed** on durability failure; direct operator invocation **warns** and
logs — the receipt `verdict` distinguishes the paths (`finalize_durability_verdict` in
`check_frozen_lib.py`).

Transition receipts for doc-loop mechanical freezes persist under
`.cursor/sw-doc-runs/<run-id>/receipts/` with idempotency keys — resume replays completed transitions only.

## Procedure

1. Verify artifact exists and does **not** already have `frozen: true`.
2a. **All-private visibility (PRD 050 R18):** when `planning.visibilityProfile` is `all-private`, run
   `python3 scripts/planning_visibility.py check-freeze-visibility <artifact>` before stamping — git-tracked
   artifacts MUST declare `visibility: public` in frontmatter or freeze halts fail-closed.
2. **Spec-rigor gate** (`skills/spec-rigor/SKILL.md`) — halt on `fail` (exit `20`):
   - **PRD / brainstorm / amendment:** `python3 scripts/spec-rigor-check.py --root <consumer-repo> --artifact prd --path <file> --tier <full|standard>`
     (tier from triage or `--tier`; default `standard` when unknown). Consumer `--root` is required;
     omit or package-`scripts/` parent fails closed. Asterisk RID bullets (`* **R1**`) parse on the
     stored body — a hyphen-only temp copy is not freeze evidence.
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
   - **Task list:** `python3 scripts/spec-rigor-check.py --root <consumer-repo> --artifact tasks --path <file> --prd <frozen-prd>` then
     `python3 scripts/traceability-check.py --prd <frozen-prd> --tasks <file>` — both must pass before freeze.
   - `warn` (exit `10`) may proceed with logged findings.
2b. **Brainstorm forward ref (R53):** when freezing a **Full-tier PRD**, if the source brainstorm is not frozen,
    run `python3 scripts/doc_link.py write-forwardref --brainstorm <source> --prd <prd-path>` so the
    brainstorm `prd:` field points at this PRD (skip when brainstorm is frozen).
2a. **Strip sizing advisory (PRD 040):** for task lists, remove any `## Sizing & Split Suggestions` block via `python3 scripts/phase_sizing.py strip-advisory --inplace <path>` before stamping.
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


## Issue-store freeze (PRD 043 — when `planning.store.backend` is `issue-store`)

When the effective backend is `issue-store`, `/sw-freeze` delegates artifact immutability to the
issue API instead of (or in addition to) local `frozen: true` frontmatter:

```bash
python3 scripts/planning_store.py freeze --unit-id <unit-id> --body-path <artifact-path>
```

- Locks the issue, applies `sw:frozen`, records canonical hash in a `sw-freeze-record` comment
- PRD freeze: distills linked brainstorm rationale to memory (`research`) via `memory-redact`;
  closes+links brainstorm issue (retained, not deleted)
- Distillation failure flags `sw:freeze-incomplete` and blocks deliver (fail-closed)
- CI/deliver verify via `python3 scripts/planning_store.py verify-frozen-hash ...`
- **Linear reconstruct-before-ok (PRD 358 R9 / PRD 359):** freeze of a Linear-backed unit is
  refused when reconstruction fails (truncated head, missing overflow, `writeToken`/authorship
  mismatch, or `linear_public_markdown_equivalent()` mismatch against the pre-chunk body), even if
  spec-rigor parses asterisk `* **R1**` R-IDs on the stump. Original bytes remain the freeze/hash
  witness. A normalized temporary copy is never freeze evidence or frozen-hash input. Pass consumer
  `--root` into spec-rigor on the freeze path.



### Jira lifecycle-drift (PRD 047 R104)

When `planning.store.issuesProvider` is `jira`, freeze immutability is **decoupled from Jira workflow status**
(D26): `sw:frozen` + canonical content-hash are authoritative; Jira `status` is display/probe only. An
external or automation status transition on a frozen issue is classified as **`lifecycle-drift`** — distinct
from PRD 043 R37 `tamper-detected`. `issue-lock` is degraded (hash-authoritative tamper-evidence only).

Local `frozen: true` frontmatter and INDEX registration remain required for file-native artifacts.
Decision-class artifacts stay file-native (D8).

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

**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-freeze`.

## Currency (PRD 080)

Issue-store freezes continue to route durability through `planning_store.py` (`freeze` /
`verify-frozen-hash`). Credential material for store access resolves by **credential reference** via the
broker — freeze receipts and CI output still must never print secret values. `durabilityState`,
`driverInvoked`, and `durability-not-verified` semantics are unchanged.

## Guardrails

- No unfreeze path exists.
- Post-freeze parent edits are forbidden — use `/sw-amend`.
- Credential hygiene: hook/CI output must not contain secrets.

## Planning-store facade (PRD 082)

Issue-store freeze / `verify-frozen-hash` entrypoints remain `scripts/planning_store.py` (generated
shim). Canonical implementation lives in `scripts/planning_store_facade.py` — operators and CI still
invoke the shim path; do not import the facade module from workflow commands.

## Currency note

Freeze durability continues through `planning_store.py` → `planning_store_facade.py` and
`check_frozen_lib.py` / `check-frozen.py`. Closeout (`close-delivery-units`) re-pins the newest
`sw-freeze-record` after frozen state/label mutations so `get` / `verify-frozen-hash` stay
tamper-clean (PRD 275) — freeze stamp itself unchanged.

## Command-doc currency regen (PRD 362 R3/R5)

This file is in `COMMAND_DOC_CURRENCY_ARTIFACTS`. When `docs-currency-gate` reports drift on bound code
paths, regen downstream from the **primary checkout** only — never invoke `python3 -m sw generate --all`
(or Codex/OpenCode MCP emit) with cwd in an orchestrator worktree under `.sw-worktrees/` (R3).

**Default stamp chain** (after the command body matches the code):

1. `python3 scripts/agent_instruction_compiler.py` (write mode; `--check` alone is not green).
2. `python3 -m sw generate cursor` and `python3 -m sw generate claude-code` from primary.
3. `python3 scripts/golden_manifest.py generate` (refreshes `scripts/test/fixtures/parity/cursor-golden.manifest` after dist/cursor generate).

Shortcut after editing this file:
`python3 scripts/docs-currency-gate.py restamp-command-doc <repo-root> core/commands/sw-freeze.md` bumps
the marker and runs the stamp chain. Or `python3 scripts/docs-currency-gate.py regen-command-doc-chain
<repo-root>` when the doc is already current.

Full-tree `python3 -m sw generate --all` is **primary-checkout only** when every platform plus MCP JSON
must be refreshed; pass `--restore-plan` when the generator refuses without it. Do not use
`ship-build-chain-check --check` as regen.

<!-- currency: refreshed 2026-09-15T20:26:00Z — terminal docs-currency after planning_store shipped_issues_providers export; check_frozen_lib / check-frozen / planning_store -->
