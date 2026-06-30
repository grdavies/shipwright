---
brainstorm: docs/brainstorms/2026-06-26-guidelined-autonomous-orchestration-requirements.md
date: 2026-06-26
topic: orchestrator-plan-policy-adoption
frozen: true
frozen_at: 2026-06-26
---
# PRD 024 — Orchestrator plan-policy adoption (fan-out)

## Overview

This is **PRD-4 of the four-PRD guidelined-autonomous-orchestration program** (021 → 022 → 023 → 024). The
`/sw-deliver` pilot (PRD-023) proves the mechanism end-to-end on the highest-leverage entry point; this PRD
fans the **proved** pattern out to the remaining orchestrators — `/sw-debug`, `/sw-doc`, `/sw-feedback` — so
every entry point resolves capabilities through the same selector (PRD-021) and validates its plan through the
same fail-closed gate (PRD-022), with consistent behavior and **mechanically preserved** legitimate halts.

Each adoption *references* the shared conductor contract and the shared gate/selector — it does not re-author
loop logic, re-specify the kernel, or rebuild the durable driver. It owns R18–R20 and re-asserts the
cross-cutting R21/R22/R23 per adopted orchestrator (wire-only, consuming 022/023). Source brainstorm R-IDs are
carried forward verbatim; no R-ID is renumbered or double-owned.

**Hard dependency gate (consumed from 022/023).** PRD-024 is strictly downstream of frozen 021 + 022 + 023.
Fan-out **must not begin** until (a) the named PRD-023 pilot fixtures are green in CI, **and** (b) the PRD-023
R31 decision rule returns a **positive** outcome (net steps-skipped at **equal kernel verdict**, with
sufficient N). This is enforced mechanically by TR0, not by prose.

**Program exit (consumed from 022 / brainstorm SC9).** If R31 is non-positive or N is insufficient, PRD-024 is
**not adopted** — not merely left default-off. The `proposed`-path wiring for debug/doc/feedback is retired or
iterated; the default stays `canonical` indefinitely; the standalone value of 021 (manifest/selector) and 022
(kernel/gate) is retained regardless. "Pilot proves the mechanism is *safe*" (022/023 parity) is distinct from
"R31 proves the mechanism is *valuable*" (this gate) — fan-out requires both.

**Plan model — single-tier, not deliver two-tier.** `/sw-debug`, `/sw-doc`, and `/sw-feedback` are linear
diagnose/route/normalize chains, not deliver phase executors. They adopt a **single-tier orchestrator-step
plan** (a closed-world, per-orchestrator step vocabulary mapped from each command's existing procedure),
validated by the *same* `wave.sh plan validate` gate under an orchestrator tier — **not** deliver wave-batching
or per-phase step plans (those remain 023-owned). The `/sw-doc → /sw-deliver` handoff reuses the 023 deliver
wiring unchanged.

**Scope of `/sw-ship`.** Per-phase `/sw-ship --phase-mode` is exercised by the PRD-023 deliver pilot.
Interactive (non-phase-mode) `/sw-ship` plan-policy consumption is **deferred** (tracked by the 022 TR9
call-site map) and is **not** in this PRD. The 009 adoption-audit order is cited only for legitimate-halt
classification and conductor continuation — not as the plan-schema authority.

**Two tracks.** Conductor in-turn continuation (009/017 audit deltas — DBG-A1/A2, DOC-A1, FB-A1) is already
landed and is *not* gated by R31. The **plan-policy** surface (gate + selector + guideline packs) is what this
PRD wires and is the track gated by the program-exit contract above.

## Goals

1. `/sw-debug`, `/sw-doc`, and `/sw-feedback` adopt the plan-policy surface and capability manifest by
   *reference* to the shared conductor contract — no loop/kernel/driver re-authoring.
2. Every adopted orchestrator validates its **single-tier orchestrator-step plan** through the same
   `wave.sh plan validate` gate and resolves capabilities through the same selector, so behavior is consistent
   across implement/debug/feedback/document.
3. Every legitimate halt is **mechanically preserved per orchestrator** (driver-asserted, not prose), and only
   routine post-confirmation turn-yields are removed.

## Success Criteria

- **SC1 — Canonical parity per orchestrator.** Under default `canonical`, each adopted orchestrator is
  byte-for-byte identical to its pre-024 behavior (TR9 freshness + canonical fixtures green).
- **SC2 — Gate consistency.** Each orchestrator's plan is rejected fail-closed for unknown/forbidden steps,
  floor violations, or `signal_context` divergence, using the *same* gate as deliver (no weaker path).
- **SC3 — Mechanically preserved halts.** Every legitimate halt (feedback handoff confirm + hook/monitor
  fail-closed; debug route confirm + RCA human-decision; doc-review `manual`/`gated_auto` + `doc.afterTasks`;
  exhausted budgets; main-merge) fires under `proposed`, proven by a named failing-before/passing-after fixture
  per gate.
- **SC4 — No privilege escalation.** No `proposed` plan for a diagnose/route/normalize orchestrator can include
  a deliver-only step (merge enqueue/run-next, terminal-ship, git-push, main-merge, inline `/sw-execute`);
  proven by per-orchestrator deny-list fixtures.
- **SC5 — Kernel + ingestion parity.** The orchestrator-applicable subset of the 022 TR7 parity suite passes
  under `proposed` for each adopted orchestrator, including ingestion-path redaction/memory-preflight for
  `/sw-debug` Sentry enrichment and `/sw-feedback` inbound signals.
- **SC6 — State isolation.** A fault in one orchestrator's plan mapping cannot corrupt another orchestrator's
  or an in-flight deliver run's durable state (namespaced run dirs/keys; isolation fixture).
- **SC7 — Program gate honored.** Fan-out tooling is unreachable (TR0 failing-before fixture) until the 023
  R31 decision rule passes; resume re-validates `planPolicy` mode.

## Non-Goals

- The manifest/selector (PRD-021), kernel/gate/guidelines/flag definition (PRD-022), and the deliver pilot +
  benefit metric (R31) + intra-phase parallelism (PRD-023) — all **consumed, not rebuilt**.
- Rebuilding the conductor loop (PRD-009) or the durable driver / crash-safe state core (PRD-007) — consumed
  and wired, not rebuilt.
- `/sw-ship` (interactive) and `/sw-deliver` adoption — phase-mode `/sw-ship` is covered by the PRD-023 pilot;
  interactive `/sw-ship` is deferred per 022 TR9; not re-adopted here.
- Deliver two-tier wave-batching or per-phase step plans on non-deliver orchestrators — these use a single-tier
  orchestrator-step plan only.
- Turning `proposed` on by default — the default remains `canonical`; any default flip is separately gated by
  the PRD-023 benefit metric (R29) and is out of scope here.
- Rewriting doc-review panel human gates (`gated_auto` / `manual`) or auto-merging to `main`.
- Duplicating conductor-contract / gate / selector prose into each command file.

## Requirements

### Owned — adoption + consistency + preserved halts

- **R18** `/sw-debug`, `/sw-doc`, and `/sw-feedback` adopt the plan-policy surface plus the capability manifest,
  in the sequenced order from the 009 adoption audit (debug → doc → feedback), each *referencing* the shared
  conductor contract rather than re-authoring loop, kernel, or driver logic.
- **R19** The legitimate-halt set is preserved **per entry point and mechanically (driver-asserted)**.
  Security/quality halts that **must fire before** any routed dispatch or merge — `/sw-feedback` handoff
  confirmation and hook/monitor fail-closed triggers, `/sw-debug` route confirmation and RCA human-decision,
  `/sw-doc` doc-review `manual`/`gated_auto` trade-offs and the `doc.afterTasks` checkpoint, exhausted budgets,
  and the `main`-merge gate — are distinguished from **routine post-confirmation** turn-yields. Only the latter
  are removed; the former are pinned and cannot be reclassified as routine.
- **R20** Each adopted entry point validates its single-tier orchestrator-step plan through the same
  plan-validation gate (R6) and resolves capabilities through the same selector (R10), so behavior is
  consistent across implement/debug/feedback/document.

### Cross-cutting (re-asserted per adopted orchestrator — wire-only)

- **R21** *(extends the PRD-023 deliver-scoped R21 surfacing pattern to `/sw-debug`, `/sw-doc`,
  `/sw-feedback`.)* The chosen plan, the resolved capability set, and any plan rejections (with reason) are
  surfaced in each orchestrator's run record and the consolidated halt/terminal report.
- **R22** *(consumes the PRD-023 driver-enforced budgets; wire-only.)* Each adopted orchestrator's plan-driven
  runs stay bounded by the autonomy budgets and no-progress circuit breaker, enforced by the deterministic
  driver (durable counters, not agent prose). Orchestrator-scoped budget keys are defined where deliver keys do
  not apply.
- **R23** *(consumes the PRD-022 kernel envelope; wire-only.)* No-auto-merge-to-`main`, push/secret-scan
  chokepoint, single-flight merge under concurrency, `memory-preflight`/redaction, and the non-selectable
  guardrails hook are unchanged for every adopted orchestrator, including ingestion paths.

## Technical Requirements

- **TR0 — Program dependency gate (mechanical).** A failing-before fixture
  (`fanout-024-blocked-without-023-r31`) refuses debug/doc/feedback `proposed` adoption — and blocks 024 task
  generation — until the named 023 pilot fixtures are green **and** the R31 decision rule returns positive.
  Mirrors 023 TR0.
- **TR1 — Orchestrator-step-plan schema (single-tier).** Define
  `orchestrator-step-plan.schema.json` with a **closed-world** step vocabulary per orchestrator, mapped from
  existing procedures (debug: triage → normalize → enrich → RCA → route; doc: tier-gated atomic chain;
  feedback: normalize → redact → route → handoff). Extend `wave.sh plan validate` with an **orchestrator tier**
  distinct from deliver wave/phase tiers. Unknown step IDs are rejected closed-world.
- **TR2 — Guideline packs (the 022-deferred packs).** Author `core/sw-reference/guidelines` packs for the
  debug, doc, and feedback phase types: canonical fallback chains, signal-conditional **floors** (R33) pinning
  mandatory steps, and **forbidden deliver-only steps** (merge enqueue/run-next, terminal-ship, git-push,
  main-merge, inline `/sw-execute`, lock-acquire where N/A). Schema-validate via the extended 021 harness with a
  completeness lint; ship before each orchestrator's TR4 wiring goes live.
- **TR3 — `signal_context` capture per orchestrator.** Specify entry-time `signal_context` snapshot + durable
  owner before `plan validate` (debug: signal type + relatedFiles + Sentry ref; feedback: sourceClass +
  invocation + route; doc: tier + doc_path), so the gate's anti-spoof/divergence check (022 R6) is applicable.
- **TR4 — Per-orchestrator adoption (wire-only).** At each orchestrator's proposal site: read
  `orchestration.planPolicy` (R29 — consumption delegated here by 022); when `proposed`, propose the
  single-tier plan → `wave.sh plan validate` → selector → persist → drive from the stored plan via the
  deterministic step driver (kernel re-check at each `advance`); `canonical` remains byte-identical.
  - **TR4a `/sw-debug`:** after one human route confirmation continue in-turn (DBG-A1); preserve RCA
    human-decision halt and Sentry degrade-and-continue; redact Sentry bodies before any persist/handoff.
  - **TR4b `/sw-doc`:** plan covers atomic-chain ordering + parallel persona dispatch only; preserve doc-review
    `manual`/`gated_auto` halts and `doc.afterTasks` (`stop`/`confirm`/`auto`); the deliver handoff reuses 023
    wiring unchanged.
  - **TR4c `/sw-feedback`:** `invocation ∈ {hook, monitor}` → **hard halt** (never in-turn dispatch); redact
    full signal JSON before any route record; require persisted human-confirm before any routed dispatch.
- **TR5 — Shared-contract references.** Each adopted command/skill references `skills/conductor`, the gate, and
  the selector rather than duplicating them (R18, Non-Goal).
- **TR6 — Cross-orchestrator state isolation.** Namespace durable artifacts by orchestrator + runId
  (e.g. `sw-debug-runs/`, `sw-feedback-runs/`); add cross-orchestrator write-refusal and concurrent-run
  isolation fixtures so a debug/feedback run cannot mutate a deliver run's state or selector output.
- **TR7 — Surfacing + budgets + invariants + parity (per orchestrator).** Wire R21 surfacing, R22 driver
  budgets, and R23 invariants; re-run the **orchestrator-applicable subset** of the 022 TR7 parity suite under
  `proposed` as blocking gates (memory-preflight, memory-redact-fail-closed, guardrails-hook-non-selectable for
  all three; merge/push/no-main only where the orchestrator step-trace can reach those transitions, else
  explicit N/A with rationale). Add ingestion fixtures:
  `debug-proposed-sentry-enrich-redact-before-preflight`,
  `feedback-proposed-inbound-redact-fail-closed`,
  `feedback-proposed-human-confirm-before-dispatch`,
  `feedback-hook-trigger-no-autodispatch-under-proposed`.
- **TR8 — Adoption call-site map.** Produce the 022 TR9 *adoption-side* map: proposal site, canonical chain
  source, guideline-pack id, durable owner path, `signal_context` snapshot point, and parity fixture set per
  orchestrator. Kernel-completeness lint must cover the new orchestrator step IDs.
- **TR9 — Emitter propagation + freshness.** Regenerate both dist trees; freshness gate green.

## Documentation deliverables

Fan-out delta only — **do not** re-document the shared 021/022 artifacts, and per program scope exclusion
**do not** touch `docs/prds/INDEX.md`, `COMPLETION-LOG.md`, or `GAP-BACKLOG.md` (PRD-009 living-doc gate).

- `core/commands/sw-debug.md`, `core/commands/sw-doc.md`, `core/commands/sw-feedback.md` — add a
  **Plan-policy adoption** subsection each (read `planPolicy`; route single-tier plan via gate + selector by
  reference; preserved halts; R21 surfacing; default `canonical`).
- `core/skills/conductor/SKILL.md` — extend the orchestrator-adoption table with plan-policy consumer status
  for the three commands (pointer only; lifecycle prose stays 022/023-owned).
- `core/rules/sw-naming.mdc` — one sentence per orchestrator boundary noting plan-policy routing under
  `proposed`; existing human-gate bullets unchanged.
- `docs/guides/configuration.md`, `docs/guides/workflows.md`, `docs/guides/commands.md`, `README.md`,
  `docs/guides/getting-started.md` — extend the 022/023 plan-policy base to list all four orchestrators as flag
  consumers; default `canonical`; default flip remains 023-metric-gated.
- `CONTRIBUTING.md` — named per-orchestrator fixture suites (adoption, preserved halts, R21–R23, ingestion
  redaction, parity, state isolation) + regenerate-dist reminder.
- `core/skills/debug/SKILL.md`, `core/skills/feedback/SKILL.md` — brief cross-ref that orchestrator-level plan
  proposal/validation is owned by the command + conductor skill (no gate/selector duplication).
- `.sw/layout.md` + `core/sw-reference/layout.md` — orchestrator-scoped validated-plan / run-record paths
  (TR6), if new paths land.

## Security & Compliance

- **Mechanically preserved legitimate halts (R19).** Pre-dispatch security/quality gates are pinned in the
  guideline floors and asserted by the driver, not prose: a `proposed` plan that omits or reorders them is
  rejected fail-closed. Only routine post-confirmation yields are removed.
- **`/sw-feedback` untrusted-signal chokepoint (highest risk).** Hook/monitor (`invocation ≠ human`) signals
  hard-halt and are never auto-dispatched; the full signal JSON is redacted (`memory-redact.py`) and wrapped as
  `untrusted_payload` before any route record or memory write; routed dispatch requires a persisted human-ack
  keyed by signalId. Proven by `feedback-hook-trigger-no-autodispatch-under-proposed` and
  `feedback-proposed-redact-before-route-record`.
- **No privilege escalation (R18, R20).** Diagnose/route/normalize orchestrators cannot acquire
  implement/merge/push capability: their guideline packs forbid deliver-only steps closed-world, proven per
  orchestrator (`orchestrator-proposed-plan-rejects-deliver-only-steps`).
- **Consistent kernel enforcement (R20, R23).** Every adopted orchestrator runs the same fail-closed gate and
  the orchestrator-applicable subset of the 022 TR7 parity suite under `proposed`; no orchestrator gets a
  weaker path.
- **Ingestion-path redaction/memory (R23).** `/sw-debug` Sentry enrichment and `/sw-feedback` inbound signals
  route through `memory-preflight`/redaction under `proposed`; concurrency on DBG-A2 (parallel enrich +
  preflight) redacts before any persist/handoff.
- **State isolation (TR6).** Orchestrator-scoped run dirs/keys bound blast radius; cross-orchestrator and
  concurrent-deliver corruption is fixture-refused.
- **Reversibility.** Default `canonical` keeps the entire fan-out dormant; the R29 flag is the single
  kill-switch; program exit retires the `proposed` wiring cleanly.

## Testing Strategy

All fixtures use failing-before / passing-after and wire into `verify.test` suites; per the rollout, each
orchestrator lands its full row set green before the next begins.

| Fixture | Asserts | R-IDs |
|---|---|---|
| `fanout-024-blocked-without-023-r31` | TR0 gate: adoption/tasks refused until 023 fixtures green + R31 positive | TR0, SC7 |
| `{debug,doc,feedback}-canonical-parity` | byte-identical to pre-024 under `canonical` | R20, SC1 |
| `{debug,doc,feedback}-proposed-routes-gate-selector` | single-tier plan validated + capability set resolved | R18, R20, SC2 |
| `orchestrator-plan-rejects-unknown-step` | closed-world unknown step ID rejected | TR1, SC2 |
| `orchestrator-proposed-plan-rejects-deliver-only-steps` | merge/push/ship/inline-execute forbidden per orchestrator | R18, SC4 |
| `feedback-hook-trigger-no-autodispatch-under-proposed` | `invocation ≠ human` hard-halts, no dispatch | R19, TR4c, SC3 |
| `feedback-proposed-human-confirm-before-dispatch` | persisted human-ack required before route dispatch | R19, SC3 |
| `feedback-proposed-inbound-redact-fail-closed` | redact-before-record; fail-closed on redaction error | R23, TR7, SC5 |
| `debug-route-confirm-halt-required` | route confirmation fires before in-turn continuation | R19, SC3 |
| `debug-rca-human-decision-halt-required` | RCA human-decision halt preserved | R19, SC3 |
| `debug-proposed-sentry-enrich-redact-before-preflight` | Sentry body redacted before persist/handoff | R23, TR7, SC5 |
| `doc-review-halt-{manual,gated-auto}-required` | doc-review trade-off halts fire before freeze steps | R19, SC3 |
| `doc-afterTasks-checkpoint-required` | `stop`/`confirm`/`auto` boundary preserved | R19, SC3 |
| `{debug,doc,feedback}-022-parity-under-proposed` | orchestrator-applicable 022 TR7 subset green | R23, SC5 |
| `{debug,doc,feedback}-budget-trip` | driver-enforced budget/no-progress breaker | R22 |
| `{debug,doc,feedback}-r21-surfacing` | chosen plan + capability set + rejections in run record/report | R21 |
| `cross-orchestrator-state-isolation` | one orchestrator cannot corrupt another / a deliver run | TR6, SC6 |
| `resume-revalidates-planpolicy-mode` | resume re-validates persisted mode/version, fail-closed on stale | TR4, SC7 |
| `emitter-freshness-stale-fails` | stale dist artifact fails the gate | TR9, SC1 |

## Rollout Plan

0. **Program gate (TR0).** Do not start fan-out until the named 023 pilot fixtures are green **and** the R31
   decision rule returns positive. If R31 is non-positive / N insufficient → **program exit**: 024 is not
   adopted; `proposed` wiring is retired or iterated; default stays `canonical`.
1. Adopt in 009-audit order: `/sw-debug` → `/sw-doc` → `/sw-feedback`, each behind `orchestration.planPolicy`
   (default `canonical`), with its guideline pack (TR2) landed first.
2. Each adoption lands green with its full fixture row set (Testing Strategy) before the next begins.
3. Default stays `canonical` across all orchestrators; any default flip remains gated by the PRD-023 benefit
   metric (R29) and is out of scope here.

## Decision Log

- **Hard program gate, not just default-off** (consumed from 022/023): fan-out itself is gated on a positive
  R31 outcome; a negative outcome triggers program exit and retires the `proposed` wiring. Distinct from the
  separate default-flip gate (R29).
- **Single-tier orchestrator-step plan** (resolves feasibility P0): diagnose/route/normalize orchestrators are
  not phase executors; they validate a closed-world single-tier plan via the same gate under an orchestrator
  tier — not deliver wave/phase plans. The `/sw-doc → /sw-deliver` handoff reuses 023 wiring.
- **Guideline packs owned here** (discharges 022 TR3 deferral): debug/doc/feedback packs with forbidden
  deliver-only steps and signal-conditional floors are authored by this PRD.
- **Driver-asserted halt preservation** (R19): legitimate halts are pinned in floors and enforced by the
  deterministic driver with named fixtures — not classified by agent prose, closing the misclassification
  vector.
- **Two tracks separated**: conductor in-turn continuation (009/017) is already landed and not R31-gated; only
  the plan-policy surface is gated.
- **`/sw-ship` scoping**: phase-mode covered by 023; interactive `/sw-ship` deferred per 022 TR9; not in 024.
- **State isolation** (TR6): orchestrator-scoped run dirs/keys bound blast radius across the shared gate +
  selector.
- **Per-orchestrator value acceptance** (product residual): the 009 audit shows minimal routine-yield headroom
  for `/sw-doc` and short chains for debug/feedback. Adoption is accepted on a **consistency + safety-floor**
  basis (one gate/selector everywhere) rather than per-orchestrator adaptivity benefit; per-orchestrator
  opt-out / "consistency-only" wiring (manifest + selector without proposed guideline packs) is a permitted
  scope cut recorded as an open question for task planning.

## Open Questions

Program sequencing and the default-flip gate are resolved (TR0 + R29; brainstorm 2026-06-26). Residual
questions deferred to task planning:

1. If R31 is **inconclusive** (insufficient N) rather than negative, is fan-out blocked, deferred, or allowed
   in canonical-wiring-only mode?
2. For orchestrators with no practical plan-shape variance (e.g. `/sw-doc` with no routine yields), is scope
   cut to manifest + selector consistency only (defer the proposed guideline pack), per the Decision Log
   value-acceptance entry?
3. Do debug/feedback runs get their own durable run-record + crash-resume, or remain episodic with validation
   only at entry (TR6 path implications)?
