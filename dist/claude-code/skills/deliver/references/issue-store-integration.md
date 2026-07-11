# Issue Store Integration

## Issue linkage, annotations, and safe close (PRD 045 R22, R67–R74)

Inert when `planning.store.backend != issue-store`. Builds on PRD 043 identification (`projectKey`, body
marker) and the PRD 043 R40 call-site map.

### Annotation batch (R22, R68, R73)

After each phase reaches merge-ready green, `/sw-deliver` and `/sw-ship` (phase-mode) write **marker-delimited**
`sw:deliver-annotate` comments on deliver-linked artifact issues **before** the human merge gate
(annotate-before-merge-gate ordering, R70):

```bash
python3 scripts/wave.py issue-batch annotate --phase-slug <slug> --pr <n> --run-id <runId>
```

- **Linkage SoT (R73):** annotation comments are authoritative for PR↔issue linkage. Host introspection
  (GraphQL `linked-pr` behind PRD 043 R5 flag, REST/body-encoded fallback) is **verify-only** — disagreement
  fails closed; never overrides annotation comments.
- **Redaction (R68):** private/`memory` units emit opaque PR refs (host PR number + `runId` marker only — no
  private repo/branch/fork names) via the PRD 043 R28 destination resolver. Host-sourced fields (branch, PR
  title, author, URL) are PRD 043 R45 **ingest** inputs — `secret-scan` redacts/refuses before submit.
  Emission points: `deliver-annotation`, `deliver-annotation-ingest` (see
  `skills/visibility/references/emission-points.md`).
- **Upsert-by-marker (R70):** each annotation is keyed by deterministic content hash
  (`runId+phase+issueRef`); resume upserts — never duplicates. Tolerates issues closed-during-batch.

### Safe close-on-merge (R67)

Close behavior is **location-aware and allowlisted** — never raw provider keywords on planning artifacts:

| Location | Close mechanism |
| --- | --- |
| **same-repo** | Provider closing keywords gated on **default-branch merge** plus deliver-linked allowlist (`projectKey` + `sw:deliver-link` body marker) |
| **separate-repo** | Explicit idempotent `issue-close` API via `issuesTokenEnv`, keyed `runId+issueRef` |

- Unlinked `Closes`/`Fixes` refs in PR bodies are **rejected/warned** — cannot close unrelated planning issues.
- **Keep-open override:** `sw:deliver-keep-open` marker suppresses auto-close for a linked issue.
- Unverifiable close **fails closed**; `planning-graph doctor` flags merged-PR-but-still-open linked issues.

`/sw-ship` invokes close verification at terminal green; `/sw-deliver` orchestrates the batch across phases.

### Multi-issue transaction journal (R74, R70)

Multi-issue updates (annotations, gap/state transitions, closes) use idempotent phase markers and a deliver
**issue-batch journal** (`.cursor/sw-deliver-runs/<phase>/issue-batch-journal.json`):

```bash
python3 scripts/wave.py issue-batch run --phase-slug <slug> --run-id <runId>
python3 scripts/wave.py issue-batch resume --phase-slug <slug>   # inherits original runId (R70)
python3 scripts/planning_graph.py <root> doctor --check annotation-close-skew
```

Journal states reuse PRD 044-style progression (`pending` → `annotated` → `closed` | `skipped` | `failed`).
Partial API failure → `deliver-aborted-inconsistent` halt + repair/resume. Resume inherits the **original**
`runId`; annotation writes upsert-by-marker so resume never duplicates. Doctor classifies and repairs
annotation↔close skew; auto-close racing a deliver batch is reconciled idempotently.

Linked-PR introspection uses GraphQL only behind the PRD 043 R5 capability flag (`graphql.linked-pr` on
`github-issues`) with REST/body-encoded fallback. Minimum GraphQL scopes are documented in
`core/providers/issues/CAPABILITIES.md` (R37 table) and probed at init.


## Task-list hierarchy and inFlight tracking issues (PRD 046 R23, R89, R91, R94)

Inert when `planning.store.backend != issue-store`.

### Epic/sub-issue projection (R23, R94)

Frozen task lists map to a provider **epic** with one **sub-issue per phase** when hierarchy verbs are
supported; absent capability degrades to checkbox/body-encoded phase list with operator notice — deliver
continues.

```bash
python3 scripts/planning_hierarchy.py --root <repo> resolve-mode
python3 scripts/planning_hierarchy.py --root <repo> project docs/prds/<n>-<slug>/tasks-<n>-<slug>.md
python3 scripts/planning_hierarchy.py --root <repo> matrix
```

- **Capability matrix:** `core/providers/issues/CAPABILITIES.md` epic/sub-issue verb table (REST vs
  capability-gated GraphQL per R50).
- **Budget:** per-phase API calls compose with `planning.store.requestBudget` (R81) — never exhaust
  scheduler-critical reserve.
- **Parent status (R91):** `aggregate-status` reconciles epic labels from children on read; fails closed when
  children contradict parent tier/status; `sw-edges` body block is authoritative on native-link conflict.

### inFlight tracking issue (R89)

Optional read-only projection of committed `inFlight` tuples to a tracking issue routes through PRD 034
`redact_inflight_tuple` + visibility resolver:

```bash
python3 scripts/planning_tracking_issue.py prepare --payload-json '{"unitId":"<id>","tuple":{"runId":"r1","epoch":1,"branch":"feat/x"},"visibility":"private"}'
```

- **Redaction:** `private`/`memory` units emit opaque title/body and hashed `branchToken`/`runId`.
- **Refusal:** private/`memory` tracking issues are **refused** on public/shared origin stores
  (`probe_remote_visibility` → `public`) — fail-closed per PRD 043 R28.
- **Committed projection:** run-state → INDEX `inFlight` region remains the cross-clone SoT (R80); tracking
  issue is an optional downstream projection only.
