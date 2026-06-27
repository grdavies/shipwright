---
brainstorm: docs/brainstorms/2026-06-26-guidelined-autonomous-orchestration-requirements.md
date: 2026-06-26
topic: kernel-classification-and-plan-validation
frozen: true
frozen_at: 2026-06-26
---
# PRD 022 — Kernel classification, guidelines, and plan-validation gate

## Overview

This is **PRD-2 of the four-PRD guidelined-autonomous-orchestration program** (021 → 022 → 023 → 024). It
delivers the heart of the architecture: a documented **deterministic safety kernel** vs **agent-decidable
plan policy** split, a first-class **guidelines** artifact that bounds what an agent may propose, and a
fail-closed **plan-validation gate** (`wave.sh plan validate`) — all shipped **dark** behind the
`orchestration.planPolicy` flag (default `canonical`, byte-identical to today).

It builds on PRD-021's capability manifest (the gate validates against the kernel envelope *and* the
applicable guideline, and guidelines share a validation harness with the manifest). It introduces the
agent-proposed-plan mechanism and persists validated plans as data so the deterministic driver and crash-safe
resume are preserved. It does **not** itself adopt the proposed path in any orchestrator's default behavior —
that is the PRD-023 pilot. With the flag at its `canonical` default, this slice changes nothing observable.

**Execution fidelity, not just plan validation.** Because the per-phase ship chain is *markdown-orchestrated*
today (the agent invokes each step; `ship_phase_steps.py` tracks a cursor over a hardcoded `SHIP_CHAIN`),
validating a plan *document* at entry is not sufficient for safety — an agent could still skip or reorder
steps at execution time. This PRD therefore requires a **deterministic step driver** that reads the persisted,
validated plan as the *sole* authority for the next step and **re-checks kernel ordering at each `advance`**
(R26, TR4). The kernel envelope is asserted across the **full executed trace** (conductor + phase + merge/push/
redaction transitions), not just the phase step list (R28). These are corrections surfaced in doc-review that
make the "deterministic safety kernel" claim mechanically true rather than documentary.

**Standalone value (before 023).** Even dark, this slice pays off: (a) the single-sourced kernel
classification (R28) ends silent orchestration drift — kernel membership/ordering can no longer be narrowed
without a failing test; (b) the guideline floor (R33) codifies safety-adjacent step rules as fixtures;
(c) the formalized `wave.sh plan validate` primitive de-risks the 023 pilot. **Program exit:** if PRD-023's
benefit metric (R31) shows no net benefit, the default stays `canonical` indefinitely and PRD-024 is gated —
the proposed-path machinery is retired or iterated, not adopted (brainstorm SC9). The cost of the dark period
is honest: a dual-path maintenance tax (every future orchestration change keeps both canonical parity and
proposed-path fixtures green until one path is retired).

Source brainstorm R-IDs are carried forward verbatim. This PRD owns R1–R8, R26, R28, R29, R30, R32, R33, R34,
plus the gate-scoped portions of cross-cutting R23/R24/R25. Enhancements surfaced in doc-review are folded into
Technical Requirements / Security / Testing rather than new R-IDs (the brainstorm namespace is frozen).

## Goals

1. The system is split into a documented, single-sourced **safety kernel** (non-skippable) and an enumerated
   **plan-policy** surface, with a fixture asserting the kernel's membership and ordering invariants cannot
   drift.
2. A fail-closed **plan-validation gate** validates any agent-proposed plan against the kernel envelope and
   the applicable guideline, falling back to the canonical chain (and `wave.sh schedule` for wave shape) on
   any invalid/ambiguous proposal.
3. **Guidelines** exist as a first-class, version-controlled, fixture-covered artifact that bounds the
   proposer, including a signal-conditional **floor** of mandatory non-kernel steps.
4. Agent-proposed plans (phase step plan at phase entry; conductor wave-batching at wave entry) are validated
   and persisted to the correct durable owner, so the deterministic driver and a fresh-agent resume work
   without re-invoking the model.
5. The entire mechanism ships behind `orchestration.planPolicy` (default `canonical`); with the default,
   behavior is byte-identical to today, and the flag is an instant per-repo kill-switch.

## Non-Goals

- Turning the proposed path on by default in any orchestrator — PRD-023 pilots it on `/sw-deliver`; default
  stays `canonical` here.
- The capability manifest/selector themselves — delivered in PRD-021 and consumed here.
- Intra-phase parallelism, the benefit metric, and budgets — PRD-023.
- Conductor adoption for `/sw-debug`, `/sw-doc`, `/sw-feedback` — PRD-024.
- LLM ownership of gate/merge/state decisions — explicitly excluded; the kernel stays deterministic.
- Rebuilding the durable driver / crash-safe state core (PRD-007) or the conductor loop (PRD-009) — consumed,
  not rebuilt.
- **Per-orchestrator flag *consumption*** — this PRD owns the `orchestration.planPolicy` *definition* (schema,
  default `canonical`, seeding, in-flight + resume semantics). Wiring each orchestrator to read it at proposal
  time is adoption work: `/sw-deliver` in PRD-023, `/sw-debug`/`/sw-doc`/`/sw-feedback` in PRD-024.
- **Live orchestrator call-site wiring / first production enablement of `proposed`** — PRD-023 pilot; this
  slice ships the path dark and exercises it only in fixtures and opt-in dev repos.
- **Budget/circuit-breaker *enforcement* (R22) and the benefit metric (R31)** — PRD-023; this PRD emits the
  plan-rejection signal (a minimal in-slice breaker for runaway rejection) but does not own run budgets.
- Consolidated halt/terminal-report surfacing of chosen plans (full R21) — PRD-023/024.

## Success Criteria

Measurable, PRD-local outcomes:

1. **SC1 — Canonical parity:** with `orchestration.planPolicy: canonical` (default), the full existing fixture
   suite passes byte-identical; merge is blocked if canonical parity regresses (the canonical-path
   kill-switch is the parity fixtures, not a config flip).
2. **SC2 — Kernel completeness + ordering:** a fixture rejects any plan (across the full executed trace) that
   omits an enumerated kernel chokepoint or violates an ordering invariant; adding an orchestration step not
   classified as kernel-or-plan-policy fails CI (R28, R3).
3. **SC3 — Fail-closed gate:** every invalid / ambiguous / unknown-step / contention-violating proposal falls
   back to the canonical chain (phase) or canonical waves / `wave.sh schedule` (wave), with a logged reason;
   none execute as-proposed (R6, R32).
4. **SC4 — Execution fidelity:** under `proposed`, the step driver refuses an out-of-order or
   not-in-plan step invocation and hard-halts; a skipped-kernel-step fixture halts (R26, TR4).
5. **SC5 — Resume integrity:** a fresh agent resumes two-tier plans from durable state under the *recorded*
   `planPolicy` mode + kernel/guideline versions; a corrupt/partial/stale-version plan fails closed (halt or
   canonical replacement) — never partial execution (R7, R8, R29).
6. **SC6 — Floor holds under mis-tagging:** security-sensitive work forces its floor steps even when triage
   under-tags it (path-glob + signal_context triggers), proven by a mis-tagging fixture (R33).
7. **SC7 — Harness reuse:** guideline validation rides PRD-021's manifest lint/harness (extended, not
   rewritten), proven by a shared-harness fixture (R30).

## Requirements

R-IDs carried forward from the frozen-namespace brainstorm.

### A. Safety kernel / plan-policy separation (owned)

- **R1** The architecture defines two layers with a documented hard boundary: a **deterministic safety
  kernel** and an **agent-decidable plan policy**; every orchestration concern is classified into exactly
  one layer.
- **R2** The safety kernel is enumerated and non-skippable. It includes, at minimum: durable state
  transitions and **scoped run identity**; gate evaluation (`check-gate.sh`, `verification-gate`); the
  serialized merge queue (journal + `O_EXCL` lock) and the **merge gate-check barrier**; branch/merge targets
  (**no `main` auto-merge**, human terminal-merge gate); the **push / secret-scan chokepoint** (`git-push.sh`);
  the **redaction chokepoint** and the **range-scoped redaction guard** (no bare-branch filter-branch on
  shared `main`); the **`memory-preflight` routing chokepoint** (no direct provider calls); the
  **`beforeSubmitPrompt` guardrails hook** (non-selectable, non-reorderable — consistent with PRD-021 TR5
  kernel-hook pinning); and the orchestrator / living-doc `O_EXCL` locks. No plan-policy decision, proposal,
  or config override can remove, reorder past, or bypass a kernel step.
- **R3** The plan-policy surface is **enumerated in the same single-sourced artifact as the kernel** (R28):
  which *non-safety* steps a phase runs (e.g. simplify/gap-check inclusion), the order of non-gating steps,
  intra-phase parallelization, and the wave batching of dependency-ready phases within deterministic
  contention/ceiling constraints (R32). Anything not on this surface is kernel-owned by default (fail-safe
  classification), and an **unknown step id is rejected** by the gate (closed-world vocabulary, R6).
  Intra-phase parallelization is *classified* as plan-policy here; its implementation latitude is delivered
  in PRD-023 (R15–R17).
- **R4** Kernel decisions remain deterministic: identical inputs yield identical kernel outputs, and the
  existing fixture suites continue to pin kernel behavior unchanged.
- **R28** The kernel-vs-plan-policy classification (R1–R3) is maintained as a single-sourced,
  version-controlled artifact in `core/` with one owner of record, recording kernel-step **membership**, the
  **ordering invariants** (which steps must precede which gate), the **plan-policy step enumeration**, and the
  signal-conditional **guideline floor matrix** (R33). The validated plan is a **multi-layer object** (wave
  batching + per-phase step sequences + conductor merge/push/redaction transitions); a fixture asserts that
  every enumerated kernel chokepoint is present and **reachable in the full executed trace** (defined as
  appearing in the deterministic driver-transition log before any dependent merge/push action), and that
  ordering invariants hold — not merely that the phase step list names them. A **completeness lint** fails CI
  if any step referenced by an orchestrator command/skill is absent from both enumerations, so neither
  membership nor ordering can drift silently or be narrowed without a failing test.

### B. Agent-proposed plan within a validated envelope (owned)

- **R5** For a given phase, the **phase executor** (inside the phase worktree, at phase entry) may propose a
  structured step plan derived from the applicable guideline (R30) rather than executing a single hardcoded
  chain. **Wave shape** (which dependency-ready phases batch together) is proposed separately at the
  **conductor** level and validated against deterministic contention edges + `worktree.parallelCeiling`
  (R32) — contended phases are never co-scheduled regardless of any proposal.
- **R6** A deterministic **plan-validation gate** — implemented as a dedicated `wave.sh plan validate`
  primitive (sibling to the `wave_*` modules, reachable via the shell entrypoint and fixture-tested) —
  validates proposals in **two tiers**: a **phase step plan** is checked against the kernel envelope (all
  required kernel steps present and reachable, no gate skipped, ordering satisfied), the applicable
  **guideline** (R30), and the **signal-conditional floor** (R33); a **wave-batching plan** is checked
  against contention edges + `worktree.parallelCeiling` (R32) only. The gate is **closed-world**: any
  **unknown/extraneous step id** (not in the guideline candidate set + kernel envelope) is rejected, and
  **"ambiguous" is defined** as a proposal admitting multiple valid topological orders, a partial order that
  does not cover all kernel ordering pairs, or duplicate/no-op placeholder steps. The verdict contract is
  `{verdict: pass|reject|ambiguous, reasons[]}`. It **fails closed**: phase rejections fall back to the
  canonical chain; wave rejections fall back to canonical waves (contention/dependency violation) or
  `wave.sh schedule` (over-ceiling). The gate consumes the **persisted PRD-021 `signal_context`** (not signals
  embedded in the proposal payload) and rejects proposals whose embedded signals diverge from it. Every
  rejection is logged with its reason; **persistent rejection** (N consecutive for the same phase) trips a
  minimal in-slice circuit breaker → consolidated halt, and feeds the no-progress / budget signals (R22,
  enforced in PRD-023) rather than silently burning model calls.
- **R7** Each validated plan is persisted to the **correct durable owner** (auditable, replayable) so a
  fresh agent resumes by reading the recorded plan, not by re-improvising it: the **phase** step plan is
  written to the **per-phase run dir** (executor-owned, alongside `status.json` / `ship-steps.json`), and
  the **wave-batching** plan is written to **shared run-state by the conductor only**. The single-writer
  invariant is **mechanically enforced** (not prose): shared run-state writes accept the conductor
  role/caller identity only; phase writes are scoped to the phase slug's run dir; a simulated phase
  sub-agent write to shared run-state is refused (exit 20). Each persisted plan is stamped with its
  `planPolicy` mode + `kernelVersion` + `guidelineVersion`, written atomically (temp-file + rename).
- **R8** When a fresh agent resumes mid-run, the next action is reconstructable deterministically from
  durable state + the persisted plan; no safety-affecting step depends on a prior turn's unrecorded
  reasoning. A **corrupt, partial, or stale-version** persisted plan **fails closed** — halt with cause if
  execution is already past a step the re-validated plan no longer contains, otherwise atomically replace
  with the canonical chain after re-validation — never partial execution.
- **R26** The phase executor proposes a phase's step plan **once at phase entry** (inside its worktree); the
  plan-validation gate (R6) accepts and persists it to the **per-phase run dir** (R7), after which a
  **deterministic step driver** (distinct from the conductor deliver-loop `nextAction`; this is the
  per-phase `nextStep`/`nextShipCommand`) reads the **stored plan as the sole authority** for the next step
  — never fresh per-step LLM judgment, and never the hardcoded `SHIP_CHAIN` (which becomes the canonical
  *fallback* source only). The driver **re-checks kernel ordering at each `advance`** and refuses an
  out-of-order or not-in-plan step invocation, so execution fidelity — not just plan-document validity — is
  enforced. The driver stays deterministic (reads stored data), so the crash-safe resume contract (R7/R8)
  holds without re-invoking the model.
- **R30** Guidelines are a first-class, version-controlled artifact in `core/` that bound the proposer: for
  each phase type they declare the candidate step set, which steps are required vs optional, the allowed
  reorderings, and the forbidden deviations. The proposer (R5) may select only within a guideline's declared
  latitude, and the validation gate (R6) checks the proposal against both the kernel envelope and the
  applicable guideline. Guidelines are themselves schema-validated and fixture-covered, and (like the kernel
  classification, R28) are single-sourced so latitude cannot widen silently. Guidelines and the capability
  manifest are **separate artifact types** sharing a common validation harness: guidelines bound step shape
  per phase type; the manifest selects capabilities by signal.
- **R33** Guidelines have a **floor**: independent of a guideline's declared latitude, the validation gate
  (R6) enforces signal-conditional mandatory non-kernel steps — e.g. `sw-review` is non-skippable when work
  is security-relevant — and any step the floor marks mandatory cannot be dropped or reordered past its
  constraint by a proposal. Floor triggers are **tamper-resistant**: they fire from **immutable task-list
  metadata and path globs** (e.g. `auth/**`, `payments/**`, kernel scripts/providers, `hooks.json`) **and**
  the persisted PRD-021 `signal_context` — **not** triage tags alone — so **under-tagging cannot evade the
  floor**. The floor matrix is part of the single-sourced classification (R28) and fixture-covered (incl. a
  mis-tagging fixture), so "optional" never silently includes a safety-adjacent step for high-risk work.
- **R32** The conductor may propose the **wave batching** of dependency-ready phases (which ready phases
  dispatch together), but the validation gate (R6) enforces the deterministic contention edges and
  `worktree.parallelCeiling`: enumerated contended phases (shared-migration paths, `INDEX`/doc-numbering,
  `CHANGELOG`/`version.txt`, **security-critical shared paths** — config schema, `hooks.json`,
  `scripts/wave_*`, `git-push.sh`, secret-scan) are never co-scheduled, **and undeclared file overlaps are
  auto-serialized** by intersecting the phases' declared `**File:**` paths at validation time (PRD-013 R14
  precedent) so a new shared mutable path cannot evade the ban. Any over-ceiling proposal fails closed to
  `wave.sh schedule`; any **contention/dependency violation** fails closed to **canonical waves** (re-derived
  from the frozen plan — `wave.sh schedule` alone only re-batches by ceiling and cannot fix contention).
  Wave-batching proposals are persisted to **shared run-state by the conductor only** (R7).
- **R34** The proposal lifecycle is two-tier and ordered: at **wave entry** the conductor proposes wave
  batching → validates (R6/R32) → persists to shared run-state; then for each dispatched phase, at **phase
  entry** the executor proposes the phase step plan → validates (R6) → persists to the per-phase run dir
  (R7/R26). The conductor deliver-loop drives from the stored wave layer; the per-phase step driver (R26)
  drives from the stored phase layer; neither tier is re-proposed mid-run. The lifecycle carries explicit
  **states** (`wave-validated` → `phase-plan-pending` → `phase-plan-validated`) so a crash **between tiers**
  has defined recovery: resume with a validated wave but a missing/`pending` phase plan re-runs the **phase**
  proposal+validate only (not the wave); resume (R8) otherwise reads stored plans at both levels.

### C. Rollout gate (owned)

- **R29** Plan-policy autonomy is gated by config `orchestration.planPolicy: canonical | proposed` (default
  `canonical`). This PRD owns the flag **definition** — schema, default, seeding, and the in-flight + resume
  semantics below — for a single kill-switch spanning **all** orchestrators (deliver/phase dispatch,
  `/sw-doc`, `/sw-debug`, `/sw-feedback`, and **interactive** `/sw-ship`), so there is one rollback surface
  rather than per-command knobs. Per-orchestrator *consumption* (reading the flag at each proposal site) is
  adoption work landed in PRD-023 (`/sw-deliver` pilot) and PRD-024 (remaining entry points); see Non-Goals.
  `canonical` runs the existing fixture-pinned chain byte-identical to today; `proposed` enables the
  two-tier agent-proposed-plan path (R5–R8, R26, R32, R34). The flag is a per-repo kill-switch: flipping back
  to `canonical` restores prior behavior with no code change, seeds via `/sw-init`/config schema, and composes
  orthogonally with the existing autonomy knobs (`deliver.autonomy.mode`, `phaseAckCadence`). It is read at
  **plan-proposal time** and the resolved mode (plus `kernelVersion`/`guidelineVersion`) is **stamped on each
  persisted plan** (R7): a run whose plan was already persisted under `proposed` completes under its
  **recorded** mode (honored over live config), and is **re-validated** against the *current* kernel envelope
  on resume — on re-validation failure it **fails closed** per R8 (halt or canonical replacement). A mid-run
  flip after wave persistence but before phase entry leaves the recorded wave mode authoritative for that run;
  the flip only stops *new* proposals. (The canonical-path regression kill-switch is the parity fixtures, not
  this flag — a code regression in `canonical` is caught by failing CI, see SC1.)

### D. Cross-cutting (gate-scoped slice; primary home in this PRD)

- **R23** (gate slice) No-auto-merge-to-`main`, the push/secret-scan chokepoint, single-flight merge under
  concurrency, `memory-preflight` routing, and memory/range-scoped redaction guarantees are **unchanged under
  plan-driven autonomy** — each enumerated as a kernel chokepoint (R2) and asserted by named parity fixtures
  under `planPolicy: proposed` (TR7).
- **R24** (gate slice) The kernel classification, guidelines, the `wave.sh plan validate` primitive, and the
  `orchestration.planPolicy` schema/seed are authored in `core/` and propagated to both dist trees with the
  freshness gate passing.
- **R25** (gate slice) Kernel invariants (membership + ordering), the plan-validation gate, the guideline
  floor, and the kill-switch in-flight semantics each have failing-before / passing-after fixtures wired into
  the test gate.

## Technical Requirements

- **TR1 — Single-sourced kernel classification + canonical chain source.** A version-controlled `core/`
  artifact (e.g. `core/sw-reference/kernel-classification.{md,json}`) enumerates kernel-step **membership**,
  **ordering invariants**, the **plan-policy step enumeration**, and the signal-conditional **guideline floor
  matrix**. It is the **single source** of the canonical phase chain: `ship_phase_steps.py`'s `SHIP_CHAIN` and
  the `sw-ship.md` prose chain are **emitted/derived** from it (ending today's duplication). A fixture asserts
  every kernel chokepoint is present and **reachable in the full executed trace** (driver-transition log), that
  ordering invariants hold, and a **completeness lint** fails if any orchestrator-referenced step is
  unclassified (R1–R3, R28, R33).
- **TR2 — `wave.sh plan validate` primitive.** New `wave_plan_validate.py` behind a disambiguated `wave.sh`
  branch (`plan validate` routes here; bare `plan` continues to `wave_deliver.py`, mirroring the existing
  `phase dispatch-env` nested-routing pattern). It takes a proposed plan + the **persisted PRD-021
  `signal_context`** (fail-closed if absent when a floor predicate needs it) and returns stable canonical JSON
  `{verdict: pass|reject|ambiguous, reasons[]}`. Closed-world: unknown/extraneous step ids reject. Two
  fail-closed fallbacks: phase → canonical chain (from TR1); wave **contention/dependency** violation →
  **canonical waves** re-derived from the frozen plan, wave **over-ceiling** → `wave.sh schedule` (R6, R32).
- **TR3 — Plan + guidelines schemas.** (a) `core/sw-reference/phase-step-plan.schema.json` — versioned phase
  step plan (ordered step ids, optional flags, kernel-injected non-droppable steps, `planPolicy`/version
  stamps); plus the wave-batching plan shape persisted in shared run-state. (b)
  `core/sw-reference/guidelines.{schema.json,md}` — per-phase-type candidate steps, required/optional, allowed
  reorderings, forbidden deviations, floor refs; schema-validated and **riding PRD-021's manifest lint/harness**
  (extended, not rewritten) (R30). Guideline phase-type coverage in this slice is bounded to deliver/ship phase
  types exercised by 022 fixtures; debug/doc/feedback guideline packs land with PRD-024 adoption.
- **TR4 — Two-tier persist + deterministic step driver.** Distinguish the **conductor deliver-loop**
  `nextAction` (`wave_deliver_loop.py`, drives from the stored wave layer) from the **per-phase step driver**
  `nextStep` (extends `ship_phase_steps.py`: `advance`/`resolve-resume` read the persisted phase plan's step
  list as the **sole authority**, not the hardcoded `SHIP_CHAIN`, and **reject advance to an out-of-order or
  not-in-plan step**). Phase step plan persisted to the per-phase run dir; wave-batching plan persisted to
  shared run-state with a **conductor-only writer guard** (caller-identity check); both stamped + atomically
  written (R7, R8, R26, R32, R34). Resolve the wave **authority** question: validated batching is written into
  the plan artifact (or overlaid at `compute_next_action` read time) — one source of truth, documented in
  `.sw/layout.md`.
- **TR5 — `orchestration.planPolicy` flag (definition).** Add an `orchestration` object to `.sw/config.schema.json`
  + `core/sw-reference/config.schema.json` (`planPolicy: enum[canonical, proposed], default canonical`),
  example config, and `/sw-init` seeding (doctor surfaces current vs default, never overwrites an explicit
  `proposed` without confirm). Stamp the resolved mode + `kernelVersion`/`guidelineVersion` on each persisted
  plan; resume honors the recorded stamp; re-validation failure fails closed per R8 (R29).
- **TR6 — Rejection observability + minimal breaker.** Define the durable `planRejectionLog` / per-phase
  counter schema and run-log events in this slice; persistent rejection (N consecutive for a phase) trips an
  in-slice consolidated halt and feeds the no-progress / budget signal surface (R6; budget *enforcement* owned
  by PRD-023 R22).
- **TR7 — Safety-invariant parity fixtures under proposal.** Named fixtures assert each kernel chokepoint
  unchanged when `planPolicy: proposed`: `plan-proposed-memory-preflight-required`,
  `plan-proposed-memory-redact-fail-closed`, `plan-proposed-secret-scan-before-push`,
  `plan-proposed-no-main-auto-merge`, `plan-proposed-merge-single-flight`,
  `plan-proposed-redaction-guard-range-scope`, `plan-proposed-guardrails-hook-non-selectable` (R2, R23).
- **TR8 — Single-writer enforcement.** A fixture asserts a simulated **phase sub-agent** write to shared
  run-state is refused (exit 20) while the conductor write succeeds; phase writes are scoped to the phase
  slug's run dir (R7).
- **TR9 — Call-site / integration map.** Enumerate every orchestrator proposal entrypoint reading the flag
  (deliver/phase dispatch, `/sw-doc`, `/sw-debug`, `/sw-feedback`, interactive `/sw-ship`), its canonical
  fallback, and its parity-fixture scope — even where `proposed` is fixture-only until 023/024 — so a flag
  read is not silently missed on a non-deliver path (mirrors PRD-021 TR9).
- **TR10 — Emitter propagation + freshness.** Regenerate both dist trees for the classification, guidelines,
  schemas, and config; freshness gate green (R24).

## Documentation deliverables

Companion documentation must land with the gate so the orchestration contract is not described two ways. Tasks
generation must include:

- **New:** `core/sw-reference/kernel-classification.{md,json}` (kernel membership + ordering invariants +
  plan-policy enumeration + floor matrix; the single source for `SHIP_CHAIN`), `core/sw-reference/guidelines.{schema.json,md}`,
  `core/sw-reference/phase-step-plan.schema.json` — emitted to both dist trees.
- **Config:** add `orchestration.planPolicy` to `.sw/config.schema.json` + `core/sw-reference/config.schema.json`
  + `workflow.config.example.json`; add an **Orchestration plan policy** subsection + all-keys-table entry to
  `docs/guides/configuration.md`; seed in `core/commands/sw-init.md`.
- **`.sw/layout.md` + `core/sw-reference/layout.md`:** add the kernel-classification artifact, guidelines
  artifact, validated phase-step-plan path (per-phase run dir) and wave-batching plan field (shared run-state,
  conductor-only), and the `wave.sh plan validate` primitive.
- **Orchestration prose (note the plan-policy surface behind the flag; keep canonical default):**
  `core/skills/conductor/SKILL.md` (add `wave.sh plan validate` to the mechanical-source table + two-tier
  lifecycle + durable owners), `core/rules/sw-conductor.mdc` (route proposals through `wave.sh plan validate`,
  no hand-authored plan JSON), `core/skills/deliver/SKILL.md` (phase plan persistence + driver reads stored
  plan), `core/commands/sw-deliver.md` (`plan validate` primitive), `core/commands/sw-ship.md` (proposed-mode
  caveat at phase entry; canonical default unchanged), `core/rules/sw-workflow-sequencing.mdc` (kernel vs
  plan-policy boundary), `core/skills/parallelism/SKILL.md` (wave-batching proposal + fallbacks),
  `core/rules/sw-subagent-dispatch.mdc` (plan-rejection → no-progress link). Cross-ref the PRD-021
  capability-manifest harness from the guidelines doc.
- **Guides:** `docs/guides/workflows.md` (plan-policy overview), `docs/guides/commands.md` (`plan validate`),
  `docs/guides/getting-started.md` (default-canonical disclosure); `CONTRIBUTING.md` (new fixture suites +
  regenerate-dist reminder); one-line `.sw/models-tiering.md` orthogonality note.
- **Invariants home:** treat `core/sw-reference/kernel-classification.md` as the single authoritative kernel
  invariants home (cross-linked from README/CONTRIBUTING); do **not** duplicate the kernel enumeration in a
  second file.
- **Out of scope (PRD-009 living-doc gate owns these):** `docs/prds/INDEX.md`, `COMPLETION-LOG.md`,
  `GAP-BACKLOG.md`.

## Security & Compliance

- **Deterministic safety kernel (R2, R28).** The kernel enumeration includes state transitions + scoped run
  identity, gates, the merge queue + gate-check barrier, no-`main`-merge + human terminal gate, push/secret-scan,
  redaction + range-scoped redaction guard, `memory-preflight` routing, the `beforeSubmitPrompt` guardrails hook
  (non-selectable), and orchestrator/living-doc locks. None are skippable or reorderable by any proposal or
  config override; asserted by fixture across the full executed trace, not prose.
- **Execution fidelity (R26, TR4).** The step driver reads the validated stored plan as sole authority and
  re-checks kernel ordering at each `advance`; a skipped/out-of-order step hard-halts — closing the
  "validate the document, then execute freely" gap inherent to the markdown-orchestrated chain.
- **Floor cannot be evaded by mis-tagging (R33).** Floor triggers fire from immutable task-list metadata +
  path globs **and** the persisted `signal_context`, not triage tags alone; a mis-tagging fixture proves
  security-sensitive paths force their floor steps regardless of triage tier.
- **Fail-closed validation (R6).** Invalid / ambiguous (multiple topo orders, partial order missing a kernel
  pair, duplicate/no-op) / unknown-step / contention-violating proposals revert to canonical (chain or waves)
  with a logged reason — never execute as-proposed. The gate consumes persisted signals and rejects
  proposal-embedded signal divergence (anti-spoof).
- **Single-writer of shared state (R7, TR8).** Mechanically enforced: phase sub-agents cannot write shared
  run-state (caller-identity guard); only the conductor mutates the wave-batching plan and merge queue.
- **Resume integrity (R8, R29).** Corrupt/partial/stale-version persisted plans fail closed (halt or canonical
  replacement); recorded `planPolicy` + kernel/guideline versions are honored on resume.
- **Memory / redaction unchanged (R23).** `memory-preflight` routing, the redaction chokepoint, and
  range-scoped redaction are kernel chokepoints; no proposed-path runs bypass them (named TR7 fixtures).
- **Reversibility (R29).** The `proposed` default is byte-identical to today (kill-switch = config flip); the
  *canonical*-path regression kill-switch is the parity fixtures (failing CI), not the flag.

## Testing Strategy

A fixture table (name | asserts | R-IDs | harness), wired into `verify.test` suites (R25), at PRD-013/015
rigor:

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `kernel-membership-complete` | every enumerated chokepoint present + reachable in executed trace | R2, R28 |
| `kernel-ordering-inversion-rejected` | a plan reordering past any gate/chokepoint is rejected | R28 |
| `kernel-classification-completeness-lint` | an orchestrator step absent from both enumerations fails CI | R3, R28 |
| `plan-validate-unknown-step-rejected` | closed-world: extraneous/synthetic step id rejected | R3, R6 |
| `plan-validate-ambiguous-rejected` | multi-topo-order / partial-order / no-op proposal → fail closed | R6 |
| `plan-validate-signal-divergence-rejected` | proposal signals diverging from persisted `signal_context` rejected | R6, R33 |
| `phase-fallback-canonical-chain` | invalid phase plan → canonical chain (from TR1) | R6 |
| `wave-fallback-canonical-waves` | contention/dependency violation → canonical waves (not just schedule) | R32 |
| `wave-fallback-schedule-overceiling` | over-ceiling wave proposal → `wave.sh schedule` | R32 |
| `wave-undeclared-overlap-serialized` | undeclared `**File:**` overlap auto-serialized | R32 |
| `floor-mistagging-forces-review` | security path w/ non-security triage still forces floor steps | R33 |
| `exec-fidelity-out-of-order-halt` | driver refuses out-of-order/not-in-plan `advance` → halt | R26, TR4 |
| `resume-two-tier-deterministic` | fresh agent resumes both tiers without model re-invocation | R7, R8, R34 |
| `resume-corrupt-plan-fail-closed` | corrupt/partial/stale-version plan → halt or canonical replacement | R8, R29 |
| `resume-between-tiers-rerun-phase-only` | crash after wave-validated, phase pending → re-propose phase only | R34 |
| `single-writer-phase-refused` | phase sub-agent shared-state write refused (exit 20) | R7, TR8 |
| `killswitch-canonical-parity` | `canonical` default byte-identical to today | R29, SC1 |
| `killswitch-flip-midrun-recorded-mode` | in-flight `proposed` run completes under recorded mode after flip | R29 |
| `plan-proposed-memory-preflight-required` | proposed run cannot skip `memory-preflight` | R2, R23 |
| `plan-proposed-secret-scan-before-push` | push only after secret-scan under proposed | R2, R23 |
| `plan-proposed-no-main-auto-merge` | no `main` auto-merge under proposed | R2, R23 |
| `plan-proposed-redaction-guard-range-scope` | no bare-branch filter-branch on shared `main` | R2, R23 |
| `guidelines-harness-reuse` | guideline validation rides the PRD-021 lint/harness | R30, SC7 |
| `emitter-stale-classification-fails` | stale kernel/guidelines artifact fails the freshness gate | R24 |

Each selector/gate/driver fixture ships paired **failing-before / passing-after** cases (R25).

## Rollout Plan

1. Land classification + guidelines + gate + flag with default `canonical`; prove byte-identical behavior via
   parity fixtures (no observable change).
2. Exercise the `proposed` path only in fixtures and opt-in dev repos; no orchestrator turns it on by default.
3. PRD-023 pilots `proposed` on `/sw-deliver` and measures benefit before any default change is contemplated.
4. Kill-switch (`planPolicy: canonical`) is the documented rollback; no code change required to revert.

## Decision Log

- **Deterministic kernel, agent-decidable plan policy** (brainstorm key decision): rejected a full dynamic
  rewrite that would collapse the fixture/resume/auditability model.
- **Agent proposes; gate validates; driver drives from stored plan** (R26): keeps the driver deterministic
  and resume crash-safe despite agent input.
- **Execution fidelity, not just plan validation** (doc-review feasibility/adversarial/security P0): because
  the ship chain is markdown-orchestrated, the gate alone cannot guarantee safety; the step driver reads the
  stored plan as sole authority and re-checks ordering at each `advance`, and the kernel envelope is asserted
  across the full executed trace (not the phase step list).
- **Complete kernel enumeration** (doc-review security P0): R2/R28 enumerate *all* standing chokepoints
  (`memory-preflight`, guardrails hook, locks, scoped identity, merge gate-check barrier, terminal human gate,
  range-scoped redaction), with the `SHIP_CHAIN` single-sourced from the classification artifact — so safety
  membership cannot be narrowed without a failing test.
- **Floor triggers are tamper-resistant** (doc-review security P0): path globs + persisted `signal_context`,
  not triage tags alone, so under-tagging cannot drop mandatory review.
- **Wave batching is agent-influenced but contention-bounded** (brainstorm OQ3): contended phases never
  co-schedule; over-ceiling → `wave.sh schedule`; contention/dependency violation → canonical waves (since
  `schedule` cannot re-derive contention serialization); undeclared file overlaps auto-serialized.
- **Flag *definition* here, *consumption* in 023/024** (doc-review scope-guardian): 022 owns the
  `orchestration.planPolicy` schema/default/seed + in-flight/resume semantics; per-orchestrator wiring and the
  first production `proposed` enablement are adoption work in the pilot/fan-out PRDs. Wave-tier proposals
  (R32/R34) remain *defined and gated* here per the frozen brainstorm slicing (the product reviewer's "defer
  wave-tier to 023" was considered and rejected: the gate must validate both proposal tiers before 023 can
  pilot either).
- **Ship dark behind a flag** (R29): a boundary change to a tool that merges to `main` must be operationally
  reversible; default stays byte-identical, with the dual-path maintenance tax accepted.
- **Program exit if benefit is unproven** (brainstorm SC9): if PRD-023's R31 metric shows no net benefit, the
  default stays `canonical` indefinitely and PRD-024 is gated — the proposed-path machinery is retired/iterated,
  not adopted.

## Open Questions

None — the program's open questions were resolved in the brainstorm (2026-06-26). Doc-review deferred
questions (resume-failure behavior, floor trigger source, static-vs-trace reachability) are **decided** in this
revision: resume failure fails closed per R8; floor triggers are path-glob + `signal_context`; reachability is
runtime-trace equality (R28). The `wave.sh plan validate` home (OQ2), plan granularity (OQ3), and
guideline/manifest boundary (OQ6) are settled and reflected in TR1–TR4 and R30/R32.
