---
brainstorm: docs/brainstorms/2026-06-26-in-loop-retrospection-and-adaptive-replanning-requirements.md
date: 2026-06-26
topic: in-loop-retrospection-and-adaptive-replanning
frozen: true
frozen_at: 2026-06-27
---
# PRD 025 — In-loop retrospection and adaptive plan insertion

## Overview

Shipwright runs a retrospective once per deliver run (per PRD), at the terminal boundary — not once per
implementation loop (per phase). Per-phase **defect** handling already exists (`gap-check` → `verify` →
`review` → `stabilize`, plus post-merge incremental verify with revert and blast-radius), but per-phase
**process retrospection** and **learning compounding** do not, and a high-severity issue discovered mid-run
has no autonomy-preserving response beyond the existing stabilize path.

This PRD adds two capabilities to `/sw-deliver` phase-mode, derived from the frozen-namespace brainstorm
(R1–R25):

1. **Non-halting per-phase learning capture** that mines existing run signals plus a thin qualitative
   record, compounds within a run (feeding later phases' pre-work), and synthesizes once at the terminal
   retrospective.
2. **Adaptive plan insertion** — when a phase surfaces a qualifying issue, the loop grows the remaining plan
   with a validated remediation unit (`phase 1 → hi-sev-fix → phase 2 → …`) instead of pausing.

The design is bounded by the project's existing contracts: the conductor "no routine halts" invariant
(009 R11), the deterministic safety kernel and plan-validation gate (022), and frozen-spec discipline
(amendments only, human-gated scope/rule promotion). Governance of scope-changing fixes binds to the
**terminal PR human merge gate that already exists** (asynchronous, batched), with an evidence-gated opt-in
to fuller autonomy following the Progressive-Trust elevation asymmetry (elevation is a human decision;
reduction may be automatic).

This is **PRD-of-record for a new capability** that *consumes* (does not re-author) PRD 022's
`wave.sh plan validate` gate + kernel classification and PRD 023's per-phase run records / `benefitMetric` /
plan surfacing, and **explicitly extends PRD 022 R34** ("neither tier is re-proposed mid-run") to permit
governed mid-run insertion.

## Goals

1. Capture per-phase learnings without pausing the deliver loop, compound them within the run, and
   synthesize them once at the terminal retrospective into the existing `/sw-retrospective` chain.
2. Let the loop respond to a high-severity in-phase discovery by inserting a validated remediation unit into
   the remaining plan rather than halting — dependency-scoped and kernel-gated.
3. Keep frozen-spec discipline and the conductor autonomy contract intact: scope-changing fixes are governed
   at the existing terminal gate by default, with a single opt-in to full-auto; no new routine per-phase
   pause is introduced.

## Non-Goals

- Reintroducing any routine per-phase pause (conductor R11 is inviolable).
- Re-authoring the conductor loop (009/017), the kernel/gate/guidelines (022), the selector (021), the
  durable driver (007), the retro/compound chain (014), or the benefit metric (023) — all consumed.
- A synchronous mid-run human approval for routine scope changes (the terminal gate absorbs review).
- An external "messaging bridge" for live async approval (FORGE L3 style) — terminal-gate review suffices
  for v1.
- Turning adaptive insertion on by default and/or full-auto scope authoring by default — both opt-in /
  evidence-gated.
- Adaptive insertion for single-phase `/sw-ship` and the non-deliver orchestrators (`/sw-debug`, `/sw-doc`,
  `/sw-feedback`) — v1 targets `/sw-deliver` phase-mode (capture may apply trivially elsewhere; insertion
  requires a multi-phase plan).
- A standalone Progressive-Trust scoring engine — v1 uses a simple operator opt-in, not behavioral scoring.

## Requirements

R-IDs carried forward verbatim from the frozen-namespace brainstorm
(`docs/brainstorms/2026-06-26-in-loop-retrospection-and-adaptive-replanning-requirements.md`).

### A. Per-phase capture + within-run compounding + terminal synthesis (owned)

- **R1** After each phase reaches a terminal `status.json`, the deliver loop records a structured per-phase
  learning artifact **without pausing**; the conductor `next.action` advances exactly as today (capture adds
  no new legitimate halt).
- **R2** Capture is **existing-signal-first**: it derives from already-emitted artifacts (`run.log` events,
  `status.json`, `blockers.json`, `remediationAttempts`, gap-check escalations, stabilize re-entries,
  forward-merge conflicts) and adds only a minimal qualitative `phase-learnings` record for signals not
  otherwise logged (spec ambiguity, painful step, context-blindness); it never duplicates existing storage.
- **R3** A phase's captured learnings are available to **later phases' pre-work in the same run** (a
  read-only discovery input to the next phase's plan proposal / pre-work memory search) before the terminal
  synthesis.
- **R4** At run end, the existing `/sw-retrospective` chain **synthesizes** per-phase captures into
  phase-attributed learning candidates, performs a **single redacted compound write** through
  `memory-preflight` (redaction chokepoint preserved), and routes gaps through the existing `/sw-feedback`
  router (`GAP-BACKLOG.md` / `/sw-amend` / brainstorm) — introducing **no new memory-write path**.
- **R5** Per-phase capture is **cheap**: no model invocation (or cheap-tier only); model-cost synthesis runs
  once per run at the existing retro tier.

### B. Adaptive in-loop plan insertion (owned; extends 022 R34)

- **R6** When a phase surfaces a qualifying issue, the loop **may insert one or more remediation units** into
  the remaining plan instead of pausing; insertion is **dependency-scoped** — inline before dependents that
  require the fix, otherwise deferred to a run-end remediation unit or `GAP-BACKLOG.md`. Inline insertion is
  **added executing work, not a pause** (the loop keeps running the inserted unit); but because it serializes
  dependents behind the inserted unit's ship chain, an inline insertion that would block **>1 remaining phase**
  **defers to a run-end remediation unit by default** unless an operator opt-in (or a configured inline
  wall-clock budget) permits the inline stall.
- **R7** Every inserted unit is validated by **`wave.sh plan validate`** (kernel envelope, contention edges,
  `worktree.parallelCeiling`, guideline floor) **before dispatch**; an invalid insertion **fails closed**
  (no insertion; routed to the consolidated report). No insertion bypasses any kernel chokepoint
  (no-`main`-auto-merge, push/secret-scan, single-flight merge, `memory-preflight`, redaction).
- **R8** Discovered issues follow a **tiered escalation** policy — retry → in-scope remediation insertion →
  governed scope-changing insertion → human escalation — each tier triggering only when the prior is
  insufficient. The terminal **human-escalation** tier maps to the **existing legitimate-halt set**
  (budget/no-progress or ambiguous/destructive) or to defer-to-backlog routing — it introduces **no new
  per-phase pause class** beyond the R12 circuit-breaker.
- **R14** Inserted units are **first-class, provenance-tagged, persisted+validated** entries in the deliver
  plan and run-state; a fresh agent **resumes deterministically** a run containing inserted units from
  durable state alone (reusing 022 R7/R8) — never re-improvised on resume.

### C. Governance boundary (owned)

- **R9** The **authority boundary** is explicit and tamper-resistant: an in-scope defect remediation inserts
  **automatically** (within standing mandate); a scope-changing fix (adds/edits/retracts an R-ID, touches
  frozen-PRD scope, or changes documented behaviour) is **authority elevation** governed per R10/R11.
  Classification draws on durable signals (task-list metadata, path globs, persisted `signal_context`), not
  agent prose. **Anti-under-tagging (mechanical):** classification **unions declared metadata with the
  realized git diff** at insertion time; any touched path **outside** the declared `**File:**` union, or any
  touched frozen-PRD / documented-behaviour surface (public API/export, config-schema, or command-contract
  diff), **forces scope-changing disposition fail-closed** regardless of declared metadata. Under-declared
  overlap therefore cannot route scope-changing work as in-scope auto-dispatch.
- **R10** Under **default** configuration, a scope-changing fix may be **implemented in-loop** on a stacked
  unit and its **delta-only amendment auto-drafted (unfrozen)** with provenance, but its **frozen promotion
  is reviewed at the existing terminal PR human merge gate** — asynchronous and batched, adding **no new
  mid-run pause**. A declined review **reverts the inserted unit cleanly** (no partial frozen state).
- **R11** An operator may **elevate** scope-changing authoring to fully autonomous (auto-author + in-loop
  freeze) via an explicit, evidence-informed config opt-in; **elevation is always a human decision and never
  automatic**, while **reduction/revert** to the gated default **may be automatic** on negative signals. The
  opt-in reuses the existing autonomy-knob pattern and never bypasses a kernel chokepoint.
- **R15** **Frozen-spec integrity is preserved**: no frozen artifact is edited in place; scope changes are
  delta-only amendments per the existing layout; an auto-drafted amendment remains **unfrozen** until the
  governing gate (R10/R11) accepts it; the freeze CI contract is unchanged.

### D. Safety, defaults, and configuration (owned)

- **R12** Self-modification is bounded by an **insertion circuit-breaker** with three limits: (a) a **per-run
  cap** on inserted units, (b) a **depth limit** — depth counts **chained** insertions (an insertion that
  itself triggers a further insertion); sibling insertions from distinct phase signals do not increment depth
  but count against the per-run cap, and (c) a **cumulative semantic budget** (aggregate growth of the
  inserted `**File:**` union / touched R-ID surface) so many small under-cap insertions cannot silently drift
  scope. Exceeding any limit trips a **clean consolidated halt** (budget / no-progress class, reusing existing
  breaker machinery) — never runaway self-modification.
- **R13** Every inserted unit records **provenance** (triggering signal, severity, dependency scope,
  validation verdict, governance disposition) in the versioned plan artifact, `run.log`, the terminal
  report, and `COMPLETION-LOG.md`, so the executed plan's divergence from the frozen task list is fully
  attributable (reusing the 023 R21 plan-surfacing surface).
- **R16** A single, documented **config object** exposes **three orthogonal toggles**: (a) per-phase capture
  on/off (default **on**), (b) adaptive insertion on/off (default **off**), (c) scope-change governance mode
  (**terminal-gate** default | auto). It composes orthogonally with `orchestration.planPolicy`,
  `deliver.autonomy`, and `compound.autonomy`, and acts as a **unified disable surface** (setting capture and
  insertion off restores pre-025 behaviour); v1 introduces **no governance dimensions beyond these three**.
- **R18** The **conductor R11 invariant holds**: capture and in-scope insertion add no new legitimate halt;
  the only added halt is the insertion circuit-breaker (R12), a budget/no-progress class halt — not a
  routine per-loop pause.
- **R21** *(refines R16.)* Capture defaults **ON**; adaptive insertion defaults **OFF** (opt-in
  kill-switch). When insertion is enabled, in-scope insertion may auto-dispatch but scope-changing authoring
  stays terminal-gated (R10) until elevated (R11). Default config is byte-equivalent to today's deliver
  behaviour aside from the cheap capture record.
- **R22** *(refines R6/R8/R9.)* The insert-vs-defer decision uses a **closed, deterministic rubric** over
  durable signals. **Insert inline** when: (i) the issue is **P0/P1 on a kernel/security path** (always
  inline on **first** occurrence — severity dominates recurrence), (ii) dependent-blocking (remaining-phase
  plan edge or declared `**File:**` overlap), or (iii) recurring (identical failure signature in ≥2 phases,
  the recurrence path used only for **P2/P3**). **Defer** to a run-end remediation unit (independent) or
  `GAP-BACKLOG.md` (trivial) otherwise. Tiers map to the existing P0–P3 vocabulary; classification is
  reproducible from signals alone.
- **R23** *(refines R16.)* Any default-on flip of adaptive insertion is **benefit-gated** by a metric reusing
  023's `benefitMetric`: inline remediation that prevents a downstream phase failure scores positive; an
  inserted unit that triggers an attributed stabilize re-entry or terminal-PR red scores zero/negative; the
  rule **fails closed to OFF** on insufficient N. The metric is captured even while insertion is opt-in.
- **R25** *(refines R1/R4.)* Per-phase captures accumulate to a **run-scoped ledger** under the phase run dir
  (`phase-learnings.json`) plus a run aggregate; the **only** memory/provider write is the single redacted
  compound write at terminal synthesis (R4).

### E. Concurrency, consumption, and propagation (owned/consumed)

- **R17** The capability **consumes** 022's `wave.sh plan validate` + kernel classification and 023's
  per-phase run records / `benefitMetric` / plan surfacing, and **explicitly extends PRD 022 R34** to permit
  governed mid-run insertion. R17 is the **superseding requirement-of-record** (022 R34 → 025 R17), declared
  here and in the Decision Log; PRD 022 itself is **not** amended or edited (no current process for in-flight
  or post-freeze edits). None of the conductor loop, kernel, selector, or driver is re-authored.
- **R19** v1 targets **`/sw-deliver` phase-mode** (the multi-phase loop). Single-phase `/sw-ship` and
  non-deliver orchestrators are out of scope for adaptive insertion.
- **R24** *(refines R10/R15.)* Auto-drafted amendment files are created by the **conductor single-writer**
  under the living-doc lock in the serialized merge/bookkeeping step, late-binding the `A<k>` number; phase
  sub-agents never create amendment files (reuse 022 R32 / PRD 013 R12 living-doc serialization +
  single-writer guard).
- **R20** Documentation and emitter — author/adjust the full companion surface (closed list, mirroring 022/023):
  - **Skills:** `core/skills/deliver/SKILL.md`, `core/skills/conductor/SKILL.md`, `core/skills/retro/SKILL.md`
    (+ `core/skills/retro/references/output-contract.md` for TR3's per-phase attribution fields),
    `core/skills/feedback/SKILL.md`, and `core/skills/compound/SKILL.md` (terminal-synthesis ledger inputs, R4).
  - **Commands:** `core/commands/sw-deliver.md` (capture + optional insertion + circuit-breaker resume),
    `core/commands/sw-retrospective.md` (pre-merge ledger synthesis), `core/commands/sw-retro.md`
    (phase-attributed candidates), `core/commands/sw-amend.md` (conductor single-writer auto-draft exception).
  - **Rules:** `core/rules/sw-conductor.mdc` (insertion circuit-breaker as a budget-class legitimate halt;
    capture/in-scope insertion are not halts).
  - **Layout + schemas:** **both** `.sw/layout.md` *and* `core/sw-reference/layout.md`; `core/sw-reference/`
    schema/reference docs for `phase-learnings.json`, inserted-unit provenance on `sw-deliver-plan.json`, and
    the `wave.sh plan classify-signal` disposition shape.
  - **Guides + README:** `README.md`, `docs/guides/workflows.md`, `docs/guides/configuration.md` (capture
    default-on, insertion default-off kill-switch, scope-change governance modes, terminal synthesis).
  - Regenerate **both** dist trees (`dist/cursor/`, `dist/claude-code/`) with the freshness gate green
    (`emitter-freshness-stale-fails`). Living indexes (`INDEX.md`, `COMPLETION-LOG.md`, `GAP-BACKLOG.md`) remain
    owned by the PRD 009 living-doc currency gate and are **out of scope** for hand edits here.

## Technical Requirements

- **TR0 — Dependency gate (mechanical) + program order.** Adaptive-insertion wiring (R6–R8, R14) and the
  benefit metric (R23) consume PRD 022's `wave.sh plan validate` and PRD 023's per-phase records /
  `benefitMetric`. **Program-order gate (hard):** insertion TRs (TR4–TR6, TR8, TR10) are blocked until
  022 TR2/TR4/TR5 (plan validate, two-tier persist/resume, kernel classification) **and** 023 TR0–TR4
  (per-phase records, `benefitMetric`) are green in CI; a failing-before fixture
  (`insertion-blocked-without-022-validate`) refuses insertion enablement until 022's `wave.sh plan validate`
  is green. **The 022 R34 override is owned by this PRD (025), not by editing PRD 022:** 025 R17 is the
  superseding requirement-of-record that permits governed mid-run insertion, declared once here (R17 +
  Decision Log). PRD 022 is left untouched — no amendment and no in-flight edit, since there is no current
  process for either. Insertion implementation simply *consumes* 022's `wave.sh plan validate` as built. The **capture slice
  (R1–R5, R25)** has **no hard dependency** on 022/023 (it consumes only existing `run.log`/`status`/retro
  chain) and may land first.
- **TR1 — Per-phase capture ledger + writer.** Define `phase-learnings.json` (per-phase run dir) and a run
  aggregate; a mechanical writer mines existing artifacts (`run.log`, `status.json`, `blockers.json`,
  `remediationAttempts`, gap-check/stabilize/forward-merge signals) and appends the thin qualitative record;
  numeric/enumerated + short-text fields only. **Redaction runs via `memory-redact.py` on every ledger
  append and on each run-aggregate merge — before persist** (not deferred to the terminal write), so neither
  the on-disk ledger nor the R3 carry-forward pre-work input can carry unredacted secrets/PII mid-run; the
  single *provider/memory* write still occurs once at terminal synthesis (R4/R25). Schema home documented in
  **both** `.sw/layout.md` and `core/sw-reference/layout.md`, with a pinned reference doc under
  `core/sw-reference/` (R1, R2, R5, R25).
- **TR2 — Within-run carry-forward.** The next phase's pre-work (pre-work memory search / plan proposal
  input) reads the accumulated run-aggregate ledger read-only as a discovery input; no provider write occurs
  mid-run (R3).
- **TR3 — Terminal synthesis wiring.** Extend the `/sw-retrospective` pre-merge chain to read the run-scoped
  ledger, produce **phase-attributed** learning candidates, perform the single redacted compound write
  (`memory-preflight` + `memory-redact.py`), and route gaps via `/sw-feedback`; no new memory-write path
  (R4). The atomic `/sw-retro` output contract gains optional per-phase attribution fields.
- **TR4 — Insertion engine + plan as versioned mutable artifact.** A `wave.sh plan insert` primitive
  produces a provenance-tagged inserted unit (triggering signal, severity, dependency scope, governance
  disposition), places it by dependency scope, and **calls `wave.sh plan validate` before dispatch** using a
  **deliver-graph validation tier** (re-runs contention edges, `**File:**` overlap, `worktree.parallelCeiling`,
  and kernel reachability over the *mutated* plan graph — not only the phase-step/wave-batching tiers 022
  defines). **Transactional write ordering:** validate → stamp `pending` unit → **atomic single commit** of
  `sw-deliver-plan.json` + run-state (temp+rename) → dispatch; inserted units carry an explicit resume state
  (`pending` | `dispatched` | `merged`) so a crash at any boundary resumes exactly once (no double-dispatch /
  skip). **Insertion occurs only at a wave boundary** (or after quiescing in-flight phases) to avoid reordering
  work under running phases. One source-of-truth + writer rules documented in **both** `.sw/layout.md` and
  `core/sw-reference/layout.md`, with inserted-unit provenance + `classify-signal` disposition shapes pinned
  under `core/sw-reference/`. Provenance-tagged inserted phases are **exempt from the frozen-tasks-currency
  merge gate** (or auto-append a synthetic ledger entry) so R6 auto-dispatch is not blocked (R6, R7, R14).
- **TR5 — Deterministic severity classifier.** `wave.sh plan classify-signal` returns
  `{disposition: insert-inline|defer-runend|defer-backlog, tier: P0..P3, scopeClass: in-scope|scope-changing,
  reasons[]}` from durable signals only (plan edges, declared `**File:**` overlap, recurring failure
  signature, kernel/security path globs, persisted `signal_context`, **and the realized git diff** per R9).
  Normative rules, fixture-pinned: (a) **severity dominates recurrence** — P0/P1 on a kernel/security path
  inserts inline on first occurrence; (b) recurring-signature = identical failure signature in ≥2 phases,
  used for P2/P3; (c) `scopeClass` is computed by the R9 metadata∪diff union with a behaviour-change detector;
  (d) a scope-changing `scopeClass` is **never** routed to `defer-backlog` — it always takes the R10
  terminal-gated path. The classifier consumes an **insertion-time `signal_context`** (entry snapshot ∪
  inserted-unit declared/observed globs) persisted atomically with the insertion; absent `signal_context`
  fails closed to scope-changing (R8, R9, R22).
- **TR6 — Governance + amendment authoring.** In-scope insertion auto-dispatches. Scope-changing insertion
  splits the `/sw-amend` chain to stay non-halting (R18): **(a)** a **mechanical draft writer**
  (`wave_amend_draft.py` or equivalent) writes a **delta-only, unfrozen** amendment markdown under the
  living-doc lock with late-bound `A<k>` (R24) — **no `/sw-doc-review` or `/sw-freeze` runs in-loop**;
  **(b)** promotion to frozen happens only after the gate accepts (below). The terminal PR human gate reviews
  promotion via the existing PR body checklist; the **decline signal** is the existing terminal-gate `deny`
  (or an explicit amendment-disposition record). **Decline protocol (ordered):** decline → revert the inserted
  unit + blast-radius dependents (reuse `wave.sh revert phase`; pre-merge vs post-merge handled per existing
  revert rules, halting only if revert is unsafe) → scrub the unfrozen amendment/ledger stubs → **only then**
  run terminal synthesis / the R4 compound write, so a rejected scope never reaches memory or `COMPLETION-LOG`.
  The `auto` elevation (R11) auto-freezes in-loop **but still runs the mandatory `/sw-doc-review` floor
  (coherence + scope-guardian + security when the change touches a Security surface) before `/sw-freeze`** and
  honors the unchanged freeze CI contract — autonomy never skips review; reduction may be automatic
  (R10, R11, R15).
- **TR7 — Config surface.** Add an in-loop retrospection/insertion object to `.sw/config.schema.json` +
  `core/sw-reference/config.schema.json` + `workflow.config.example.json` (`capture: on|off` default on;
  `insertion: on|off` default off; `scopeChangeGovernance: terminal-gate|auto` default terminal-gate),
  composing with `orchestration.planPolicy` / `deliver.autonomy` / `compound.autonomy`; `/sw-init` seeding;
  unified disable surface (R16, R21). **Operator surfacing (mirror 022 TR5):** `/sw-init` doctor and
  `/sw-status` surface the object's current vs default values and composition with the other autonomy knobs.
  **Mid-run flip semantics (mirror 022 R29):** the resolved capture/insertion/governance mode is **stamped on
  deliver run-state at run start** and honored over live-config drift for the duration of the run; a live flip
  affects only the **next** run (or resume), never in-flight phases/insertions, and the recorded-vs-live state
  appears in consolidated-halt/terminal reports.
- **TR8 — Insertion circuit-breaker.** Persist `insertedUnitCount`, `insertionDepth` (chained lineage), and
  `insertedScopeDelta` (File:/R-ID union growth) in deliver run-state; enforce per-run cap, depth limit, and
  semantic-budget in `wave_deliver_loop.py` (config defaults seeded in TR7; if 023's driver no-progress
  substrate has not landed, 025 defines standalone breaker fields rather than claiming reuse). On trip emit a
  clean consolidated halt (reuse no-progress breaker / `report terminal`) whose report includes an
  **insertion-breaker block** — `insertedUnitCount`, `insertionDepth`, the cap/limit values, the triggering
  inserted-unit id(s) with provenance one-liners, the cause code, and an invokable `/sw-deliver run … resume`
  command (R12). The breaker halt is registered in the conductor legitimate-halt set (see R20 docs).
- **TR9 — Provenance + surfacing.** Inserted units and synthesized learnings appear in the plan artifact,
  `run.log`, the terminal report, and `COMPLETION-LOG.md` (reuse 023 R21 surfacing); divergence from the
  frozen task list is attributable (R13).
- **TR10 — Benefit metric (consume 023).** Capture insertion outcomes in 023's `benefitMetric` shape
  (rework-avoided vs escaped-defect attribution within the existing attribution window); a report helper
  applies the R23 decision rule and **fails closed to OFF** on insufficient N (R23).
- **TR11 — Resume integrity.** Inserted units are stamped + atomically written; a fresh agent resumes both
  the wave layer and any inserted units deterministically from durable state, including governance
  disposition (reuse 022 R7/R8) (R14).
- **TR12 — Emitter propagation + freshness.** Regenerate both dist trees for prose, schemas, config, and
  layout; freshness gate green (R20).

## Security & Compliance

- **Kernel chokepoints unchanged under insertion (R7, R17).** No-`main`-auto-merge, push/secret-scan,
  single-flight merge, `memory-preflight` routing, and range-scoped redaction remain non-skippable; every
  inserted unit passes `wave.sh plan validate` and the full executed-trace assertion (022) — proven by
  parity fixtures run with insertion enabled.
- **Frozen-spec integrity (R15, R24).** No in-place edits to frozen artifacts; scope changes are delta-only,
  unfrozen amendments until the governing gate accepts them; amendment files are created only by the
  conductor single-writer under the living-doc lock (no phase-worktree authoring).
- **Authority boundary is tamper-resistant (R9, R22).** In-scope vs scope-changing classification fires from
  durable signals (task metadata, path globs, persisted `signal_context`), not agent prose. Under-tagging
  cannot evade the gate because classification **unions declared metadata with the realized git diff** and
  fails closed to scope-changing on any out-of-declared-scope or documented-behaviour touch (R9); a
  scope-changing verdict is never routed to `defer-backlog` (R22/TR5).
- **No new routine halt (R18).** Capture and in-scope insertion add no legitimate halt; the only added halt
  is the insertion circuit-breaker (budget/no-progress class). Conductor R11 holds.
- **Redaction chokepoint preserved (R4, R25).** Exactly one redacted *provider/memory* write per run at
  terminal synthesis and no per-phase provider write; additionally, ledger content is scrubbed via
  `memory-redact.py` **on every append and aggregate merge before persist**, so mid-run carry-forward (R3)
  exposes no unredacted secrets/PII.
- **Bounded self-modification (R12).** Per-run insertion cap + depth limit prevent runaway plan growth; trip
  → clean consolidated halt with resume command.
- **Reversibility (R10, R16, R21).** Default config is byte-equivalent to today aside from the capture ledger;
  insertion off by default; the config object is a unified disable surface (three orthogonal toggles); a declined terminal review reverts the
  inserted unit cleanly.

## Success Criteria

Carried verbatim from the brainstorm (`docs/brainstorms/2026-06-26-in-loop-retrospection-and-adaptive-replanning-requirements.md`); each maps to a fixture in Testing Strategy.

- **SC1 — Autonomy preserved.** Under default config, a multi-phase deliver run with per-phase capture and
  in-scope insertions completes to the terminal human gate with **zero new mid-run pauses**.
- **SC2 — Compounding works within a run.** A learning captured in phase *k* is demonstrably available to
  phase *k+1*'s pre-work.
- **SC3 — Insertion is safe.** An inserted unit that violates a kernel ordering/chokepoint or contention edge
  is rejected fail-closed; a valid in-scope insertion dispatches and merges via the existing serialized queue.
- **SC4 — Governance boundary holds.** Under default mode, an auto-drafted amendment for a scope-changing fix
  remains **unfrozen** and surfaces at the terminal gate; a declined review reverts the inserted unit with no
  frozen residue.
- **SC5 — Bounded self-modification.** Exceeding the insertion cap or depth limit trips a clean consolidated
  halt with a resume command — never an unbounded insert loop.
- **SC6 — Full attribution.** Every inserted unit and synthesized learning is traceable in the plan artifact,
  `run.log`, terminal report, and `COMPLETION-LOG.md`.
- **SC7 — Resume integrity.** A fresh agent resumes a run containing inserted units deterministically from
  durable state, including governance disposition.
- **SC8 — Default parity.** With capture ON and insertion OFF (default), a deliver run is byte-equivalent to
  today's behaviour apart from the cheap capture ledger **and** the read-only carry-forward of prior-phase
  learnings into later-phase pre-work (R3); disabling capture restores prior pre-work inputs with no code
  change. (Artifact parity and pre-work-input parity are asserted separately — see SC8a/SC8b fixtures.)
- **SC9 — Deterministic rubric.** The insert-vs-defer classifier yields identical verdicts from identical
  durable signals, and a non-blocking issue is never inserted inline.

## Testing Strategy

Failing-before / passing-after fixtures wired into `verify.test` (mirrors 022/023 rigor).

| Fixture | Asserts | R/TR |
|---|---|---|
| `capture-no-pause` | per-phase capture record written; `next.action` advances with no halt | R1, R18 |
| `capture-existing-signal-first` | capture mines existing artifacts; no duplicate signal storage | R2 |
| `capture-carry-forward-next-phase` | phase *k* learnings present in phase *k+1* pre-work input | R3, TR2, SC2 |
| `capture-no-per-phase-provider-write` | zero provider writes mid-run; single redacted write at terminal | R4, R25, TR3 |
| `capture-default-on-parity` (SC8a) | default artifact stream byte-equivalent aside from capture ledger | R21, SC8 |
| `capture-prework-input-parity` (SC8b) | with capture disabled, later-phase pre-work inputs match pre-025 | R3, R21, SC8 |
| `capture-no-model-invocation` | per-phase capture performs no non-cheap model call | R5 |
| `autonomy-no-midrun-pause-default` | default run with capture + in-scope insertion: zero user-visible halts | R18, SC1 |
| `config-killswitch-offstates` | capture-off restores pre-025 behaviour; insertion-off blocks insert path | R16, TR7 |
| `capture-ledger-scrubbed-before-persist` | redaction runs on every ledger append + aggregate merge | R4, R25, TR1 |
| `capture-carry-forward-no-cleartext-secrets` | carry-forward pre-work input contains no unredacted secrets/PII | R3, TR2 |
| `insertion-blocked-without-022-validate` | insertion enablement refused until `wave.sh plan validate` green | TR0 |
| `insertion-validates-before-dispatch` | inserted unit rejected fail-closed on kernel/contention violation | R7, SC3 |
| `insertion-inscope-auto-dispatch` | valid in-scope insertion dispatches + merges via serialized queue | R6, SC3 |
| `severity-rubric-deterministic` | identical signals → identical disposition; non-blocking never inline | R22, SC9 |
| `severity-rubric-p0-kernel-first-inline` | single-occurrence P0/P1 on kernel/security path inserts inline | R22 |
| `insertion-deliver-graph-validate` | deliver-graph mutation re-validates contention/ceiling/kernel reachability | R7, TR4 |
| `insertion-scopechange-under-tag-rejected` | realized diff outside declared `**File:**` union forces scope-changing | R9, R22 |
| `insertion-behaviour-change-forces-scopechange` | API/export/config-schema/command-contract diff classifies scope-changing | R9 |
| `insertion-inline-stall-budget` | inline insert blocking >1 phase defers to run-end unless opt-in / budget set | R6, R18 |
| `insertion-atomic-resume-crash` | crash at each insert boundary resumes once (pending\|dispatched\|merged); no double-dispatch | R14, TR11 |
| `insertion-merge-not-blocked-by-tasks-currency` | provenance-tagged inserted phases exempt from frozen-tasks-currency gate | R6 |
| `insertion-exec-fidelity-inserted-phase` | inserted phase runs under the step driver; out-of-order kernel step halts | R7, R17 |
| `insertion-scopechange-terminal-gated` | scope-change amendment stays unfrozen; surfaces at terminal gate | R9, R10, SC4 |
| `insertion-scopechange-decline-reverts` | declined terminal review reverts inserted unit; no frozen residue | R10, R15, SC4 |
| `insertion-elevation-human-only` | full-auto authoring requires explicit opt-in; never auto-elevates | R11 |
| `amendment-single-writer-serialized` | phase-worktree amendment-create refused; conductor late-binds `A<k>` | R24, TR6 |
| `insertion-circuit-breaker-halt` | exceeding insertion cap/depth → clean consolidated halt + resume cmd | R12, SC5 |
| `insertion-provenance-surfaced` | inserted unit in plan, run.log, terminal report, COMPLETION-LOG | R13, TR9, SC6 |
| `insertion-resume-deterministic` | fresh agent resumes inserted units + governance disposition | R14, TR11, SC7 |
| `benefit-metric-insertion-fail-closed` | default-on flip gated; fails closed to OFF on insufficient N | R23, TR10 |
| `kernel-parity-under-insertion` | 022 chokepoint parity holds with insertion enabled | R7, R17 |
| `emitter-freshness-stale-fails` | stale dist artifact fails the freshness gate | R20, TR12 |

Success criteria SC1–SC9 are enumerated in the **Success Criteria** section above; each maps to a fixture in this table.

## Rollout Plan

1. **Capture slice first (no hard dep).** Land R1–R5/R25 (capture ledger, carry-forward, terminal synthesis)
   with capture **ON** by default; prove default parity (`capture-default-on-parity`).
2. **Insertion slice behind the dependency gate (TR0).** Land R6–R14/R22/R24 with adaptive insertion **OFF**
   by default; exercise only in fixtures + opt-in/hermetic repos; require `wave.sh plan validate` (022)
   green first.
3. **Benefit soak (R23).** Capture the `benefitMetric` while insertion is opt-in; pre-register the
   threshold/cohort during the soak (as 023 does); a default-on flip requires a positive, sufficient-N
   outcome — else insertion stays opt-in indefinitely.
4. **Elevation is opt-in only (R11).** Full-auto scope authoring is never defaulted; reduction to the gated
   default may be automatic on negative signals.
5. **Kill-switch.** The config object disables capture and/or insertion with no code change.

## Decision Log

- **Capture-only baseline is non-halting; terminal synthesis** (brainstorm): preserves conductor R11;
  rejected a halt-and-improve-per-phase model (breaks autonomy, multiplies cost).
- **Existing-signal-first capture** (brainstorm): mine `run.log`/`status`/`blockers` + a thin qualitative
  record; rejected a rich new capture pipeline for v1.
- **Adaptive insertion via scoped replanning** (brainstorm; 2026 best-practice convergence): grow the plan
  with a validated remediation unit instead of pausing; dependency-scoped (inline vs deferred).
- **Authority boundary on the Progressive-Trust elevation line** (brainstorm): in-scope = standing mandate
  (auto); scope-changing = authority elevation (governed).
- **Default governance = review at the existing terminal gate; opt-in to full-auto** (brainstorm): binds
  governance to the one mandatory human gate per run, so the default is non-pausing yet human-reviewed;
  elevation is a human decision, reduction may be automatic.
- **Explicitly extend 022 R34** (brainstorm): mid-run insertion is new behaviour beyond the 022/023 envelope
  and is recorded as a deliberate superseding extension that still routes through `wave.sh plan validate`.
  The override is **owned by this PRD (025 R17)** — not by amending or editing PRD 022 (no current process
  for either). The extension is scoped to deliver phase-mode **inserted units** — it does not re-open
  wave/phase-step re-proposal.
- **Defaults: capture ON, insertion OFF; benefit-gate the flip** (OQ1/OQ3): ship insertion dark/opt-in;
  default-on requires a positive 023-style benefit metric, fail-closed to OFF.
- **Deterministic severity rubric** (OQ2): closed classifier over durable signals mapped to P0–P3; never
  agent prose.
- **Conductor single-writer for amendment creation** (OQ4): serialize amendment files under the living-doc
  lock, late-bind `A<k>` (reuse 022 R32 / PRD 013 R12).
- **Run-scoped ledger; single terminal memory write** (OQ5): no per-phase provider write.
- **Standalone PRD, not a 023/024 amendment** (OQ6): distinct cross-cutting theme; consumes the 022→024
  program rather than extending a frozen, not-started PRD.

## Open Questions

1. **`benefitMetric` threshold/cohort.** The concrete numeric thresholds and minimum N per stratum for the
   R23 default-on decision rule are **pre-registered during the soak** (as in 023), not in this PRD.
2. **Ledger schema sharing.** Whether `phase-learnings.json` is a **distinct** schema or a **shared
   extension** of 023's `dispatch-decisions.json` (both are per-phase run-dir records) — resolve at task
   planning to avoid duplicate plumbing.
3. **Config namespace.** Whether the config object lives under `orchestration.*` (alongside `planPolicy`),
   `deliver.*`, or a new `inLoop.*` key — naming only; resolve at task planning. (Default behavior and
   semantics are fixed by R16/R21.)
