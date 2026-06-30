---
date: 2026-06-27
amends: docs/prds/024-orchestrator-plan-policy-adoption/024-prd-orchestrator-plan-policy-adoption.md
frozen: true
frozen_at: 2026-06-27
---

# Amendment A2: parallel dispatch-preflight + command-authoritative tier binding (GAP-039, GAP-040)

## Overview

Parent PRD 024 fans plan-policy out to `/sw-debug`, `/sw-doc`, and `/sw-feedback`. TR4b requires `/sw-doc` to
cover **parallel persona dispatch** for doc-review. Two open GAP-BACKLOG items block faithful `/sw-doc`
execution on the **canonical path** (including consistency-only adoption per R36c — the panel runs regardless
of `proposed` surface):

- **GAP-039** — `core/hooks/before_task_dispatch.py` + `wave_preflight.py` persist a **single**
  overwrite-on-consume record (`.cursor/hooks/state/task-dispatch-preflight.json`). The first bound Task
  spawn consumes it; subsequent parallel persona Tasks fail `stale-preflight-nonce` /
  `preflight-agent-mismatch`. This contradicts `skills/doc-review/SKILL.md` (R28/R31) and `/sw-doc` delegated
  Task binding (one preflight per persona in parallel).
- **GAP-040** — `scripts/dispatch-check.py` and `wave_preflight.py` resolve model tier via
  `resolve-model-tier.py --agent` only, while orchestrator prose (KD8 / `sw-subagent-dispatch.mdc`) requires
  delegated atomics to inherit `--command` routing. Example: `--command sw-prd` → `deep`, but agent-default
  resolution → `build` / `composer-2.5`, silently down-tiering delegated PRD authoring (observed on PRD 026).

This amendment adds **R38** (parallel preflight) and **R39** (command-authoritative tier resolution). It is
additive, closes no parent requirement, and is a **prerequisite** for `/sw-doc` adoption (parent phase 6) —
not optional hygiene.

## Context

**GAP-039 surfaces today:**

- `scripts/wave_preflight.py` `cmd_dispatch` writes one JSON file per repo root; each write overwrites the
  prior record; `consumedAt` on first hook pass invalidates all other spawns in the same turn.
- `core/hooks/before_task_dispatch.py` `validate_dispatch_preflight` matches a single `agent` id and consumes
  the lone record.
- `/sw-doc` binding contract: unique `--dispatch-id` per persona Task, but the storage model is still
  single-record.

**GAP-040 surfaces today:**

- `scripts/dispatch-check.py` lines 67–68: `MODEL_ARGS=(--agent "$AGENT")` — `--command` affects intensity
  only, not model tier.
- `scripts/wave_preflight.py` line 276: `model_cmd = [..., "--agent", agent]` — same gap.
- `core/rules/sw-subagent-dispatch.mdc` KD8: orchestrators with `inherit` routing **must** resolve delegated
  atomics via `--command <child-slug>` and never downgrade the child — procedural today, not mechanical.
- PRD 012 R1–R5 shipped binding for reviewer agents; the command-vs-agent split is residual (partially
  resolved GAP-009).

**Why PRD 024 (not a standalone PRD or PRD 012 reopen):**

- TR4b explicitly owns parallel persona dispatch in the `/sw-doc` adoption slice.
- Without R38/R39, phase 6 cannot satisfy parent SC3 halt fixtures on the canonical doc-review path nor the
  `/sw-doc` delegated-atomic contract in `core/commands/sw-doc.md`.
- Debug/feedback adoption (phases 5/7) benefits from the same binding floor but does not drive the urgency;
  `/sw-doc` does.

## Goals

1. N doc-review persona Tasks spawned in one turn each pass fail-closed binding — no shared consume slot.
2. Delegated doc-chain atomics (`sw-brainstorm`, `sw-prd`, `sw-tasks`, `sw-doc-review` personas) resolve
   model tier from `--command` when the dispatch carries it, matching KD8 and `sw-doc.md` prose.
3. Intentional per-agent tier overrides via `models.routing.agents` remain possible when explicitly authored.
4. Fixture-backed regression gates wire into the 024 fan-out suite (and existing dispatch foundation
   suites).

## Non-Goals

- Re-tiering semantic assignments in `models.tiers` or changing which personas exist (PRD 012 non-goal).
- `models.platforms.*` dual-map or interactive `/sw-setup` model picker (GAP-014 residual).
- Platform guarantee that pre-tool hooks mutate Task `model:` (PRD 012 DL — preflight remains the floor).
- Sequential-only doc-review panel as the "fix" — parallel panel is the contract (GAP-039 option 2 rejected).
- Deliver-loop, phase-mode `/sw-ship`, or terminal retrospective fixes (GAP-041/042 — out of parent scope).
- Editing `docs/prds/GAP-BACKLOG.md` (parent Documentation deliverables exclusion).

## Requirements

Continue the program namespace (parent R18–R23 + A1 R35–R37; this amendment adds R38–R39).

- **R38** (closes GAP-039) Dispatch preflight MUST support **N independent, concurrently valid records** so a
  parallel doc-review persona panel (parent TR4b; `skills/doc-review` R28/R31) can each pass fail-closed
  binding without a shared single-consume slot.
  - **R38a** Records are keyed by `dispatchId` and carry `agent`, `command`, `skill`, `modelId`, `modelTier`,
    `intensity`, `nonce`, `createdAt`, `expiresAt`, `consumedAt`. A new preflight for dispatch-id `B` MUST NOT
    overwrite or invalidate an unconsumed record for dispatch-id `A`.
  - **R38b** Storage MUST be a **keyed directory** (e.g.
    `.cursor/hooks/state/task-dispatch-preflight/<dispatch-id>.json`) or an equivalent map structure with
    per-key consume semantics. The legacy single-file path MAY be supported as a read fallback for one record
    only during migration; new writes use the keyed form.
  - **R38c** `core/hooks/before_task_dispatch.py` MUST validate and consume **only** the record matching the
    Task's `dispatchId` (from `tool_input.metadata.dispatchId` when present, else the sole matching
    `agent`+unconsumed record if exactly one exists — fail-closed on ambiguity). Consuming record `A` MUST
    leave record `B` valid.
  - **R38d** `bash scripts/wave.sh dispatch preflight --dispatch-id <id> ...` remains the operator/agent
    entrypoint; each parallel persona spawn uses a **unique** `--dispatch-id`. `/sw-doc` and
    `skills/doc-review/SKILL.md` parallel panel procedure MUST document the per-persona id requirement (no
    prose-only sequential fallback).
  - **R38e** TTL and `consumedAt` are **per record**. Expired or consumed records fail closed with the
    existing cause enums (`stale-preflight-nonce`, `preflight-agent-mismatch`, `missing-preflight-nonce`).
- **R39** (closes GAP-040) When a dispatch carries `--command <sw-slug>`, model-tier resolution MUST treat the
  command routing as authoritative so orchestrator-delegated atomics are not silently down-tiered by
  agent-default fallback (KD8; `core/rules/sw-subagent-dispatch.mdc`).
  - **R39a** When `bash scripts/wave.sh dispatch preflight` or `scripts/dispatch-check.py` is invoked with
    `--command <sw-slug>`, model tier resolution MUST use `resolve-model-tier.py --command <sw-slug>` as the
    **primary** lookup. `--agent` alone MUST NOT down-tier a command-backed delegation.
  - **R39b** **Precedence** (single-sourced, fixture-backed):
    1. If `models.routing.agents[<agent>]` is an **explicit** entry (not merely the `roles.reviewer` default
       fallback) **and** the dispatch is a reviewer/persona/native-panel bound agent (`sw-*-reviewer`, native
       panel ids), use `--agent` resolution — intentional per-persona tier.
    2. Else if `--command` is present, use `--command` resolution (KD8 — orchestrator-delegated atomics).
    3. Else use `--agent` resolution.
  - **R39c** `scripts/resolve-model-tier.py` MAY gain a combined `--command` + `--agent` mode implementing
    R39b; callers (`wave_preflight.py`, `dispatch-check.py`) MUST NOT duplicate precedence logic in ad-hoc
    form.
  - **R39d** The preflight record's `modelId` / `modelTier` MUST reflect the R39b-resolved tier. The hook's
    `binding:model-mismatch` check (preflight vs live resolution) MUST use the same precedence.
  - **R39e** `core/rules/sw-subagent-dispatch.mdc` KD8 cross-reference: mechanical enforcement of
    command-inheritance is owned by this amendment's resolver + preflight path (not prose-only).

**Orchestrator scope note:** R38/R39 are **shared infrastructure** consumed by `/sw-doc` (required) and available
to `/sw-debug` / `/sw-feedback` if they delegate bound Tasks; they do not change parent R37 episodic durability.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `dispatch-preflight-parallel-n-personas` | N distinct `dispatch preflight` records → N parallel bound Task validations pass; consuming one does not invalidate others | R38, R38a–R38e |
| `dispatch-preflight-ambiguous-agent-fail-closed` | two unconsumed records for the same `agent` without `dispatchId` on Task → fail-closed (no silent pick) | R38c |
| `dispatch-command-tier-inherits-routing` | `dispatch-check --command sw-prd --agent <any>` resolves `deep` (or configured command tier), not `roles.reviewer` default | R39, R39a, R39b |
| `dispatch-command-tier-sw-tasks` | same for `sw-tasks` command slug | R39a |
| `dispatch-agent-explicit-override-wins` | `routing.agents[sw-coherence-reviewer]` explicit entry overrides command tier when policy intends per-persona tier | R39b |
| `dispatch-preflight-command-model-parity` | `wave.sh dispatch preflight --command sw-prd ...` stamps `modelId` matching `--command sw-prd` resolution | R39c, R39d |
| `doc-review-parallel-panel-binding` | end-to-end: `/sw-doc-review` selection → N preflights → N persona Task spawns pass binding (integration row in fan-out or dispatch foundation suite) | R38 + R39 |

Extend `scripts/test/run-dispatch-foundation-fixtures.sh` and `scripts/test/run-fanout-fixtures.sh` (or
`run-model-binding-fixtures.sh` where appropriate). Emitter/dist propagation folds into **parent TR9** on task
regeneration.

## Implementation note (task integration)

R38–R39 join the PRD 024 spec union (R18–R23 + A1 R35–R37 + **A2 R38–R39**). The frozen task list
`tasks-024-orchestrator-plan-policy-adoption.md` MUST be regenerated before implementation.

**Suggested task placement** (insert before current phase 6 — `/sw-doc` adoption):

| New task | Files | R-IDs |
|----------|-------|-------|
| **6.0a** Keyed parallel preflight store + hook consume-by-dispatch-id | `scripts/wave_preflight.py`, `core/hooks/before_task_dispatch.py`, `.sw/layout.md` | R38 |
| **6.0b** Command-authoritative tier in preflight + dispatch-check + resolver precedence | `scripts/dispatch-check.py`, `scripts/resolve-model-tier.py`, `core/rules/sw-subagent-dispatch.mdc` | R39 |
| **6.0c** Parallel panel + command-tier fixtures | `scripts/test/run-dispatch-foundation-fixtures.sh`, `scripts/test/run-fanout-fixtures.sh` | R38, R39 |
| **6.2** (existing) Update — doc-review halt fixtures assume parallel preflight + command tier are green | `core/commands/sw-doc.md`, `core/skills/doc-review/SKILL.md` | R19, R38, R39 |

Phases 5 (`/sw-debug`) and 7 (`/sw-feedback`) may proceed in parallel with 6.0a–c scaffolding but phase 6
(`/sw-doc`) MUST NOT start until 6.0c is green.

No new feature branch — same `feat/orchestrator-plan-policy-adoption`.

## Documentation deliverables (amendment delta)

Fold into **parent TR9** + phase 8 on task regeneration (PRD-009 living-doc indexes remain out of scope).

- `core/commands/sw-doc.md` — Delegated Task binding: each parallel persona requires a **unique**
  `--dispatch-id`; model tier resolved via `--command <child-slug>` per R39.
- `core/skills/doc-review/SKILL.md` — Step 7 parallel panel: N preflights (unique ids) before N Task spawns;
  reference R38.
- `core/rules/sw-subagent-dispatch.mdc` — KD8 mechanical enforcement pointer to R39b precedence (not
  prose-only).
- `.sw/layout.md` + `core/sw-reference/layout.md` — keyed preflight directory path + per-record TTL/consume
  semantics.
- `CONTRIBUTING.md` — add the seven amendment fixtures to the dispatch/fan-out suite tables with R-ID mapping.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Amend PRD 024 (A2), not reopen PRD 012 | 012 shipped reviewer binding; gaps are residual command-vs-agent + parallel preflight — surfaced on `/sw-doc` adoption (TR4b). Co-locate with the orchestrator that requires the fix. |
| DL-2 | Keyed preflight by `dispatchId`, not sequential-only panel | GAP-039 option 2 (document sequential panel) contradicts doc-review R28/R31 and increases latency; parallel panel is the contract. |
| DL-3 | Command-primary with explicit agent override (R39b) | Preserves intentional `routing.agents` per-persona tiers while fixing KD8 down-tier for `sw-prd`/`sw-tasks`/etc. |
| DL-4 | Prerequisite gate before phase 6 | `/sw-doc` consistency-only (R36c) still runs doc-review on the canonical path; binding defects are not gated on `proposed` surface. |
| DL-5 | Additive only — no parent supersede | R38/R39 extend TR4b wiring; they do not change R35–R37, program gate, or episodic debug/feedback model. |

## Open Questions

None.

## Gap resolution (on ship)

When this amendment ships, update GAP-BACKLOG:

| ID | Expected status |
|----|-----------------|
| GAP-039 | `resolved` — absorbed by PRD 024 A2 R38 |
| GAP-040 | `resolved` — absorbed by PRD 024 A2 R39 |
| GAP-009 | `resolved` (if no other residual) — or remain `partially resolved` with note that hook injection (PRD 012 R5) is still best-effort |
