---
date: 2026-06-30
topic: issue-native-dev-tracking
prd: docs/prds/045-issue-native-dev-tracking/045-prd-issue-native-dev-tracking.md
program: issue-backed-planning-store
frozen: true
frozen_at: 2026-06-30
visibility: public
---

# Tasks — PRD 045 Issue-native dev-tracking

Single-pass task list from the frozen PRD 045 spec union (R21, R22, R24, R26, R67–R74 band; decisions
D19–D21). Phases mirror the PRD Rollout Plan with a per-phase documentation-impact gate backed by
`run-planning-045-doc-impact-fixtures.sh` (PRD 043 R49). Builds on PRD 043 (identification, `planning_store`
call-site map, visibility resolver, secret-scan registry) and is inert when `backend != issue-store`.

## Tasks

### 1. Gaps as issues + write-through shim (M)

Native gap lifecycle under issue-store; legacy backlog becomes an issue-derived projection only.

- [x] 1.1 Native gap-issue capture + status model (R21)
  - **File:** `scripts/planning_gap_capture.py`, `core/skills/feedback/SKILL.md`
  - **Expected:** under issue-store, gap capture creates `sw:gap` issues; status via issue state + labels (`open`/`gap-scheduled`/`resolved`); absorbed-by-PRD via native link/close; vocabulary disjoint from PRD 046 scheduler labels
  - **R-IDs:** R21
- [x] 1.2 `GAP-BACKLOG.md` write-through projection + doctor + sunset (R72)
  - **File:** `scripts/planning_gap_capture.py`, `core/skills/feedback-closure/SKILL.md`
  - **Expected:** backlog is issue-derived write-through only, never authoritative input; `/sw-feedback` capture routes to gap issues; `planning-graph doctor` fails closed on issue-vs-projection divergence; sunset gate removes projection at zero file-native open gaps
  - **R-IDs:** R72
- [x] 1.3 Phase-1 documentation exit-gate (PRD 043 R49)
  - **File:** `.sw/layout.md`, `core/skills/living-status/SKILL.md`
  - **Expected:** `run-planning-045-doc-impact-fixtures.sh` asserts gap-status + emission-point doc updates before phase ship
  - **R-IDs:** R21

### 2. Linkage, safe close, and deliver annotations (L)

Location-aware commit/PR linkage and allowlisted close-on-merge with a fail-closed deliver batch.

- [x] 2.1 Location-aware commit/PR ↔ issue linkage encoding (R22)
  - **File:** `core/skills/git-workflow/SKILL.md`, `core/commands/sw-commit.md`, `core/commands/sw-pr.md`
  - **Expected:** normative linkage encoding per location mode (same-repo `#id` vs separate-repo `owner/repo#id`/pointer-record id); `/sw-deliver` and `/sw-ship` annotate issues with PR links + phase status
  - **R-IDs:** R22
- [x] 2.2 Location-aware allowlisted close-on-merge (R67)
  - **File:** `core/skills/deliver/SKILL.md`, `core/commands/sw-ship.md`
  - **Expected:** same-repo keyword close gated on default-branch merge + `projectKey`+body-marker allowlist; separate-repo explicit idempotent `issue-close` keyed `runId+issueRef`; unlinked `Closes`/`Fixes` rejected/warned; keep-open override; unverifiable close fails closed + doctor for merged-but-open
  - **R-IDs:** R67
- [x] 2.3 Annotation redaction + ingest secret-scan (R68)
  - **File:** `core/skills/deliver/SKILL.md`, `core/skills/visibility/references/emission-points.md`
  - **Expected:** private/`memory` units emit opaque PR refs via PRD 043 R28 resolver; host-sourced fields (branch/title/author/URL) scanned as PRD 043 R45 ingest, redacted/refused on hit; annotation write points join emission registry
  - **R-IDs:** R68
- [x] 2.4 Deliver multi-issue transaction journal (R74)
  - **File:** `core/skills/deliver/SKILL.md`, `core/skills/shipwright-state/SKILL.md`
  - **Expected:** multi-issue updates use idempotent phase markers + deliver issue-batch journal; partial failure → `deliver-aborted-inconsistent` halt + repair/resume; linked-PR introspection GraphQL only behind PRD 043 R5 flag with REST/body-encoded fallback
  - **R-IDs:** R74
- [x] 2.5 Batch resume, upsert-by-marker, skew doctor (R70)
  - **File:** `core/skills/deliver/SKILL.md`
  - **Expected:** batch reuses PRD 044-style journal states; resume inherits original `runId`; annotation writes upsert-by-marker (deterministic hash) so resume never duplicates; tolerates closed-during-batch; doctor repairs annotation↔close skew; annotate-before-merge-gate ordering
  - **R-IDs:** R70
- [x] 2.6 Annotation comments as linkage source-of-truth (R73)
  - **File:** `core/skills/deliver/SKILL.md`, `core/sw-reference/capability-index.json`
  - **Expected:** marker-delimited annotation comments are SoT for PR↔issue linkage; host introspection (GraphQL behind PRD 043 R5 flag / REST fallback) is verify-only, fails closed on disagreement; GraphQL min scopes added to PRD 043 R37 table and probed at init
  - **R-IDs:** R73
- [x] 2.7 Phase-2 documentation exit-gate (PRD 043 R49)
  - **File:** `core/skills/git-workflow/SKILL.md`, `core/sw-reference/capability-index.json`
  - **Expected:** doc-impact fixture asserts linkage/close/annotation docs updated before phase ship
  - **R-IDs:** R22

### 3. Comment doc-review + milestones (M)

Integrity-checked issue-comment doc-review with IDE fallback, and capability-gated milestone grouping.

- [x] 3.1 Doc-review via issue comments + fallback (R24)
  - **File:** `core/commands/sw-doc-review.md`, `core/skills/doc-review/SKILL.md`
  - **Expected:** under issue-store, persona + human doc-review via PRD-issue comments (subject to R69); `backend != issue-store` falls back to in-IDE parallel sub-agent panel + JSON synthesis with no regression
  - **R-IDs:** R24
- [x] 3.2 Comment integrity + review-round manifest (R69)
  - **File:** `core/skills/doc-review/references/synthesis.md`, `core/skills/doc-review/SKILL.md`
  - **Expected:** bot-only marker-delimited persona comments; review-round manifest pins ordered comment IDs+revisions under PRD 043 R33 checkpoint; fails closed on any add/edit/delete before synthesis; read-time author/marker verification; `sw:doc-review` marker excluded from PRD 043 R35 canonicalization
  - **R-IDs:** R69
- [x] 3.3 Milestone/iteration grouping (R26)
  - **File:** `.sw/config.schema.json`, `docs/guides/configuration.md`
  - **Expected:** release grouping maps to provider milestones/iterations where available, degrading gracefully per PRD 043 R31
  - **R-IDs:** R26
- [x] 3.4 Capability-gated `issue-milestone` verb + matrix (R71)
  - **File:** `core/sw-reference/capability-index.json`, `core/providers/issues/CAPABILITIES.md`
  - **Expected:** `issue-milestone` verb + per-provider matrix entry; groups `sw:prd` units by milestone (flat-label fallback); absent capability → skip with operator notice, deliver continues (normative degradation table)
  - **R-IDs:** R71
- [x] 3.5 Phase-3 documentation exit-gate (PRD 043 R49)
  - **File:** `docs/guides/workflows.md`, `README.md`
  - **Expected:** doc-impact fixture asserts doc-review + milestone + getting-started notes updated before phase ship
  - **R-IDs:** R24

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |

## Traceability

| R-ID | Task ref | Named test scenario |
|------|----------|---------------------|
| R21 | 1.1 | gap flows open→gap-scheduled→resolved/absorbed entirely as issue state |
| R72 | 1.2 | GAP-BACKLOG write-through only; doctor fails closed on issue-vs-projection divergence |
| R22 | 2.1 | commit/PR linkage encoding per location mode; deliver/ship annotate PR links + phase status |
| R67 | 2.2 | merged PR closes only its deliver-linked issue; stray/cross-project/non-default-merge does not close |
| R68 | 2.3 | private unit's PR annotation opaque; token in branch/title redacted/refused before submit |
| R69 | 3.2 | persona comments round-trip under manifest; mid-synthesis edit/delete fails closed; forged comment rejected |
| R24 | 3.1 | doc-review via comments under issue-store; IDE panel fallback with synthesis parity off-mode |
| R26 | 3.3 | milestone grouping applied on supported providers; skipped with notice elsewhere |
| R71 | 3.4 | `issue-milestone` capability present → grouped; absent → skip+notice, deliver continues |
| R74 | 2.4 | injected mid-batch failure halts `deliver-aborted-inconsistent` and resumes |
| R70 | 2.5 | resume inherits original `runId`, no duplicate annotations; auto-close race reconciled; pre-closed tolerated |
| R73 | 2.6 | annotation comments win over disagreeing host introspection (verify-only, fail closed) |
| D19 | 2.2 | close-on-merge location-aware + allowlisted, never raw keywords on planning artifacts |
| D20 | 3.1, 3.2 | doc-review integrity comments + review-round manifest + IDE fallback; excluded from freeze canonicalization |
| D21 | 1.2 | GAP-BACKLOG is issue-derived write-through projection only with doctor + sunset gate |
