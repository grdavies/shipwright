---
date: 2026-06-25
topic: autonomous-orchestration-conductor
prd: docs/prds/009-autonomous-orchestration-conductor/009-prd-autonomous-orchestration-conductor.md
frozen: false
status: audit-complete
---

# Orchestrator adoption audit (R33, R35)

Per-orchestrator audit of `/sw-doc`, `/sw-ship`, `/sw-debug`, and `/sw-feedback` for **unnecessary
turn-yields** and **missed parallelism**, plus sequenced adoption requirements that reference the shared
conductor contract (`core/skills/conductor/SKILL.md` + `core/rules/sw-conductor.mdc` — authored in PRD 009
Phase 3). This artifact does **not** duplicate the contract; it records gaps and adoption deltas only.

**Pilot:** `/sw-deliver` (Phase 3–7 implement the contract against this audit).

**Recommended convergence order (DL-10):** `/sw-ship` → `/sw-debug` → `/sw-doc` → `/sw-feedback`.

## Method

1. Read each orchestrator command (`core/commands/sw-*.md`) and delegated skills.
2. Classify halt surfaces: **legitimate** (human merge gate, destructive/ambiguous action, exhausted budget)
   vs **routine** (orchestrator ends the turn while the next atomic step is runnable without new human input).
3. Classify parallelism: independent I/O-bound or sub-agent work currently serialized.
4. Map each gap to a sequenced adoption requirement referencing the shared contract clause it will invoke
   (not re-specify).

## Shared contract (reference only)

Adoption work in later phases MUST cite these contract surfaces (to be authored in Phase 3):

| Clause | Behavior |
| --- | --- |
| **In-turn self-continuation** | After `awaitAgent: true`, conductor performs agent work and re-invokes the driver in the same turn until a legitimate halt (R2, R6, R7). |
| **Legitimate-halt set** | Halts only on main-merge gate, exhausted remediation, ambiguous/destructive action, configured checkpoint, phase-liveness timeout, external-wait exhaustion (R10). |
| **Parallel dispatch** | Independent sub-agent work dispatched concurrently within worktree/ceiling limits (R14–R15). |
| **Durable resumption** | Fresh agent resumes from `.cursor/sw-deliver-state.json` + plan + run log (R4). |
| **Self-wake / bounded wait** | Terminal CI and external waits arm teardown-safe watchers; exhausted wait → consolidated halt + re-derive (R8, R9, R40). |
| **Loop hard-stop** | Max-iteration + no-progress circuit breaker on identical `nextAction` + unchanged state signature (R38). |

---

## `/sw-doc` audit

**Chain:** triage → [brainstorm] → prd → doc-review → spec-rigor → freeze → tasks → spec-rigor + traceability → freeze → `doc.afterTasks` boundary.

### Turn-yields (unnecessary or routine)

| ID | Location | Yield | Legitimate? | Adoption note |
| --- | --- | --- | --- | --- |
| DOC-Y1 | `doc.afterTasks: confirm` | Halts for explicit `proceed`/`yes` before `spec-seed` + `deliver-loop` | **Configured checkpoint** — legitimate when mode is `confirm`; routine when operator intended `auto` | Contract: respect `doc.afterTasks`; conductor may only auto-dispatch when mode is `auto` or agent override is recorded (R8). |
| DOC-Y2 | `/sw-doc-review` synthesis | Halts on `gated_auto` / `manual` trade-offs for user decision | **Legitimate** for doc quality | Not a conductor target — panel outcomes stay human-gated. |
| DOC-Y3 | spec-rigor / traceability `fail` | Halts on gate failure | **Legitimate** | Conductor should surface consolidated report, not re-prompt per gate. |
| DOC-Y4 | Quick tier handoff | Stops after triage with implementation handoff | **Legitimate** routing | N/A — Quick bypasses doc orchestrator. |
| DOC-Y5 | End of `stop` mode | Print-only halt (no dispatch) | **Legitimate** by design | Conductor must not override `stop`. |

No **routine** yield found where the next doc atomic is runnable without new human input, except when
`doc.afterTasks` is misconfigured (`confirm` vs `auto`).

### Missed parallelism

| ID | Location | Today | Opportunity | Adoption note |
| --- | --- | --- | --- | --- |
| DOC-P1 | `/sw-doc-review` personas | Parallel sub-agents (step 9) | **Already parallel** | Preserve; conductor must not serialize persona dispatch when adopting similar patterns elsewhere. |
| DOC-P2 | spec-rigor + traceability | Sequential after tasks draft | Low value — traceability consumes PRD + tasks union | Defer; not worth parallelizing. |
| DOC-P3 | Memory preflight + file load | Typically sequential at stage entry | Preflight search parallel with loading large PRD draft | Minor; optional in supervised mode only. |

---

## `/sw-ship` audit

**Chain:** sw-tmp init → execute → verify → verification-gate → review → simplify → gap-check → commit → pr → watch-ci → stabilize → ready.

### Turn-yields (unnecessary or routine)

| ID | Location | Yield | Legitimate? | Adoption note |
| --- | --- | --- | --- | --- |
| SHIP-Y1 | Default merge gate pause | "ready to merge — your call" at `sw-ready` | **Legitimate** for interactive runs; **routine** under deliver dispatch | Phase-mode already suppresses (R48). Adoption: all orchestrator-dispatched ships use `--phase-mode`. |
| SHIP-Y2 | `sw-commit` inconclusive verify | Decision prompt when verify is `no-baseline` / `unattributed` | **Routine** in autonomous phase dispatch | Contract: phase-mode logs and continues per verification-gate policy; conductor must not end turn waiting for commit ack. |
| SHIP-Y3 | Local review `haltOn` P0/P1 | Stops chain for validated severities | **Legitimate** safety | Phase-mode writes `blocked` without prompt (R48). |
| SHIP-Y4 | `sw-stabilize` interactive loop | Human-in-loop for review/CI fixes | **Routine** when stabilize needs scope decisions | Adoption: conductor re-enters stabilize in-turn until green or remediation budget exhausted (R11). |
| SHIP-Y5 | CI `yellow` polling | Turn ends while waiting for CI | **Routine** without self-wake | Adoption: self-wake sentinel + in-turn poll fallback (R8, R9, R46) — same contract as deliver terminal PR. |
| SHIP-Y6 | `--signal-id` feedback close | Optional human confirm after green | **Legitimate** optional checkpoint | Keep optional; not on critical path. |
| SHIP-Y7 | Branch/scope/config ambiguity | Interactive halt | **Legitimate** | Contract: write `blocked` + consolidated report. |

### Missed parallelism

| ID | Location | Today | Opportunity | Adoption note |
| --- | --- | --- | --- | --- |
| SHIP-P1 | Native review panel agents | Sub-agent dispatch gated by `sw-subagent-dispatch.mdc` | Independent reviewers can run parallel when heuristics fire | Align with contract parallel-dispatch clause; respect ceiling. |
| SHIP-P2 | `watch-ci` + memory write | Sequential after PR | Low priority | Defer. |
| SHIP-P3 | gap-check + simplify | Sequential after review | Dependency — simplify must follow review | N/A. |

---

## `/sw-debug` audit

**Chain:** triage → normalize/redact → [Sentry enrich] → memory preflight → RCA → route handoff (stops).

### Turn-yields (unnecessary or routine)

| ID | Location | Yield | Legitimate? | Adoption note |
| --- | --- | --- | --- | --- |
| DBG-Y1 | End of procedure | Always returns handoff summary; does not auto-dispatch route | **Routine** for small-fix path | Adoption: after human confirms route once, conductor provisions worktree + `/sw-start` in-turn (R24 handoff automation). |
| DBG-Y2 | RCA human-decision hard stop | Stops on ambiguous root cause | **Legitimate** | Remains in legitimate-halt set. |
| DBG-Y3 | RCA max iterations / no-progress | Hard stop | **Legitimate** | Map to consolidated report + `blocked`. |
| DBG-Y4 | Sentry MCP unavailable | Degrades and continues | **Good** — no yield | Preserve. |

### Missed parallelism

| ID | Location | Today | Opportunity | Adoption note |
| --- | --- | --- | --- | --- |
| DBG-P1 | Sentry enrich + memory search | Sequential (steps 3–4) | Parallel after normalize — independent I/O | Adoption req DBG-A2. |
| DBG-P2 | Normalize + triage | Sequential | Triage needs normalized input | N/A. |

---

## `/sw-feedback` audit

**Chain:** normalize → redact → dedup → route → gap split → record → handoff summary (**stop**).

### Turn-yields (unnecessary or routine)

| ID | Location | Yield | Legitimate? | Adoption note |
| --- | --- | --- | --- | --- |
| FB-Y1 | Step 7 explicit stop | "do not chain until user confirms handoff" | **Routine** for every signal | Adoption: single confirmation per signal, then conductor dispatches chosen route in-turn (debug / amend / brainstorm). |
| FB-Y2 | Hook/monitor triggers | Require human confirmation | **Legitimate** safety | Keep; contract must not auto-dispatch untrusted triggers. |
| FB-Y3 | Dedup drop | Silent drop when handled in-loop | **Good** — no yield | Preserve. |

### Missed parallelism

| ID | Location | Today | Opportunity | Adoption note |
| --- | --- | --- | --- | --- |
| FB-P1 | Sentry expand + redact | Sequential for bare refs | Expand then redact — dependency | N/A. |
| FB-P2 | Route + record | Sequential | Record depends on route | N/A. |

---

## Sequenced adoption requirements (R35)

Each requirement references the **shared conductor contract** (Phase 3). Implementation is **after** the
`/sw-deliver` pilot (R34). Order follows DL-10.

### Wave 1 — `/sw-ship` (highest frequency)

| ID | Requirement | Contract clause | Depends on |
| --- | --- | --- | --- |
| SHIP-A1 | Orchestrator-dispatched `/sw-ship` invocations always pass `--phase-mode` / `SW_PHASE_MODE` and write durable `status.json` without interactive merge pause. | Legitimate-halt set; in-turn continuation | Pilot complete (R34) |
| SHIP-A2 | When `sw-stabilize` is routed, conductor re-enters the stabilize loop in-turn until live green or remediation budget exhausted — no routine turn-yield at stabilize entry. | In-turn self-continuation; legitimate-halt set | SHIP-A1 |
| SHIP-A3 | CI watch segment uses self-wake sentinel (or bounded in-turn poll fallback) instead of ending the turn while checks are `yellow`. | Self-wake / bounded wait | SHIP-A1, pilot self-wake (R8) |
| SHIP-A4 | Parallelize independent native review sub-agents when `sw-subagent-dispatch` heuristics allow; respect `worktree.parallelCeiling`. | Parallel dispatch | SHIP-A1 |

### Wave 2 — `/sw-debug`

| ID | Requirement | Contract clause | Depends on |
| --- | --- | --- | --- |
| DBG-A1 | After one human route confirmation, conductor provisions worktree + dispatches `/sw-start` without a second turn-yield. | In-turn self-continuation | Pilot complete |
| DBG-A2 | Run Sentry enrich and memory preflight search concurrently after normalize when both are applicable. | Parallel dispatch | DBG-A1 |

### Wave 3 — `/sw-doc`

| ID | Requirement | Contract clause | Depends on |
| --- | --- | --- | --- |
| DOC-A1 | `doc.afterTasks: auto` path runs `spec-seed` + `deliver-loop` in-turn with recorded agent override when applicable — no second prompt. | In-turn self-continuation; legitimate-halt set | Pilot complete |
| DOC-A2 | On spec-rigor/traceability failure, emit consolidated halt report — do not yield for per-gate re-prompts. | Legitimate-halt set; consolidated report (R12) | DOC-A1 |

### Wave 4 — `/sw-feedback`

| ID | Requirement | Contract clause | Depends on |
| --- | --- | --- | --- |
| FB-A1 | After single handoff confirmation, dispatch routed command (`/sw-debug`, `/sw-amend`, `/sw-brainstorm`) in-turn. | In-turn self-continuation | DBG-A1, DOC-A1 (shared handoff pattern) |
| FB-A2 | Preserve fail-closed behavior for hook/monitor triggers — contract documents these as legitimate halts. | Legitimate-halt set | FB-A1 |

### Explicit non-goals (this PRD)

- Rewriting doc-review panel human gates (`gated_auto` / `manual`).
- Auto-merging to `main` from any orchestrator.
- Duplicating conductor contract prose in each command file (surface docs refresh is Phase 10 / A2).

---

## Traceability

| R-ID | Task | Satisfied by |
| --- | --- | --- |
| R33 | 2.1 | Per-orchestrator turn-yield + parallelism sections above |
| R35 | 2.2 | Sequenced adoption requirements table (references shared contract) |
