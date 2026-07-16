---
description: Consolidated post-delivery retrospective (retro → compound write → memory-sync → status). Supports --pre-merge/--post-merge phase dispatch; does not merge or auto-promote rules.
alwaysApply: false
---

# `/sw-retrospective`

Single user-facing entry for post-delivery compounding. Delegates to atomic `sw-` commands and the internal
compound write step; does not reimplement their procedures.

## Modes

| Mode | When | Preconditions |
| --- | --- | --- |
| **Pre-merge (in-loop)** | `/sw-deliver` after all phases green, before human merge gate | Feature branch merge-ready; invoke with `--pre-merge` |
| **Post-merge (standalone)** | After human merge to `main` | PR merged by a human — this command does **not** merge |

**Auto-detect (no flag):** resolve phase from deliver run-state + merge status:

```bash
python3 scripts/wave.py retrospective detect-phase
```

Returns `pre-merge` when the target feature branch is merge-ready but not yet on `main`; `post-merge` when
merge is detected or no deliver context applies.

Driver env (pre-merge): `python3 scripts/wave.py retrospective premerge-env`

## Chain

```
sw-retro → compound-write (internal) → [sw-memory-sync] → sw-status reconcile → sw-status append-log
```

- The **compound write** step loads `skills/compound/SKILL.md` inline — not `/sw-compound` (internal-only, R3).
- `sw-memory-sync` runs by default; omit with `--skip-memory-sync`.
- Atomic `/sw-retro`, `/sw-memory-sync`, and `/sw-status` remain independently runnable.

## Subsumed steps

Internal: compound write (`skills/compound/SKILL.md`). Atomic: `/sw-retro`, `/sw-memory-sync`, `/sw-status`.

## Flags

- `--pre-merge` — in-loop mode (R6): commit file outputs on the feature branch; record
  `completed-pending-merge` via `python3 scripts/wave.py retrospective record-premerge --prd <n> --phase <name>`.
- `--post-merge` — standalone reconcile after merge detection.
- `--from <step>` — resume mid-chain (`retro`, `compound`, `memory-sync`, `status`).
- `--skip-memory-sync` — skip transcript distillation.
- `--dry-run` — print the chain; no mutations.

## Autonomy (`compound.autonomy`)

Read mode: `python3 scripts/wave.py retrospective autonomy` (config key `compound.autonomy`, default `supervised`).

| Mode | Behavior |
| --- | --- |
| **`supervised`** (default) | Preserve today's gates: retro/compound approval prompts; pre-merge waits for human merge acknowledgment before INDEX → `complete`. |
| **`auto`** | Run the pre-merge chain hands-off when the terminal PR is green; commit learnings/status on the feature branch; treat merge as external; post-merge reconcile on merge detection without re-prompting. |

**Safety gates (all modes, R7/R8):** memory writes remain fail-closed via `memory-preflight` + redaction; rule-class
promotion stays human-gated (`/sw-memory-audit` allowlist). Autonomy never bypasses these.

**Completion semantics (R6/R11):** pre-merge always records `completed-pending-merge`; INDEX → `complete` only on
real merge detection (`reconcile --require-merge` pre-merge; merge detection post-merge) — even under `auto`.

## State (per-worktree)

Via `scripts/shipwright-state.py`: record `lastCommand: sw-retrospective` and the completed sub-step when
resuming with `--from`.

Run state (pre-merge): `.cursor/sw-deliver-state.json` gains `compoundShip.premergeDone` and
`completion.status: completed-pending-merge` after `record-premerge` (R6).

## Procedure

When `loopHealth.enabled`, run `python3 scripts/loop_health.py --summary`

### Execution telemetry advisory (R30)

During `/sw-retro`, include execution telemetry as quantitative input:

```bash
python3 scripts/execution_telemetry.py summary
python3 scripts/execution_telemetry.py draft-suggestion
```

The drafted `phase-authoring-improvement` suggestion is **advisory only** — never auto-applied to frozen
task lists or committed checkbox toggles. Human review is required before any task authoring change.

 during retro compounding and include the diagnostic downstream-cost summary (review effort, rework/defect, incidents, ranked meta-inbox) in the retrospective output. Loop-health never gates merge or ship.


### Phase resolution

1. If `--pre-merge` → pre-merge mode.
2. If `--post-merge` → post-merge mode.
3. Else run `python3 scripts/wave.py retrospective detect-phase` and use the returned `phase`.

### Pre-merge (`--pre-merge` or auto-detected)

1. Confirm feature branch is merge-ready (all phases `green-merged` on `<type>/<slug>`).
2. **`/sw-retro`** — learning candidates (report-only).
3. **Compound write** — load `skills/compound/SKILL.md`; route writes through `memory-preflight` +
   `scripts/memory-redact.py` (internal step — not `/sw-compound`).
4. **`/sw-memory-sync`** — unless `--skip-memory-sync`; provider unreachable → **fail-closed** (R7).
5. **`/sw-status`** — `python3 scripts/reconcile-status.py reconcile --require-merge` (INDEX `complete` only
   after merge detection, R11); `append-log` for COMPLETION-LOG.
6. **Commit file outputs only** on the feature branch: COMPLETION-LOG, INDEX, CHANGELOG/version,
   learnings notes. **Never commit** memory/provider artifacts (R7).
7. `python3 scripts/wave.py retrospective record-premerge --prd <n> --phase <name> [--notes "..."]`
8. Hand off to terminal merge gate (`/sw-deliver` → `terminal-ship`).

### Post-merge (`--post-merge` or auto-detected)

### Planning closure preview (any mode)

Before post-merge apply, operators may preview:

```bash
python3 scripts/planning_store.py close-delivery-units --prd-unit <prd-unit-id> --dry-run
```

Use printed `resumeCommand` on partial apply.


### Closure-audit resume (R9)

Post-merge and finalize paths run `close-delivery-units` over the expected planning-store set. When discovery
or closure is incomplete, the JSON report is **`verdict: not-ready`** with `openRemaining` — never treat
partial discovery as green.

| Field | Meaning |
| --- | --- |
| `openRemaining` | Unit ids still open after the audit loop |
| `resumeCommand` | Exact retry — typically `python3 scripts/planning_store.py close-delivery-units --prd-unit <id>` |
| `considered` / `skipped` | Per-unit disposition with `reason` |

**Operator rule:** retry **only** via the printed `resumeCommand`. Bare `reconcile-status.py reconcile` or
manual INDEX edits do not satisfy closure-audit evidence. Under `/sw-deliver` finalize, `wave_deliver_loop`
fails closed when `close-delivery-units` returns `not-ready` and surfaces the same `resumeCommand`.

Preview without mutation:

```bash
python3 scripts/planning_store.py close-delivery-units --prd-unit <prd-unit-id> --dry-run
```


### Deliver completion semantics (PRD 060 R16–R17)

- Phase PRs may merge independently when green (`merge-ready-green` + phase acceptance + gap-check pass).
- `living-docs reconcile` runs after each phase merge; `gap-resolve` flips absorbed backlog rows only when INDEX status is `complete` (all phases terminal — last phase on integration, or target merged to default).
- PRD-absorbed implementation gaps (e.g. `gap-105`…`gap-099`) resolve only after the owning phase passes `phase_acceptance_gate` — not at raw ship-green.
- Under file contention, prefer landing phases 1–2 before later doc-only phases.
- Issue-store gap units reach **resolved** via this post-merge closure loop (`close-delivery-units`), not from INDEX projection edits alone (see `living-status` timing gate).

1. Confirm post-merge context (merged PR or explicit user acknowledgment).
2. Run the same chain; `reconcile` without `--require-merge` may mark INDEX `complete` when appropriate.
3. **Planning-store closure (PRD 059 R16–R24)** — resolve linked PRD, tasks, brainstorm, and gap
   units via `sw-edges`/frontmatter linkage, then close them in the planning store:

   ```bash
   python3 scripts/planning_store.py close-delivery-units --prd-unit <prd-unit-id>
   ```

   Preview without mutation: add `--dry-run`. On partial failure, retry with the printed `resumeCommand`.
   The JSON report includes `considered`, `closed`, and `skipped` (with `reason` per skip); phase sub-issues
   close via deliver-ledger refs with live issue-store fallback (`wave_deliver.py closure-close-phases`).
   Gap units close last (delivery-grade evidence only — related-only gaps are skipped with reason).
   Cache invalidation runs unconditionally after the loop.
   COMPLETION-LOG/INDEX file updates below remain additive — this step does not replace them.
4. Report memories written/updated and handoff to next phase.

## Stop conditions

- User halts at retro or compound approval gates when `compound.autonomy: supervised` (default).
- Under `compound.autonomy: auto`, skip approval / "did you merge?" prompts only — not memory or rule-class gates.
- Memory provider unreachable (fail-closed per R7).
- `reconcile-status.py` errors on frozen PRD guard.

**Communication intensity:** full

**Model tier:** inherit — resolve delegated atomics via `python3 scripts/resolve-model-tier.py --command <child-slug>`; do not dispatch on bare `--command sw-retrospective`.

## Guardrails

- **Never merge** or force-push.
- **Delegates** — do not bypass atomic command guardrails.
- **Never auto-promote rule-class memories** (R8) — rule writes require user confirmation +
  `/sw-memory-audit` allowlist; pre-merge `record-premerge` stamps `ruleClassPromotion: human-gated`.
- Redact before any memory persist (`scripts/memory-redact.py`).
- Frozen PRDs never modified by status reconcile (except permitted checkbox progress on task files).
- Pre-merge completion is **`completed-pending-merge`** until merge detection — a declined human merge must
  not report `complete` or `merged` (R11).

## Handoff

- **Pre-merge:** `/sw-deliver` terminal PR prepare/gate; human merges; loop suggests `/sw-cleanup` when
  merge detected.
- **Post-merge:** stack next phase via workflow sequencing.

## Automated merge-boundary close-out (PRD 070 R29)

After a terminal delivery PR merges to the default branch, planning units in the delivery set (PRD, task
list, brainstorm, absorbed gaps) close automatically at the merge boundary. Close-out correctness derives
from the completeness audit in `scripts/planning_store.py` — partial closure is never green.

### Triggers

| Layer | When | Entrypoint |
| --- | --- | --- |
| **In-session self-wake** | Conductor terminal gate while deliver state is `completed-pending-merge` and merge is detected within the watch window | `python3 scripts/deliver_closeout.py self-wake-poll --run-id <sw-deliver-<prd>-<slug>>` (armed via `DELIVER_WAKE_<run-id>` sentinel) |
| **CI fallback** | Push to `main` after the operator merges the terminal PR (post-session) | `.github/workflows/deliver-closeout.yml` → `python3 scripts/closeout_ci.py run` |
| **Manual / post-merge retrospective** | Operator runs `/sw-retrospective --post-merge` or retries a partial apply | `python3 scripts/planning_store.py close-delivery-units --prd-unit <id>` |

The in-session fast-path and CI driver both resolve the delivery via the immutable PR-to-delivery mapping
recorded at terminal-PR creation (`.sw/deliver-closeout/pr-delivery-map/`) — never slug or branch heuristics.
A non-delivery merge to `main` cleanly no-ops (`skipped: no-delivery-mapping`).

### Operator surfaces

- Preview without mutation: `python3 scripts/planning_store.py close-delivery-units --prd-unit <id> --dry-run`
- On `verdict: not-ready`, retry **only** via the printed `resumeCommand` (same rule as **Closure-audit resume**
  above).
- Closure manifests and optional post-audit markers persist under `.sw/deliver-closeout/` (see `.sw/layout.md`).

CI observe-only rollout: the workflow runs `closeout_ci.py --mode observe` until the repository variable
`DELIVER_CLOSEOUT_CI_GATE` flips to `mutate`. Mutating steps require `SW_PLANNING_ISSUES_TOKEN` (see config
schema `planning.store.issues.credentialContract`).

## Post-merge INDEX safety (A1)

Post-merge compounding uses `completion finalize-if-merged` only. On failure, resume with the printed `resumeCommand` — do **not** fall back to bare `reconcile-status.py reconcile` on `main`. Single-unit bookkeeping belongs on a docs branch.
