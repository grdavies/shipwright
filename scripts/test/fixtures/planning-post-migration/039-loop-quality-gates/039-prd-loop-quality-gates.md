---
brainstorm: docs/brainstorms/2026-06-30-loop-hardening-requirements.md
date: 2026-06-30
topic: loop-quality-gates
frozen: true
frozen_at: 2026-06-30
visibility: public
---
# PRD 039 — Loop Quality Gates

## Overview

PRD A of the **loop-hardening** program (successor to the 2026-06-23 nine-item loop-improvement program).
It closes the post-green quality gap in the delivery loop: today per-task TDD reaches **green**
(`tdd-gate.py`) and `/sw-simplify` performs behavior-preserving deslop, but nothing evaluates whether the
freshly-green code is *worth keeping as-is*, no third **refactor** step exists, TDD can skip silently, and
agent-authored test/mocking weaknesses pass unflagged. This PRD adds: an explicit red→green→**refactor**
step (enforced consideration, signal-gated action), a pluggable coupling/cohesion **metric harness** that
emits a refactor-worthiness signal, TDD hardening (no silent skips, test-tampering + over-mock detection,
ZOMBIES test-list-first, optional mutation hook), deliberately heterogeneous review, and an agent
decision-log/provenance capture on the PR.

Scope traces to brainstorm requirements **R1–R14** (plus cross-cutting **R30–R31**). PRD B (granularity)
and PRD C (self-improving loop) are separate deliverables in the same program; this PRD does **not**
implement any of **R15–R29**.

## Goals

- Give the loop a deterministic **refactor** step after green — the step is **always run and always
  recorded** (honors red→green→refactor), while the structural *edit* is driven by a quality signal, not a
  vibe and not forced churn.
- Make structural quality (coupling/cohesion/complexity/churn) a **first-class, pluggable** signal that
  works on any host codebase, **safe-by-default (`none`)** — zero loop-behavior change until opted in.
- Eliminate **silent** TDD skips and catch the agent-specific test failure modes the 2026 research names
  (assertion rewriting, over-mocking, mock drift), with deterministic rules where possible and advisory
  flags where detection needs judgment.
- Move review toward **heterogeneous reviewers** and **captured agent reasoning** so the reviewer is not
  "the first human to ever lay eyes on this code."
- Preserve every existing safety invariant (human owns merge, deterministic gates strict, redaction).

## Non-Goals

- No auto-merge to `main`; no autonomous rule/PRD promotion (program-wide invariant).
- No **mandatory hard** quality gate by default — the structural signal is advisory unless a blast-radius
  tier explicitly promotes it.
- No bespoke metric engine beyond one built-in default provider; advanced/multi-language providers are
  third-party adapters.
- No re-implementation of shipped predecessor items (verification-gate, rca-core, spec-rigor, TDD gate,
  two-stage review, simplify/deslop, feedback-closure). The refactor step is a **distinct concern** from
  `/sw-simplify` deslop (see Technical Requirements → refactor-vs-simplify boundary).
- **Explicitly deferred to PRD B (R15–R19):** phase sizing heuristic, auto-split into smaller dependent
  units, parallelism scheduling, files-touched/path-sensitivity blast-radius axis.
- **Explicitly deferred to PRD C (R20–R29):** meta/dogfood capture channel, cross-run recurring-failure
  RCA, inefficiency scanner, capture→RCA→auto-propose, behavioral-anomaly guardrails, downstream-cost and
  loop-health metrics, **cross-run churn history** (this PRD's churn is per-change/diff-local only).
- `/sw-doc-review` persona-panel heterogeneity is out of scope; R13 applies only to the execute/ship
  review surface (`review.provider` → `review.providers`).

## Requirements

Carried forward from the brainstorm (stable R-IDs).

- **R1** The execute discipline SHALL add an explicit **refactor** step after the TDD green step
  (red→green→refactor). The step SHALL **always run and always record an outcome**; when the quality
  signal (R4) verdict is `clean`, the recorded outcome MAY be "considered — no change needed" (no forced
  edit), and when `advise`/`poor` a behavior-preserving refactor attempt is required. Any refactor edit
  re-runs verification before commit.
- **R2** The refactor step SHALL be the **enforced default** (it is never silently skipped). A *no-edit*
  outcome on a `clean` signal is recorded with `verdict: clean` and needs no justification; an operational
  **skip** (step not run) SHALL require an explicit recorded `skipReason` or the gate fails.
- **R3** A coupling/cohesion **metric harness** SHALL be a pluggable provider abstraction (analogous to
  `review.provider`), with `none` the safe default. The built-in provider activates only when
  `quality.provider` is set to `auto` or a concrete id (R6) — `none` performs no analysis and changes no
  loop behavior. `quality.provider` SHALL be registered in the capability manifest/trust model with the
  same parity as `review`/`verify` providers.
- **R4** When active, the harness SHALL emit a per-change **refactor-worthiness signal** derived from at
  least coupling, cohesion, complexity, and **per-change (diff-local) churn** for the module neighborhood
  of the files touched by the freshly-green change. The signal SHALL be a **delta vs the pre-green
  snapshot**, not absolute values, so cosmetic file splits without dependency-graph improvement do not
  register as wins.
- **R5** The signal SHALL be **advisory by default** (surfaced like a PR-test-plan advisory; non-blocking)
  and **promotable to blocking per blast-radius tier** via config. PRD A reuses the existing
  **triage tiers (Quick/Standard/Full)** for promotion; a separate files-touched/path-sensitivity axis is
  deferred to PRD B.
- **R6** The harness SHALL ship a **built-in metric provider** scoped to the host repo's **primary
  detected language**. MVP metrics are **per-change churn + a complexity proxy** for the primary language;
  coupling/cohesion are best-effort heuristics where an import/dependency graph is available and MAY be
  omitted (reported `unavailable`) otherwise. Non-primary languages and richer metrics are third-party
  adapters.
- **R7** The refactor step (R1) SHALL **consume the harness signal** (R4) when one is available; advisory
  surfacing (R5) and the refactor step are independently usable (the harness MAY run without forcing
  refactor edits, and the refactor step runs on `quality:none` recording "signal: none").
- **R8** TDD enforcement SHALL require red→green→refactor by default; the existing `skipped` escape SHALL
  require an explicit recorded `skipReason` (no silent skip). A `skipped` outcome SHALL be **rejected**
  when the bound traceability entry lists a `testScenario` for the task ref.
- **R9** The loop SHALL detect **test-tampering** against an **immutable test baseline frozen at
  traceability-bind (pre-red)** — not against `HEAD`. Detection SHALL be tiered: (a) **deterministic
  high-confidence** rules block/flag (deleted `*_test.*`/`test_*` files, net-negative `assert`/`expect`
  counts in test hunks, delete+recreate of the same test path, lowered coverage thresholds anywhere in
  repo/CI config); (b) **advisory** flags for ambiguous assertion-strength changes surfaced to stage-1
  review. The tamper check SHALL be authoritative over the self-reported `testWeakened` field (fail-closed
  when self-report disagrees with the baseline diff).
- **R10** The loop SHALL detect **over-mocking** as an **advisory** review flag (not a deterministic
  blocker) and carry **mock-realism guidance** in the agent config surface. Scan scope is defined
  (test files + fixtures + `conftest`/shared test helpers); flags target mock-to-SUT ratio and
  internal-module patching. Numeric thresholds are calibrated on fixtures (see Open Questions).
- **R11** Task/execute authoring guidance SHALL include **ZOMBIES test-list-first** prompts (Zero, One,
  Many, Boundaries, Interfaces, Exercise, Simple). Task start for a task with a `testScenario` SHALL gate
  on a **non-empty ZOMBIES checklist** in the traceability/plan record.
- **R12** The verify/quality surface SHALL provide an **optional, contract-only mutation-testing hook**
  (`verify.mutation`): when configured, it runs after green and reports surviving mutants as an **advisory**
  signal (never default-blocking). No built-in mutation provider ships in this PRD; the exclude-list is not
  agent-writable without a human gate.
- **R13** Review SHALL support **deliberately heterogeneous reviewers** via a `review.providers` array
  (back-compat: scalar `review.provider` accepted as a single-element array); the synthesizer reports the
  **severity-weighted union** of non-overlapping findings. Default remains a **single** provider;
  heterogeneous mode is opt-in. This applies to the execute/ship review surface only.
- **R14** Each PR/phase SHALL capture an **agent decision log / provenance** record (intent, alternatives
  ruled out, high-risk areas) attached to the PR to reduce reviewer intent-reconstruction cost. The record
  SHALL be **schema-validated with non-empty required fields**, **auto-populate high-risk anchors** from
  the gates (test-tamper flags, quality verdict, config changes, touched task R-IDs), and **`/sw-ship`
  SHALL fail on a missing/empty record**.
- **R30** All new gates/signals SHALL preserve human-owns-merge, human-gated promotion, and no nested
  orchestrator dispatch; automation may propose but never merge or promote. Quality/tier config SHALL be
  **frozen for the duration of a deliver run** (checksum in run-state; mid-run mutation of
  `quality.provider`/`blockingTier`/triage tier fails the gate), and any exemption is a **human-only,
  committed, expiring** entry — never silent demotion.
- **R31** All new commands/skills SHALL obey `sw-` naming, orchestrator/atomic boundaries, and the
  model-tier floor, and route external/provider context through the redaction chokepoint.

## Technical Requirements

- **Refactor step placement.** Extend `skills/execute-discipline` so the per-task loop is
  `red → green → tdd-gate → refactor → stage-1 review → stage-2 review`. The refactor step re-runs the
  configured verify command and a `simplify-gate.py`-style pre/post comparison so it stays
  behavior-preserving; a `regressed` verdict reverts the refactor edits (not the feature) and is recorded
  as `skipped` unless a human override is present. **Anti-gaming substance bar:** when `verdict` is
  `advise`/`poor` and `refactorHints` are non-empty, a recorded `ran: true` with **no metric delta** vs the
  pre-refactor harness snapshot fails the step (comment/whitespace/import-only churn does not satisfy
  refactor). Status is recorded in the **per-task execute status** (alongside the existing TDD status), with
  an optional rollup into the per-phase deliver `status.json`:
  `refactor: { ran, skipped, skipReason, signalRef, verdict, metricDelta }`.
- **Refactor-vs-simplify boundary.** Refactor (this PRD) is **per-task, pre-commit, structural-quality
  driven** by the harness signal. `/sw-simplify` deslop remains a **separate, post-review, delta-deslop**
  concern in `/sw-ship` gated by `simplify-gate.py`; it is not replaced or inlined. Stage-2 review remains
  spec-scope/naming, not structural redesign. Both `skills/execute-discipline` and `skills/simplify` docs
  are updated to state the boundary.
- **Metric harness provider abstraction.** New `quality.*` config block (`quality.provider` default
  `none`; `quality.blockingTier` default unset/advisory). Adapter contract under
  `providers/quality/<provider>.{md,sh}` mirroring `providers/review/`, with a neutral
  `core/providers/quality/CAPABILITIES.md`. The adapter consumes the changed-file set and emits a JSON
  signal validated against `core/sw-reference/quality-signal.schema.json`:
  `{ verdict: clean|advise|poor, metrics: { coupling, cohesion, complexity, churn } (each value or
  "unavailable"), perFile: [...], refactorHints: [...] }`. The built-in default provider is selected from
  repo language signals **only when `quality.provider: auto`** (or a concrete id); on `none` or unresolved
  language the outcome is `quality:none` and the loop proceeds unchanged.
- **Advisory vs blocking.** The signal surfaces through the existing advisory channel used by the PR
  test-plan (`pr-test-plan.manifest.json` / `advisoryFailingChecks` in `skills/checks-gate`), non-blocking
  by default. When the change's **triage tier ≥ `quality.blockingTier`**, a `poor` verdict blocks
  commit/merge via the **existing gate path** (`scripts/check-gate.py` consumer; never a new bespoke gate),
  and never weakens an existing required check.
- **TDD hardening.** `tdd-gate.py` gains a `--require-skip-reason` mode (default on under deliver/phase
  mode): `skipped` without `skipReason` → exit 20; `skipped` with a bound `testScenario` → rejected. A new
  `scripts/test-tamper-check.sh` compares the working tree and final diff against the **traceability-bind
  baseline hash** (test files + coverage config), emitting deterministic high-risk flags (R9a) and advisory
  flags (R9b), and is authoritative over `testWeakened`. Over-mock detection (R10) is advisory: a defined
  scan scope + ratio/fan-in heuristics surfaced to stage-1 review (thresholds in fixtures).
  Mock-realism guidance is injected into the configured `agentsFile` (default `AGENTS.md`).
- **ZOMBIES test-list.** `skills/tasks` + `skills/spec-rigor` + `skills/execute-discipline` authoring
  guidance gains a test-list-first prompt backed by a new `core/skills/spec-rigor/references/zombies.md`;
  `/sw-tasks` traceability authoring enumerates Zero/One/Many/Boundaries cases; task start gates on a
  non-empty checklist (R11).
- **Mutation hook.** Optional `verify.mutation` command key (placed beside `verifyE2e` in config); when
  set, runs after green and reports surviving mutants as advisory (never default-blocking). Documented in
  `verification-gate` evidence table.
- **Heterogeneous review.** `review.providers` (array) supersedes scalar `review.provider` (scalar coerced
  to single-element array). Phased: (1) array config + parallel adapter invocation + union dedupe in a new
  `scripts/review-synthesize.sh`; (2) generalize the per-head `reviewLanded` barrier in
  `scripts/check-gate.py` (provider-agnostic); (3) update `skills/stabilize-loop` success predicate.
  Default single provider; Standard/Full heterogeneous mode SHOULD include at least one deep/external
  reviewer.
- **Provenance / decision log.** `/sw-ship`/`/sw-pr` capture a `## Decision log` block on the PR body
  (extends `core/sw-reference/templates/pr-body.md`, validated by `scripts/git_template_lib.py` against
  `core/sw-reference/decision-log.schema.json`): required non-empty `intent`, `alternativesRuledOut`,
  `highRiskAreas` (auto-seeded from gate flags), `taskRefs`. Content passes `scripts/memory-redact.py`
  (R31, fail-closed) before persist. PR-body is the v1 storage; a committed append-only artifact is a
  documented fallback when PR context is absent.

### Documentation deliverables

Each phase ships its doc updates with the code (no drift):

- **Config/schema:** `core/sw-reference/config.schema.json` (+`quality.*`, `verify.mutation`,
  `review.providers`), `workflow.config.example.json`, `docs/guides/configuration.md` (keys + defaults),
  `core/sw-reference/capability-index.json` (`config_flag` triggers), `core/sw-reference/quality-signal.schema.json`,
  `core/sw-reference/decision-log.schema.json`.
- **Provider contracts:** `core/providers/quality/CAPABILITIES.md` + provider-authoring guidance.
- **Skills/commands/rules:** `core/skills/execute-discipline/SKILL.md`, `core/skills/simplify/SKILL.md`
  (boundary), `core/commands/sw-execute.md`, `core/rules/sw-subagent-dispatch.mdc` (refactor placement),
  `core/commands/sw-review.md` + `core/rules/code-review-automation.mdc` + `core/skills/checks-gate/SKILL.md`
  (heterogeneous review + flag surfacing), `core/commands/sw-ship.md` + `core/commands/sw-pr.md`
  (decision log), `core/skills/verification-gate/SKILL.md` (mutation), `core/skills/stabilize-loop/SKILL.md`
  (review barrier + flags), `core/sw-reference/layout.md` (status fields).
- **User-facing:** `docs/guides/workflows.md` + `README.md` updated for the red→green→refactor step
  (Phase 2).

## Security & Compliance

- All provenance/decision-log and metric-output text routes through `scripts/memory-redact.py` before
  persist or PR write (fail-closed on non-zero exit) — no secrets/tokens/transcripts leak via metrics or
  decision logs.
- Metric/quality providers are untrusted external surfaces: their output is treated as advisory data,
  embedded only in fenced `untrusted_payload` blocks when forwarded to sub-agents, never executed.
- Deterministic gates remain strict: the advisory→blocking promotion never *weakens* an existing required
  check; it can only add a block at high blast-radius tiers.
- Quality/tier config is frozen per deliver run (R30); config diffs to `quality.*`/triage tier mid-run are
  high-risk (R9-class) and fail the gate. Exemptions are human-only, committed, and expiring.
- No new network egress by default (`quality.provider: none`); built-in providers run locally.

## Success Criteria

Outcome-based (not just "the gate exists"); measured on fixtures + a dogfood pilot:

- **SC1** On the fixture corpus, every silent-TDD-skip and test-tamper scenario is caught (0 false
  negatives on the deterministic R9a set) with a bounded false-positive budget on legitimate test-fix
  fixtures (R9b advisory, not blocking).
- **SC2** On `advise`/`poor`-signal fixtures the refactor step produces a measurable structural-metric
  delta (coupling/complexity improved or recorded `clean` no-op); no-op churn on a non-empty hint set is
  rejected.
- **SC3** Heterogeneous review on a seeded fixture surfaces ≥1 finding not produced by the single-provider
  baseline (demonstrates non-overlap value) without duplicate-rule noise.
- **SC4** Decision-log capture is present and schema-valid on every shipped phase in the pilot; `/sw-ship`
  blocks on a missing record.
- **SC5** Default (`quality.provider: none`, scalar review, advisory-only) reproduces today's loop
  behavior byte-for-byte on the existing fixture suite (no regression).

Loop-health/downstream-cost metrics (review-seconds-saved, defect-escape rate) are **PRD C** scope; PRD A
records the raw signals C will aggregate.

## Testing Strategy

Fixture-driven (consistent with the existing `scripts/test/run-*-fixtures.sh` suite). New suites:

- `run-refactor-step-fixtures.sh` — red→green→refactor ordering; `regressed` reverts refactor only;
  no-silent-skip (missing `skipReason` fails); `clean` no-op recorded; anti-gaming (no metric delta on
  non-empty hints fails); status fields.
- `run-quality-provider-fixtures.sh` — `none` default proceeds unchanged (`quality:none`); `auto` built-in
  language auto-selection; signal schema + `unavailable` metrics; delta-vs-snapshot; advisory vs
  triage-tier blocking.
- `run-tdd-hardening-fixtures.sh` — silent skip rejected; `skipped` with bound scenario rejected;
  baseline-anchored tamper flags (assertion rewrite / test deletion / delete+recreate / coverage-threshold
  drop); `testWeakened` disagreement fails closed; over-mock advisory flags; ZOMBIES non-empty gate.
- `run-heterogeneous-review-fixtures.sh` — union of non-overlapping findings; severity-weighted dedup;
  scalar back-compat single-element coercion.
- `run-provenance-fixtures.sh` — decision-log schema-valid + redacted; missing record fails ship;
  high-risk anchors auto-seeded; redaction fail-closed.

Each requirement **R1–R14** maps to at least one named fixture scenario for the traceability gate at task
freeze. **R30** (config-freeze/exemption) and **R31** (naming/redaction chokepoint) carry explicit
invariant fixtures (config-mutation-mid-run fails; redaction fail-closed) rather than inherited-only
coverage.

## Rollout Plan

Phased to land safe primitives before behavior changes; **each phase ships its doc deliverables**:

1. **Phase 1 — Quality harness contract.** `quality.*` config + `none` default + signal schema + advisory
   surfacing + capability/trust registration (R3, R4 schema, R5 advisory path). **Built-in provider (R6)
   not yet active by default.** No loop behavior change when unconfigured.
2. **Phase 2 — Refactor step + built-in provider.** Add red→green→refactor to execute-discipline consuming
   the signal; built-in `auto` provider; no-silent-skip + anti-gaming bar; status fields; refactor-vs-
   simplify boundary docs (R1, R2, R6, R7). Behavior-changing only when `quality.provider` is opted in.
3. **Phase 3 — TDD hardening.** `--require-skip-reason` mode, baseline-anchored `test-tamper-check`,
   over-mock advisory + mock-realism guidance, ZOMBIES test-list + gate, optional `verify.mutation`
   contract (R8–R12).
4. **Phase 4 — Review & provenance.** `review.providers` union + decision-log/provenance capture
   (R13, R14). Triage-tier blocking promotion wired last (R5 blocking path).

Backward compatible throughout: defaults (`quality.provider: none`, scalar `review.provider`,
advisory-only) preserve today's behavior byte-for-byte until a repo opts in (SC5).

## Decision Log

- **2026-06-30** Adopted pluggable `quality.provider` (default `none`) over a built-in-only metric engine —
  matches the `review.provider` precedent and keeps Shipwright language-agnostic.
- **2026-06-30** Structural signal is advisory-by-default with **triage-tier** promotion (files-touched
  blast-radius axis deferred to PRD B) — avoids over-blocking and respects behavior-preserving philosophy.
- **2026-06-30 (doc-review synthesis)** Refactor step is **enforced consideration, signal-gated action**:
  the step always runs/records (honors `enforce_rgr`) but only forces an edit on `advise`/`poor`, with an
  anti-gaming metric-delta substance bar — resolves the R7/R1 "opt-in vs enforced" tension and the
  over-refactoring/churn risk raised by product + adversarial review.
- **2026-06-30 (doc-review synthesis)** Built-in provider activates only on `quality.provider: auto`/concrete
  id, not on the `none` default — preserves byte-for-byte backward compatibility (SC5).
- **2026-06-30 (doc-review synthesis)** Test-tamper detection anchors on an **immutable traceability-bind
  baseline** and is authoritative over self-reported `testWeakened`; detection is tiered (deterministic
  block vs advisory) to bound false blockers on legitimate test fixes.
- **2026-06-30 (doc-review synthesis)** R10 over-mock and R12 mutation are **advisory/contract-only** (no
  deterministic blocker, no built-in mutation provider) — keeps PRD A buildable and avoids false-positive
  DoS on normal DI patterns.
- **2026-06-30 (doc-review synthesis)** `review.providers` is a phased multi-adapter refactor (not a
  config-only change); default stays single-provider; heterogeneity applies to execute/ship review only,
  not the `/sw-doc-review` persona panel.
- **2026-06-30 (sequencing trade-off, product review)** PRD A ships before PRD B per the program decision;
  noted that B (granularity) attacks PR-size/reviewability and MAY run in parallel with A Phase 1–2 — left
  to the program checkpoint, not re-litigated here.

## Open Questions

1. **Over-mock thresholds (R10):** exact mock-to-SUT ratio / patched-symbol fan-in that constitutes a flag
   vs noise — calibrate on fixtures (including negative/legitimate-DI cases) before Phase 3 freeze.
2. **Built-in coupling/cohesion fidelity (R6):** for the primary language, how far beyond churn+complexity
   can the MVP credibly go (import-graph coupling) without per-ecosystem AST tooling? — resolve at
   spec-rigor clarify gate.
3. **Decision-log fallback storage (R14):** confirm the committed append-only artifact format for the
   no-PR-context case (PR body is the v1 default).
