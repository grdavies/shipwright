# Graph-domain terminology

Locked vocabulary for the WorkflowGraph cutover. Three **runtime** domains are distinct from
issue-store / planning hierarchy.

## Domains

| Domain | Definition | Authority |
| --- | --- | --- |
| **Planning graph** | Durable dependency graph of planning units (product docs, tasks, gaps) used for scheduling eligibility and absorb edges. | Planning store / planning-graph — **not** the execution runtime. |
| **Execution graph** | Runnable `WorkflowGraph` of nodes + edges that the scheduler dispatches under resource pools, fan-in, and isolation policy. | Runtime IR under `scripts/graph/` |
| **Artifact / provenance graph** | Hash-addressed artifacts and per-node receipts linking inputs → outputs → verification evidence. | Artifact registry + execution receipts |

## Explicit non-domains

| Concept | Why it is not a runtime domain |
| --- | --- |
| **Issue-store hierarchy** | Epic / phase / checkbox projection in the issues provider. Topology for humans and planning status — never treated as an execution DAG. |
| **Deliver wave plan** | Phase-mode wave batching (`sw-deliver-plan.json`) is a *compile target* into a WorkflowGraph, not a fourth graph domain. |

## Locked terms

| Term | Meaning |
| --- | --- |
| `WorkflowGraph` | Versioned execution-graph document (`apiVersion`-stamped). |
| `NodeSpec` | Single executable node: kind, inputs, outputs, isolation, resource pool, verification. |
| `resource pool` | Named concurrency budget (code-writers, read-only-reviewers, web-research, provider-api). |
| `fan-in policy` | How parallel predecessors settle into a join (mode, quorum, required nodes, insufficient coverage). |
| `isolation policy` | Per-node write/read isolation: `none` \| `process` \| `worktree` \| `container` \| `remote`. |
| `degraded verdict` | Visible non-success coverage outcome; **halt-by-default** unless an explicit override is recorded. |

## Distinguisher

- Planning graph answers: *what may be scheduled next as a planning unit?*
- Execution graph answers: *what nodes run, in what order, under which pools/isolation?*
- Artifact/provenance graph answers: *what was produced, from what, and was it verified?*
- Issue-store hierarchy answers: *how is work projected for humans in the issues UI?* — never silently
  substituted for any of the three runtime domains above.
