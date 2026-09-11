# Graph-domain terminology

Locked vocabulary for the WorkflowGraph cutover. Three **runtime** domains are distinct from
issue-store / planning hierarchy.

**Sole production runtime:** after cutover, **`WorkflowGraph`** is the only production execution
engine. Legacy serial adapters remain compile/migration aids — not a second live runtime.
Operator surfaces stay `/sw-deliver` and `/sw-status` (no graph-prefixed slash commands).

## Domains

| Domain | Definition | Authority |
| --- | --- | --- |
| **Planning graph** | Durable dependency graph of planning units (product docs, tasks, gaps) used for scheduling eligibility and absorb edges. | Planning store / planning-graph — **not** the execution runtime. |
| **Execution graph** | Runnable `WorkflowGraph` of nodes + edges that the scheduler dispatches under resource pools, fan-in, and isolation policy. | Runtime IR under `scripts/graph/` — **sole production runtime after cutover** |
| **Artifact / provenance graph** | Hash-addressed artifacts and per-node receipts linking inputs → outputs → verification evidence. | Artifact registry + execution receipts (`.cursor/sw-graph-runs/<runId>/`) |

## Explicit non-domains

| Concept | Why it is not a runtime domain |
| --- | --- |
| **Issue-store hierarchy** | Epic / phase / checkbox projection in the issues provider. Topology for humans and planning status — never treated as an execution DAG. |
| **Deliver wave plan** | Phase-mode wave batching (`sw-deliver-plan.json`) is a *compile target* into a WorkflowGraph, not a fourth graph domain. |
| **Legacy serial adapter** | Compatibility compile path during cutover; not a parallel production scheduler once `full-ownership` is active. |

## Locked terms

| Term | Meaning |
| --- | --- |
| `WorkflowGraph` | Versioned execution-graph document (`apiVersion`-stamped); sole production runtime after cutover. |
| `NodeSpec` | Single executable node: kind, inputs, outputs, isolation, resource pool, verification. |
| `resource pool` | Named concurrency budget (code-writers, read-only-reviewers, web-research, provider-api). |
| `fan-in policy` | How parallel predecessors settle into a join (mode, quorum, required nodes, insufficient coverage). |
| `isolation policy` | Per-node write/read isolation: `none` \| `process` \| `worktree` \| `container` \| `remote`. |
| `degraded verdict` | Visible non-success coverage outcome; **halt-by-default** unless an explicit override is recorded. |
| `runId` | Generic graph run identity (mapped from deliver/orchestrator `runId`); indexes receipts, intents, status/explain. |
| `explain-plan` | Read-only `/sw-deliver` plan summary (node count, concurrency, critical path). |
| `graph-progress` / `explain` | `/sw-status` live progress and per-node blocker hierarchy. |
| `cutover stage` | Dogfood-gated ownership: `dogfood` → `limited-scope` → `full-ownership`. |
| `maxConcurrency: 1` | Serial-equivalent mitigation lane on the graph scheduler (not a second runtime). |
| `ExecutionBackend` | Submit/poll/cancel/result boundary for node work (`scripts/graph/execution_backend.py`). Host adjudicates identity, purity, and timing; backend terminal envelopes are advisory only. |
| `GraphScheduler` | Single owning loop for WorkflowGraph admission and state transitions — distinct from orchestrator conductor fan-out. |
| **fragment pin** | Typed `use:` reference `<name>@<version>` to a versioned `WorkflowFragment` in `.sw/workflows/fragments/`; expansion records each pin's digest and fails closed on cycles or ceiling violations. |
| **shadow score** | Kernel-derived comparison of candidate vs canonical graphs: predicted latency, cost, parallelism, node count, resource demand, and verification coverage (aggregate and per verifier class). Proposal-supplied metric fields are ignored; shadow never mutates dispatch. |
| **`dry-clean`** | Convergence verdict when a discovery round exited successfully, produced non-empty evidence, and was not truncated or rate-limited. May converge only after round-health attestation passes. Reason code: `graph.convergence.dry-clean`. |
| **`dry-error`** | Convergence halt when discovery errored, was truncated, rate-limited, or otherwise failed round-health attestation — not a success path. Reason codes include `graph.convergence.dry-error`, `graph.convergence.discovery-error`, `graph.convergence.truncated`, and `graph.convergence.rate-limited`. |
| **`max_rounds`** | Hard ceiling on convergence loop iterations; exceeding it preserves partial fingerprints and emits `graph.convergence.max-rounds-exceeded`. Discretionary early stops (marginal-value, duplicate-rate, token-budget) require at least two healthy productive rounds first. |

## Distinguisher

- Planning graph answers: *what may be scheduled next as a planning unit?*
- Execution graph answers: *what nodes run, in what order, under which pools/isolation?*
- Artifact/provenance graph answers: *what was produced, from what, and was it verified?*
- Issue-store hierarchy answers: *how is work projected for humans in the issues UI?* — never silently
  substituted for any of the three runtime domains above.

## Production runtime and operator surfaces (post-cutover)

After cutover, **`WorkflowGraph` is the sole production execution runtime** for orchestrated work
(`/sw-deliver`, `/sw-doc`, `/sw-debug`, `/sw-feedback`). Legacy deliver wave plans and phase step
plans are compile targets into WorkflowGraph — not a parallel runtime.

| Surface | Command | Role |
| --- | --- | --- |
| Plan explain (read-only) | `wave_deliver.py explain-plan` / `--explain-plan` | Pre-run DAG summary — no mutation |
| Live progress | `status_integrity.py graph-progress --run-id <runId>` | Receipt-backed node states |
| Per-node explain | `status_integrity.py explain <nodeId> --run-id <runId>` | Blocker hierarchy + `nextAction` |
| Planning unit status | `planning-graph.py status --unit-id <id>` | Planning graph only — not execution |

There are **no** `/sw-graph-*` slash commands. `/sw-status` surfaces live execution progress when a
graph run is active.

**Generic `runId`:** graph `metadata.runId` matches the deliver (or orchestrator) `runId`. Receipt
journal, in-flight intents, pool snapshots, and status/explain queries all index under
`.cursor/sw-graph-runs/<runId>/` — see `.shipwright/layout.md` **Graph execution store**.

**Cutover:** `dogfood` → `limited-scope` (requires live status/explain) → `full-ownership` (named
authorizer). The human merge gate is never removed.

## Conductor vs GraphScheduler

Orchestrator conductors fan out **phases** and **execute-tier Tasks** — they do not own WorkflowGraph node admission. `GraphScheduler` runs the **single owning loop** for execution-graph state; completions marshal as events on that loop. Parallel phase dispatch and graph concurrency are complementary layers, not duplicate schedulers. Operator surfaces remain `/sw-deliver`, `/sw-ship`, and `/sw-status` — no `/sw-graph-*` commands.
