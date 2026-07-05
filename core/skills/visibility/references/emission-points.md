# Visibility emission points (PRD 034 + 035)

Single registry for `planning_visibility.py` `EMISSION_POINTS`. Every consumer routes
private/memory bodies through the resolver before emit.

| Point | Description |
| --- | --- |
| `index-active` | Unified INDEX active rows |
| `index-archive` | Unified INDEX archived rows |
| `legacy-gap-backlog` | 033/045 legacy GAP-BACKLOG projection (issue-derived write-through under issue-store) |
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
| `pull-in-confirm` | **035 pull-in confirm lists** — ranked absorption/amendment proposals from `scripts/planning-related.py`; metadata-only for private units; never auto-absorb |
| `deliver-annotation` | **045 R68** — `/sw-deliver` and `/sw-ship` issue annotation comments (`sw:deliver-annotate` marker); opaque PR refs for private/memory units via PRD 043 R28 resolver |
| `deliver-annotation-ingest` | **045 R68** — host-sourced annotation fields (branch, PR title, author, URL) scanned as PRD 043 R45 ingest before write; redacted/refused on secret hit |
| `issue-derived-ingest` | **046 R82/R84** — issue-search/get canonical form secret-scanned then redacted before INDEX row or query-cache write |
| `issue-close-batch` | **045 R67** — allowlisted close-on-merge and separate-repo `issue-close` API batch |
