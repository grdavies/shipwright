---
date: 2026-06-30
topic: issue-native-dev-tracking
brainstorm: docs/brainstorms/2026-06-30-issue-backed-planning-store-requirements.md
program: issue-backed-planning-store
depends: [043-issue-backed-planning-store]
frozen: true
frozen_at: 2026-06-30
---

# PRD 045 — Issue-native dev-tracking

## Overview

This PRD adds the issue-native **dev-tracking and collaboration** layer on top of the PRD 043 backend: gaps
as native issues, commit/PR ↔ issue linkage with **safe, location-aware** close-on-merge, doc-review persona
feedback via integrity-checked issue comments, and milestone/iteration grouping. These are the process-improvement
payoffs of relocating artifacts to issues. Scheduler, issue-derived INDEX, and epic/sub-issue hierarchy are
owned by PRD 046.

Hardening requirements use the program-allocated band **R67–R79** (PRD 043 Program table); cross-PRD
references are written `PRD 043 RNN`.

## Adopter impact

- **P-A — Default file-store user.** Inert (PRD 043 R1/R3); file-store gap reconciler projection (PRD 033)
  and the in-IDE doc-review panel are unchanged.
- **P-B — Greenfield issue-store adopter.** Primary beneficiary: native gap lifecycle (R21), commit/PR
  linkage + safe auto-close (R22/R67), and traceability without manual tracking.
- **P-C — Shared multi-project planner.** Benefits but is the highest-risk surface for cross-project close and
  comment forgery; protected by R67 (allowlisted API close) and R69 (comment integrity).
- Milestones (R26/R71) are annotation/grouping only in 045; their scheduler value is wired in PRD 046.

## Goals

- Route gap capture to native gap issues under issue-store; retire the hand-maintained backlog for adopters
  with a safe, write-through shim.
- Link commits/PRs to artifact issues and close them on merge **safely** (location-aware, allowlisted).
- Conduct doc-review feedback as integrity-checked issue comments, with a file-store/IDE fallback.
- Group releases via provider milestones/iterations where available, degrading gracefully.

## Non-Goals

- Backend, freeze, identification, canonical hashing (PRD 043).
- Issue-derived INDEX/living-status derivation, epic/sub-issue hierarchy, scheduler, cross-project recall
  (PRD 046 — R23/R25/R27).
- Migration of incumbent file gaps (PRD 044) — gap capture here is native-issue creation, not file migration.
- Jira (PRD 047). Changing file-store behavior when `backend != issue-store`.

## Requirements

### Gaps as issues

- **R21** — Under issue-store, gap capture creates native gap issues; gap status is expressed via issue state + labels (`open`, `gap-scheduled`, `resolved`) and absorbed-by-PRD via a native issue link/close. Label vocabulary is disambiguated from the PRD 046 deliver-scheduler labels.
- **R72** — The legacy `GAP-BACKLOG.md` projection is **issue-derived write-through only, never an authoritative input**: the reconciler emits it from gap issues during transition; `/sw-feedback` gap capture routes to gap issues (not file append) under issue-store; `planning-graph doctor` fails closed on issue-vs-projection divergence; an explicit sunset gate removes the projection once zero file-native open gaps remain. Incumbent file gaps reach issue-store only via PRD 044.

### Linkage and safe close

- **R22** — Commits and PRs link to artifact issues via a normative linkage encoding (per location mode); `/sw-deliver` and `/sw-ship` annotate issues with PR links and phase status. Close-on-merge behavior is defined by R67 (not by raw provider keywords alone).
- **R67** — Close-on-merge is **location-aware and allowlisted**: (a) same-repo planning store → provider closing keywords gated on a default-branch merge **plus** verification that the closed issue is in Shipwright's deliver-linked allowlist (`projectKey` + body-marker, PRD 043 R12); (b) separate planning repo (PRD 043 R4) → an explicit idempotent `issue-close` API call via `issuesTokenEnv`, keyed `runId+issueRef`. Keyword-driven close of planning artifacts is otherwise disabled; an unlinked `Closes`/`Fixes` ref in a PR body is rejected/warned (cannot close an unrelated planning issue). The default branch is resolved at the merge event; fork/base mismatch and default-branch rename are handled; a keep-open override marker is supported; close that cannot be verified fails closed with a doctor for merged-PR-but-still-open linked issues.
- **R68** — Annotations route through the PRD 043 R28 destination resolver: for `private`/`memory` units on a public/shared store, PR references are emitted opaque (host PR number + runId marker; no private repo/branch/fork names). All host-sourced annotation fields (branch, PR title, author, URL) are treated as PRD 043 R45 secret-scan **ingest** inputs and redacted/refused on a secret hit; issue-store annotation write points join the PRD 043 R45 emission registry.

### Doc-review via comments

- **R24** — Under issue-store, doc-review persona feedback and human review are conducted via issue comments on the PRD issue, subject to R69; when `backend != issue-store` the current in-IDE parallel sub-agent panel + JSON synthesis is the fallback (no regression).
- **R69** — Doc-review comment integrity: persona findings are marker-delimited structured comments authored **only** by the plugin token; synthesis opens a **review-round manifest** pinning the ordered persona-comment IDs + revisions at checkpoint open (mirroring PRD 043 R9/R35) under the PRD 043 R33 exclusive checkpoint, and **fails closed** on any comment add/edit/delete before synthesis completes; comments are read-time author/marker-verified (PRD 043 R12); human and persona channels are separated; persona/review comments carry a reserved `sw:doc-review` system marker **excluded** from PRD 043 R35 canonicalization (cannot poison freeze verification).

### Milestones

- **R26** — Release grouping maps to provider milestones/iterations via a capability-gated `issue-milestone` verb (R71) where available, degrading gracefully where not (PRD 043 R31).
- **R71** — A capability-gated `issue-milestone` verb + per-provider matrix entry (PRD 043 R31) defines what is grouped (`sw:prd` units by milestone; flat-label fallback) and which command applies it; absent capability → skip with a documented operator notice, deliver continues (normative degradation table).

### Deliver multi-issue transaction

- **R74** — Multi-issue update operations during deliver/ship (annotations, gap/state transitions) use idempotent phase markers and a deliver issue-batch journal; on partial API failure they fail closed with a `deliver-aborted-inconsistent` halt plus repair/resume (R70). Linked-PR introspection uses GraphQL only behind the PRD 043 R5 capability flag (GitHub) with a REST/body-encoded fallback (R73).
- **R70** — The deliver issue-batch reuses PRD 044-style journal states; resume **inherits the original `runId`**; annotation writes are **upsert-by-marker** (deterministic content hash) with provider-side dedup so resume never duplicates annotations; resume tolerates issues closed-during-batch; a doctor classifies and repairs annotation↔close skew; the ordering contract is annotate-before-merge-gate (or idempotent reconcile) so an auto-close racing a deliver batch cannot leave inconsistent state.
- **R73** — Marker-delimited annotation comments are the **source of truth** for PR↔issue linkage; host introspection (GraphQL behind the PRD 043 R5 flag, REST/body-encoded fallback) is **verify-only** and fails closed on disagreement. GraphQL linked-PR minimum scopes are added to the PRD 043 R37 scope table and probed at init.

## Technical Requirements

- Gap issues reuse PRD 043 identification (`sw:gap`, project key, body marker) and route through `planning_store`
  + the PRD 043 R40 call-site map; absorbed-by edge via PRD 043 R29 `sw-edges` + native link projection.
- Linkage encoding is location-mode aware (same-repo `#id` vs separate-repo `owner/repo#id`/pointer-record id);
  `host` PR-body template + commit-msg guard extended with planning-issue refs; deliver annotation batch is a
  distinct write path from host PR creation (PRD 026 `host.*`).
- Doc-review transport: structured persona comments (`sw:doc-review` marker), review-round manifest, paginated
  concurrency-checked read-back; file-store fallback preserved.
- Deliver journal: states + idempotency markers keyed `runId+phase+issueRef`; upsert-by-marker.
- Milestone + GraphQL linked-PR + concurrency entries registered in `core/sw-reference/capability-index.json`.

## Security & Compliance

- **Safe close (R67).** No keyword-driven close of planning artifacts; allowlisted API close after
  `projectKey`+marker verification; cross-project/forged-ref close prevented.
- **Annotation redaction + ingest scan (R68).** Private units emit opaque PR refs; host-sourced fields scanned
  as ingest inputs; emission points registered (PRD 043 R40).
- **Comment integrity (R69).** Bot-only authorship + signed markers + review-round manifest + fail-closed on
  drift; read-time verification; exclusion from freeze hash.
- **Visibility (PRD 043 R28).** No annotation/comment exposes a private artifact on a public/shared store.
- **Token scope (R73/PRD 043 R37).** GraphQL linked-PR min scopes documented + probed; no over-privilege on
  shared stores.

## Testing Strategy

- **Gaps-as-issues (R21/R72):** open → gap-scheduled → resolved/absorbed entirely as issue state; shim is
  write-through only; doctor fails on divergence; no `GAP-BACKLOG.md` authoritative write.
- **Safe close (R22/R67):** same-repo keyword close on default-branch merge of a linked issue; separate-repo
  API close; a stray `Closes #sibling` does **not** close an unlinked planning issue; non-default/fork merge
  does not close; unverifiable close fails closed + doctor flags it; keep-open override respected.
- **Annotation redaction (R68):** a private unit's PR annotation is opaque; a token in a branch name/PR title
  is redacted/refused.
- **Comment doc-review (R69):** persona comments post + read back under the review-round manifest; a comment
  edited/deleted mid-synthesis fails closed; a forged non-bot comment is rejected; `backend != issue-store`
  uses the IDE panel fallback with synthesis parity.
- **Milestones (R26/R71):** grouping applied where supported; skip+notice where not.
- **Deliver transaction (R74/R70):** injected mid-batch failure halts `deliver-aborted-inconsistent` and
  resumes with the original `runId` and no duplicate annotations; an auto-close racing the batch is
  reconciled; pre-closed issues tolerated.
- **Linked-PR SoT (R73):** annotation comments win over disagreeing host introspection (fail closed).
- **Doc-impact fixture:** `run-planning-045-doc-impact-fixtures.sh` asserts per-phase doc updates.

## Success Criteria

1. A gap flows open → gap-scheduled → resolved/absorbed entirely as issue state; the `GAP-BACKLOG.md` shim is
   write-through only and the doctor fails closed on divergence.
2. A merged PR closes only its deliver-linked planning issue (same-repo keyword or separate-repo API), never an
   unlinked or cross-project issue; deliver/ship annotate issues with PR links + phase status.
3. A private unit's PR annotation leaks no private repo/branch/fork name, and a secret in host metadata is
   redacted/refused before submit.
4. Doc-review persona feedback round-trips as integrity-checked issue comments (bot-only, manifest-pinned,
   fail-closed on drift); `backend != issue-store` keeps the IDE panel with synthesis parity.
5. Milestone/iteration grouping is applied on supported providers and skipped with an operator notice
   elsewhere; deliver continues either way.
6. A mid-deliver partial failure halts consistently and resumes (original `runId`) without duplicate
   annotations; an auto-close racing the batch is reconciled without inconsistent state.

## Rollout Plan

Per-phase documentation-impact gate backed by `run-planning-045-doc-impact-fixtures.sh` (precedent PRD 034/035/043).

1. **Gaps-as-issues + write-through shim** (R21, R72). *Docs:* `core/skills/feedback/SKILL.md`,
   `core/skills/feedback-closure/SKILL.md`, `core/commands/sw-feedback-close.md`, `.sw/layout.md` (+
   `core/sw-reference/layout.md` sync), `core/rules/sw-naming.mdc`, `core/skills/living-status/SKILL.md`
   (gap-status only), `core/skills/visibility/references/emission-points.md`.
2. **Linkage + safe close + deliver annotations** (R22, R67, R68, R74, R70, R73). *Docs:*
   `core/skills/git-workflow/SKILL.md`, `core/commands/sw-commit.md`/`sw-pr.md`/`sw-ship.md`,
   `core/skills/deliver/SKILL.md`, `core/skills/shipwright-state/SKILL.md`, `core/sw-reference/capability-index.json`.
3. **Comment doc-review + milestones** (R24, R69, R26, R71). *Docs:* `core/commands/sw-doc-review.md`,
   `core/skills/doc-review/SKILL.md` + `references/synthesis.md`, `.sw/config.schema.json` (+ mirror) milestone
   keys, `docs/guides/configuration.md`, plus `docs/guides/workflows.md`/`commands.md`/`getting-started.md` and
   `README.md` issue-native dev-tracking notes.

## Decision Log

- **D5a** — Dev-tracking payoffs are a dependent PRD, sequenced after the PRD 043 core so adopters get artifact
  relocation before the process layer.
- **D19** — Close-on-merge is location-aware and allowlisted (explicit API close for separate repos; verified
  keyword close for same-repo) — never raw provider keywords on planning artifacts (prevents cross-repo
  silent non-close and cross-project/forged-ref close).
- **D20** — Doc-review under issue-store uses integrity-checked comments with a review-round manifest and a
  file-store/IDE fallback; persona comments are excluded from freeze canonicalization.
- **D21** — The legacy `GAP-BACKLOG.md` is an issue-derived write-through projection only (never authoritative
  input), with doctor-enforced divergence detection and an explicit sunset gate.

## Open Questions

None blocking. Resolved during `/sw-tasks`: the exact per-provider closing-keyword allowlist and whether the
plugin strips closing keywords from generated PR templates; the milestone field mapping per provider; and the
persona-comment marker/nonce encoding (shape fixed by R69).
