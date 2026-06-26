---
date: 2026-06-26
topic: pre-work-memory-search-gate
brainstorm: docs/brainstorms/2026-06-26-pre-work-memory-search-gate-requirements.md
frozen: true
frozen_at: 2026-06-26
---

# PRD 019 — Pre-work memory-search obligation (read-before-work gate)

## Overview

Shipwright's compounding-memory premise assumes every agent consults durable memory — rules, prior decisions,
similar changes, learnings — **before** performing substantive work, so the development lifecycle stays
consistent. Today that consultation is **best-effort, not enforced**: `sessionStart` injection is explicitly
best-effort; fail-closed enforcement exists only at `beforeSubmitPrompt` and only for **guardrails**, not for
memory reads; `skills/memory/SKILL.md` (`memory-preflight`) frames its read mode as per-command **guidance**;
and `rules/sw-subagent-dispatch.mdc` imposes **no** search obligation, so a delegated work sub-agent can
implement, debug, or author without ever querying memory. The result is agents re-deriving existing decisions
and drifting from established rules/learnings.

This PRD makes the pre-work memory search a **categorical, enforced obligation** at the entry of every
work-performing command and at sub-agent dispatch, expressed against the provider-agnostic `memory-preflight`
adapter (the memory location is provider-variable: `in-repo` | `recallium`), surfaced and reconciled before
mutation, recorded as an auditable breadcrumb, and backed by a mechanical pre-mutation record that
**degrades open** on a provider outage. It closes GAP-BACKLOG row 38 (memory-before-work enforcement) and
derives from the frozen brainstorm
`docs/brainstorms/2026-06-26-pre-work-memory-search-gate-requirements.md` (R1–R10).

It composes with — and does not re-specify — PRD 017 (R25 dispatch-prompt redaction; R23 preflight/`preToolUse`
deny pattern, reused as the enforcement vehicle) and PRD 015 (decision-class source-of-truth) — this is the
**read-before-work** obligation, orthogonal to PRD 015's store/authority contract.

## Goals

1. Every work-performing command searches relevant memory before its first substantive mutation — not as
   guidance, but as a recorded, enforced step.
2. Delegated work sub-agents inherit the same obligation, so delegation never bypasses memory consultation.
3. The obligation is provider-agnostic, degrades open on outage (never blocks work), and is auditable
   (including an explicit "no relevant memory found").
4. Found rules/decisions are reconciled before action, not silently ignored.

## Non-Goals

- Changing the memory **store / source-of-truth** contract (PRD 015 territory) — this is read-before-work only.
- Making memory the **authority** over git/state/`agentsFile` — memory remains an input, not an authority
  (memory SKILL boundary).
- **Blocking work when the provider is unreachable** — the gate degrades open (memory SKILL outage contract).
- Introducing a second dispatch/`preToolUse` enforcement mechanism — reuse the PRD 017 R23 preflight/deny
  pattern rather than a parallel hook.
- Auto-promoting found memory to rule-class or auto-resolving conflicts — reconciliation is surfaced to the
  agent; rule-class promotion stays human-gated (`memory-guardrails` R42).
- Mandating a search before purely read-only / informational commands (`/sw-status`, `/sw-watch-ci` green
  path) — the obligation is scoped to *work-performing* surfaces.

## Requirements

R1–R10 are carried forward from the frozen brainstorm (stable namespace; do not renumber). Requirement text
receives only clarifying edits.

### The obligation

- **R1** A mandatory pre-work `memory-preflight` **search** (read mode) MUST run at the entry of every
  *work-performing* command before its first substantive mutation. The enumerated set is: `/sw-execute`,
  `/sw-debug` (`rca-core` entry), `/sw-prd`, `/sw-brainstorm`, `/sw-amend`, `/sw-review`, `/sw-stabilize`.
- **R2** The obligation MUST be inherited at **sub-agent dispatch**: `rules/sw-subagent-dispatch.mdc` MUST
  require that a delegated work-performing sub-agent either performs the pre-work search itself or is handed a
  fresh redacted search result, so delegation cannot bypass it. Mechanical/cheap-tier non-work dispatch
  (pure exploration with no mutation) is exempt.
- **R3** The search MUST route through `memory-preflight` + `providers/<memory.provider>.md`
  (provider-agnostic; the store location is variable: `in-repo` | `recallium` | future) — never a direct
  provider call (`sw-guardrails`).

### Scope, surface, reconcile

- **R4** The search MUST be **scoped** to the touched files/feature plus the relevant classes (`rule`,
  `decision`, `learning`, `code-context`, `design`) per the `CAPABILITIES.md` read recipe — file-path +
  semantic + optional category, not one broad query.
- **R5** Hits MUST be **surfaced to the acting agent before mutation** and **reconciled** against found
  rules/decisions: an applicable `rule` or a contradicting prior `decision` is a reconcile obligation (the
  agent records alignment or an explicit conflict + how it is resolved), never a silent ignore. A direct
  conflict with a frozen decision/rule that cannot be reconciled is a blocker (route per the command's
  halt contract).

### Degrade-open, audit, enforcement

- **R6** On provider unreachability the obligation MUST **degrade open**: record a `memory:offline` breadcrumb
  and proceed. It MUST NOT block work on a memory outage (consistent with the `memory-preflight` outage
  contract). Offline status MUST be determined by the adapter reachability probe (mechanical), not by an agent
  assertion, so "offline" cannot be claimed to skip a reachable search.
- **R7** The search and its outcome MUST be recorded as a durable, auditable breadcrumb (`run.log` / per-repo
  state) — including an explicit `memory:none` ("no relevant memory found") — redacted via
  `scripts/memory-redact.sh` (R41) before persist. A raw transcript/result dump MUST NOT be the breadcrumb.
- **R8** Enforcement MUST be mechanical, not procedural-only, and MUST reuse the PRD 017 R23 pattern: a
  pre-mutation **search record** (resolved scope + classes + nonce, or a `memory:offline` breadcrumb) MUST be
  written for the work surface immediately before the first file-mutating tool call, and the registered
  `preToolUse` hook MUST **deny** that first mutation for a work-performing surface when no fresh search record
  exists. The hard-block is on the *attempt/record*, never on work when the provider is down (R6 degrade-open
  satisfies the gate via the offline breadcrumb).

### Security + cross-cutting

- **R9** Memory-search results assembled into a delegated `Task` prompt MUST pass `scripts/memory-redact.sh`
  and be fenced (reuse PRD 017 R25); raw memory payloads MUST NOT be forwarded.
- **R10** All behavior authored in `core/` MUST propagate to `dist/cursor` and `dist/claude-code` via
  `python3 -m sw generate --all` (freshness gate passing), be covered by fixtures (see Testing Strategy), and
  be documented in `skills/memory/SKILL.md`, `rules/sw-subagent-dispatch.mdc`, the enumerated command files,
  `.sw/layout.md`, and the memory guide.

## Technical Requirements

- **TR1 — Memory-preflight entry obligation.** Encode R1/R4/R5 in `core/skills/memory/SKILL.md`: a "pre-work
  search (mandatory)" section with the scoped read recipe + reconcile contract, and a per-command entry hook
  reference in each enumerated command file's procedure (`/sw-execute`, `/sw-debug`, `/sw-prd`,
  `/sw-brainstorm`, `/sw-amend`, `/sw-review`, `/sw-stabilize`).
- **TR2 — Search record + degrade-open breadcrumb.** Add a `scripts/wave.sh memory preflight` verb (or extend
  the existing dispatch-preflight from PRD 017 R23) that records a per-surface search artifact
  (scope + classes + nonce) or a `memory:offline` / `memory:none` breadcrumb, redacted via `memory-redact.sh`
  (R6, R7). Single-sourced so command and dispatch paths share one recorder. The `memory:offline` breadcrumb
  MUST be gated on the adapter reachability probe (mechanical), never on an agent-supplied flag (R6).
- **TR3 — `preToolUse` deny reuse.** Extend `core/hooks/before_task_dispatch.py` / the registered `preToolUse`
  hook to deny the first file-mutating tool call for a work-performing surface lacking a fresh search record,
  reusing the PRD 017 R23 deny mechanism (no second hook) and honoring the degrade-open breadcrumb (R8).
- **TR4 — Dispatch-rule obligation.** Update `core/rules/sw-subagent-dispatch.mdc` so delegated
  work-performing sub-agents carry the pre-work search obligation (perform-or-be-handed-redacted-result);
  exempt pure-exploration/mechanical non-mutating dispatch (R2).
- **TR5 — Redaction reuse.** Forwarded memory results into delegated prompts pass `memory-redact.sh` + fencing
  via the existing PRD 017 R25 assembly path (R9).
- **TR6 — Emitter + docs + fixtures.** Regenerate `dist/`; update R10 docs; add the Testing Strategy fixtures.

## Security & Compliance

- **Redaction chokepoint (R41) preserved and extended.** The search breadcrumb and any forwarded result are
  redacted before persist/inject (R7, R9); no raw transcript/secret is stored.
- **Trust boundary unchanged.** The obligation only *reads* memory through the existing adapter; it grants no
  new provider scope and never makes memory authoritative (memory SKILL boundary; PRD 015 unchanged).
- **Degrade-open, not fail-open-silently.** A provider outage degrades to a recorded `memory:offline`
  breadcrumb (auditable), so availability is preserved without silently skipping the obligation (R6, R7).
- **No new enforcement surface.** Enforcement reuses the PRD 017 R23 `preToolUse` deny path; the deny cannot
  inject content, only block a mutation lacking a record — consistent with the Cursor hook capability
  (PRD 012 DL-2 / PRD 017 R8).
- **Rule-class gate intact.** Reconciliation surfaces found rules to the agent; it never auto-promotes memory
  to rule-class (`memory-guardrails` R42 human gate unchanged).

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test` (memory + dispatch
suites). Enforcement fixtures are integration-style (observe the record + deny), not doc-grep-only.

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `memory-prework-search-entry` | each enumerated work-performing command routes a scoped `memory-preflight search` before its first mutation | R1, R4 |
| `memory-prework-dispatch-inherited` | a delegated work sub-agent performs/receives the pre-work search; pure-exploration dispatch exempt | R2 |
| `memory-prework-provider-agnostic` | the search routes through `memory-preflight` + the resolved adapter; no direct provider call | R3 |
| `memory-prework-surface-reconcile` | hits are surfaced before mutation; a contradicting frozen rule/decision forces a recorded reconcile/blocker, not a silent ignore | R5 |
| `memory-prework-degrade-open` | provider unreachable → `memory:offline` breadcrumb recorded and work proceeds (no block) | R6 |
| `memory-prework-breadcrumb-audited` | search outcome (hits / `memory:none`) recorded durably and redacted via `memory-redact.sh` | R7 |
| `memory-prework-pretooluse-deny` | the first file-mutation for a work surface is denied without a fresh search record (or offline breadcrumb); reuses the PRD 017 R23 deny path | R8 |
| `memory-prework-prompt-redacted` | forwarded memory results into a delegated prompt are redacted + fenced; raw payloads not forwarded | R9 |
| `memory-prework-emitter-freshness` | `dist/` regenerated and fresh | R10 |
| `memory-prework-docs-presence` | memory skill, dispatch rule, enumerated commands, layout, guide describe the obligation | R10 |

## Rollout Plan

- **Single feature branch** `feat/pre-work-memory-search-gate`, dependency-ordered: (1) memory-preflight
  entry obligation + scoped read recipe + reconcile contract (R1, R3, R4, R5; TR1); (2) search record +
  degrade-open breadcrumb recorder, single-sourced (R6, R7; TR2); (3) `preToolUse` deny reuse + dispatch-rule
  obligation + redaction reuse (R2, R8, R9; TR3–TR5); (4) docs + dist + fixtures (R10; TR6).
- **Reuses PRD 017 enforcement.** TR3 depends on the PRD 017 R23 preflight/`preToolUse` deny mechanism; if
  PRD 017 has not landed, ship the recorder + procedural obligation first and wire the deny when 017's hook is
  present (graceful sequencing, not a hard dependency).
- **Backward compatible.** Degrade-open preserves today's behavior on a memory outage; the obligation adds a
  recorded step, not a new blocking failure mode for offline memory.
- **Bootstrap caution.** First adoption SHOULD be supervised until the enforcement fixtures are green.
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | New standalone PRD, not an amendment to PRD 015 | PRD 015 is the decision-class store/authority (source-of-truth) contract; the read-before-work gate is orthogonal and cross-cutting across ~7 commands + dispatch. Folding it into 015 would breach 015's decision-SoT scope (scope-guardian lens). |
| DL-2 | Gate degrades open on provider outage; never blocks work | The `memory-preflight` contract already mandates degrade-not-block on outage; a hard fail-closed gate would make every work command brittle to memory availability. The hard-block is on the *attempt/record*, satisfied by an offline breadcrumb (feasibility + adversarial lenses). |
| DL-3 | Enforcement reuses the PRD 017 R23 preflight/`preToolUse` deny pattern, not a new hook | One mechanical deny mechanism avoids a second, divergent enforcement surface; the Cursor hook can deny (not inject), which is exactly what a pre-mutation record check needs (coherence + feasibility lenses; PRD 017 DL-5). |
| DL-4 | Obligation scoped to enumerated *work-performing* commands + work dispatch; read-only/exploration exempt | A categorical "every command" gate would fire on `/sw-status` and pure exploration with no consistency benefit and real friction; scoping to mutation-bearing surfaces matches the stated intent (scope-guardian lens). |
| DL-5 | Record an explicit `memory:none` when nothing relevant is found | Without a positive "searched, found nothing" breadcrumb the gate cannot distinguish "searched, empty" from "never searched"; the audit needs both (adversarial lens). |
| DL-6 | Reconciliation is surfaced to the agent, not auto-applied | Auto-resolving a memory↔change conflict would let stale memory silently override fresh intent (or vice versa); surfacing + recorded reconcile keeps the human/agent decision explicit and preserves the rule-class human gate (product + security lenses). |

## Open Questions

None. The enforcement vehicle is resolved (reuse PRD 017 R23; DL-3); doc-authoring commands
(`/sw-prd`/`/sw-brainstorm`) are in the enumerated work-performing set (R1) since they author durable
artifacts that should reconcile against prior decisions; the degrade-open boundary is fixed by the memory
outage contract (DL-2).
