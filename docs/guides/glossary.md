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
| **Corpus** | The versioned external-consumer evaluation fixture set (`eval-corpus.schema.json`) spanning greenfield, brownfield, and mixed planning-store repositories; drives release-gate metrics. |
| **Holdout** | Corpus fixtures excluded from release-gate metric partitions; used for regression detection without polluting ship readiness signals. |
| **HandoffBundle transition** | Portable cross-harness state export/import (`HandoffBundle@v1`) capturing source/destination harness, session transition (resume/switch), model transition, and integrity metadata. |
| **Capability matrix** | Versioned planning-store verb contract (`CAPABILITIES.md`); mandatory put/get/exists/materialize/freeze semantics plus normalized error codes. |
| **Explicit degradation** | A declared, allowlisted partial capability (for example `backend-deferred`) — undeclared degradation is a conformance failure. |
| **Priority authority** | `.sw/program-priorities.json` — sole authoritative P0–P3 ranking and release sequence; labels and graph fields are projections only. |
| **Priority projection** | Read-only metadata emitted by `planning_priority_projection.py` from the authority file; never writable as planning truth. |
| **Trust matrix** | Remote-execution prerequisite contract (identity, isolation, least-privilege credentials, integrity, idempotency, cancellation, audit) defined in `core/providers/execution/remote.md`. |
| **Spec/stub status** | P2/P3 providers documented and conformance-tested but **not shipped** — stubs return `not-enabled` and cannot enter shipped registries without green corpus evidence. |

See also: [getting started](getting-started.md), [workflows](workflows.md), [configuration](configuration.md).

## Document-review terms (PRD 341)

| Term | Meaning |
| --- | --- |
| Review round | One `roundId` of persona findings under a body witness + pins |
| Post-then-open | New-round sequence: persona posts → open manifest → verify → complete |
| Five facade ops | `post_review_finding`, `open_review_manifest`, `read_review_manifest`, `verify_review_manifest`, `complete_review_round` |
| Stripped-hash | Canonical/`body-sha256/v1` hash over body with live `sw-doc-review-round` witness excluded |
| Completion receipt | Evidence written by `complete_review_round` after successful verify |
| Cache-only doc-review runs | `.cursor/doc-review-runs/` scratch — non-authoritative |
