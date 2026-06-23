---
date: 2026-06-23
topic: local-code-review-loop-integration
---

# Local Code Review in the Ship Loop (CE code-review integration)

## Summary

Add a **local, multi-agent code review against the implementation** as the first phase of `/pf-review`,
running before the external review provider (CodeRabbit) and before CI — "a local review of the code prior
to any other tooling." It is wired in via the plugin's existing **provider-adapter** pattern: a new
`review.local.provider` config selects a code-review adapter under `providers/code-review/`, with
`ce-code-review` (the compound-engineering skill) as the adapter — a **soft dependency**: if it is not
installed, phase 1 skips with a clear message and the loop proceeds to the provider review. The local review
reports normalized findings; **phase-flow owns the apply and the gate** (P0/P1 halt `/pf-ship`, P2/P3 surface and continue). Requirements completeness stays owned by the
existing `gap-check`, so there is one source of truth. This document also records researched recommendations
for other compound-engineering commands, with integrate/defer/skip verdicts — no build commitment beyond the
local-review integration.

## Problem Frame

`/ce-code-review` has proven useful during development: a parallel-persona LLM review (correctness, security,
maintainability, testing, and conditional reviewers) that catches issues fast, locally, before any external
service runs. The phase-flow v2 ship loop has no equivalent for **code**:

```
pf-execute → pf-verify → pf-review → gap-check → pf-commit → pf-pr → pf-watch-ci → pf-stabilize → pf-ready
```

`/pf-review` today means **the external provider** (CodeRabbit CLI over the uncommitted delta). The earliest
substantive review of code quality therefore depends on an external tool and, for branch/PR concerns, on CI.
There is a gap: no fast, local, requirements-aware review of the implementation before that tooling engages.

Notably, the plugin **already has the exact pattern** `ce-code-review` uses — parallel persona sub-agents +
synthesis — but only for *documents* (`/pf-doc-review` + `agents/pf-*-reviewer.md` + `skills/doc-review`).
And `gap-check` already maps plan (spec union) vs diff for **requirements completeness**. So the missing piece
is specifically a **code-quality** local review, not a second requirements checker.

**Why now:** the user has adopted `/ce-code-review` manually in the dev process; promoting it into the loop
makes the local-first review consistent and gated rather than ad hoc.

## Key Decisions

- **Provider-adapter coupling; `ce-code-review` is a soft dependency (Q1).** The local review is selected by
  `review.local.provider` and implemented by an adapter under `providers/code-review/`, exactly mirroring the
  existing `review.provider` abstraction for CodeRabbit. `ce-code-review` is the default (and, this effort, the
  only) adapter; `none` disables. **The local-review guarantee is conditional on `ce-code-review` being
  installed:** if the configured adapter's skill is unavailable, phase 1 **skips with a clear message**
  (fail-closed, matching the CodeRabbit "review disabled" path) and the loop proceeds to phase 2. A pf-native
  persona panel was considered as a no-dependency fallback but is **deferred as YAGNI** (one real consumer
  today; skip-with-message already satisfies fail-closed — see Open Questions). The adapter pattern keeps the
  integration `pf-`-namespaced and swappable; it isolates the runtime dependency rather than eliminating it.
- **Two-phase `/pf-review`: local first, then provider (Q2).** `/pf-review` becomes phase 1 = local
  multi-agent review (adapter), phase 2 = provider review (CodeRabbit, unchanged). "Review" stays the single
  review gate in the loop; loop length is unchanged. Phase 1 before phase 2 satisfies "prior to any other
  tooling."
- **`gap-check` remains the requirements authority (Q3).** The local review is requirements-*aware* (it
  receives the intent summary) but emits **no completeness verdict**. The original mechanism here was wrong and
  is corrected: omitting `plan:` does **not** silence requirements checking, because `ce-code-review` Stage 2b
  *auto-discovers* a plan from the branch name / PR body and leaks unaddressed-requirement findings into
  `findings[]` (P3 if inferred, P1 if explicit). Authority is preserved instead by the **adapter filtering out
  requirement-stage findings** before they reach pf's gate (see Adapter contract). `gap-check` (spec union vs
  diff + bounded closers + feedback-workstream escalation) stays the one source of truth. No double-reporting,
  no conflicting verdicts.
- **Report-only adapter; phase-flow owns apply + the severity gate (Q4).** The adapter runs the review in
  **report-only** mode (`ce-code-review mode:agent`, schema-stable JSON; the skill mutates nothing — note the
  *content* is not reproducible, it is an LLM pipeline). pf auto-applies only **low-risk P2/P3** fixes that
  carry a concrete `suggested_fix` (with `requires_verification:false`) through **its own** edit machinery (so
  redaction/commit/memory guardrails stay intact); **P0/P1 are never auto-fixed.** pf re-verifies, then gates:
  **any P0/P1 halts `/pf-ship`** for the human (like the merge gate); **P2/P3 are surfaced and the loop
  continues** to phase 2. To avoid false-halts, only **validated** P0/P1 (post the skill's Stage 5b validation
  wave) reach the halt, and the gate may ship surface-only (non-halting) until the local false-positive rate is
  known (see Open Questions). Keeps mutation under pf control rather than letting an external skill commit into
  the pf worktree.
- **The reviewed diff and adapter output are untrusted at the apply boundary (new, from review).** The code
  under review is untrusted input and the adapter's `suggested_fix`/`file` fields flow into pf's auto-apply
  path — a prompt-injection-to-apply sink. Before applying, pf validates adapter output: `file` must resolve
  **within the repo** (no path traversal), fix size is bounded, and fixes touching security-sensitive surfaces
  (auth, secrets, credentials, CI config) are **never auto-applied** — they are surfaced for the human. The
  adapter is pinned to an assumed `ce-code-review` schema version with a golden-schema contract test that fails
  loudly on drift.
- **Redaction at the persist edges (Q5).** The diff is reviewed in the clear — it is the user's local code and
  in-session sub-agents share the main agent's trust boundary, so redacting the input would cripple the review
  for no egress benefit. There are **two persist edges, not one:** (1) durable review learnings are written
  only via `memory-preflight` + `scripts/memory-redact.sh` (no direct Recallium, no raw dumps); and
  (2) `ce-code-review` independently writes cleartext run artifacts (`full.diff`, quoted evidence,
  `review.json`, `report.md`) to `/tmp/compound-engineering/<run-id>/` **outside** pf's chokepoint — so the
  adapter must **scrub/shred the run dir after parsing** (or the residual cleartext-`/tmp` exposure is
  documented and explicitly accepted as residual risk). These files are not "ephemeral" in any security sense.
- **Focused build scope (Q6, defaulted).** This effort builds the local-review integration only. Other
  compound-engineering commands are evaluated in the Recommendations section with integrate/defer/skip
  verdicts and **no build commitment**, keeping the plan to the plugin's one-workstream-per-plan rhythm.

## High-Level Design

```mermaid
flowchart TB
  EXEC[pf-execute] --> REVIEW
  subgraph REVIEW[/pf-review: two-phase/]
    P1L[Phase 1: local multi-agent review\nreview.local.provider adapter] --> APPLY[pf applies safe fixes\n+ targeted re-verify]
    APPLY --> GATE{severity gate}
    GATE -->|P0/P1 unresolved| HALT[HALT pf-ship -> human]
    GATE -->|P2/P3 / clean| P2P[Phase 2: provider review\nCodeRabbit, unchanged]
  end
  P2P --> GAP[gap-check\nrequirements authority]
  GAP --> COMMIT[pf-commit -> pf-pr -> pf-watch-ci -> pf-stabilize -> pf-ready]
```

### Adapter contract (provider-neutral)

The `/pf-review` phase-1 step consumes a **normalized findings JSON**, so any adapter is swappable:

```json
{
  "status": "complete | skipped | failed | degraded",
  "verdict": "ready | ready-with-fixes | not-ready",
  "findings": [
    {
      "severity": "P0 | P1 | P2 | P3",
      "file": "path/to/file",
      "line": 0,
      "title": "terse issue",
      "suggested_fix": "concrete fix or empty",
      "confidence": 0,
      "requires_verification": true
    }
  ]
}
```

- **`ce-code-review` adapter:** invokes `ce-code-review mode:agent base:<parentBranch> grouping:auto`, parses
  the skill's JSON object, and **normalizes** it — the `findings[]` contract fields are a subset of the ce
  finding object, and the verdict string (`Ready to merge | Ready with fixes | Not ready`) is mapped to the
  contract enum. It must handle the skill's non-finding outcomes: `{"status":"skipped|failed|degraded"}`
  carries **no `findings` array** and is treated **fail-closed** (surface the reason + skip phase 1), **never**
  as a clean review — a missing `findings` array must not deserialize to "0 findings → pass."
- **Requirements suppression (corrects the original dormancy assumption):** omitting `plan:` does **not** keep
  the Requirements Completeness stage dormant — the skill auto-discovers a plan and emits requirement findings
  *into `findings[]`* (P3 inferred / P1 explicit). So the adapter **post-filters requirement-stage findings**
  out of its normalized output (heuristic, pending a `plan:none`-style affordance upstream); dropping only a
  top-level field is insufficient. This is what preserves `gap-check`'s sole authority.
- **`native` adapter:** deferred this effort (see Q1 / Open Questions). When `ce-code-review` is absent, phase
  1 skips with a message rather than falling back.

### `/pf-review` procedure (revised)

1. Resolve `review.local` from `workflow.config.json`. If `review.local.enabled` is false or
   `review.local.provider` is `none`, skip to phase 2.
2. Resolve `review.local.provider`; read `providers/code-review/<provider>.md`. If the adapter's underlying
   skill is unavailable → **skip phase 1 with a clear message** (no `native` fallback this effort).
3. `memory-preflight` **read** for known bot false-positives / prior learnings (as today).
4. Compute base = per-worktree `parentBranch` (aligns with `gap-check`'s base). Invoke the adapter → normalized
   JSON. A `status` of `skipped|failed|degraded` (no `findings`) → surface the reason and skip phase 1
   (fail-closed); never treat as clean. Filter out requirement-stage findings before gating.
5. pf **applies** only low-risk **P2/P3** fixes carrying a concrete `suggested_fix` — after validating `file`
   resolves in-repo, the fix is size-bounded, and the target is not security-sensitive; **P0/P1 are never
   auto-fixed.** Re-run targeted `pf-verify`. Bounded: one re-verify pass; circuit-breaker on 3 identical
   failures (per `pf-subagent-dispatch`).
6. **Severity gate:** any **validated P0/P1** → halt `/pf-ship`, surface to the human. **P2/P3** → surface,
   continue. (Gate may ship surface-only first — see Open Questions.)
7. `memory-preflight` **write** for durable learnings only (redacted; no raw dumps). Scrub the
   `ce-code-review` run dir after parsing.
8. **Phase 2:** provider review flow. pf-applied phase-1 fixes are committed/labeled first so the provider
   reviews the post-fix state as baseline; any phase-2 finding on a phase-1-touched line is annotated
   "contests applied fix" for the human (no automatic re-litigation).

### Configuration

```jsonc
// .cursor/workflow.config.json
"review": {
  "provider": "coderabbit",          // existing external/provider review (phase 2)
  "enabled": true,
  "local": {                          // NEW (phase 1)
    "enabled": true,
    "provider": "ce-code-review",     // adapter under providers/code-review/  (| native | none)
    "gate": { "haltOn": ["P0", "P1"], "surface": ["P2", "P3"] },
    "grouping": "auto"
  }
}
```

### Error handling & guardrails

- Adapter never pushes, opens PRs, or merges. No external network/API for the local phase.
- Skill/adapter unavailable, or a `status` of `skipped|failed|degraded` → clean skip with a clear message,
  never treated as a clean review; never hang.
- Apply loop bounded (one re-verify; circuit breaker) per `rules/pf-subagent-dispatch.mdc` and
  `rules/checks-gate.mdc`; gate truth still comes only from `scripts/check-gate.sh` for CI.
- Memory writes only through `memory-preflight`; redaction via `scripts/memory-redact.sh`; no direct Recallium.
- Description contract honored: `/pf-review` states it runs local-then-provider review and does **not** run the
  CI gate or stabilize PR threads.

### Testing

- Adapter JSON parse: well-formed, malformed, and **`status:skipped|failed|degraded`** outputs handled — the
  no-`findings` outcomes are fail-closed skips, never a clean pass.
- Verdict normalization: ce verdict strings map to the contract enum.
- Severity gate: any P0/P1 halts; P2/P3 continues; clean review proceeds to phase 2.
- Skip paths: `review.local.enabled=false`, `provider=none`, and adapter-skill-absent → clean skip-with-message.
- Requirements isolation: with a discoverable `docs/plans/*.md` planted on the branch, the adapter's normalized
  output contains **zero requirement-stage findings** (gap-check unaffected).
- Untrusted-output safety: a `suggested_fix` with a path-traversal `file`, an oversize fix, or a
  security-sensitive target is **not** auto-applied.
- Persist edges: a secret/PII learning is scrubbed before any memory write; the `ce-code-review` run dir is
  scrubbed/removed after parsing.
- Contract drift: a golden-schema fixture fails loudly if the ce `mode:agent` shape changes.

### Files touched

- `commands/pf-review.md` — two-phase procedure + description.
- `providers/code-review/ce-code-review.md` — new adapter (mirror `providers/review/coderabbit.md`); includes
  verdict/`status` normalization, requirement-finding filtering, run-dir scrub, and untrusted-output
  validation. (`native` deferred — not built this effort.)
- `config/workflow.config.example.json` (+ any schema/defaults) — `review.local` block; per-repo
  `.cursor/workflow.config.json` documents the same.
- `commands/pf-ship.md` — phase-1 halt in stop-conditions / CI segment notes.
- `rules/code-review-automation.mdc`, `rules/pf-workflow-sequencing.mdc` — document local-first review and the
  updated `/pf-review` boundary row.
- `scripts/test/` — fixtures listed under Testing.

## Recommendations: other compound-engineering commands

Researched mapping of CE skills against existing pf commands. Build commitment is **only** the local-review
integration above; the rest are recommendations.

| CE command | Verdict | Rationale |
| --- | --- | --- |
| ce-brainstorm, ce-plan, ce-commit, ce-commit-push-pr, ce-compound, ce-debug, ce-doc-review, ce-worktree | **Already covered** | `pf-brainstorm`, `pf-doc`/`pf-prd`, `pf-commit`, `pf-pr`, `pf-compound`, `pf-debug`, `pf-doc-review`, `pf-worktree`. |
| **ce-code-review** | **Integrate (this effort)** | Fills the only real gap: local code-quality review. |
| **ce-simplify-code** | **Defer (re-evaluate)** | Correction: `ce-code-review` does **not** dispatch a simplicity persona — its always-on `maintainability` reviewer covers *some* complexity/abstraction concerns, but dedicated simplification is not run, so there is no free absorption. A standalone `/pf-simplify` pass (or a simplicity persona in a future `native` panel) is a deliberate follow-up, not captured by adopting the adapter. |
| **ce-sessions** | **Defer** | Synthesizes prior agent sessions — a useful input to `pf-debug`/`memory`, not the ship loop. Wire into the debugging workstream later. |
| **ce-test-browser** | **Defer (conditional)** | Could augment `pf-verify` for web changes via an E2E provider adapter, gated on project type. Out of scope here. |
| **ce-resolve-pr-feedback** | **Skip** | `pf-stabilize` already owns PR-thread resolution. |
| ce-optimize, ce-proof, ce-strategy, ce-ideate, ce-product-pulse, ce-slack-research, ce-demo-reel, ce-frontend-design, ce-promote, lfg/ce-work | **Skip (for the loop)** | Product/strategy/design/orchestration concerns outside the ship loop, or overlapping `pf-ship`. |

## Scope Boundaries

### In scope

- Two-phase `/pf-review` with a `review.local` provider-adapter (the `ce-code-review` adapter), report-only +
  pf-owned apply with untrusted-output validation, the validated-severity gate, both-persist-edge redaction
  (memory + run-dir scrub), a version-pinned contract test, config, docs, and fixtures.

### Out of scope / deferred

- The `native` no-dependency fallback adapter (deferred as YAGNI; fallback is skip-with-message).
- A standalone `/pf-simplify` command (not absorbed by `ce-code-review`; a deliberate later follow-up).
- `ce-sessions` and `ce-test-browser` integrations.
- Any change to `gap-check`'s requirements ownership beyond passing the local review the intent summary as
  context.
- Changing the external provider (CodeRabbit) behavior in phase 2.

## Open Questions

- **Cost/latency budget & marginal value.** Phase 1 is a heavy nested run (reviewers + a per-finding validator
  wave — potentially 20+ sub-agent dispatches) before CodeRabbit and CI on the same delta. State a cost budget
  and a do-nothing baseline (what unique P0/P1 does local catch over CodeRabbit+CI?), consider a lighter
  default (capped validator dispatch / reduced persona set), and instrument adoption so "disabled in practice"
  (a one-line `enabled:false` opt-out) is observable rather than assumed away.
- **Surface-only vs. halting rollout.** Whether to ship the P0/P1 halt on day one or start surface-only until
  the validated local false-positive rate is measured, then promote to halting.
- **native fallback (deferred).** If the local-review guarantee must later hold *without* `ce-code-review`
  installed, promote `native` from deferred to a hard in-scope deliverable with a defined minimal roster and
  the same JSON-conformance tests as the ce adapter.
- **Apply aggressiveness.** Exact threshold for auto-applying P2/P3 (current default: concrete `suggested_fix`
  + `requires_verification=false` + in-repo, size-bounded, non-security target) — tune during implementation
  against `pf-subagent-dispatch` bounds.

## Sources & Research

- phase-flow v2 plugin: `commands/pf-ship.md`, `commands/pf-review.md`, `commands/pf-doc-review.md`,
  `skills/gap-check/SKILL.md`, `rules/pf-workflow-sequencing.mdc`, `rules/pf-subagent-dispatch.mdc`,
  `rules/code-review-automation.mdc`, `providers/review/coderabbit.md`, `agents/pf-*-reviewer.md`.
- compound-engineering: `ce-code-review` SKILL (modes, requirements-completeness stage, normalized findings,
  persona roster incl. `ce-code-simplicity-reviewer`) and the broader CE skill catalog.
- Prior decision context: `docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md` (frozen),
  `docs/plans/2026-06-22-005-feat-feedback-workstream-plan.md`.
