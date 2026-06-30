# Visibility emission points (PRD 034 + 035)

Single registry for `planning_visibility.py` `EMISSION_POINTS`. Every consumer routes
private/memory bodies through the resolver before emit.

| Point | Description |
| --- | --- |
| `index-active` | Unified INDEX active rows |
| `index-archive` | Unified INDEX archived rows |
| `legacy-gap-backlog` | 033 legacy GAP-BACKLOG projection |
| `legacy-prd-index` | 033 legacy PRD INDEX projection |
| `pr-diff` | PR diff planning-body paths |
| `dispatch-context` | Dispatch / subagent planning context |
| `spec-seed` | wave spec-seed body copy |
| `store-get` | planning.store get / list --json |
| `superseded-manifest` | SUPERSEDED manifest rows |
| `inflight-tuple` | Committed INDEX inFlight tuple (032 R13 handoff) |
| `reconciler-output` | 033 reconciler emitted bodies |
| `run-log` | Deliver run logs |
| `handoff-032` | 032 handoff artifacts |
| `pull-in-confirm` | **035 pull-in confirm lists** — ranked absorption/amendment proposals from `scripts/planning-related.sh`; metadata-only for private units; never auto-absorb |
