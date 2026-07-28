# Visibility emission points (PRD 034 + 035 + 082 R32)

Single registry for `planning_visibility.py` `EMISSION_POINT_REGISTRY`. Every consumer routes
private/memory bodies through the resolver before emit and binds redaction to an explicit
destination tier via `resolve_emission_destination`.

| Point | Destination | Description |
| --- | --- | --- |
| `index-active` | `committed` | Unified INDEX active rows |
| `index-archive` | `committed` | Unified INDEX archived rows |
| `legacy-gap-backlog` | `committed` | 033/045 legacy GAP-BACKLOG projection (issue-derived write-through under issue-store) |
| `legacy-prd-index` | `committed` | 033 legacy PRD INDEX projection |
| `pr-diff` | `committed` | PR diff planning-body paths |
| `dispatch-context` | `external` | Dispatch / subagent planning context |
| `spec-seed` | `committed` | wave spec-seed body copy |
| `store-get` | `external` | planning.store get / list --json (configured backend body read) |
| `superseded-manifest` | `committed` | SUPERSEDED manifest rows |
| `inflight-tuple` | `committed` | Committed INDEX inFlight tuple (032 R13 handoff) |
| `reconciler-output` | `committed` | 033 reconciler emitted bodies |
| `run-log` | `logs` | Deliver run logs |
| `handoff-032` | `local` | 032 handoff artifacts |
| `pull-in-confirm` | `committed` | **035 pull-in confirm lists** — ranked absorption/amendment proposals from `scripts/planning-related.py`; metadata-only for private units; never auto-absorb |
| `deliver-annotation` | `cross-project` | **045 R68** — `/sw-deliver` and `/sw-ship` issue annotation comments (`sw:deliver-annotate` marker); opaque PR refs for private/memory units via PRD 043 R28 resolver |
| `deliver-annotation-ingest` | `cross-project` | **045 R68** — host-sourced annotation fields (branch, PR title, author, URL) scanned as PRD 043 R45 ingest before write; redacted/refused on secret hit |
| `issue-derived-ingest` | `cross-project` | **046 R82/R84** — issue-search/get canonical form secret-scanned then redacted before INDEX row or query-cache write |
| `issue-close-batch` | `cross-project` | **045 R67** — allowlisted close-on-merge and separate-repo `issue-close` API batch |
| `issue-store-memory-pointer` | `external` | Issue-store brainstorm distillation pointer (PRD 043 R19) |
| `issue-store-freeze-record` | `external` | Issue-store freeze-record comment (PRD 043 R13) |
| `issue-store-comment` | `external` | Issue-store comment / overflow chunk write (PRD 043 R45) |
| `issue-store-put` | `external` | Issue-store put/create body write (PRD 043 R45) |

## Destination tiers (PRD 082 R32)

| Tier | Intended surfaces |
| --- | --- |
| `local` | Run-state and cache writes |
| `committed` | Committed planning artifacts and index projections |
| `external` | Planning body writes via configured backend; dispatch context |
| `cross-project` | Provider sync and cross-project copy |
| `logs` | Doctor, status, and conductor output |

Unregistered or omitted emission points resolve to `external` (strictest practical tier during migration).

## Redaction binding

Call sites MUST pass an explicit `--destination` to `memory_redact.py` / `memory-redact.py`,
resolved from this registry via `planning_visibility.resolve_emission_destination` — never from
caller free text. Lint: `python3 scripts/visibility-callsite-lint.py`.
