---
description: Destination-first structured exploration before planning — idea, notebook, resume, promote, and explicit doc handoff. Does not create PRDs/tasks, dispatch implementation, or resolve Quick/Standard/Full tier at entry.
alwaysApply: false
---

# `/sw-explore`

First-class pre-planning exploration surface (PRD 331). Captures destination, structured fields, and
optional graph promotion through conversation — then hands off to `/sw-doc` when readiness is sufficient.
Explore is **optional** (not mandatory) for every workflow.

## Scope

- **Input:** rough idea, notebook graduation, resumed exploration map, or operator continuation.
- **Output:** `ExplorationMap@v1` session state, optional graph nodes after promotion, and explicit forward
  handoff proposals — never PRDs, tasks, branches, or implementation dispatch.
- **Does not:** create PRDs or tasks (no mega-planning — does not create PRDs, does not create tasks),
  invoke `/sw-deliver` / `/sw-ship` / `/sw-execute`
  (no implementation dispatch), act with autonomous product authority, require explore for every change,
  or treat prototypes as production-eligible without restriction.

## Entry paths

| Path | Invocation | Behavior |
| --- | --- | --- |
| **idea** | `/sw-explore idea <text>` or `/sw-explore <text>` | Start a new map with destination-first capture via `scripts/exploration_engine.py`. |
| **notebook** | `/sw-explore --from-notebook <id>` | Resume from `/sw-note graduate <id> --to explore` provenance (`notebookId` on map provenance). |
| **resume** | `/sw-explore resume <map-id>` | Load persisted map from `scripts/exploration_store.py`; fail closed on stale revision. |
| **promote** | `/sw-explore promote <map-id> --trigger <name>` | Conversation → graph promotion via `scripts/exploration_policy.py` (operator confirmation required). |
| **handoff** | `/sw-explore handoff <map-id> --to doc` | Propose explicit forward route to `/sw-doc` after readiness/brief validation (human confirm). |

**No tier at entry (R7):** Quick / Standard / Full classification is absent at explore entry. Never call
`resolve_entry_tier` or route through `/sw-triage` tier selection from this command.

## Procedure

1. Load `core/skills/explore/SKILL.md` and follow the **ask → decide → confirm** interaction state machine.
2. **Pre-work memory (optional, degradable)** — when historical context is requested, route through
   `memory-preflight` and credential brokers via `scripts/exploration_security.py`; never read ambient tokens.
3. **Destination first** — capture `destination.statement` before graph expansion (`exploration_engine.py`).
4. **Structured fields** — collect required fields (`problem`, `outcomes`, `successCriteria`) and optional
   fields without forcing premature planning writes.
5. **Evidence (when present)** — bind `ResearchEvidence` / `PrototypeEvidence` through
   `scripts/exploration_evidence.py`; prototypes remain **non-production-eligible**.
6. **Promotion (optional)** — graph expansion only after an allowed promotion trigger and operator confirm.
7. **Handoff (explicit)** — forward to `/sw-doc` only after readiness/brief checks and human confirmation;
   never nested orchestrator dispatch.

See `docs/guides/workflows.md` (**Lifecycle routing**) for Capture → Explore → Specify → Build → Learn
entry paths and bidirectional notebook provenance.

**Communication intensity:** lite

**Model tier:** mid — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-explore`.

## Authority boundaries

- **Human owns intent** — blocking unknown classification, promote triggers, and doc handoff require explicit
  human confirmation; agents propose, humans decide.
- **No implementation dispatch** — refuse `/sw-deliver`, `/sw-ship`, `/sw-execute`, `/sw-start`, and
  `/sw-worktree` from within explore; route to doc handoff instead.
- **No planning writes** — explore does not create PRDs, tasks, branches, or issue-store planning units.
- **No `/sw-graph-*` commands** — WorkflowGraph execution surfaces are out of scope; use existing `sw-*`
  workflow commands only.

## Closed anti-goals (R34, R48)

Explore MUST refuse and document all five anti-goals inline:

1. **Mega-planning** — does not create PRDs, tasks, or planning-store artifacts during exploration.
2. **Implementation dispatch** — does not invoke deliver/ship/execute/start/worktree from explore.
3. **Autonomous product authority** — does not commit product decisions without human confirm receipts.
4. **Mandatory explore** — explore is optional; operators may skip directly to `/sw-doc` or implementation
   when appropriate.
5. **Unrestricted prototypes** — prototype evidence is explicitly non-production-eligible; never silently
   promote prototype output to production scope.

## First-release capabilities (R3)

This command binds to shipped core surfaces — not a shell-only stub:

- `scripts/exploration_store.py` — `ExplorationMap@v1` lifecycle and optimistic revision
- `scripts/exploration_engine.py` — destination-first structured field collection
- `scripts/exploration_policy.py` — conversation default and promotion triggers
- `scripts/exploration_evidence.py` — evidence reuse without parallel silos
- `scripts/exploration_security.py` — brokered `memory-preflight` access and redaction

## Guardrails

- Conversation remains the default interaction mode until graph promotion (R6).
- Persistence occurs only on defined triggers (blocking unknowns, resume, promote receipt) — not every turn.
- Canonical maps, status, and projections are secret-free; redact before persist.
- Cancellation is always available; resume recovery instructions must be explicit in skill procedure.
- Preserves Shipwright architectural principles: Python-first workflow logic, broker-only credentials,
  worktree-isolated delivery, and check-gate merge authority.
