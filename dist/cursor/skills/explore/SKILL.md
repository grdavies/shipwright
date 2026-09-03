---
name: explore
description: Destination-first structured exploration through ask → decide → confirm — humans own intent, blocking policy, promote, and doc handoff. Use when scope is unclear before /sw-doc. Does not dispatch implementation or create PRDs/tasks.
---
# Explore (`/sw-explore`)

Pre-planning structured exploration. Produces `ExplorationMap@v1` state and optional readiness/brief
handoff — never PRDs, tasks, or implementation dispatch.


**Model tier:** mid — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill explore`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Core principles

1. **Ask → decide → confirm** — every promote or handoff passes through explicit human confirmation.
2. **Humans own intent** — agents surface trade-offs; humans own intent, blocking unknown policy, and
   forward routing.
3. **Destination first** — capture non-committal destination before graph expansion.
4. **Conversation default** — graph promotion follows only defined triggers in `exploration_policy.py`.
5. **No implementation dispatch** — never invoke `/sw-deliver`, `/sw-ship`, or `/sw-execute` from explore.

## Interaction state machine (R24, R31, R45)

```
ask ──► decide ──► confirm ──► (promote | handoff | persist | continue)
  ▲         │           │
  └─ cancel ┘           └─ cancel (no side effects on declined confirm)
```

| State | Agent behavior | Human gate |
| --- | --- | --- |
| **ask** | One clarifying question at a time; optional intelligence inputs may degrade non-blocking. | Operator may cancel or defer. |
| **decide** | Summarize destination, structured fields, unknowns, and evidence; propose next action. | Operator chooses promote, handoff, or continue conversation. |
| **confirm** | Show declared persistence effects before any write or route. | Explicit `proceed` required for promote/handoff; decline returns to ask/decide without mutation. |

### Blocking policy

- Classify unknowns as blocking / non-blocking / deferred only after human confirmation.
- Never auto-promote blocking policy or product commitments.
- On conflicting intent, halt in **decide** and ask one reconciliation question.

### Cancellation and resume recovery

- **Cancel** — operator may abort at any state; no promote/handoff/persist without confirm receipt.
- **Resume** — `/sw-explore resume <map-id>` reloads map + interaction state; on stale revision, print
  recovery instructions (re-read map, re-confirm destination, retry with current revision).
- **Notebook entry** — when `--from-notebook <id>` is present, verify `notebookId` provenance round trip
  from `/sw-note graduate --to explore`.

Lifecycle placement and Capture → Explore → Specify → Build → Learn routing:
`docs/guides/workflows.md` (**Lifecycle routing**).

## Procedure

### Phase 1: Entry and destination

1. Resolve entry path (`idea`, `notebook`, `resume`).
2. Start or resume via `ExplorationEngine` + `ExplorationStore`.
3. Capture destination statement (non-committal).
4. Refuse tier routing at entry (`entry_tier_routing_forbidden`).

### Phase 2: Structured exploration

1. Collect required structured fields before suggesting `/sw-doc`.
2. Optionally bind evidence via `exploration_evidence.py` (prototypes non-production-eligible).
3. Stay in conversation mode until promotion trigger + confirm.

### Phase 3: Promote or handoff

1. **Promote** — evaluate trigger via `exploration_policy.py`; require operator confirm receipt.
2. **Handoff** — when readiness is sufficient, propose `/sw-doc` with reason + declared effects; require
   confirm; never nested orchestrator dispatch.
3. Report map id, revision, and next command (`/sw-explore resume`, `/sw-doc`, or `/sw-status`).

## Guardrails

- No PRD/task/branch creation (mega-planning anti-goal).
- No implementation dispatch anti-goal — refuse deliver/ship/execute/start routes.
- No autonomous product authority — confirm receipts required.
- Explore is optional — never imply mandatory explore for all work.
- Prototypes remain non-production-eligible (unrestricted prototypes anti-goal).
- Broker-only memory access via `memory-preflight`; redact all persisted artifacts.
