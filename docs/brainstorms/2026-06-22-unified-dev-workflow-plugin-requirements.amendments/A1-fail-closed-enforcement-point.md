---
date: 2026-06-22
amends: docs/brainstorms/2026-06-22-unified-dev-workflow-plugin-requirements.md
frozen: true
frozen_at: 2026-06-22
supersedes: [R39]
---

# Amendment A1 — Fail-closed guardrail enforcement point

## Context

The frozen requirements place fail-closed rule-class guardrail enforcement at the `sessionStart` hook
(R32, R39). The foundation plan (`docs/plans/2026-06-22-001-feat-plugin-foundation-infrastructure-plan.md`)
found during review that Cursor's `sessionStart` hook is fire-and-forget and cannot block a session, so the
"halt loudly, no unguarded session" guarantee cannot be honored at that event. This amendment relocates the
enforcement point while preserving the fail-closed intent. The parent is not edited.

## R44 (supersedes R39's fail-closed clause)

Rule-class guardrail enforcement is asserted at the `beforeSubmitPrompt` hook, whose `continue: false` is
enforced by Cursor: if rule-class guardrails cannot be confirmed (memory provider unreachable / fetch
fails), the first user prompt is blocked with a loud, actionable error — no unguarded **action** proceeds.
`sessionStart` still injects rule-class memories and the tiered caveman directive on a **best-effort** basis
when the provider is reachable, but is no longer the fail-closed enforcement point (it cannot block).
`sessionStart` injection, the caveman directive, and the stop-hook memory-sync scheduler remain fail-open.

R32's intent is preserved verbatim — always-on guardrails cannot silently fail to surface, and reachable
memory is a hard precondition for guarded action; only the **enforcing hook event** changes (from
`sessionStart` to `beforeSubmitPrompt`).

Additionally, because Cursor's `sessionStart` `additional_context` injection is subject to a known platform
reliability bug (context can be dropped before the composer is created), an always-on guardrail subset is
mirrored to a static `.cursor/rules` fallback so the most critical guardrails surface even if hook injection
drops. This is a resilience backstop, not a replacement for the `beforeSubmitPrompt` enforcement.

This amendment changes only R39's fail-closed clause and the enforcing hook event. R39's other content
(sessionStart injection existing at all, the caveman directive, the stop-hook scheduler, the fail-open
split for non-guardrail operations) and all other requirements are unaffected.
