---
date: 2026-06-26
amends: docs/prds/024-orchestrator-plan-policy-adoption/024-prd-orchestrator-plan-policy-adoption.md
frozen: true
frozen_at: 2026-06-26
---

# Amendment A1: close Open Questions (R31-inconclusive, consistency-only adoption, episodic non-deliver runs)

## Overview

Parent PRD 024 (fan-out of plan-policy to `/sw-debug`, `/sw-doc`, `/sw-feedback`) freezes with three Open
Questions deliberately deferred to task planning. This amendment **decides** all three with new requirements
**R35–R37**, continuing the program R-ID namespace (program max R34). R35 crisps a wording tension and R36 is
an additive scope-reduction; R37 carries a **declared, scope-limited narrowing** (debug/feedback only) of the
parent's durable-adjacent wording for the question the parent left open (OQ3). No frontmatter
`supersedes`/`retracts` is used because nothing is wholesale-replaced (see Decision Log DL-2).

## Context

The parent's `## Open Questions` lists:

1. If R31 is **inconclusive** (insufficient N) rather than negative, is fan-out blocked, deferred, or allowed
   in canonical-wiring-only mode?
2. For orchestrators with no practical plan-shape variance (e.g. `/sw-doc` with no routine yields), is scope
   cut to manifest + selector consistency only (defer the proposed guideline pack)?
3. Do `/sw-debug`/`/sw-feedback` runs get their own durable run-record + crash-resume, or remain episodic with
   validation only at entry (TR6 path implications)?

The parent already states (Hard dependency gate / Program exit / Rollout step 0) that insufficient N → "not
adopted / program exit", while OQ1 reopened that case — a wording tension R35 closes. OQ2 is permitted in the
parent Decision Log but lacks an objective criterion. OQ3 is an unspecified TR6 path choice.

## Goals

1. Make the insufficient-N branch unambiguously fail-closed (matches and crisps the parent body).
2. Give "consistency-only" adoption an objective, fixture-backed entry criterion and a default for `/sw-doc`.
3. Bound non-deliver run durability so the fan-out does not silently acquire crash-resume scope.

## Non-Goals

- Changing the positive-R31 program gate, the default-`canonical` posture, or the separate default-flip gate
  (R29) — all parent-owned, unchanged.
- Building durable run-state / crash-resume for non-deliver orchestrators — that stays PRD-007/013 scoped.
- Re-owning the manifest/selector standalone value (PRD-021) or the kernel/gate (PRD-022).
- Editing the parent file (never written per `/sw-amend`).

## Requirements

Continue the parent namespace (program max R34).

- **R35** (closes parent OQ1). An **inconclusive** R31 outcome (insufficient N) is treated **identically to a
  non-positive** outcome: the proposed-path fan-out is **not adopted** — program exit, fail-closed. There is no
  intermediate "deferred/blocked-then-maybe" state keyed on N. This makes the parent's Hard-dependency-gate,
  Program-exit, and Rollout-step-0 wording authoritative for the insufficient-N case and removes the ambiguity
  parent OQ1 implied. *(Refinement of the parent's existing fail-closed wording — not a contradiction.)*
- **R36** (closes parent OQ2). A per-orchestrator **consistency-only** adoption mode is defined as a scope
  reduction **within** the positive-R31-gated fan-out (R35/TR0 still apply). **Once** at adoption-authoring time
  (before any parent-TR2 pack work), a **variance probe** runs a minimal fixture set — exactly the
  orchestrator's canonical-parity row plus at most one plan-shape-latitude check derived from its TR1 step
  vocabulary — and emits a boolean `canonical ≡ proposed`. The probe adds no standing CI suite beyond the named
  fixtures below.
  - **R36a** If `canonical ≡ proposed` (no plan-shape latitude), the orchestrator is adopted **consistency-only**:
    the manifest + selector + canonical-parity wiring (parent TR4 canonical path, TR5 references) land, and the
    **proposed guideline pack and any `proposed` surface for that orchestrator are deferred** (not built). This
    **qualifies** parent Rollout step 1 ("guideline pack (TR2) landed first"): TR2-first applies to
    full-adoption orchestrators (R36b) only; a consistency-only orchestrator runs the probe in its place.
  - **R36b** Otherwise, full adoption (parent TR1–TR7) proceeds.
  - **R36c** `/sw-doc` **defaults to consistency-only** pending its probe (009 audit: no routine yields); a probe
    showing latitude flips it to R36b (recorded in task notes).
  - **R36d** A consistency-only orchestrator still satisfies parent SC1/SC2 (canonical byte-parity + same
    selector); **all of that orchestrator's `proposed`-path fixtures are N/A** because no `proposed` surface
    exists. This includes every `*-proposed-*` and `*-022-parity-under-proposed` row **and** the parent SC3 halt
    rows that lack a `proposed` substring (`doc-review-halt-{manual,gated-auto}-required`,
    `doc-afterTasks-checkpoint-required`, `debug-route-confirm-halt-required`,
    `debug-rca-human-decision-halt-required`). For consistency-only orchestrators, halt preservation (R19) is
    proven on the **canonical** path (SC1 + R19), not via a non-existent `proposed` surface. The orchestrator's
    "full row set" for parent Rollout step 2 gating is the **reduced** set (canonical-parity + selector +
    isolation + R36 fixtures).
- **R37** (closes parent OQ3). `/sw-debug` and `/sw-feedback` adoption is **episodic**: the single-tier
  orchestrator-step plan is validated at entry and R21 surfacing is written into each command's **existing
  episodic run/handoff summary**. These orchestrators do **not** receive a deliver-style durable run-record or
  crash-resume in this PRD; durable run state and crash-resume remain deliver-scoped (PRD-007/013). A future
  non-deliver durable-run need is a separate slice. To avoid undeclared tension with the parent's
  durable-adjacent wording, R37 **declares the following narrowing for `/sw-debug` + `/sw-feedback` scope only**
  (the parent left this open as OQ3, so nothing is contradicted):
  - **R37a** Parent **R21** "run record" is satisfied by the episodic run/handoff summary; the parent
    `{debug,doc,feedback}-r21-surfacing` fixture asserts that path for debug/feedback, not deliver durable state.
  - **R37b** Parent **TR3** `signal_context` "durable owner" is **session/ephemeral** for these orchestrators
    (held for the single invocation, not crash-resumable).
  - **R37c** Parent **R22** budget counters are **session-scoped** for these orchestrators until/unless
    PRD-007/013 extends non-deliver durability; the driver still enforces them mechanically within the run.
  - **R37d** Parent fixture `resume-revalidates-planpolicy-mode` is **deliver / doc-handoff-scoped** and **N/A**
    for episodic debug/feedback; the amendment fixture `non-deliver-episodic-no-durable-resume` asserts no
    resume artifact exists for them.
  - **R37e** Parent **TR6** isolation holds via **ephemeral, per-invocation** namespaced scratch (abandoned on
    terminal halt; no crash-resume checkpoint; no shared-state writes; never satisfying PRD-007/013 durability).
  `/sw-doc` follows its existing tier-gated chain semantics, and the `/sw-doc → /sw-deliver` handoff inherits
  deliver durability unchanged.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---|---|---|
| `fanout-024-insufficient-n-not-adopted` | R31 inconclusive (insufficient N) refuses fan-out exactly like a negative outcome (extends parent `fanout-024-blocked-without-023-r31`) | R35 |
| `orchestrator-consistency-only-defers-proposed-pack` | variance probe `canonical ≡ proposed` → orchestrator wired manifest + selector + canonical only; no proposed pack/surface; `/sw-doc` defaults consistency-only | R36, R36a, R36c |
| `consistency-only-exempts-proposed-fixtures` | consistency-only orchestrator passes canonical-parity + selector (SC1/SC2) and treats ALL its `proposed`-path rows as N/A — `*-proposed-*`, `*-022-parity-under-proposed`, and the SC3 halt rows (`doc-review-halt-*`, `doc-afterTasks-checkpoint-required`, `debug-route-confirm-halt-required`, `debug-rca-human-decision-halt-required`); halts proven on canonical | R36d |
| `non-deliver-episodic-no-durable-resume` | `/sw-debug`/`/sw-feedback` validate at entry, surface R21 in the episodic summary, expose no durable run-record/crash-resume; `resume-revalidates-planpolicy-mode` is N/A; isolation preserved | R37, R37a–R37e |

These extend the parent Testing Strategy table; emitter/dist propagation folds into parent TR9 on task
regeneration — no new doc/dist phase.

## Implementation note (task integration)

R35–R37 join the PRD 024 spec union. The frozen task list (once generated) MUST be regenerated against the
union (R18–R23 + R35–R37) before implementation so each new requirement carries a task + traceability. R35
attaches to parent TR0 / Rollout step 0; R36 to TR2/TR4 (per-orchestrator adoption); R37 to TR4/TR6. No new
feature branch — same `feat/orchestrator-plan-policy-adoption`.

## Documentation deliverables (amendment delta)

These fold into **parent TR9** + the parent **Documentation deliverables** section on task regeneration — they
are deltas the new requirements add, not new doc surfaces. (PRD-009 living-doc indexes remain out of scope.)

- `docs/guides/configuration.md`, `docs/guides/workflows.md` — state R35 (R31 inconclusive = non-positive →
  fan-out not adopted / program exit) and R36 (consistency-only adoption via variance probe; `/sw-doc` default;
  proposed pack deferred when `canonical ≡ proposed`).
- `core/commands/sw-debug.md`, `core/commands/sw-feedback.md` — in the planned Plan-policy adoption subsection,
  state the **episodic** run model (R37): validate at entry, R21 in handoff summary, no durable run-record /
  crash-resume, ephemeral namespaced scratch.
- `core/commands/sw-doc.md` — state the consistency-only default (R36c) and proposed-fixture exemption (R36d).
- `core/skills/conductor/SKILL.md` — adoption-table extension distinguishes **run durability** (`durable`
  deliver / doc→deliver handoff vs `episodic` debug/feedback) and **adoption mode** (`full` vs
  `consistency-only`); deliver durable-artifact paths stay authoritative for `/sw-deliver` only.
- `.sw/layout.md` + `core/sw-reference/layout.md` — if TR6 paths land, document ephemeral episodic scratch for
  debug/feedback separately from deliver-scoped durable run-state.
- `CONTRIBUTING.md` — add the four amendment fixtures to the 024 fan-out suite with R-ID mapping.
- `core/rules/sw-conductor.mdc`, `core/rules/sw-naming.mdc` — one line each: debug/feedback adopt the conductor
  contract **episodically** (durable-state authority stays deliver-scoped); `/sw-doc` defaults consistency-only.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Amend rather than re-open the frozen parent | Parent 024 is frozen; the resolutions are a three-requirement delta over a settled spec, the sanctioned post-freeze path. |
| DL-2 | R35–R37 decide open questions; R37a–R37e are a **declared** scope-narrowing, not an undeclared contradiction | R35 crisps the parent's existing fail-closed wording; R36 is an additive scope-reduction. R37 narrows the parent's durable-adjacent wording (R21/TR3/R22 + resume fixture) **for `/sw-debug`/`/sw-feedback` scope only** — declared in-body because the parent left durability open as OQ3, so no settled requirement is overridden. No frontmatter `supersedes`/`retracts` is used because the narrowing is scope-limited, not a wholesale replacement. |
| DL-3 | Insufficient N = fail-closed (not adopted), no intermediate state | Conservative, matches the parent program-exit posture; avoids an under-powered metric authorizing autonomy expansion. |
| DL-4 | Consistency-only is a scope reduction *within* fan-out, still R31-gated | The standalone manifest/selector value belongs to PRD-021; here the goal is one-gate/one-selector consistency without building a proposed surface that the variance probe shows is inert. |
| DL-5 | Non-deliver runs stay episodic; durable resume remains deliver-scoped | Prevents scope creep into PRD-007/013 crash-safety; `/sw-debug`/`/sw-feedback` are short diagnose/route chains where entry-time validation + episodic surfacing suffice. |

## Open Questions

None.
