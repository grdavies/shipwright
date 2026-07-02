---
brainstorm: docs/brainstorms/2026-07-02-sub-task-execute-orchestration-requirements.md
date: 2026-07-02
topic: sub-task-execute-orchestration
visibility: public
frozen: true
frozen_at: 2026-07-02
---
# PRD 053 — Sub-task execute orchestration

## Overview

Frozen task lists encode executable work at **sub-task ref** granularity (`2.1`, `2.2`, …), but `/sw-deliver`
and `/sw-ship` today dispatch **one sub-agent per phase**, looping sub-tasks inside a single `/sw-execute`
context. Medium/large phases therefore lose focus, review quality, and safe partial parallelism (dogfood:
PRD 049 phase 2 — five sub-tasks processed as one sub-agent operation).

This PRD adds a **fourth planning tier** — the **execute plan** — between phase dispatch and the phase ship
chain. At phase entry, `/sw-ship` proposes and validates a task-ref DAG (with optional runtime recursive
expansion), provisions isolated sub-branches (`feat/<slug>-phase-<pslug>--task-<ref>`), dispatches one
sub-agent per ref, integrates sub-branch tips into the phase branch via `execute_integrate.py`, and applies
task-ref blast-radius on failures — **before** the existing `sw-verify` → … → `sw-commit` chain runs once per
phase.

Scope traces to brainstorm `docs/brainstorms/2026-07-02-sub-task-execute-orchestration-requirements.md`
(requirements **R1–R31**). This PRD **supersedes the intent** of PRD 004's non-goal deferring sub-task-level
parallelism; wave-level `/sw-deliver` orchestration is unchanged. PRD 040 (author smaller phases at freeze)
remains complementary — 053 honors sub-task structure at **runtime** when authors did not split phases further.

**Depends on:** PRD 004 (phase-mode deliver), 022 (plan validate + durable plans), 023 (intra-phase caps),
039 (execute discipline + per-ref status), 040 (structural sizing signals — imported, not replaced).

## Goals

- Introduce a validated **execute-plan tier** (`execute-step-plan.json`) with DAG dispatch, durable resume,
  and `wave.py plan validate --tier execute`.
- Dispatch **one sub-agent per task ref** (and runtime-expanded children) with full execute discipline,
  isolated git context, and partial parallelism where file contention permits.
- Integrate sub-branches into the phase branch via **`execute_integrate.py`** (Option C: dedicated script +
  shared thin git helper; `wave_merge.py` phase→target path unchanged).
- Apply **task-ref blast-radius** and per-ref remediation on execute/integration failures without reverting
  green sibling integrations.
- Gate the phase ship chain on execute-plan terminal status — **one verify/review/commit per phase**.
- Wire **`deliver.autonomy.mode`** as the execute-tier automation selector (`autonomous` vs supervised plan
  confirm + fail-fast).
- Prove correctness with fixture-driven tests including a **PRD 049 phase 2 replay** scenario.

## Non-Goals

- Per-sub-task PRs or per-sub-task phase worktrees at the deliver **wave** tier.
- Auto-rewrite of frozen task lists or PRDs (PRD 040 advisory splits remain authoring-time only).
- Reimplementing wave planning, conductor loop, phase `mergeQueue`, or `merge run-next` semantics.
- Per-sub-task full `/sw-ship` chains (verify/review/commit once per phase only).
- Bypassing kernel chokepoints (`verification-gate`, `check-gate`, human terminal merge gate, `git-push.py`
  secret scan).
- Amending PRD 049 or other shipped PRDs — dogfood evidence only.
- Cross-phase sub-task parallelism (wave tier unchanged).
- ML/judgment-based dependency inference beyond deterministic prose rules.
- Rich live dashboard for per-ref progress (integrate journal + per-ref status sufficient for v1).

## Requirements

Carried forward from the brainstorm (stable R-IDs).

### Execute-plan tier

- **R1** At phase entry, the phase executor SHALL propose an **execute plan** — a validated DAG of task refs
  (authored and/or runtime-expanded) with explicit serial and parallel batch groupings — before the phase ship
  chain advances to `sw-verify`. When the execute tier is active (`execute.enabled: true`), per-ref
  `/sw-execute` dispatches (R13) **replace** the monolithic `sw-execute` step in `phase-step-plan.json`; the
  stored phase chain resumes at `sw-verify` once every execute-plan ref is terminal (R22).
- **R2** Execute plans SHALL validate through `python3 scripts/wave.py plan validate --tier execute` against a
  closed-world vocabulary and kernel ordering invariants; rejections fall back to **canonical linear order** of
  authored sub-tasks for the phase (fail-closed on ambiguous proposals).
- **R3** Validated execute plans SHALL persist at
  `.cursor/sw-deliver-runs/<phase-slug>/execute-step-plan.json` and be the sole authority for execute-tier
  resume (never chat history).
- **R4** Execute-plan proposals SHALL record `planPolicy`, `kernelVersion`, and `guidelineVersion` stamps
  consistent with PRD 022 planning-tier lifecycle patterns (wave / phase / execute).

### DAG construction and contention

- **R5** The execute-plan builder SHALL parse executable sub-tasks from the frozen task list for the active phase
  (`- [ ] N.M…` checklist items with `**File:**` and `**Expected:**`; authored refs match `\d+(\.\d+)+`).
- **R6** The builder SHALL inject mandatory serial edges when sub-task `**File:**` sets overlap, using the same
  contention primitives as `wave_deliver.py` (`inject_contention_edges`, `paths_contend`,
  `expand_generator_contention_paths`, serializing families in `skills/parallelism/SKILL.md`).
- **R7** The builder SHALL inject logical implement-before-wire edges when prose or task structure implies
  dependency (e.g. a "wire X into Y" sub-task depends on an "implement X" sub-task) — deterministic rules, not
  model judgment.
- **R8** Parallel batches SHALL be proposed only when the DAG permits and `intraPhase.parallelBudget` / global
  cap (`waveSlots + activeIntraPhase ≤ min(parallelCeiling, harnessLimit)`) allow; decisions recorded in
  `dispatch-decisions.json`.

### Runtime recursive expansion

- **R9** When a single task ref exceeds configurable structural thresholds (PRD 040 signals scoped to one ref:
  files touched, distinct dirs, traceability scenarios), the execute-plan proposer MAY synthesize child refs
  (`2.3.1`, `2.3.2`, …) in the execute plan only.
- **R10** Runtime-expanded refs SHALL never be written to frozen task lists or PRDs; parent ref traceability
  R-IDs remain satisfied when all children reach terminal status.
- **R11** Runtime expansion depth SHALL be capped by `execute.maxExpansionDepth` (default **2**); fail-closed
  when expansion would exceed the cap.

### Sub-branch provision and dispatch

- **R12** Each execute-plan unit SHALL provision an isolated sub-branch
  `feat/<slug>-phase-<pslug>--task-<ref>` (sanitized ref) off the phase branch or prior integrated tip, using
  existing worktree provision primitives where applicable.
- **R13** Each unit SHALL dispatch as a bound sub-agent Task running `/sw-execute` scoped to that ref only
  (plan-self-review, TDD, refactor gate, two-stage review per PRD 039).
- **R14** Under `execute_fan_out` conductor mode, nested execute Tasks SHALL be permitted; under
  `background_phase`, only the execute-tier carve-out applies — review panel remains inline per R45.

### Integration (Option C)

- **R15** Sub-branch tips SHALL integrate into the phase branch via `execute_integrate.py`, invoked by the phase
  executor — **not** by the deliver conductor's `merge enqueue` / `merge run-next`. Integrations on a given
  phase worktree SHALL be **serialized** (single-flight integrate queue or equivalent lock) even when execute
  refs were dispatched in parallel; integrate-journal ordering MUST be deterministic for resume (R28).
- **R16** `execute_integrate.py` SHALL use a shared thin git helper (`scripts/_sw/git_integrate.py` or
  equivalent) for fetch, `--no-ff` merge, conflict path enumeration, and bounded retry; `wave_merge.py`
  phase→target merge SHALL delegate to the same helper without behavior change.
- **R17** Integrate operations SHALL append to
  `.cursor/sw-deliver-runs/<phase-slug>/integrate-journal.json` (separate from phase `mergeQueue` /
  `mergeJournal`).

### Failure handling and blast radius

- **R18** **Execute failure** (TDD gate, review, agent crash): mark ref `blocked` in execute plan and per-ref
  execute status; apply **task-ref blast-radius** to transitive dependents in the execute DAG only; green
  siblings retain integrated commits on the phase branch.
- **R19** **Integration merge conflict**: mark losing ref(s) `blocked` with `cause: integrate:conflict`; do not
  revert successful sibling integrations; surface conflict paths and scoped remediation. On integrate failure,
  the phase worktree MUST abort the in-progress merge and return to a clean tree before the next integrate or
  ship-chain step (mirror `wave_merge.cmd_merge_exec` abort semantics).
- **R20** **Partial batch failure**: integrate successful refs immediately; unblock dependents only when deps are
  satisfied; resume from execute-plan frontier — never restart the whole phase for one ref failure.
- **R21** Per-ref `remediationAttempts` SHALL be tracked separately from phase-level counters; budget from
  `deliver.remediation.maxAttempts`.
- **R22** Phase ship chain (`sw-verify` onward) SHALL NOT start until every execute-plan ref is terminal
  (`green` or documented `skipped`).

### Autonomy selectors

- **R23** `deliver.autonomy.mode: autonomous` SHALL auto-propose, validate, persist, and dispatch execute plans
  without per-phase plan confirmation; remediate per-ref failures up to budget; halt only on legitimate halt
  conditions (conductor contract).
- **R24** `deliver.autonomy.mode: supervised` SHALL halt **once per phase** after execute-plan validation for
  human confirmation of the full DAG before dispatch; SHALL halt on first sub-task failure without
  auto-remediation.
- **R25** Under `orchestration.planPolicy: proposed`, execute plans MAY adapt (parallel batches, runtime
  expansion); under `canonical`, execute order SHALL be deterministic linear authored sub-task order with
  contention-serialization edges only.

### Phase ship chain gate and metrics

- **R26** After execute-plan completion, the phase `phase-step-plan.json` ship chain SHALL run from
  `sw-verify` through `sw-commit` (single verify/review/commit cycle per phase). The `sw-execute` step is
  satisfied by execute-tier completion when `execute.enabled: true`; the driver MUST NOT re-run monolithic
  `sw-execute` after per-ref work completes.
- **R27** `benefitMetric.stepPlanAdaptivity` SHALL record execute-plan adaptations (refs parallelized, runtime
  expansions, skipped refs) on phase terminal status.

### Resume and tokenizer

- **R28** Resume from `execute-step-plan.json` + per-ref `.cursor/sw-execute-runs/<ref>/status.json` +
  integrate journal SHALL be sufficient for a fresh agent with no chat context.
- **R29** Task-list tokenizers and scorers (`doc_format.py`, `phase_sizing.py` sub-task counters) SHALL accept
  authored refs matching `\d+(\.\d+)+`.

### Cross-cutting

- **R30** Execute plans, integrate journals, and failure reports routed to memory SHALL pass
  `scripts/memory-redact.py`; frozen artifacts SHALL never be auto-mutated.
- **R31** New workflow logic SHALL be Python stdlib-first; no new shell scripts under enforced trees.

## Technical Requirements

### Execute-plan schema and validation

- **Schema:** `core/sw-reference/execute-step-plan.schema.json` — `{ version, tier: "execute", phaseId,
  phaseSlug, refs: [{ id, branch, files[], status, parentRef? }], edges: [{ from, to, kind }], batches:
  [[refId...]], planPolicy, kernelVersion, guidelineVersion, validatedAt }`.
- **Validator:** extend `wave_plan_validate.py` with `--tier execute`; closed-world ref IDs from parsed
  frozen sub-tasks + runtime children; cycle detection; batch disjointness vs contention edges.
- **Fallback:** `execute_fallback_canonical_linear_order(task_list, phase_id)` — authored sub-task numeric
  order + injected contention edges; stamped on reject per PRD 022 patterns.
- **Kernel registry:** add execute-tier step vocabulary to `kernel-classification.json` (`planPolicySteps`
  entry `phaseType: execute`); lint via `kernel_classification_lint.py`.

### Execute-plan builder (`scripts/execute_plan.py`)

- Parse phase section from frozen task list via `doc_format.py` / shared wave_deliver parsers.
- Build contention graph per ref file-sets; inject serial edges (R6).
- Apply deterministic implement-before-wire rules (R7): title patterns (`implement`, `wire`, `fixture`),
  ordering within phase prose.
- Under `planPolicy: proposed`, compute parallel batches greedily respecting DAG + `intra_phase_dispatch.py`
  cap evaluation; record via `--record` on phase run dir.
- Under `planPolicy: canonical`, emit linear batches of width 1 except where contention forces no choice.
- **Runtime expansion:** call `phase_sizing.py` scorer scoped to single ref; when `overThreshold` and
  separable, emit synthetic children up to `execute.maxExpansionDepth`.

### Integration primitive (Option C)

- **`scripts/execute_integrate.py`:** CLI `integrate --task-ref <ref> --phase-slug <slug> [--retry]` —
  merge sub-branch tip into phase branch worktree; append integrate-journal entry; emit conflict paths on
  failure (exit 20, `cause: integrate:conflict`).
- **`scripts/_sw/git_integrate.py`:** shared `merge_branch_into(target_wt, source_ref) -> { verdict, conflicts[] }`;
  refactor `wave_merge.cmd_merge_exec` to call it (no semantic change to phase→target merges).
- **`wave.py` dispatch:** `python3 scripts/wave.py execute integrate …` aliases `execute_integrate.py` (OQ2
  resolved).

### Sub-branch lifecycle

- Provision: `worktree.py provision` with branch `feat/<slug>-phase-<pslug>--task-<ref>`, base = current phase
  branch tip (or integrated tip after prior batch).
- Teardown: sub-branch worktrees removed after successful integrate (eager teardown parity with phase
  worktrees); failed refs retain worktree for remediation until budget exhausted.

### Conductor mode carve-out (R45)

- `intra_phase_dispatch.py stamp-context` accepts `execute_fan_out` in addition to `inline` /
  `background_phase`.
- `sw-dispatch-background-phase.mdc` updated: `background_phase` disables nested Tasks **except** execute tier
  when `execute-step-plan.json` has `batches` with width > 1 or multiple refs.
- Capability index: `intraphaseSubagentDispatch: enabled` for execute partition only.

### Failure primitives (`scripts/execute_failure.py`)

- `blast-radius apply --task-ref <ref> --phase-slug <slug>` — block transitive dependents in execute plan only.
- `remediation route --task-ref <ref>` — increment per-ref attempts; surface `/sw-stabilize` scoped to phase
  branch when integration conflicts.

### Config (`workflow.config.json` + schema)

New top-level `execute` object (OQ1 resolved — separate from `tasks.sizing`):

```json
"execute": {
  "enabled": false,
  "maxExpansionDepth": 2,
  "sizing": {
    "thresholds": { "filesTouched": 3, "distinctDirs": 2, "traceabilityScenarios": 2 }
  }
}
```

Document in `docs/guides/configuration.md`, `workflow.config.example.json`, and
`core/sw-reference/config.schema.json` (and `.sw/config.schema.json` mirror).

### Planning tier enumeration (extends PRD 022)

| Tier | Artifact | Proposer | Validate | Resume owner |
|------|----------|----------|----------|--------------|
| Wave | `waveBatchingPlan` on shared run-state | Conductor at wave entry | `wave.py plan validate --tier wave` | Conductor |
| Phase | `phase-step-plan.json` | Phase executor at phase entry | `wave.py plan validate --tier phase` | Phase executor (`ship_phase_steps.py`) |
| **Execute** | `execute-step-plan.json` | Phase executor before fan-out | `wave.py plan validate --tier execute` | Phase executor (`execute_plan.py`) |

Phase entry lifecycle (ordered): `phase-step-plan` validate → `execute-step-plan` validate (when
`execute.enabled`) → execute fan-out → resume phase chain at `sw-verify`.

### Documentation deliverables

- **Layout:** `.sw/layout.md` + `core/sw-reference/layout.md` — tree nodes and registry rows for
  `execute-step-plan.json`, `integrate-journal.json`, sub-branch worktree naming, three-tier lifecycle naming,
  `benefitMetric.stepPlanAdaptivity` execute fields.
- **Kernel/schema:** `core/sw-reference/execute-step-plan.schema.json`, `kernel-classification.json` (+ emitter
  sync), `build-chain-sot.json` schema registration, PRD 022 `call-site-map.md` execute-tier row.
- **Skills/commands:** `core/skills/deliver/SKILL.md`, `core/commands/sw-ship.md`, `core/commands/sw-execute.md`
  (ref-scoped mode), `core/skills/execute-discipline/SKILL.md`, `core/skills/conductor/SKILL.md`
  (`execute_fan_out`, `wave.py execute integrate` primitive row), `core/skills/parallelism/SKILL.md`.
- **Rules:** `core/rules/sw-dispatch-background-phase.mdc` (execute carve-out),
  `core/rules/sw-subagent-dispatch.mdc`, `core/rules/sw-conductor.mdc` (integrate vs merge-queue boundary).
- **Capability index:** `core/sw-reference/capability-index.json` — execute-partition
  `intraphaseSubagentDispatch: enabled`.
- **Config:** `docs/guides/configuration.md` — `execute.*`, `execute.enabled` pilot opt-in, execute-tier
  `deliver.autonomy.mode` halt matrix, `planPolicy` × autonomy interaction.
- **PRD 004 supersede note:** deliver skill + `docs/guides/configuration.md` footnote — sub-task parallelism
  lives at execute tier under `/sw-ship` when `execute.enabled`; wave tier unchanged (D-053-7).

## Security & Compliance

- Execute plans and integrate journals are gitignored under `.cursor/` — never committed; memory writes pass
  `memory-redact.py` (R30).
- Sub-branch provision obeys existing worktree guard and secret-scan pre-push on phase branch pushes only (unchanged).
- Conductor-only phase→target merge invariant preserved (R15); execute integrate is phase-executor scoped.
- No new network egress; builders and integrators are local deterministic scripts.

## Success Criteria

Determinism + correctness:

- **SC1** PRD 049 phase 2 replay fixture: execute plan proposes batch `{2.1, 2.3}` then serial `2.2`, `2.4`,
  `2.5` with mandatory `2.2 → 2.4` edge on `scripts/wave_deliver_loop.py`.
- **SC2** Each ref produces isolated `.cursor/sw-execute-runs/<ref>/status.json` from a distinct sub-agent run.
- **SC3** Integration conflict blocks only losing ref(s) + dependents; green sibling integration retained on
  phase branch.
- **SC4** `supervised`: exactly one plan-confirmation halt per phase; `autonomous`: no plan halt on dogfood pilot.
- **SC5** Phase ship chain starts only after execute-plan terminal; one PR per phase preserved.
- **SC6** Resume from durable artifacts alone reproduces execute frontier (no chat).
- **SC7** `wave_merge.py` phase→target fixtures remain green after shared git helper extraction.

Outcome (dogfood):

- **SC8** On a replay of a medium phase (≥4 sub-tasks), `stepPlanAdaptivity` records parallel batch width ≥2
  and distinct per-ref status artifacts (SC2); optional operator note on context isolation — no blocking
  metric on raw token counts in v1.

## Testing Strategy

Fixture-driven suite `scripts/test/run_execute_orchestration_fixtures.py` (registered in PR test-plan manifest):

| Scenario | Covers |
|----------|--------|
| `execute-plan-dag-049-phase-2` | SC1 — PRD 049 phase 2 excerpt replay (OQ3) |
| `execute-plan-linear-fallback` | R2 canonical fallback on reject |
| `execute-plan-contention-serializes-shared-file` | R6 shared `wave_deliver_loop.py` |
| `execute-runtime-expansion-depth-cap` | R9–R11 synthetic oversized ref |
| `execute-integrate-clean-merge` | R15–R16 happy path |
| `execute-integrate-conflict-partial-batch` | R19–R20 sibling retained |
| `execute-blast-radius-dependents` | R18 task-ref blast-radius |
| `execute-autonomy-supervised-plan-halt` | R24 one halt per phase |
| `execute-ship-chain-gated` | R22 verify blocked until refs terminal |
| `execute-resume-frontier` | R28 crash mid-batch resume |
| `execute-resume-stale-sub-branch` | R28 rebase/reprovision after partial integrate |
| `execute-integrate-parallel-batch-serialized` | R15 single-flight integrate on phase worktree |
| `wave-merge-no-regression` | SC7 shared git helper |
| `execute-tokenizer-deep-refs` | R29 `\d+(\.\d+)+` parsing |

Synthetic mini task-list fixtures (OQ3) live under `scripts/test/fixtures/execute-orchestration/`; dogfood
replay uses a frozen excerpt from PRD 049 tasks (read-only, not mutated).

Each requirement **R1–R31** maps to at least one named scenario or an explicit invariant row above.

## Rollout Plan

1. **Phase 1 — Schema + git helper.** `execute-step-plan.schema.json`, `_sw/git_integrate.py`, refactor
   `wave_merge.cmd_merge_exec` (SC7 gate); no runtime behavior change to deliver.
2. **Phase 2 — Execute plan builder + validate.** `execute_plan.py`, `wave_plan_validate --tier execute`,
   canonical fallback; read-only dry-run from `/sw-ship` phase entry.
3. **Phase 3 — Integrate + journal.** `execute_integrate.py`, `wave.py execute integrate`, integrate-journal
   writes; unit fixtures for clean merge + conflict.
4. **Phase 4 — Dispatch + sub-branches.** Sub-branch provision, `execute_fan_out` mode, per-ref Task dispatch,
   `execute_failure.py` blast-radius + remediation counters.
5. **Phase 5 — Autonomy + ship-chain gate.** `deliver.autonomy.mode` wiring (R23–R24), R22 gate before
   `sw-verify`, `benefitMetric.stepPlanAdaptivity` (R27).
6. **Phase 6 — Docs + dogfood.** Skill/command updates, PRD 049 phase 2 replay fixture green, pilot on next
   medium phase deliver.

Backward compatible: when `execute.enabled` is false (default until pilot opt-in), phase-mode `/sw-ship` retains
today's single `sw-execute` Task behavior.

## Decision Log

- **D-053-1 (2026-07-02):** Integration primitive is **Option C** — dedicated `execute_integrate.py` + shared
  `_sw/git_integrate.py`; no `--scope execute` on `wave_merge.py`.
- **D-053-2 (2026-07-02):** Sub-branch naming **`feat/<slug>-phase-<pslug>--task-<ref>`** (sanitized).
- **D-053-3 (2026-07-02):** Config thresholds live under top-level **`execute.*`** (not `tasks.sizing`) —
  per-ref expansion is runtime deliver policy, not authoring policy.
- **D-053-4 (2026-07-02):** CLI home is **`scripts/execute_integrate.py`** with **`wave.py execute integrate`**
  dispatch alias.
- **D-053-5 (2026-07-02):** Test corpus requires **both** synthetic mini task-lists and **PRD 049 phase 2
  excerpt replay**.
- **D-053-6 (2026-07-02):** **`supervised`** emits **one plan-confirmation halt per phase** (not per batch).
- **D-053-7 (2026-07-02):** Supersedes PRD 004 non-goal on sub-task parallelism **by documented reversal** —
  wave tier unchanged; execute tier added under `/sw-ship` phase executor.
- **D-053-8 (2026-07-02):** Pilot guarded by **`execute.enabled: false` default** until fixtures + dogfood pass.

## Open Questions

1. **Pilot opt-in gate:** default is config-only (`execute.enabled`); decide at task freeze whether a
   TR0-style prerequisite fixture (mirror `pilot_dependency_gate.py`) is also required before enablement.
2. **Implement-before-wire rule table:** finalize closed title/prose patterns for R7 in
   `core/sw-reference/execute-dependency-rules.json` (referenced at freeze) — not open-ended NLP.
3. **Runtime expansion in v1:** defer R9–R11 to post-pilot milestone vs ship with MVP — decide at task freeze.
4. **Sub-branch worktree ceiling:** whether execute sub-branches use `countsTowardCeiling: false` with a
   separate budget or count against `worktree.parallelCeiling` — decide at task freeze.
