# Glossary

Shipwright coined terms. For command routing, see the [decision tree](decision-tree.md).

| Term | Meaning |
|------|---------|
| **Unit** | A planning artifact set with a stable id (for example a PRD folder or issue-backed planning unit) that can freeze into a task list. |
| **Gap** | A tracked shortfall against shipped behavior or docs; captured for later planning, not executed as an ad-hoc patch on `main`. |
| **Freeze** | The moment a task list (or related artifact) becomes authoritative for delivery—checkboxes and ledger drive progress. |
| **Deliver** | `/sw-deliver`: dependency-ordered waves that drive each phase through `/sw-ship` to an integration branch and halt at the human merge gate. |
| **Wave** | A parallelizable batch of phases in a deliver plan. Later waves wait on declared dependencies. |
| **Phase** | One work package inside a frozen task list (often one worktree and one PR onto the integration branch). |
| **Conductor** | The in-turn loop that runs mechanical deliver/ship steps and agent steps until a legitimate halt. |
| **Integration branch** | Feature branch that collects green phase merges before the terminal PR to the default branch. |
| **Worktree** | Linked git worktree isolating phase or orchestrator work so bare `main` stays clean. |
| **Ship loop** | The `/sw-ship` chain: execute → verify → review → commit → PR → watch CI → stabilize → ready (merge gate). |
| **Legitimate halt** | An allowed stop (terminal merge gate, exhausted remediation, destructive git, configured checkpoint, timeout, or budget)—not a casual “continue?” prompt. |
| **Persona** | A named consult stance (`/sw-ask` routes questions to one; `/sw-become` crystallizes a new one) grounded in a specific domain—distinct from the doc-review reviewer panel it can reuse. |
| **Notebook** | The local, planning-store-external capture surface behind `/sw-note`—ideas, tasks, and notes that graduate into a gap or brainstorm only after explicit confirm. |
| **Calibration loop** | A convergence primitive that resolves genuine either/or ambiguity (brainstorm divergence, doc-review disposition disputes, feedback scope calls) through concrete instances instead of repeating the same abstract question. |

See also: [getting started](getting-started.md), [workflows](workflows.md), [configuration](configuration.md).
