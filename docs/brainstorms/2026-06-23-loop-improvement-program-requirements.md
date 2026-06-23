---
date: 2026-06-23
topic: loop-improvement-program
---

# Loop Improvement Program (cross-loop quality gates + skill adoption)

## Summary

A prioritized program of nine improvements across phase-flow v2's document, implementation, and debugging
loops, drawn from three converging research streams (internal loop/gap map, external 2026 agentic-workflow
best practices, and a survey of installed skill ecosystems). The improvements add the quality gates the loops
are missing — evidence-before-done verification, a unified root-cause discipline, test-first implementation,
spec rigor with requirements-to-test traceability, a simplification pass, and lifecycle closure — and adopt
proven external skills (superpowers TDD / systematic-debugging / verification-before-completion / subagent-
driven-development, compound-engineering simplify, Spec-Kit-style clarify/checklist/analyze gates) rather than
reinventing them. Items are sequenced into three dependency-ordered waves. Two prior brainstorms (local code
review, conditional doc personas) remain the in-flight prerequisites that several items build on.

## Problem Frame

phase-flow v2 has a complete loop graph — doc → implement → debug → feedback → compound — but the loops are
gated unevenly. Some gates are strong and deterministic (the CI checks-gate, freeze-in-depth, redaction
chokepoint, the doc-review persona panel); others are thin or missing. The user asked: where are the
improvement areas across all loops, and which additional skills should be employed for writing documents,
implementing code, and debugging — researched beyond the current implementation.

Three independent research streams converged on the same holes:

- **Internal loop/gap map** (read of `commands/`, `skills/`, `rules/`, `agents/`, `docs/plans/`): the
  implementation loop has no test-first gate and no local code review; `/pf-stabilize` does not load
  `skills/rca-core/SKILL.md` despite R35's "one discipline, two entry points"; there is no simplification pass;
  no post-merge compound orchestrator; feedback stops at handoff.
- **External best practices (2026)**: phase-gated spec-driven development with clarify/checklist/analyze gates
  and requirements traceability; red-green TDD adapted for agents; an executable Definition-of-Done /
  verification-before-completion gate that reads real artifacts rather than trusting "done" claims; subagent-
  driven development with two-stage review; and for debugging, "no fix without a log-proven root cause,"
  reproduction-first, git-bisect for regressions, and a rule-of-three escalation.
- **Skill-ecosystem survey**: concrete, adoptable skills already exist for nearly every gap — superpowers
  `test-driven-development`, `systematic-debugging`, `verification-before-completion`, `subagent-driven-
  development`, `writing-plans`; compound-engineering `ce-simplify-code`, `ce-sessions`; cursor-team-kit
  `deslop`, `verify-this`.

The cross-cutting meta-pattern from the external research — which phase-flow already partly embodies — is:
**chain single-purpose skills with a mandatory verification gate between each, read real artifacts/diffs/logs
instead of the agent's transcript, and use fresh-context subagents for review.** This program extends that
pattern into the loops where it is currently absent.

## Scope Boundaries

### In flight (prerequisites, not re-specced here)

- **Local multi-agent code review** in `/pf-review` —
  `docs/brainstorms/2026-06-23-local-code-review-loop-integration-requirements.md` (not built).
- **Conditional doc-persona selection** —
  `docs/brainstorms/2026-06-23-conditional-review-personas-requirements.md` (not built).

### Deferred (recommendation only)

- **`ce-sessions` prior-attempt retrieval** as a debug preflight ("what was already tried" across past agent
  sessions). Useful complement to the memory seam, but lower leverage than the nine committed items; revisit
  after Wave 1.

### Out of scope

- Re-architecting the existing strong gates (checks-gate, freeze, redaction, memory seam).
- Domain skill packs (Vercel/Supabase/Stripe/Sentry) beyond the existing Sentry debug enrichment.

## Improvement Catalog

Each item carries an `IM-ID`, the gap, the requirement, the external source/champion, the loop step it
augments, and dependencies. Requirements are intent-level; mechanism and file layout are planning's job.

### Wave 1 — foundations (cheap, no dependencies, high fit)

**IM1 — Verification-before-completion gate (cross-cutting).** *Gap:* `skills/checks-gate` is CI-only and
`skills/gap-check` is plan-vs-diff; nothing forces *evidence over claims* before `/pf-commit` or `/pf-ready`.
*Requirement:* a reusable gate that blocks a "done" transition until fresh verification artifacts exist, with a
three-state verdict (verified / not-verified / inconclusive) distinguishing new failures from pre-existing.
*Source:* superpowers `verification-before-completion`, cursor-team-kit `verify-this`. *Augments:* the
commit/ready boundary in `commands/pf-ship.md`; reusable by debug and feedback. *Deps:* none. Fits pf's
fail-closed, no-false-green ethos.

**IM2 — Unify RCA + harden debugging.** *Gap:* `commands/pf-stabilize.md` uses an ad-hoc blocker ledger and
never loads `skills/rca-core/SKILL.md`, breaking R35's "one discipline, two entry points"; `/pf-debug` is
post-ship signal-only (no dev-time entry for test/build failures); no reproduction-first gate, no failing-
regression-test-before-fix, no rule-of-three escalation. *Requirement:* route `/pf-stabilize` through
`rca-core`; add a dev-time systematic-debugging entry; require a reliable repro (or a logged inability) before
a scoped fix; add a failing regression test before the fix; escalate to architecture review after three failed
fix attempts; offer git-bisect for regressions. *Source:* superpowers `systematic-debugging`, Hermes
`debug-runtime-evidence`, git-bisect practice. *Augments:* `skills/rca-core`, `commands/pf-stabilize.md`,
`commands/pf-debug.md`. *Deps:* none (debug/stabilize exist).

**IM3 — Post-merge compound orchestrator.** *Gap:* retro → compound → memory-sync → status reconcile is
documented in `rules/pf-workflow-sequencing.mdc` but never chained, so compounding does not reliably run each
ship. *Requirement:* an orchestrator that runs the post-merge compound sequence after the human merge gate,
honoring the existing report-only / human-gated promotion guardrails. *Source:* internal gap; mirrors
`commands/pf-ship.md`'s orchestration pattern. *Augments:* post-merge sequence. *Deps:* none.

### Wave 2 — document + execute rigor

**IM4 — Spec-rigor gates + requirements traceability.** *Gap:* the doc loop has no ambiguity/quality/
consistency passes before freeze, and R-IDs are not traced to tests, so coverage gaps surface only after
coding. *Requirement:* add clarify (ambiguity), checklist (requirement-quality), and analyze (spec ↔ task
consistency) passes before `/pf-freeze`, and an **R-ID → task → test** traceability check that flags
uncovered requirements. *Source:* GitHub Spec Kit (`clarify`/`checklist`/`analyze`), requirements-traceability
practice. *Augments:* `skills/prd`, `skills/doc-review`, `skills/tasks`, `skills/spec-union`. *Deps:* benefits
from conditional personas (in flight) but not blocked by it.

**IM5 — Test-first / TDD gate (execute).** *Gap:* the implementation step has no failing-test-before-code
discipline; PRD Testing Strategy is never enforced downstream. *Requirement:* a red-green-refactor gate in
`/pf-execute` — a failing test (traced to an R-ID, per IM4) exists and is observed to fail before
implementation; tests are not rewritten to pass. *Source:* superpowers `test-driven-development`. *Augments:*
`commands/pf-execute.md`. *Deps:* pairs with IM6 (same step); consumes IM4 traceability.

**IM6 — Subagent-driven execute + executable-plan granularity.** *Gap:* no execution discipline skill; `tasks`
is a checklist, not a code-bearing plan with a self-review gate. *Requirement:* fresh subagent per task with a
two-stage review (spec-compliance, then code-quality) between tasks; upgrade `tasks` toward executable steps
(exact paths, expected output) with a self-review pass (spec-coverage / placeholder-scan / type-consistency).
*Source:* superpowers `subagent-driven-development`, `writing-plans`. *Augments:* `commands/pf-execute.md`,
`skills/tasks`. *Deps:* design jointly with IM5 as one "execute discipline" workstream; honors
`rules/pf-subagent-dispatch.mdc`.

### Wave 3 — quality + lifecycle (depend on in-flight work)

**IM7 — Simplification / deslop pass.** *Gap:* nothing performs behavior-preserving cleanup after
implementation; the local-code-review spec explicitly deferred this. *Requirement:* a simplification step
(reuse / quality / efficiency review + AI-slop removal) between execute and stabilize, behavior-preserving and
re-verified. *Source:* compound-engineering `ce-simplify-code`, cursor-team-kit `deslop`. *Augments:* the ship
loop between `/pf-execute`/review and `/pf-stabilize`. *Deps:* slots alongside the in-flight local code review;
the conditional-persona rule governs any persona panel it uses.

**IM8 — Feedback closure loop.** *Gap:* `/pf-feedback` stops at handoff; `prds/GAP-BACKLOG.md` is not consumed
by `/pf-gaps` or `/pf-execute`; no "did the routed fix ship?" verification. *Requirement:* consume backlog
items into the implementation loop, and close a routed signal once its fix is verified shipped (reusing IM1's
verification gate). *Source:* internal gap. *Augments:* `skills/feedback`, `skills/gap-check`,
`commands/pf-execute.md`. *Deps:* IM1 (verification), and execute consuming the backlog.

**IM9 — E2E / smoke verification adapter.** *Gap:* `/pf-verify` runs config commands only
(`config/workflow.config.example.json` placeholders); browser/E2E verification was deferred. *Requirement:* a
provider-style verify adapter for smoke/E2E (e.g. Playwright / agent-browser) over affected routes, gated on
project type. *Source:* cursor-team-kit `run-smoke-tests`, compound-engineering `ce-test-browser`. *Augments:*
`commands/pf-verify.md`. *Deps:* stack-dependent; independent of the others.

## Sequencing

Three dependency-ordered waves (confirmed):

- **Wave 1 — foundations:** IM1 (verification gate), IM2 (RCA unification), IM3 (post-merge compound
  orchestrator). No dependencies; each is high-fit and self-contained; IM1 is reused by later waves.
- **Wave 2 — doc + execute rigor:** IM4 (spec rigor + traceability), then IM5 + IM6 together (one "execute
  discipline" workstream). IM5 consumes IM4's R-ID → test traceability.
- **Wave 3 — quality + lifecycle:** IM7 (simplification, after local code review lands), IM8 (feedback closure,
  after IM1 + execute-consumes-backlog), IM9 (E2E adapter, independent/stack-gated).

Each item is a candidate standalone workstream; `/pf-triage` + planning size them individually. IM5 and IM6
should be planned as a single unit.

## Open Questions

- **Verification-gate scope (IM1).** Whether the gate is a new atomic command, a step folded into
  `/pf-verify`/`/pf-commit`, or a reusable skill the loops call — resolve in planning.
- **Execute discipline ownership (IM5/IM6).** Whether TDD and subagent-driven execution ship as one
  `/pf-execute` rewrite or as a gate plus an orchestration mode.
- **Spec-rigor gate weight (IM4).** Whether clarify/checklist/analyze are always-on or tier-gated (interacts
  with the conditional-persona work).
- **Re-evaluate `ce-sessions` (deferred J)** after Wave 1, once the verification and RCA gates exist to consume
  prior-attempt context.

## Sources & Research

- Internal loop/gap map of `commands/`, `skills/`, `rules/`, `agents/`, `docs/plans/`, `docs/brainstorms/`.
- External 2026 best practices: GitHub Spec Kit (clarify/checklist/analyze, traceability), obra/superpowers
  (subagent-driven dev, verification-before-completion, condition-based-waiting), Hermes `systematic-debugging`
  / `debug-runtime-evidence`, atoslins/dod-guard (executable Definition of Done), TDD-with-agents writeups,
  git-bisect-for-regressions practice.
- Skill-ecosystem survey: superpowers, cursor-team-kit, and compound-engineering SKILL.md sets vs. the 19
  existing phase-flow v2 skills.
- Related in-flight brainstorms: `docs/brainstorms/2026-06-23-local-code-review-loop-integration-requirements.md`,
  `docs/brainstorms/2026-06-23-conditional-review-personas-requirements.md`.
