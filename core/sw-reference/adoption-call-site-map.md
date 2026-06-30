# Adoption call-site map — orchestrator plan policy (PRD 024 TR8)

Extends [022 call-site map](../../docs/prds/022-kernel-classification-and-plan-validation/call-site-map.md)
with per-orchestrator proposal sites, canonical chain sources, and durable owner paths.

| Orchestrator | Proposal site | Plan tier | Canonical chain source | Guideline pack | Durable owner | signal_context snapshot | Parity fixtures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `/sw-debug` | `sw-debug` procedure at entry | orchestrator (`debug`) | `orchestrator-step-plan.json` → `debug.canonicalChain` | `guidelines/debug.pack.json` (phase 3) | `.cursor/sw-debug-runs/<runId>/episodic-run-summary.json` | `orchestrator_signal_context.py capture` → `.cursor/sw-debug-runs/<runId>/signal_context.json` before `plan validate` | `debug-canonical-parity`, TR7 subset |
| `/sw-doc` | `sw-doc` procedure at entry | orchestrator (`doc`) | `orchestrator-step-plan.json` → `doc.canonicalChain` | `guidelines/doc.pack.json` (phase 3) | docs worktree + frozen PRD set | `orchestrator_signal_context.py capture` → `.cursor/sw-doc-runs/<runId>/signal_context.json` before `plan validate`: tier + doc_path | `doc-canonical-parity`, consistency-only probe |
| `/sw-feedback` | `sw-feedback` procedure at entry | orchestrator (`feedback`) | `orchestrator-step-plan.json` → `feedback.canonicalChain` | `guidelines/feedback.pack.json` (phase 3) | `.cursor/sw-feedback-runs/<runId>/episodic-run-summary.json` | `orchestrator_signal_context.py capture` → `.cursor/sw-feedback-runs/<runId>/signal_context.json` before `plan validate` | `feedback-canonical-parity`, TR7 subset |

## Mechanical primitives

| Primitive | Role |
| --- | --- |
| `python3 scripts/wave.sh plan validate --tier orchestrator --orchestrator-type <debug\|doc\|feedback> …` | Closed-world single-tier orchestrator plan gate |
| `core/sw-reference/orchestrator-step-plan.json` | Authoritative closed-world vocabulary per orchestrator type |
| `scripts/orchestrator_step_plan.py` | Load/lint helpers for orchestrator-step-plan |
| `scripts/kernel-completeness-lint.py` | Kernel classification + orchestrator step coverage |
