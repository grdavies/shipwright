---
title: "feat: phase-flow v2 feedback workstream (unified intake + routing)"
type: feat
date: 2026-06-22
origin: docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md
---

# feat: phase-flow v2 feedback workstream (unified intake + routing)

## Summary

Build the second half of phase-flow v2's Phase 2: a unified inbound-signals intake (`/pf-feedback`) that ingests production/operational signals, code-review feedback, and post-ship retrospectives, then triages each signal and routes it to the debugging workflow, to gap-capture (an amendment or a source-tagged task), or to a new brainstorm — closing the loop from shipped code back to the documentation pipeline. This is the smallest remaining workstream and the last piece of the full lifecycle.

## Problem Frame

The frozen brainstorm (see origin) commits to one unified workflow that ingests every inbound signal and routes it, rather than scattering signal handling across commands. The foundation and the three sibling workstreams provide every route target — debugging (`004`), amendments/brainstorm (`002`), tagged tasks/compounding (`003`) — but nothing yet *intakes* signals and decides where they go. This workstream is that router.

"Work missed or that extends a prior PR" is a first-class intake here (origin R27): the brainstorm explicitly wants the capture path for missed/PR-extending work to live in feedback, splitting substantial scope into an amendment and trivial in-scope gaps into a source-tagged task. Feedback is intentionally thin — it normalizes and routes; the actual analysis and authoring happen in the workstreams it routes to.

**Why now / dependency:** feedback is built last because its routes depend on the debugging workflow (`004`) and the documentation/implementation workstreams (`002`/`003`) all existing. It is the final closing of the doc → implement → ship → feedback loop.

---

## Requirements Traceability

Carried from origin (feedback-relevant requirements):

- **Unified intake:** R25 (one inbound-signals intake covering production/operational signals — deploy logs, Sentry — code-review feedback from the configured provider or a human, and post-ship retrospectives).
- **Triage + routing:** R26 (intake triages each signal and routes it to debugging, to gap-capture as an amendment or tagged task, or to a new brainstorm — closing the loop back to the documentation pipeline).
- **Missed / PR-extending work:** R27 (a first-class intake: substantial scope spawns an amendment; trivial in-scope gaps append a source-tagged task).
- **Redaction:** R41 (every ingestion edge — deploy logs, Sentry payloads, transcripts — runs a secret/PII redaction pass before content is persisted or re-injected).

Consumed: the foundation's R41 redaction chokepoint and memory seam; the debugging workflow (`004`) as the prod-fault route; the documentation workstream (`002`, `/pf-amend` and `/pf-brainstorm`) as the amendment/new-scope routes; the implementation workstream (`003`, the living task list + compounding) as the tagged-task route.

Explicitly **not** here: the RCA analysis itself (`004`), amendment/brainstorm authoring (`002`), and task execution (`003`). Feedback normalizes and routes only.

---

## Key Technical Decisions

- **Feedback is a thin router, not an analyzer.** `/pf-feedback` normalizes a signal, triages it, and dispatches to an existing workflow; it does no RCA, no authoring, no execution. Rationale: origin R25/R26 frame it as a unified *intake and routing* layer; duplicating the downstream workflows' logic here would fragment the single RCA core and the freeze/amendment model. (R25, R26)
- **One intake for three signal classes.** Production/operational signals (deploy logs, Sentry), review feedback (the configured review provider or a human), and retrospectives all enter through the same command and a single normalized signal shape. Rationale: origin R25 explicitly unifies these three sources so routing logic is written once. (R25)
- **Routing has exactly three destinations.** Each triaged signal routes to: debugging (`/pf-debug`) for a prod fault, gap-capture for work that extends a prior PR, or a new brainstorm for genuinely new scope. Rationale: origin R26 + the Architecture Overview's `Route` node. (R26)
- **Gap-capture splits by scope: amendment vs source-tagged task.** Substantial scope that extends a frozen PRD spawns an amendment (`/pf-amend` in `002`); a trivial in-scope gap appends a source-tagged task to the living task list (`003`). Rationale: origin R27 — this is the first-class capture path for missed/PR-extending work, and the split keeps the freeze model honest (real scope changes go through reviewed amendments, not silent task edits). (R27)
- **Redaction runs at the intake edge.** Deploy logs, Sentry payloads, and any transcript content are scrubbed through the foundation's shared R41 chokepoint before the signal is persisted, re-injected, or passed to a downstream workflow. Rationale: origin R41 — intake is an ingestion edge and must not land credentials/PII durably. The executable filter itself is built once as a foundation-shared chokepoint in `003` U0 (the first plan with an executable ingestion edge); this workstream consumes it and extends its corpus for the feedback edge. (R41)

---

## High-Level Technical Design

All three signal classes enter one intake, get redacted and normalized, are triaged, and route to one of three destinations — each an existing workflow.

```mermaid
flowchart TB
  PROD[deploy logs / Sentry] --> INTAKE
  REVIEW[review-provider / human feedback] --> INTAKE
  RETRO[post-ship retrospective] --> INTAKE

  INTAKE[/pf-feedback: normalize] --> REDACT[R41 redaction chokepoint]
  REDACT --> TRIAGE{route}

  TRIAGE -->|prod fault| DEBUG[/pf-debug → debugging workstream 004]
  TRIAGE -->|extends prior PR| GAP{scope?}
  TRIAGE -->|new scope| BRAIN[/pf-brainstorm → documentation workstream 002]

  GAP -->|substantial| AMEND[/pf-amend → documentation workstream 002]
  GAP -->|trivial in-scope| TASK[source-tagged task → gap backlog 002 prds/GAP-BACKLOG.md]
```

Every route target is consumed from a sibling workstream; this plan builds only the intake + triage + dispatch. The diagram is authoritative for the routing fork; per-unit Files sections are authoritative for exact paths.

---

## Implementation Units

Suggested build order: intake + redaction (U1) first, then the triage/routing decision (U2), then the gap-capture split (U3).

### U1. `/pf-feedback` unified intake

- **Goal:** A single command that ingests production signals, review feedback, and retrospectives into one normalized, redacted signal shape.
- **Requirements:** R25, R41.
- **Dependencies:** the executable R41 redaction filter (built once as a foundation-shared chokepoint in `003` U0) + memory seam. U1 consumes that filter and extends its corpus for this edge (deploy-log/feedback secret formats, high-entropy fallback, Sentry PII) rather than originating it.
- **Files:** `commands/pf-feedback.md`, `skills/feedback/SKILL.md`, `skills/feedback/references/signal-schema.md`.
- **Approach:** Define a normalized signal shape (source class, payload, originating artifact/PR where known, timestamp, an invocation/trigger-source tag — `human` | `hook` | `monitor`, `human` by default — and a class-tagged dedup/idempotency key so idempotency holds across all three classes, not just review — review = provider finding id + PR + commit; production = Sentry issue id / deploy-log event id; retro = retro item id + run id). Accept three input classes: production/operational (a deploy-log excerpt or Sentry issue ref), review feedback (normalized findings from the configured review provider, or pasted human feedback), and a retrospective (from `/pf-retro` output in `003`). For the retro class, pin a minimal `/pf-retro` output contract jointly with `003` U8 (the fields U1 reads) and freeze it before build rather than coupling on an undefined shape. Every payload routes through the R41 redaction chokepoint before it is persisted, re-injected, or handed downstream — and because a "Sentry issue ref" carries no body, the ref→payload expansion (in `004`) must itself pass the chokepoint, not just the ref. Redaction must cover more than the foundation's named-pattern list: extend it, or add a high-entropy fallback, to catch deploy-log/feedback secret formats (DB connection strings, webhook tokens, internal hostnames) and Sentry PII (IP, username, user id, request body). Pasted human and review content is untrusted: U1's normalized signal places it in a dedicated, delimited data field — a sentinel-fenced `untrusted_payload` envelope defined in `skills/feedback/references/signal-schema.md` — never interpolated as instructions. A pinned representation contract requires the downstream consumers — `002` authoring prompts (`/pf-amend`, `/pf-brainstorm`) and `003` U9 compounding/memory — to consume that field as data and preserve the envelope boundary on re-injection, so injection markers in feedback cannot become instructions anywhere along the loop. The dedup key lets an out-of-loop intake of a review finding already handled in-loop (stabilize, `003`) be detected and dropped, not double-processed. The command is the workstream's single entry point; its description states it intakes and routes but does not analyze or author.
- **Patterns to follow:** the foundation R41 chokepoint; the review seam's normalized-findings shape (`002`/foundation) for the review-feedback class; `/pf-retro` output (`003`) for the retro class.
- **Test scenarios:**
  - Each of the three signal classes is accepted and normalized to the common shape.
  - A payload containing a secret/PII pattern is scrubbed before persistence or downstream handoff. Covers R41.
  - Non-named secret formats (DB connection strings, webhook tokens, internal hostnames) are scrubbed, not just the named-pattern set. Covers R41.
  - Injection markers embedded in pasted feedback do not alter routing or downstream prompt behavior — the content stays inside the `untrusted_payload` envelope and the boundary is preserved on re-injection.
  - The command does not perform RCA or authoring (it only normalizes + routes).
- **Verification:** All three signal classes enter one normalized, redacted intake.

### U2. Signal triage and routing

- **Goal:** Triage each normalized signal and route it to debugging, gap-capture, or a new brainstorm.
- **Requirements:** R26.
- **Dependencies:** U1, debugging workstream (`004`), documentation workstream (`002`). Pin each route target's invocation contract (command name + argument shape) as a published dependency — mirroring how `003` freezes `002`'s union resolver — so U2 does not hard-code a shape the siblings later ship differently.
- **Files:** `skills/feedback/SKILL.md` (extend: routing rubric), `commands/pf-feedback.md` (extend).
- **Approach:** Classify each signal on its own axis — not `002`'s ceremony-tier rubric, which scores how much process, not which destination. The source class from U1 largely fixes the prod-fault route (error/crash/regression markers → `/pf-debug`, `004`); the extends-prior-PR vs genuinely-new-scope fork uses its own signals — linkage to an existing PRD/PR and requirement-delta detection — routing to gap-capture (U3) or `/pf-brainstorm` (`002`) respectively. Apply explicit conservative defaults for mixed signals, gated on source class: for production/operational signals an error/crash/regression marker defaults debug-vs-gap to debug; for review/retro-class signals the same markers are non-decisive and fall through to the gap-vs-new-scope fork (which, when ambiguous, defaults to gap-capture against the cited PR). The route decision and the originating signal — in their U1-redacted normalized form, never a raw re-fetch of the originating artifact — are recorded for compounding (`003` U9) via a defined route-record schema (route, originating-signal id, source class, target). Because `003` U9 does not yet define a feedback-item input contract, pin that schema jointly with `003`'s owner and freeze it before U2 build (mirroring the `/pf-retro` contract pin), or have `005` define this route-record as the source contract `003` U9 consumes — rather than asserting conformance to an unspecified shape. This closes the loop back to memory.
- **Patterns to follow:** origin Architecture Overview `Route` node + F5; the `002` triage rubric for scope/risk classification.
- **Test scenarios:**
  - A prod-fault signal routes to `/pf-debug`.
  - A signal extending a prior PR routes to gap-capture; a new-scope signal routes to `/pf-brainstorm`.
  - A production-class signal matching multiple destinations falls to the debug default on an error/crash marker; a review/retro signal carrying the same marker does not default to debug but routes by scope.
  - The route decision is verifiable in isolation against a recorded dispatch target + payload, with no sibling command built (route-decision level), separate from the end-to-end assertion.
  - The route taken + originating signal are recorded for compounding in the U1-redacted form and in `003` U9's expected schema; a secret/PII-bearing signal is absent from the compounding/memory record.
- **Verification:** The route decision is correct and auditable in isolation (verifiable before siblings ship); end-to-end, each signal lands in the correct downstream workflow once `002`/`003`/`004` exist.

### U3. Gap-capture split (amendment vs source-tagged task)

- **Goal:** For work that extends a prior PR, split by scope — substantial scope spawns an amendment, a trivial in-scope gap appends a source-tagged task.
- **Requirements:** R27.
- **Dependencies:** U2, documentation workstream (`002`, `/pf-amend` + the `prds/GAP-BACKLOG.md` layout/seed from `002` U1), implementation workstream (`003` U10, which surfaces the backlog in living status).
- **Files:** `skills/feedback/SKILL.md` (extend: gap-capture), `commands/pf-feedback.md` (extend), `prds/GAP-BACKLOG.md` (append).
- **Approach:** When U2 classifies a signal as extending a prior PR, decide scope on the freeze axis directly — independent of `002`'s tier score, which measures ceremony, not requirement change. Any change that adds, edits, or retracts a requirement (R-ID), alters a documented behavior, touches a frozen PRD's scope, **or changes shipped behavior that has no corresponding requirement**, is **substantial** → handed to `/pf-amend` (`002`) for a reviewed, frozen amendment against the relevant PRD. Everything else — a genuinely trivial, in-scope gap with no behavior change — is a **trivial in-scope gap** → append a source-tagged `- [ ]` entry (e.g. `source:feedback`, the originating signal/PR) to `prds/GAP-BACKLOG.md`, the committed, append-only, never-frozen backlog `002` U1 defines. This lands the task without touching a frozen task list or tripping the freeze CI check, and `003` U10 surfaces it in living status. Worked examples: a one-line diff that changes an R-ID is still substantial; so is a material behavior change to shipped code that no PRD ever captured (it does not escape as a task just because it touches no R-ID). The split keeps real scope changes inside the reviewed-amendment path rather than letting them slip in as silent task edits; undocumented-but-material and otherwise ambiguous cases escalate to the amendment path, never defaulting to a task.
- **Patterns to follow:** origin R27 + F5; `002` `/pf-amend` for the amendment path; `002` `prds/GAP-BACKLOG.md` for the tagged-task path; v1 gap-check's "never silently absorb scope creep" discipline.
- **Test scenarios:**
  - Substantial PR-extending scope routes to an amendment, not a task edit.
  - A trivial in-scope gap appends a source-tagged `- [ ]` entry to `prds/GAP-BACKLOG.md` (no frozen file touched; freeze CI check stays green).
  - The source tag records the originating signal/PR.
- **Verification:** Missed/PR-extending work is captured by scope: reviewed amendments for substantial changes, source-tagged tasks for trivial gaps.

---

## Open Questions

- **Review-feedback intake overlap.** Review findings already flow into the stabilize loop in-loop (foundation/`003`). Feedback intake handles review feedback that arrives *out of loop* (e.g. a post-merge human review). The boundary is now enforced, not just documented: U1's normalized signal carries a class-tagged dedup/idempotency key (review = provider finding id + PR + commit; production = Sentry/deploy event id; retro = retro item id + run id), so a duplicate intake — an out-of-loop review finding already handled in-loop, or a re-run on the same Sentry issue or retro item — is detected and dropped across all three classes.
- **Auto vs manual intake (resolved 2026-06-23).** `/pf-feedback` is human-invoked by default. The signal schema reserves an `invocation`/`trigger-source` tag (`human` | `hook` | `monitor`) now, so an automated stop-hook / monitoring trigger is an additive enhancement rather than a schema change. When automated triggers are added (a later enhancement, not built here), they must pass the same R41 redaction + `untrusted_payload` envelope as human intake, and may auto-*capture* a normalized signal but never auto-*dispatch* a route (debug / amend / brainstorm / backlog) without human confirmation — keeping a human in the loop on the injection/poisoning surface.
- **Trivial-gap task target (resolved 2026-06-23).** U3's trivial-gap path appends to `prds/GAP-BACKLOG.md` — a committed, append-only, never-frozen living artifact defined and seeded by `002` U1, written by `005` U3, and surfaced by `003` U10. This avoids the frozen task list and the freeze CI check entirely (the earlier concern that `003` had no hand-appendable task store). The diagram node "living task list 003" should read "gap backlog (`002` `prds/GAP-BACKLOG.md`)" at build time.

---

## Scope Boundaries

### Deferred to / consumed from sibling plans

- RCA analysis of a routed prod fault — debugging workstream (`004`).
- Amendment and brainstorm authoring — documentation workstream (`002`).
- Task execution and compounding of the recorded route — implementation workstream (`003`).

### Outside this product's identity (from origin)

- Performing analysis or authoring inside the feedback workflow — it normalizes and routes only.
- Team/multi-user feedback collaboration beyond single-developer use (origin Deferred for later).

---

## Risks & Dependencies

- **Routing depends on all sibling workstreams.** Every route target lives in `002`/`003`/`004`. *Mitigation:* feedback is built last (Phase 2 tail) so its targets exist; routing is testable end-to-end only after they ship.
- **Scope-split misjudgment.** Treating a substantial change as a trivial task would bypass the reviewed-amendment path and erode freeze integrity. *Mitigation:* U3 reuses the `002` triage/scope rubric and defaults ambiguous scope to the amendment (reviewed) path, not the silent-task path.
- **Redaction at a new ingestion edge.** Deploy logs and pasted feedback can carry secrets/PII. *Mitigation:* U1 routes every payload through the foundation's shared R41 chokepoint before persistence or handoff.

---

## Sources & Research

Internal (consumed — recorded in `PROVENANCE.md` per R40):

- Foundation (shipped, PR #1): the R41 redaction chokepoint, the memory seam, the review seam's normalized-findings shape.
- Sibling workstreams: `002` (`/pf-amend`, `/pf-brainstorm`, triage rubric), `003` (living task list, `/pf-retro`, `/pf-compound`), `004` (`/pf-debug`).

Origin requirements: `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md` (frozen), Architecture Overview `Route` node and Key Flow F5. Foundation: `docs/plans/2026-06-22-001-feat-plugin-foundation-infrastructure-plan.md`. Prior decision: Recallium memory #2004 (feedback is a unified intake routing to debug/gap-capture/brainstorm).