---
title: "feat: phase-flow v2 debugging workstream (signal-driven RCA + Sentry MCP)"
type: feat
date: 2026-06-22
origin: docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md
---

# feat: phase-flow v2 debugging workstream (signal-driven RCA + Sentry MCP)

## Summary

Build the first half of phase-flow v2's Phase 2: a signal-driven debugging workflow that activates the shared RCA core's `debug` entry point (scaffolded but deferred in the foundation), pulls production context via the Sentry MCP, and routes a root cause + proposed fix either to a scoped implementation phase or to a new brainstorm/amendment. It is triggered by post-ship signals — deploy logs, Sentry events, user-identified behavior — not dev-time test reproduction.

## Problem Frame

The frozen brainstorm (see origin) commits to a debugging workflow that shares one hypothesis-driven RCA core with stabilize (two entry points, one discipline) and is driven by production signals rather than test reproduction. The foundation plan shipped the shared `skills/rca-core` with the **stabilize** entry wired and the **debug** entry explicitly stubbed with a "deferred to debugging-workstream plan" marker — so the core's shape is fixed; this workstream fills in the debug entry and its signal sources.

This is Phase 2 work: the build order proves the core doc → implement → ship loop first, then adds the post-ship machinery once the shared RCA core has a second real consumer. Debugging is that second consumer. Nothing in this workstream rebuilds the RCA discipline — it feeds the existing core different inputs (deploy/Sentry/user signals instead of in-loop CI/review failures) and routes the output differently (scoped phase or new brainstorm instead of a stabilize fix).

**Why now / dependency:** this workstream depends on the shipped foundation's RCA core and on the implementation workstream (`003`, for the scoped-phase route) and documentation workstream (`002`, for the brainstorm/amendment route). It should be built after the Phase 1 loop is proven.

---

## Requirements Traceability

Carried from origin (debugging-relevant requirements):

- **Signal-driven RCA:** R22 (debugging is signal-driven RCA triggered by deploy logs, Sentry events, or user-identified behavior — not dev-time test reproduction).
- **Sentry integration:** R23 (integrate with the Sentry MCP to pull issue/event context — stack traces, breadcrumbs, traces — for RCA).
- **Output + routing:** R24 (a debug investigation produces a root cause + proposed fix and routes downstream: a scoped phase for a small fix, or a new brainstorm/PRD/amendment when substantial).
- **Shared core:** R35 (stabilize and debug share one hypothesis-driven RCA core with two entry points — same discipline, different inputs and downstream routing).
- **Loops + redaction:** R29 (the RCA loop has hard stops), R41 (ingestion edges — Sentry payloads — run a secret/PII redaction pass before content enters RCA prompts or memory).

Consumed from the shipped foundation: `skills/rca-core/SKILL.md` (the `debug` entry stub becomes a real entry here), the memory seam + the R41 redaction chokepoint, and the loop hard-stop conventions. Routes into the implementation workstream (`003`, scoped phase) and documentation workstream (`002`, brainstorm/amendment).

Explicitly **not** here: the stabilize entry (already shipped), the feedback intake that *feeds* debug (R25–R27, `005`), and any new RCA discipline (the core is reused, not rebuilt).

---

## Key Technical Decisions

- **Fill in the existing RCA core's `debug` entry; do not fork the discipline.** The foundation shipped `skills/rca-core` with a stubbed `debug` entry. This workstream implements that entry — accepting deploy/Sentry/user signals — while reusing the core's hypothesis-ranking, causal-chain gate, and hard stops. Rationale: origin R35 mandates one analysis discipline with two entry points; a separate debug RCA would diverge and reintroduce drift. (R35, R22)
- **Signal-driven, not reproduction-driven.** Debug starts from production signals (a Sentry issue, a deploy-log error, a user report), not from authoring a failing dev-time test. The RCA loop reproduces *from the signal's context* where possible but does not require a local repro to proceed. Rationale: origin R22 explicitly distinguishes this from stabilize's in-loop test failures. (R22)
- **Sentry context comes through the Sentry MCP, redacted at ingestion.** Issue/event context (stack traces, breadcrumbs, traces) is pulled via the Sentry MCP and passed through the foundation's R41 redaction chokepoint before it enters any RCA prompt or memory. Rationale: origin R23 + R41 — Sentry payloads can carry credentials/PII, and the brainstorm requires scrubbing on the way into both RCA prompts and memory distillation. (R23, R41)
- **Output routes by fix size, never auto-merges.** A debug investigation produces a root cause + a proposed fix and then routes: a small fix becomes a scoped implementation phase (handed to `003`'s loop in a worktree); a substantial fix spawns a new brainstorm/PRD/amendment (handed to `002`). The debug workflow itself does not implement or merge the fix. Rationale: origin R24 + F4 — separating diagnosis from execution keeps the merge gate and freeze model intact. (R24)
- **The RCA loop is bounded.** The debug loop carries the same hard stops as stabilize — max iterations, no-progress detection, a causal-chain gate before proposing a fix, and explicit hypothesis invalidation rather than variant-retry spirals. Rationale: origin R29 — loops are first-class but must never run unbounded. (R29)

---

## High-Level Technical Design

The debug entry feeds the shared RCA core production signals; the core runs its bounded hypothesis loop and emits a root cause + proposed fix; routing splits by fix size. Stabilize (already shipped) is the core's other entry, shown for contrast.

```mermaid
flowchart TB
  SIG[deploy logs / Sentry event / user report] --> DEBUG[/pf-debug: triage signal]
  SENTRY[Sentry MCP: issue/event context] --> REDACT[R41 redaction chokepoint]
  DEBUG --> REDACT
  REDACT --> CORE

  subgraph CORE[shared RCA core: bounded loop]
    HYP[ranked hypotheses + evidence] --> GATE{causal-chain gate}
    GATE -->|chain complete| OUT[root cause + proposed fix]
    GATE -->|incomplete + budget left| HYP
  end

  STAB[stabilize entry: in-loop CI/review failures]:::shipped -.same discipline.-> CORE
  OUT --> ROUTE{fix size}
  ROUTE -->|small| IMPL[scoped phase → implementation workstream 003]
  ROUTE -->|large| DOC[new brainstorm / amendment → documentation workstream 002]

  classDef shipped opacity:0.55,stroke-dasharray:5 5;
```

The RCA core and redaction chokepoint are consumed from the foundation, not rebuilt. The diagram is authoritative for the signal → core → route flow; per-unit Files sections are authoritative for exact paths.

---

## Implementation Units

Suggested build order: implement the debug entry (U1) so the core has a real second consumer, then the Sentry source (U2), then the command + routing (U3–U4).

### U1. RCA core `debug` entry point

- **Goal:** Implement the shared RCA core's `debug` entry — accepting deploy/Sentry/user signals — reusing the core's hypothesis loop, causal-chain gate, and hard stops.
- **Requirements:** R35, R22, R29.
- **Dependencies:** foundation `skills/rca-core` (debug stub).
- **Files:** `skills/rca-core/SKILL.md` (replace the `debug` stub with a real entry), `skills/rca-core/references/debug-inputs.md`.
- **Approach:** Replace the foundation's deferred `debug` marker with a real entry that takes a production signal (a Sentry issue ref, a deploy-log excerpt, or a user-described behavior) plus optional repo context. It runs the same core discipline as the stabilize entry: rank hypotheses with evidence + a causal chain, gate fix-proposal behind a complete trigger→symptom chain, invalidate failed hypotheses explicitly (no variant-retry spiral), and stop at max-iterations / no-progress. The difference from stabilize is the input shape (production signal vs in-loop CI/review failure) and that a local reproduction is attempted-from-context but not required.
- **Patterns to follow:** the foundation's `skills/rca-core` stabilize entry (the discipline to mirror); compound-engineering `ce-debug` phased RCA (causal-chain gate, hypothesis invalidation, escalation table) as the pattern reference.
- **Test scenarios:**
  - The debug entry accepts a production signal and produces a hypothesis → causal-chain → root-cause structure.
  - The causal-chain gate blocks a fix proposal until the trigger→symptom chain is complete (or the user authorizes a best-available hypothesis).
  - A failed hypothesis is invalidated explicitly; the loop does not retry variants of a rejected hypothesis.
  - The loop stops at max-iterations / no-progress. Covers R29.
  - The stabilize entry is unaffected (same core, two entries).
- **Verification:** The shared core now has two working entries with one discipline; debug produces a gated root cause from a signal.

### U2. Sentry MCP context integration

- **Goal:** Pull Sentry issue/event context (stack traces, breadcrumbs, traces) into the debug RCA, scrubbed through the foundation redaction chokepoint before it enters prompts or memory.
- **Requirements:** R23, R41.
- **Dependencies:** U1, foundation R41 redaction chokepoint.
- **Files:** `skills/debug/references/sentry.md` (the MCP access recipe), `skills/rca-core/references/debug-inputs.md` (extend: Sentry input shape).
- **Approach:** Define how the debug workflow queries the Sentry MCP for an issue/event (stack traces, breadcrumbs, traces, tags) and normalizes it into the debug entry's input shape. Every Sentry payload routes through the foundation's R41 redaction chokepoint before it enters an RCA prompt or any distilled memory — credentials, tokens, and PII in stack traces/breadcrumbs are scrubbed on the way in. Document the Sentry MCP as an environment dependency (per origin Dependencies/Assumptions) and degrade gracefully (proceed with the raw signal) if it is unavailable.
- **Patterns to follow:** the foundation R41 redaction chokepoint (single shared filter every ingestion edge routes through); the available Sentry MCP server tools (check the tool schema before calling).
- **Test scenarios:**
  - A Sentry issue reference yields normalized context (stack trace + breadcrumbs) fed into the debug entry.
  - A Sentry payload containing a secret/PII pattern is scrubbed before it reaches the RCA prompt and before any memory write. Covers R41.
  - Sentry MCP unavailable → the workflow degrades to the raw signal with a clear note, not a hard failure.
- **Verification:** Sentry context enriches RCA and never lands credentials/PII durably; absence degrades gracefully.

### U3. `/pf-debug` command

- **Goal:** A signal-driven debug command that triages an inbound signal, runs the bounded RCA loop, and emits a root cause + proposed fix.
- **Requirements:** R22, R24, R29.
- **Dependencies:** U1, U2.
- **Files:** `commands/pf-debug.md`, `skills/debug/SKILL.md`, `rules/pf-naming.mdc` (extend: debug orchestrator boundary).
- **Approach:** `/pf-debug` accepts a signal (a Sentry issue ref, a deploy-log excerpt, or a user-described behavior), triages it (trivial fast-path vs full framework), pulls Sentry context via U2 when a Sentry ref is given, and runs the U1 debug entry. It is an orchestrator over the RCA core; its description states what it does and does not do (diagnoses + proposes; does not implement or merge — that is the routing in U4). Memory preflight reads prior `debug` memories for the failing area before analysis.
- **Patterns to follow:** compound-engineering `ce-debug` (Phase 0 triage → investigate → root cause → handoff); the `pf-naming` orchestrator-vs-atomic boundary contract.
- **Test scenarios:**
  - A Sentry-ref signal pulls context (U2) then runs RCA; a user-report signal runs RCA without Sentry.
  - The command produces a root cause + proposed fix and stops — it does not implement or merge.
  - Memory preflight retrieves prior debug memories for the failing area.
  - The trivial fast-path still offers diagnosis-vs-fix before any edit.
- **Verification:** `/pf-debug` turns a signal into a gated root cause + proposed fix without crossing into implementation.

### U4. Downstream routing (scoped phase vs new brainstorm/amendment)

- **Goal:** Route a debug result by fix size — a small fix to a scoped implementation phase, a substantial fix to a new brainstorm/PRD/amendment.
- **Requirements:** R24.
- **Dependencies:** U3, implementation workstream (`003`), documentation workstream (`002`).
- **Files:** `skills/debug/SKILL.md` (extend: routing), `commands/pf-debug.md` (extend).
- **Approach:** After a root cause + proposed fix, classify fix size (reuse the triage rubric from `002` U2 where possible). A small, in-scope fix is handed to the implementation workstream as a scoped phase (provision a worktree, run the loop) referencing the originating signal. A substantial fix — wrong responsibility/interface, wrong requirements, or every fix is a workaround — spawns a new brainstorm (`002`) or an amendment to the relevant frozen PRD. The debug workflow records the route taken and the originating signal for compounding (`003` U9).
- **Patterns to follow:** origin F4 (route to scoped phase small / brainstorm-amendment large); compound-engineering `ce-debug` fix-vs-rethink fork.
- **Test scenarios:**
  - A small fix routes to a scoped implementation phase referencing the signal.
  - A substantial/architectural root cause routes to a new brainstorm or an amendment, not a quick patch.
  - The chosen route + originating signal are recorded for compounding.
- **Verification:** Debug results land in the right downstream workflow by fix size; nothing is silently patched in place.

---

## Open Questions

- **Sentry MCP tool surface.** The exact Sentry MCP tools (issue fetch, event detail, trace pull) and auth scope should be confirmed against the installed server before U2 hard-codes a query recipe. Default: read-only issue/event retrieval; no Sentry mutations from this workflow.
- **Fix-size threshold.** Where "small fix" ends and "substantial" begins reuses the `002` triage rubric, but the boundary for debug-originated fixes may warrant its own calibration once real signals flow.

---

## Scope Boundaries

### Deferred to sibling plans

- The feedback intake that *feeds* signals into debug (R25–R27) — feedback workstream (`005`). This plan exposes `/pf-debug` as the route target; `005` routes signals to it.
- The scoped-phase execution and the brainstorm/amendment authoring themselves — implementation (`003`) and documentation (`002`) workstreams. This plan routes to them.

### Outside this product's identity (from origin)

- Dev-time test-reproduction debugging — this workflow is signal-driven by design.
- A separate RCA discipline — the shared core is reused, not rebuilt.

---

## Risks & Dependencies

- **Sentry MCP availability.** R23 depends on the Sentry MCP being present/authenticated in the target environment (origin Dependencies/Assumptions). *Mitigation:* U2 degrades to the raw signal when the MCP is unavailable and confirms the tool surface before hard-coding queries.
- **Redaction completeness on Sentry payloads.** Stack traces/breadcrumbs are a rich PII/secret surface. *Mitigation:* every Sentry payload routes through the foundation's shared R41 chokepoint before prompts/memory; U2 tests assert scrubbing per pattern class.
- **Shared-core regression.** Filling in the debug entry must not destabilize the shipped stabilize entry. *Mitigation:* U1 reuses the core discipline and asserts the stabilize entry is unaffected.
- **Cross-plan routing dependency.** U4 routes into `002`/`003`; building debug before those workstreams exist would leave routing untestable. *Mitigation:* this is Phase 2 by design — built after Phase 1 is proven.

---

## Sources & Research

Internal (consumed / pattern-borrowed — recorded in `PROVENANCE.md` per R40):

- Foundation (shipped, PR #1): `skills/rca-core/SKILL.md` (the stubbed `debug` entry this plan implements), the R41 redaction chokepoint, the memory seam, loop hard-stop conventions.
- compound-engineering: `ce-debug` phased RCA pattern (triage → investigate → causal-chain-gated root cause → fix-vs-rethink routing) — borrowed as a pattern.

External: Sentry MCP (issue/event/trace context) — an environment dependency per origin Dependencies/Assumptions.

Origin requirements: `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md` (frozen), Key Flow F4. Foundation: `docs/plans/2026-06-22-001-feat-plugin-foundation-infrastructure-plan.md`. Sibling plans: `002` (documentation), `003` (implementation). Prior decision: Recallium memory #2004 (debug workflow is signal-driven, shares RCA core).