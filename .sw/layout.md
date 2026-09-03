# Shipwright artifact layout

Single-source path contract for the documentation pipeline and downstream implementation workstream.
All `sw-` doc commands resolve paths from this document — do not re-decide locations in commands.

## Directory tree

```text
docs/
└── brainstorms/
    ├── YYYY-MM-DD-<topic>-requirements.md
    └── YYYY-MM-DD-<topic>-requirements.amendments/
        └── A<k>-<short>.md

docs/prds/
├── INDEX.md
├── COMPLETION-LOG.md
├── GAP-BACKLOG.md
└── <n>-<slug>/
    ├── <n>-prd-<slug>.md
    ├── tasks-<n>-<slug>.md
    └── amendments/
        └── A<k>-<short>.md

docs/decisions/
├── INDEX.md
├── SUPERSEDED.log          # append-only manifest (written on record-level supersede)
├── .memory-freeze-audit.log  # offline freeze audit breadcrumb (local; not authoritative)
├── <n>-<slug>.md
└── <n>-<slug>.amendments/
    └── A<k>-<short>.md

.cursor/
├── sw-deliver-plan.json             # transient global plan (legacy; prefer run-scoped plan.json)
├── sw-living-docs.lock              # repo-wide living-doc write serialization (PRD 013 R12)
├── sw-deliver-state.json            # legacy repo-wide state (migration breadcrumb)
├── sw-deliver.lock                  # legacy repo-wide lock (superseded)
├── sw-deliver-state.<slug>.json     # legacy slug-scoped state (migration; adopt → run-scoped)
├── sw-deliver-<slug>.lock           # legacy slug-scoped orchestrator lock (migration)
├── sw-deliver-runs/
│   ├── index.json                   # discovery-only run index (R20 — no run payload)
│   └── <runId>/                     # per-run deliver namespace (R18/R20)
│       ├── plan.json                # immutable run plan + planHash in state
│       ├── state.json               # authoritative deliver run-state
│       ├── events.jsonl             # append-only run events
│       ├── lease.json               # run-local lease → target-lock digest (orphan trace)
│       ├── blocker.json             # active blocker snapshot (when set)
│       ├── terminal-acceptance.json # validated terminal acceptance record
│       ├── receipts/                # transition / mutation receipts (R25)
│       └── phases/
│           └── <phaseId>/           # stable phase id (not slug) — per-phase ship artifacts
│               ├── status.json
│               ├── ship-steps.json
│               ├── phase-step-plan.json
│               ├── execute-step-plan.json
│               ├── integrate-journal.json
│               ├── execute-supervised-confirmed.json
│               ├── gap-check.status.json
│               ├── gate-evidence/   # per-gate binding-valid records (PRD 065 R7/R9)
│               │   └── <gateId>.status.json
│               └── dispatch-decisions.json
├── sw-graph-runs/                   # gitignored WorkflowGraph receipt journal (PRD 269 R13/R17)
│   └── <runId>/                     # per-run index (receipts + intents + telemetry)
│       ├── receipts/
│       │   ├── partial/             # in-flight intents
│       │   ├── complete/
│       │   ├── quarantine/
│       │   └── cache-index/
│       ├── pool-snapshot.json
│       └── telemetry.json
├── sw-graph-cache/                  # gitignored authenticated canonical cache (PRD 271 R4/R21)
│   ├── objects/                     # immutable MAC-stamped cache entries
│   ├── manifests/                   # atomically published scope manifests
│   ├── bookkeeping/                 # incremental size accounting (R4c)
│   └── quarantine/                  # corrupt entries (untrusted-on-read)
├── sw-doc-runs/                     # durable /sw-doc driver state (R11)
│   ├── index.json
│   └── <runId>/
│       ├── state.json
│       └── receipts/
├── sw-deliver-locks/                # per-phase-head ship lease (integration+phase branch digest)
├── sw-deliver-run-locks/            # exclusive deliver runId lease (PRD 276 R9–R12, R20–R21)
│   └── reclaim-journal.jsonl        # stale reclaim + generation fencing audit
├── sw-target-locks/                 # target-branch exclusion locks (git-common-dir anchored, R19)
│   └── reclaim-journal.jsonl
├── sw-doc-run-locks/                # doc-run exclusion locks (topic digest, R19)
│   └── reclaim-journal.jsonl
├── sw-planning-reservations/        # transactional PRD number reservation locks (R16)
│   └── <nnn>.lock
├── sw-architecture-radar/           # read-only architecture radar scan artifacts (PRD 280 R1–R6)
│   ├── last.json                    # pointer to latest scan
│   └── <scanId>/                    # per-scan candidates + scoring payload
├── sw-vocabulary-divergence/        # read-only vocabulary divergence artifacts (PRD 280 R7–R11)
│   └── last.json                    # latest check-divergence summary
├── capability-promotion-registry.json  # CapabilityPromotion@v1 durable registry (PRD 332 R4, R11)
├── compression-dispatch-evidence.jsonl # append-only CompressionEvidence@v1 dispatch log (PRD 332 R7)
├── hooks/state/context-compress-cache/ # lossless/shadow compression cache (dispatch_prompt.py)
└── sw-decision-evidence/            # hash-linked research evidence records (PRD 326)
    └── <parentDecisionId>.json      # ResearchEvidence@v1 per parent decision node
```

### Per-run deliver layout (PRD 081 R18, R20)

Run identity is minted once at run creation (`scripts/wave_run_paths.py mint_run_id`) and every
run-scoped accessor requires a non-empty `runId`. Two concurrent deliveries — even when they share a
human-readable phase slug on different feature branches — remain fully isolated under distinct
`<runId>/` directories.

| Concern | Path | Writer | Notes |
| --- | --- | --- | --- |
| Run directory | `.cursor/sw-deliver-runs/<runId>/` | deliver lifecycle | Sole namespace for plan/state/events |
| Run plan | `plan.json` | `wave_run_plan.py` | Content hash verified on every read |
| Run state | `state.json` | `wave_state.save_run_scoped_state` | Cursor, phases map, merge queue |
| Run-local lease | `lease.json` | `wave_state.write_run_local_lease` | Records `lockKeyDigest` for orphan tracing |
| Phase status | `phases/<phaseId>/status.json` | `ship-phase-status.py` | Stable numeric/string phase id |
| Discovery index | `.cursor/sw-deliver-runs/index.json` | `wave_state` index helpers | `INDEX_DISCOVERY_FIELDS` only — never exclusion primitive |

**Legacy adoption (R21):** slug-scoped `.cursor/sw-deliver-state.<slug>.json` entries are enumerated for
`list` / `resume` and may be adopted into the run-scoped layout via `wave_run_adopt.py` (single global-plan
read). After adoption, `legacyAdopted` / `adoptedPlanHash` on run-scoped `state.json` is authoritative.

### Doc-run layout (PRD 081 R11)

| Path | Role |
| --- | --- |
| `.cursor/sw-doc-runs/<runId>/state.json` | Durable doc driver cursor (`doc_loop.py`) |
| `.cursor/sw-doc-runs/<runId>/receipts/` | Stage transition receipts (idempotent keys) |
| `.cursor/sw-doc-runs/index.json` | Discovery index for concurrent doc runs |
| `.cursor/sw-doc-runs/amendment-inputs/` | Post-freeze rescore signals recorded as amendment input (R17) |

Doc-run exclusion uses `.cursor/sw-doc-run-locks/` (`wave_target_lock.acquire_doc_run_lock`).

**Shared index concurrency (PRD 090 R1):** `.cursor/sw-doc-runs/index.json` and
`.cursor/sw-deliver-runs/index.json` read-modify-write through `planning_txn.store_lock` with monotonic
`revision` fields (`doc_loop.py`, `wave_state.py`) — concurrent index writers fail closed rather than
clobbering peers.

**Doc-to-feature handoff lock (PRD 085 R14):** under `file-store-feature-seed` publication mode the
`feature-seed` stage acquires a doc-loop-scoped handoff lock (`wave_spec_seed_guard.acquire_doc_to_feature_handoff_lock`)
before invoking `wave_spec_seed.py` with `remoteState.dryRun: false`, then releases it after seed verification.
Concurrent deliver target-lock holders on the same branch fail closed (`target-lock-conflict`). Separate-project
issue-store modes remain `skipped: true` and do not take the handoff lock.


### Graph execution receipt journal (PRD 269 R13/R17)

Gitignored, owner-writable run store for WorkflowGraph receipts and in-flight intents. Generated by
`scripts/gitignore_generate.py` as `.cursor/sw-graph-runs/`. Prefer `ExecutionReceiptJournal.for_run`
so every artifact is indexed under a single `runId` (no full-history scan).

```text
.cursor/sw-graph-runs/                 # gitignored; chmod 0700 when possible
└── <runId>/                           # generic graph runId (mapped from deliver/orchestrator)
    ├── receipts/
    │   ├── partial/                   # in-flight intents (begin before mutating dispatch)
    │   ├── complete/                  # settled per-node receipts (idempotency-keyed)
    │   ├── quarantine/                # corrupt receipts (queries skip; unrelated nodes continue)
    │   └── cache-index/               # content-addressed reuse index
    ├── pool-snapshot.json             # durable pool occupancy for crash replay
    └── telemetry.json                 # run-scoped cost/timing telemetry
```

| Concern | Path | Writer | Notes |
| --- | --- | --- | --- |
| Store root | `.cursor/sw-graph-runs/` | `graph.execution_receipts.default_store_root` | Gitignored; retention + size ceiling (R13) |
| Per-run directory | `.cursor/sw-graph-runs/<runId>/` | `ExecutionReceiptJournal.for_run` | Sole index key for status/explain |
| Receipt journal | `…/<runId>/receipts/` | scheduler / crash harness | `partial/` = intents; `complete/` = finished |
| In-flight intents | `…/receipts/partial/*.json` | `begin()` before dispatch | Retired atomically on `finish()` |
| Pool / telemetry | `…/pool-snapshot.json`, `…/telemetry.json` | scheduler | Survive harness teardown with receipts |

Deliver run-state (`.cursor/sw-deliver-runs/<runId>/`) remains the conductor cursor. Graph receipts are
a separate namespace keyed by the same generic `runId` — not a second operator identity.

The conductor cursor is **not** the `GraphScheduler` owning loop — phase/wave fan-out and merge queues are conductor concerns; node admission, cache, and timing attribution are graph-scheduler concerns (`scripts/graph/scheduler.py`).

### Authenticated canonical cache store (PRD 271 R4–R6, R21–R26)

Gitignored, self-contained cache distinct from run journals. Default root:
`.cursor/sw-graph-cache/` (`graph.cache_store.default_cache_root`). Entries are content-addressed,
MAC-authenticated (broker-resolved per-repo secret), and receipt-visible on hit (`cacheSource: cache`,
`cacheKey`, `originalRunId`).

```text
.cursor/sw-graph-cache/                 # gitignored; chmod 0700 when possible
├── objects/<cacheKey>.json            # immutable entries (entryMac required on read)
├── manifests/<scope>/current.json     # atomically published manifest per scope
├── bookkeeping/stats.json             # incremental totalBytes / entryCount (no per-write rglob)
└── quarantine/                        # corrupt entries — untrusted-on-read
```

| Concern | Path | Writer | Notes |
| --- | --- | --- | --- |
| Store root | `.cursor/sw-graph-cache/` | `CanonicalCacheStore` | Independent ceiling/GC from journals (R4b) |
| Scope ladder | `graphExecution.cache.scope` | config | Dogfood default `run` (intra-run memoization); `repository` only after R24/R25 green |
| MAC secret | `graphExecution.cache.credentialRef` | credential broker | Per-repo/machine secret — no source-constant key (R5a/R24) |
| Run journals | `.cursor/sw-graph-runs/<runId>/receipts/` | `ExecutionReceiptJournal` | Historical records only — no durable cross-run cache index |

**Retention:** cache GC defaults to 30-day retention and a 256 MiB ceiling independent of journal limits
(`CanonicalCacheStore.gc`); oversize writes fail closed (`CacheStoreFull`).

### Reviewer effectiveness metrics (PRD 273)

Offline, advisory-only calibration for reviewer personas and models. Metrics **never** gate live review,
kernel classification, promotion, or panel composition.

| Surface | Canonical path | Writer | Retention |
| --- | --- | --- | --- |
| Learning store (sole v1 authority) | `.cursor/sw-learning-store/` | `graph.learning_store.LearningStore` via `ReviewerMetricsStoreAdapter` | Default 90-day retention (`DEFAULT_RETENTION_SECONDS` in `learning_store.py`) |
| Metadata adapter | `scripts/graph/reviewer_metrics/store_adapter.py` | Append-only `LearningEvent` writes | Gitignored; operator-local |
| Operator CLI | `scripts/reviewer-metrics.py` | Operator label ingest / export | Delegates to learning store — no parallel SoT |

**NP-1 (no promotion inflation):** reviewer metrics MUST NOT auto-promote learnings to standing rules,
memory, or kernel classification. The thin adapter maps validated metadata into `.cursor/sw-learning-store`
only — it does not reimplement generic promotion (#678/#679). See
`scripts/unit_tests/graph/test_reviewer_metrics_no_promotion.py`.

**NP-3 (no closed-loop optimization):** ratings, calibration, and ranking reports are report-only.
`ELO_GATING_ENABLED` and `RANKING_GATING_ENABLED` remain `false`; metrics cannot authorize/deny reviewers,
alter quorum bindings, or change kernel/promotion paths.

**Out of scope (PRD 272):** receipt-derived learning-store schema, promotion pipelines, and graph execution
runtime concerns belong to PRD 272 — not duplicated here. See `scripts/graph/learning_store.py` and
`docs/guides/workflows.md` (Reviewer effectiveness calibration).

### Target-lock and run-local lease paths (PRD 081 R19, R20)

| Lock kind | Directory | Resolver | Journal |
| --- | --- | --- | --- |
| Target-branch exclusion | `.cursor/sw-target-locks/` | `wave_lock.target_lock_path_for` | `reclaim-journal.jsonl` |
| Doc-run exclusion | `.cursor/sw-doc-run-locks/` | `wave_lock.doc_run_lock_path_for` | `reclaim-journal.jsonl` |
| Doc-to-feature handoff | `.cursor/sw-doc-to-feature-handoff-locks/` | `wave_lock.doc_to_feature_handoff_lock_path_for` | `reclaim-journal.jsonl` |
| Phase-head ship lease | `.cursor/sw-deliver-locks/` | `wave_lock.lock_path_for` | — |
| Exclusive deliver runId lease | `.cursor/sw-deliver-run-locks/` | `wave_lock.run_lease_path_for` | `reclaim-journal.jsonl` |
| Run-local lease record | `<runId>/lease.json` | `wave_run_paths.lease_path` | points at target-lock digest |

Target locks are git-common-dir anchored and symlink-checked (`wave_lock.py`). Takeover appends a journal
entry before reclaim; a live heartbeat is never reclaimed without explicit cross-host acknowledgement.

### Exclusive runId lease taxonomy (PRD 276 R19)

| Concern | Contract |
| --- | --- |
| Scope | Local to the git common-dir — not a cross-clone remote lease (uncertain ownership fail-closed) |
| Key | `runId` digest under `.cursor/sw-deliver-run-locks/<digest>-<runId>.lock` |
| Acquire | Before mutating run-scoped deliver state (`deliver-loop` adoption) |
| Held halt | Second concurrent adopter → typed halt + `resumeCommand` (no double-drive) |
| Stale reclaim | Same-host + stale heartbeat + dead PID; bumps `generation` and journals the takeover |
| Generation fencing | Writes carrying a prior generation after reclaim fail closed |
| Distinct from | Phase-head ship lease (`.cursor/sw-deliver-locks/`) and run-local `lease.json` orphan-trace record |

**Cross-clone remote lease (PRD 090 R2):** target-branch and doc-to-feature handoff locks also take a
git-ref CAS lease via `wave_remote_lease` (`refs/sw-locks/…`) so two clones cannot both hold the same
logical lock. Local heartbeat still wins within a clone; remote lease covers the multi-clone race.

### Gate manifest and evidence (PRD 065)

| Artifact | Path | Role |
| --- | --- | --- |
| Declarative gate manifest | `core/sw-reference/gate-manifest.json` | Stable gate ids, class, binding mode, failure routing |
| Evidence record schema | `core/sw-reference/gate-evidence.schema.json` | Required fields + atomic-write contract |
| Per-phase evidence dir | `.cursor/sw-deliver-runs/<runId>/phases/<phaseId>/gate-evidence/` | Sole-writer path for mechanical gate records |
| Terminal acceptance | `.cursor/sw-deliver-runs/terminal-acceptance.json` | Validated acceptance before `report terminal` |
| Kernel lineage | `core/sw-reference/kernel-classification.json` | Manifest-to-lineage binding; kernel floor non-demotable |

### Decision evidence store (PRD 326)

| Artifact | Path | Role |
| --- | --- | --- |
| Research evidence schema | `core/sw-reference/research-evidence.schema.json` | `apiVersion: decision-evidence/v1`, `kind: ResearchEvidence` |
| Canonical serialization | `core/sw-reference/canonical-serialization.md` | Sorted-key JSON + `contentHash` rules |
| Per-parent evidence file | `.cursor/sw-decision-evidence/<parentDecisionId>.json` | Operator-local store; one record per parent decision node |

Writers validate against the schema before atomic write. Canonical hash rules: sorted keys at every object
level; `spec.contentHash` covers the spec object excluding itself (see **Decision evidence — ResearchEvidence**
in `canonical-serialization.md`). Link-back updates parent decision nodes in the active `DecisionGraph`
document — not a second authoritative graph store.

### Architecture doctrine and assessment (PRD 326)

| Artifact | Path | Owner | Refresh |
| --- | --- | --- | --- |
| Doctrine artifact | `core/sw-reference/architecture-doctrine.md` | platform-team | per release |
| Assessment schema | `core/sw-reference/architecture-assessment.schema.json` | platform-team | per release |
| Assessment YAML | `.cursor/architecture-assessment.yaml` | repo operator | on verdict change |
| Evaluator | `scripts/architecture_assessment.py` | platform-team | per release |

Doctrine statements use stable `AD-<n>` ids with rationale and an observable signal (or `manual: true`).
Assessment YAML is opt-in via `architecture.assessment.mode` (`off` default). `waived` entries require
`waiver.{actor,reason,expires}`; expired waivers count as `fail`. Waivers cannot be authored on autonomous
dispatch paths.

Bundled `architecture-doctrine.md` is **Shipwright-self reference only** (PRD 330 R3/R8). It MUST NOT
become consumer project law. Consumer architecture ownership lives under **Consumer ProjectDoctrine**
below.

### Consumer ProjectDoctrine and baseline (PRD 330 R8, R15)

Repo-local consumer artifacts — not bundled `core/sw-reference` law. Issue-store mirrors are
projection-only.

| Artifact | Path | Owner | Lifecycle |
| --- | --- | --- | --- |
| **ProjectDoctrine SoT** | `.sw/project-doctrine.json` | consumer repo operator | Sole doctrine authority; create only via explicit accept/promote |
| **ProjectBaseline draft** | `.sw/project-baseline.draft.json` | consumer repo operator | Advisory draft from brownfield synthesis; never autonomous promote |
| **Optional issue-store projection** | `.cursor/sw-planning-projections/project-doctrine.json` | planning projection writer | Mirror when issue-store planning is effective — **never** authority |
| **Init decline breadcrumb** | `.cursor/sw-init-project-doctrine.json` | `/sw-init` configurator | Durable skip/decline; non-authoritative |
| **ProjectDoctrine@v1 schema** | `core/sw-reference/project-doctrine.schema.json` | platform-team (`coreAuthoredAllowlist`) | per release |
| **ProjectBaseline@v1 schema** | `core/sw-reference/project-baseline.schema.json` | platform-team (`coreAuthoredAllowlist`) | per release |
| **Leakage scanner** | `scripts/project_doctrine_leakage.py` | platform-team | Reject Shipwright-self markers in consumer SoT |
| **Lifecycle CLI** | `scripts/project_doctrine.py` / `scripts/project_baseline.py` | platform-team | Scaffold, validate, draft synthesize, explicit promote |

**Shipwright-self boundary:** bundled statements under `core/sw-reference/architecture-doctrine.md`
and related plugin references stay plugin law. Valid consumer links use `shipwrightSelfRef` pointers —
never copied bundled text as project authority.

**Consent:** greenfield empty scaffold is opt-in; brownfield synthesis writes draft baseline only;
baseline→doctrine requires explicit operator `--confirm` promote and a leakage-green verdict.


### Deliver run-state ledger (PRD 059 R9–R11)

`taskLedger` on run-scoped `state.json` (`.cursor/sw-deliver-runs/<runId>/state.json`) records per-subtask
`done` state used by `planning_store.py materialize --resync`. Legacy slug-scoped
`.cursor/sw-deliver-state.<slug>.json` mirrors remain readable during adoption only.

### Slim gate manifest + request budget (PRD 062 R8, R12, R19)

| Concern | Location | Semantics |
| --- | --- | --- |
| Slim `prTestPlan` | `status.json` carries `manifestPath` + `manifestSha256` only | Full manifest snapshot at `.cursor/sw-gate-cache/pr-test-plan.manifest.json` (cleanup-safe under repo root) |
| Fail-closed load | `check_gate_lib.validate_pr_test_plan_gate` | Missing path/hash mismatch → gate `blocked` (`prTestPlan:slim-manifest-incomplete`) |
| Request budget ledger | `.cursor/hooks/state/planning-request-budget.json` | Per-run isolation; `github-issues` default `maxCalls: 750` |
| Critical revalidate | `planning_request_budget.RequestBudgetLedger.charge(critical=True)` | `critical=True` bypasses TTL cache (`cacheTtlSeconds` → 0) for authoritative status ops |
| Deliver-loop drain | `deliver.loop.drainMechanical` (default `true`) | See `core/skills/conductor/SKILL.md` **Deliver-loop mechanical drain** |
| Driver timing | `run.log` `driver-transition` / `execute-mechanical` events | `elapsedMs` numeric only (R9) |

Scoped cleanup inflight: `cleanup_lib.deliver_inflight` scopes protection to active run slugs; terminal
`complete`/`rejected` verdicts allow run-state removal when merge detection is deterministic.

### Graph execution store (PRD 269 R6/R7/R13)

Gitignored operator runtime for WorkflowGraph execution — **not** feature implementation. Default root:
`.cursor/sw-graph-runs/` (`graph.execution_receipts.default_store_root`). Status/explain and receipt
writers resolve journals per `runId` — never scan all history.

```text
.cursor/sw-graph-runs/
├── index.json                   # discovery-only run index (runId → journal path; no payload)
└── <runId>/                     # generic graph runId (matches deliver/orchestrator runId)
    ├── receipts/
    │   ├── partial/             # in-flight dispatch intents (pre-complete receipts)
    │   ├── complete/            # durable per-node execution receipts (HMAC + hash)
    │   ├── quarantine/        # corrupt receipts quarantined fail-closed
    │   └── cache-index/       # content-addressed reuse index
    ├── pool-snapshot.json       # resource pool / park queue snapshot for this run
    └── telemetry.json           # run-scoped cost telemetry
```

| Concern | Path | Writer | Notes |
| --- | --- | --- | --- |
| Store root | `.cursor/sw-graph-runs/` | `ExecutionReceiptJournal` | Mode `0700`; user-writable only |
| Per-run journal | `<runId>/receipts/` | `ExecutionReceiptJournal.for_run` | Partial = in-flight intent; complete = terminal receipt |
| Run index | `index.json` | graph run registry | Discovery fields only — not an exclusion primitive |
| Pool snapshot | `<runId>/pool-snapshot.json` | scheduler / journal | Park queue + pool occupancy for explain |
| Telemetry | `<runId>/telemetry.json` | scheduler / journal | Numeric cost fields only |

**Per-run indexing:** `status_integrity.py graph-progress` and `explain` open
`<store>/<runId>/receipts` (or an explicit `--journal-root` already scoped to the run). In-flight
intents live under `receipts/partial/` until `complete/` — the same idempotency key cannot fork.

**Retention:** receipt GC defaults to 14-day retention and a 64 MiB per-run ceiling
(`ExecutionReceiptJournal.gc`); oversize writes fail closed (`ReceiptStoreFull`).


## Planning-unit model (PRD 031)

Canonical frontmatter schema: `core/sw-reference/planning-unit.schema.json` (validated by
`scripts/planning-unit-validate.py`). Status enums are type-conditioned via `scripts/planning_status_enum.py`
(stub values only — PRD 033 owns transition semantics).

### Unit folder layout

Every planning unit is a **folder** under the typed-unit tree (`docs/planning/` at cutover; see R5). Each
folder contains:

- A **canonical body file** with planning-unit frontmatter (`id`, `type`, `status`, `title`, `visibility`, edge
  arrays, optional `priority`/`tags`).
- **Optional ancillary tracked files** co-located in the same folder (e.g. a PRD unit's frozen task lists and
  `amendments/` subtree).

```text
docs/planning/
├── INDEX.md                         # single generated unified INDEX (R5)
└── <type>/<id>-<slug>/              # one folder per unit
    ├── <id>-<type>-<slug>.md        # canonical body (frontmatter + content)
    ├── tasks-<id>-<slug>.md         # optional (PRD units)
    └── amendments/                  # optional (PRD / decision units)
        └── A<k>-<short>.md
```

### Stable unit ids (R2)

- Unit `id` values are **stable**, **monotonic**, and **never reused** after assignment.
- All cross-references (`depends`, `blocks`, `supersedes`, `extends`, `absorbs`, INDEX rows) use the **unit id**
  — never a table row index, filesystem path alone, or positional reference.
- Gap units use the same id discipline (e.g. `gap-045-sample`) — they are not anonymous backlog rows.

### Unified INDEX schema (R5/R9/R24)

`docs/planning/INDEX.md` is the **single generated unified INDEX** produced from unit frontmatter by
`scripts/planning_index_gen.py`. It is never hand-maintained.

The INDEX carries three disjoint regions (HTML comment markers):

| Region | Owner | Purpose |
|--------|-------|---------|
| `structural` | INDEX generator | Rows from unit frontmatter (`id`, `type`, `title`, `status`, `visibility`, edges) |
| `derived` | reconciler (PRD 033) | Derived lifecycle status per unit — empty schema slot at cutover |
| `inFlight` | deliver writer (PRD 032) | Committed in-flight tuple per active unit (`runId`, `branch` or `branchToken`, `epoch`) — schema: `core/sw-reference/inflight-tuple.schema.json` |

**inFlight tuple (PRD 032):** markdown table rows in the INDEX `inFlight` region; no lifecycle status in the tuple
(033 derives `in-progress`). Cleartext `branch` is committed for non-private units until PRD 034 lands; the schema
reserves `branchToken` (hashed suffix) for private-unit redaction. The region is included in the PRD 034
emission-point registry handoff.

**Read-merge-write:** every writer parses the existing INDEX and preserves non-owned regions **byte-for-byte**.
Full-file regen that drops a sibling region is prohibited; `scripts/index-region-guard.py` enforces this on
pre-commit and in CI.

### Issue-store region disposition (PRD 043 R34)

### PRD 046 phase-1 region disposition (committed inFlight)

When `planning.store.backend` is `issue-store` and the cutover gate permits issue discovery:

| Region | Phase-1 authority | Writer | Notes |
| --- | --- | --- | --- |
| `structural` | file or issue (gated) | generator / issue-derived | `planning_discover.py` single source |
| `derived` | file (gated) | reconciler | issue-derived read-only when cutover open |
| `inFlight` | deliver run-state | deliver | sole writer; committed INDEX projection read-only |

Deliver writes the `inFlight` tuple to durable run-state and projects it read-only into the committed
INDEX `inFlight` region (`planning_region_disposition.py project`). The `inFlight` region is **never
mechanically edited** by reconciler or docs-merge — deliver writer only.

Dual-mode INDEX: file-store users remain inert; issue-store derives read-only views via `discover_units`
backend plug (`file` | `issue`). Generation token serializes concurrent INDEX regeneration (R88). The `inFlight` region is never mechanically edited by reconciler or docs-merge.


When `planning.store.backend` is `issue-store`, authoritative location per INDEX region is governed by
`core/providers/planning-store/issue-store.md`. Phase-1 interim (adoption gated):

| Region | Phase-1 authoritative | Post-adoption target |
| --- | --- | --- |
| `structural` | file-store (in-repo-public) | issue-derived rows |
| `derived` | file-store (reconciler) | issue-derived lifecycle |
| `inFlight` | deliver writer file tuple (PRD 032) | projected to issue store |

Until a region is issue-derived, the file-store remains authoritative — issue-store config alone does not
migrate regions.

**Zero stub files (R7):** when issue-store is the effective backend, doc commands must not commit
planning artifact bodies to the code repo; artifacts live as issues and materialize to git-ignored paths
at deliver time (Phase 3): `planning_store.py freeze` records `sw-freeze-record` hash; `planning_materialize.py provision` verifies hash before materializing frozen task lists to `.cursor/planning-materialized/`.

**Hash-verified freeze for ledger (PRD 277 / `frozen_spec_ledger.spec_is_frozen`):** issue-store
materialized task lists often keep `status: draft` without `frozen: true` so the recorded freeze hash
stays byte-stable. Deliver ledger check, phase acceptance, and `effective_task_checkboxes` treat a
`verify-frozen-hash` pass (`issue_store_frozen_verified`) as frozen — frontmatter pin **or** hash
verification. Do not toggle checkboxes or add `frozen: true` on those bodies; that breaks the hash.

**Closeout freeze re-pin (PRD 275 / facade):** `close-delivery-units` (via `planning_store_facade` →
`IssueStoreBackend.repin_freeze_after_close`) appends a newest `sw-freeze-record` after mutating frozen
issue state/labels to closed/complete so subsequent `get` does not raise `tamper-detected`. Partial
append failure returns not-ready with idempotent retry repair — state/labels stay inside the integrity
hash (facade boundary; do not bypass).

**Status precedence:** lifecycle consumers read `derived.status` when populated and fall back to structural
`status`; gap units (`type: gap`) always use structural status only.

### Private INDEX rows (R33 — PRD 034 handoff)

INDEX structural rows for `visibility: private` units carry **provisional** title metadata (`[provisional]` prefix)
until PRD 034 defines redaction/omission of private rows. Unit bodies for brainstorm/decision private units
remain gitignored under the interim `legacy-pre-034` profile (R18); only public metadata appears in INDEX.

### Migration cutover checklist (R27/R28)

Atomic release train (031 + 032 + 033) cutover gates:

1. Acquire migration lock; halt deliver/feedback append.
2. Run `planning_migrate.py write` then mandatory `--verify`.
3. Run `scripts/relief-acceptance-check.py` (derived INDEX status vs deliver state).
4. Flip `planningDir` to `docs/planning`; regenerate planning INDEX + legacy projections.
5. Run `scripts/planning_legacy_projection.py` to emit legacy `GAP-BACKLOG.md` + `INDEX.md` shims.
6. Run `scripts/copy-to-core.py` then `python3 -m sw generate --all` + emitter freshness fixtures (R25).

**Kill-criteria / falsification (R28):** if PRD 032/033 slip past the release threshold or the reconciler
misses the accuracy floor on the relief fixture corpus, fall back to shim + legacy layout; R10 supersession
edges recorded in `.cursor/planning-migration-supersession-map.json` are **reversible** via `--rollback`.

### Gaps as first-class units (R3)

Gap artifacts are planning units with `type: gap` (folder + frontmatter) on file-backend, or native `sw:gap`
provider issues under **issue-store** (PRD 045 R21). They render as rows in the **single generated unified INDEX** — not a separate gap-only index. Legacy
`docs/prds/GAP-BACKLOG.md` is a **write-through projection** from gap issues when issue-store is active (PRD
045 R72) or a compatibility projection until consumers migrate (R27).

### Issue-store separate-project write guards (PRD 057 R1–R3)

Under issue-store `separate-project` (`planning.store.storeLocation.mode`), the code repo is no longer the
authoritative surface for derived/generated planning artifacts — the shared predicate
`issue_store_separate_project(root)` (`scripts/planning_migrate_issue_store.py`, delegating to
`planning_artifact_handle.issue_store_separate_project_effective`) gates every write below to skip the tracked
local file and project to the authoritative store (or a gitignored cache) instead. `same-repo` deployments are
unaffected — local writes are retained exactly as before this guard existed.

| Artifact | `same-repo` / non-issue-store | issue-store `separate-project` |
|----------|-------------------------------|----------------------------------|
| `docs/prds/GAP-BACKLOG.md` | local write-through projection (R1) | write-through to the issue store only; local write skipped (sunset stub once no open gaps remain) |
| `docs/prds/INDEX.md` (spec-seed) | `wave_spec_seed.ensure_redacted_index` writes it (R2) | skipped — deliver run-entry materialize + the issue store supply task content |
| `docs/prds/INDEX.md` / `INDEX-archive.md` / `SUPERSEDED.md` / legacy projection (reconcile) | `planning_reconcile.reconcile_core` writes all four (R3) | none written; derived map projects to the store via `planning_index_issue.project_derived_map` (PRD 056 R8), additionally cached at the gitignored `.cursor/hooks/state/planning-index-derived.json` when the cutover `derived` region authority is issue |

The two-track mechanical allowlist (see `core/rules/sw-git-conventions.mdc` **Two-track doc edits**) is
clarified accordingly: under issue-store authority the mechanical write projects to the store rather than a
tracked local file.

### Scheduler park state (PRD 057 R16, R28)

The scheduler frontier skips units that cannot run and can **park** units out of scheduling:

- **`sw:parked` label** — under issue-store, a unit carrying this provider-native label is dropped from the
  frontier so legacy migrated units no longer stall `next` (R16, D4).
- **`.cursor/planning-parked.json`** — a local, backend-neutral, git-ignored park registry
  (`unit-id → {reason, actor, at}`) written only on an explicit `planning-graph.py park`/`unpark`. When
  empty, the file-store scheduling path is unchanged (R23). Parking is authorized only for actors in
  `planning.scheduler.parkAllowlist` and requires a reason (fail-closed).
- An empty post-filter frontier yields an explicit `scheduler-exhausted` scheduler halt and an
  `over-parked-frontier` `planning-doctor.py` drift finding — never a silent empty result.

## Naming conventions

| Artifact | Path pattern | Written by | Frozen |
|----------|--------------|------------|--------|
| Brainstorm requirements | `docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md` | `/sw-brainstorm` | `/sw-freeze` |
| Brainstorm amendment | `docs/brainstorms/...-requirements.amendments/A<k>-<short>.md` | manual / future | `/sw-freeze` |
| PRD | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` | `/sw-prd` | `/sw-freeze` |
| Task list | `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md` | `/sw-tasks` | `/sw-freeze` |
| PRD amendment | `docs/prds/<n>-<slug>/amendments/A<k>-<short>.md` | `/sw-amend` | `/sw-freeze` |
| Decision record | `docs/decisions/<n>-<slug>.md` | `/sw-prd --type decision` | `/sw-freeze` |
| Decision amendment | `docs/decisions/<n>-<slug>.amendments/A<k>-<short>.md` | `/sw-amend` | `/sw-freeze` |
| Living index | `docs/prds/INDEX.md` | `/sw-freeze`, `/sw-tasks` | never |
| Decision index | `docs/decisions/INDEX.md` | `/sw-freeze` | never |
| Completion log | `docs/prds/COMPLETION-LOG.md` | implementation workstream | never |
| Gap backlog | `docs/prds/GAP-BACKLOG.md` | issue-derived write-through projection (issue-store) or legacy reconciler | never |

### PRD numbering (`<n>`)

- Zero-padded monotonic integer (`001`, `002`, …).
- Assign by scanning `docs/prds/` for the highest existing `<n>` and incrementing.
- Collision policy: same feature re-run → new `<n>` + distinct slug; never overwrite without explicit confirmation.

### Decision record numbering (`<n>`)

- Zero-padded monotonic integer (`001`, `002`, …).
- Assign by scanning `docs/decisions/` for the highest existing `<n>` and incrementing — **separate counter from `docs/prds/`**.
- Collision policy: same topic re-run → new `<n>` + distinct slug; never overwrite without explicit confirmation.

### Slug (`<slug>`)

- Lowercase kebab-case derived from the feature topic (e.g. `doc-pipeline`, `user-auth`).
- Must be filesystem-safe; no spaces.

### Amendment naming (`A<k>-<short>`)

- `<k>` is a monotonic integer within the parent (`A1`, `A2`, …).
- `<short>` is a brief kebab-case descriptor (e.g. `A1-fail-closed-enforcement-point`).

## Frontmatter contracts

### Brainstorm / PRD / task list (pre-freeze)

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>
origin: brainstorm|request|issue                    # provenance (R1 — tier-conditioned)
brainstorm: docs/brainstorms/YYYY-MM-DD-<topic>-requirements.md   # Full-tier PRD only (R52)
prd: docs/prds/<n>-<slug>/<n>-prd-<slug>.md                      # brainstorm forward ref (R53); list when multiple
issue: <issue-or-defect-ref>                        # Patch-tier (origin: issue) — issue #, key, or gap unit id
---
```

- **`origin:`** — typed provenance for how the PRD was authored (PRD 089 R1). Allowed values:
  `brainstorm`, `request`, `issue`. **Full-tier** PRDs require `origin: brainstorm` (implicit when absent).
  **Standard-tier** PRDs default to `request` when absent. **Patch-tier** (Quick triage) PRDs require
  `origin: issue` plus a resolvable issue/defect reference.
- **`brainstorm:`** (canonical) — repo-relative path to the source brainstorm. Required on every **Full-tier** PRD
  at draft time (`/sw-prd` writes it; `/sw-freeze` + `scripts/doc-link-check.py` verify it). Legacy alias:
  `source_brainstorm:` (accepted by the gate only; new PRDs MUST use `brainstorm:`).
- **`prd:`** — repo-relative path (or YAML list) from a **writable** brainstorm back to derived PRD(s). Written
  when the PRD is created or frozen (`/sw-prd` / `/sw-freeze`); skipped when the brainstorm is already frozen
  (PRD `brainstorm:` remains authoritative).
- **`issue:`** / **`defect:`** / **`planningIssue:`** — resolvable issue number, provider key, or gap unit id
  when `origin: issue` (Patch-tier). `planningIssues:` list form is also accepted.

### Frozen artifact

```yaml
---
date: YYYY-MM-DD
topic: <kebab-topic>          # PRD/task only
frozen: true
frozen_at: YYYY-MM-DD
---
```

### Amendment

```yaml
---
date: YYYY-MM-DD
amends: <parent-path>
frozen: true
frozen_at: YYYY-MM-DD
supersedes: [R<n>, ...]       # optional
retracts: [R<n>, ...]         # optional
---
```

Amendment body is **delta-only** — parent file is never edited.

## Command read/write map

| Command | Reads | Writes |
|---------|-------|--------|
| `/sw-triage` | user input, file list | tier decision (no files) |
| `/sw-brainstorm` | user dialogue | `docs/brainstorms/...-requirements.md` |
| `/sw-prd` | brainstorm (Full) or triaged request (Standard) | `docs/prds/<n>-<slug>/<n>-prd-<slug>.md` |
| `/sw-prd --type decision` | optional brainstorm; up-front cross-cutting decision | `docs/decisions/<n>-<slug>.md` |
| `/sw-doc-review` | PRD or decision-record draft | in-place edits (pre-freeze only) |
| `/sw-freeze` | target artifact | `frozen: true` frontmatter; `docs/prds/INDEX.md` or `docs/decisions/INDEX.md` entry |
| `/sw-amend` | frozen parent PRD | `docs/prds/<n>-<slug>/amendments/A<k>-<short>.md` |
| `/sw-tasks` | frozen PRD + union | `docs/prds/<n>-<slug>/tasks-<n>-<slug>.md`, `INDEX.md` |
| `/sw-doc` | tier from triage | delegates to above |

### Deliver state canonicalization (R28, R20)

Authoritative deliver run-state lives under `.cursor/sw-deliver-runs/<runId>/state.json`
(`wave_run_paths.state_path`). The root `index.json` carries discovery fields only (`runId`, `target`,
`taskList`, `verdict`, `statePath`, `lockKeyDigest`) — never the exclusion primitive.

Run-scoped path accessors (`wave_run_paths.runs_root`, `plan_path`, `state_path`, etc.) anchor at
`wave_state.path_normalize_anchor` — the shared primary repo root via `git-common-dir` when git is present.
When `root` is not a git tree (unit harness fixtures only), anchoring soft-fails to `root.resolve()` so
temp fixture trees can mint run ids without forking `.cursor/sw-deliver-runs/`. Production deliver paths
still fail closed through `canonical_repo_root` where git presence is mandatory.

**Primary ↔ orchestrator mirror skew (PRD 049/068/069):** `wave_state.sync_canonical_state_read` compares
repo-root primary state to any orchestrator `.cursor/sw-deliver-state.<slug>.json` mirror. Mirror fresher
than primary, or skew above `CANONICAL_STATE_SKEW_SECONDS` (300s), fails closed
(`deliver:canonical-state-desync`). Repair with `wave_state` `state repair-mirror` / 
`ensure_canonical_state_synced` (auto-repair before terminal/agent steps). Drive `deliver-loop` from the
orchestrator worktree cwd so hang-desync checks see `orchestratorWorktree.path == root`.

Legacy slug-scoped files (`.cursor/sw-deliver-state.<slug>.json`, `.cursor/sw-deliver-<slug>.lock`) remain
enumerable for `list` / `resume` until adopted. Orchestrator and phase worktrees read and write through
`wave_state.resolve_state_path()` / `scoped_paths()` at the git toplevel — never a second authoritative
copy under `.sw-worktrees/**/.cursor/`. `wave_compound.py record-premerge` and
`cleanup_lib.resolve_deliver_state()` use the same resolver.

Pre-resync backups land beside the materialized destination as `*.pre-resync.bak`. Planning query cache
state: `.cursor/hooks/state/planning-query-cache.json`.

### Deliver `target` shapes + cleanup reads (PRD 094 R10–R11/R15)

Run-scoped and legacy slug-scoped deliver state carry the integration/feature branch under `target` in
**either** shape — readers must not assume an object:

| Shape | Example | Resolver |
| --- | --- | --- |
| String branch | `"target": "feat/<slug>"` | `wave_state.target_branch_from_state` |
| Object branch | `"target": {"type": "feat", "slug": "<slug>", "branch": "feat/<slug>"}` | same helper (`branch` field) |

`cleanup_lib.resolve_deliver_state`, scoped-run enumeration (`enumerate_scoped_runs`), and inflight
protection route **all** target reads through `target_branch_from_state` — never ad-hoc
`.get("branch")` on a dict-only assumption. Migration breadcrumbs may carry a string `target` while
`scopedPath` points at a stale scoped file; unresolvable breadcrumb + live non-terminal verdict widens
in-flight protection fail-closed (R11/R15) — `/sw-cleanup` dry-run protects those paths instead of
enumerating with `AttributeError`.

### Absorbs serialization (issue-store, PRD 094 R1–R2/R13–R14)

Under `planning.store.backend: issue-store`, portable `absorbs:` frontmatter is **not** a second edge
store. On `put`, `planning_canonical.resolve_put_edge_projection` unions `rel: absorbs` edges into the
fenced `sw-edges` block (preserving existing edges and native link projections). On `get`, parsers read
`sw-edges` **before** structural-key strip; the body fence is authoritative over label projection on
conflict. Normative block shape and hash rules: `core/sw-reference/canonical-serialization.md`
(`sw-edges` section). Gap-capture absorb linkage (`planning_gap_capture.record_absorb_linkage`) uses the
same merge path — PRD-side absorbs put must not drop native links.

### PRD 324 greenfield init surfaces (R1–R14, D1–D3)

Greenfield credential UX, consent-gated CI stub, curated profile, and configuration discoverability.
Runtime modules mirrored under `core/scripts/` (`core-scripts-parity` when touched):

| Module | Role | Regression |
| --- | --- | --- |
| `scripts/init_credential_migration.py` | Ordered credential checklist + named `tokenEnv` branch | `test_init_credential_checklist.py` |
| `scripts/credentials-doctor.py` / `scripts/credentials/checklist.py` | Checklist-aligned doctor verdicts | `test_credential_checklist_doctor.py` |
| `scripts/init_ci_stub.py` | Consent-gated CI stub `plan` / `apply --confirm` | `test_init_ci_stub.py` |
| `scripts/wave_preflight.py` | CI-presence scan for init findings | `test_init_ci_stub_preflight_integration.py` |
| `scripts/init_profile_report.py` | Curated greenfield profile single source | `test_init_profile_report.py` |
| `scripts/init_posture_defaults.py` | Greenfield posture write-draft patch | `test_init_default_seeds.py` |
| `scripts/sw-configure.py` | `ci-stub` subcommand + consolidated findings | init suite |
| `scripts/doctor.py` | Consent-gated profile completeness refresh | `test_init_profile_report.py` |

Golden template: `core/sw-reference/templates/ci-stub-pull-request.yml` (see **Golden templates** below).

Operator on-ramp: `docs/guides/configuration.md` **Greenfield on-ramp**;
`core/commands/sw-init.md` (credential checklist + CI stub).

**Absorb acceptance map** (source gap → requirement cluster):

| Gap | R-IDs | Acceptance |
| --- | --- | --- |
| `gap-339-redesign-greenfield-credential-setup-ux-investig` | R1–R4 | Single ordered checklist; named `tokenEnv` under multi-account risk; no forced `.env`; broker-only resolution |
| `gap-340-seed-consent-gated-pr-ci-stub-from-sw-init-when-` | R5–R8 | `ci-stub plan` read-only; `apply --confirm` consent gate; decline recorded; unrestricted `pull_request` stub |
| `gap-341-improve-sw-init-coverage-defaults-and-config-dis` | R9–R12 | Curated profile single-sourced; present/defaulted/unset classification; example-config link; consent-gated refresh |

PRD `sw-edges` `absorbs` targets above must each resolve to exactly one open gap unit at delivery close
(`planning_store_facade` numeric absorb parity).

### PRD 278 closeout surfaces (R9, R11, D1, D3)

Deliver/ship closeout hardening modules and their `core/scripts/` mirrors (required planning gate
`core-scripts-parity` when touched):

| Module | Role | Regression |
| --- | --- | --- |
| `scripts/phase_ship_hygiene.py` | Safe auto-repair for phase-ship hygiene halts | `test_phase_ship_hygiene_autorepair.py` |
| `scripts/gap-check-gate.py` | Gap-check gate + hygiene auto-repair hook | same suite |
| `scripts/wave_deliver.py` / `wave_deliver_loop.py` | Tasks-currency auto-heal | same suite |
| `scripts/wave_terminal.py` | PR test-plan manifest mirror | same suite |
| `scripts/wave_run_adopt.py` | Prefer run-scoped plan; lock/CAS + content-hash | `test_wave_run_adopt_prefer_run_scoped.py` |
| `scripts/planning_store_facade.py` | Numeric absorb → exactly-one open gap | `test_numeric_absorb_closeout.py` |

**Absorb acceptance map** (source issue → requirement cluster):

| Issue | R-IDs | Acceptance |
| --- | --- | --- |
| #730 | R1–R2 | Hygiene auto-repair without operator file surgery; forged gap-check refused; frozen-ledger mutation refused |
| #731 | R3–R5 | Prefer run-scoped plan under foreign global `planHashMismatch`; concurrent lock/CAS |
| #739 | R6–R8 | Numeric absorb resolves to exactly one eligible open gap; 0/N>1/provider fault → not-ready |

**Decision stance (D1):** PRD 278 is a focused closeout-hardening PRD — two-PRD packaging; no mega-PRD
delivery bundling unrelated surfaces. **Decision stance (D3):** PRD 278 absorbs #731 dogfood closeout; do
not amend PRD 276 for the same behavior.

Operator command detail: `core/commands/sw-deliver.md` **Closeout hardening**;
`core/commands/sw-ship.md` **Phase-ship hygiene floors**.

### PRD 279 write-binding surfaces (R13, R17, D1, D3)

Per-repo memory write binding (absorb #733). Operator bind-before-sync guidance lives on
`core/commands/sw-init.md` (**Bind before sync**, **Absorb acceptance map**). Runtime assert:
`scripts/memory_preflight.py` / `scripts/memory_write_binding.py`.

**Absorb acceptance map** (source issue → requirement cluster):

| Issue | R-IDs | Acceptance |
| --- | --- | --- |
| #733 | R9–R12 | Unbound sync/store refuse; marker=`in-repo` only; remote needs project; PRD 277 rule dual-home unchanged |
| #733 | R15–R16 | Typed audit on refuse; secrets omitted from refuse reasons |
| #733 | R17 | Hard cut; `/sw-init` / doctor instruct bind-before-sync; no ambient auto-migration |

**Decision stance (D1):** separate PRD from deliver closeout cluster. **Decision stance (D3):** new PRD
absorbs #733 after amendment #735 cancellation — do not amend closed PRD 277.

### Codebase Intelligence surfaces (PRD 280 R1–R17, D1–D7)

Dual-engine operator runtime for architecture health radar and domain vocabulary divergence. No new
`sw-*` slash commands — existing `/sw-prd`, `/sw-doc-review`, `/sw-retrospective`, and `/sw-status`
invoke the CLIs below.

| Surface | Canonical path | Writer | Notes |
| --- | --- | --- | --- |
| Radar artifacts | `.cursor/sw-architecture-radar/` | `scripts/architecture_radar.py` | Read-only scan output; `last.json` + per-`scanId/` dirs |
| Divergence artifacts | `.cursor/sw-vocabulary-divergence/` | `scripts/domain_vocabulary.py` | Read-only `check-divergence` summary at `last.json` |
| Shared signals | `scripts/codebase_intelligence_signals.py` | collectors (read-only git/planning reads) | Mirrored to `core/scripts/`; feeds radar + vocabulary |
| Vocabulary authority | issue-store `vocab-<slug>` units | `domain_vocabulary.py put-term` | No local `docs/` writes (D3) |

Runtime modules mirrored under `core/scripts/` (`core-scripts-parity` when touched):
`codebase_intelligence_signals.py`, `architecture_radar.py`, `domain_vocabulary.py`.

**Absorb acceptance map** (source gap → requirement cluster):

| Gap | R-IDs | Acceptance |
| --- | --- | --- |
| gap-316 | R1–R6, R12–R14 | Radar scan/explain/emit-candidates; read-only + human `--confirm` on gap emit; shared signals; status/retro hooks |
| gap-317 | R7–R11, R12, R14–R17 | Vocabulary put/get/list/check-divergence via issue-store; PRD/doc-review hooks; strictMode fail-closed; unit tests green |

**Decision stance (D1):** dual-engine architecture (radar + vocabulary) documented in
`docs/guides/workflows.md` — not a third planning surface. **Decision stance (D6):** no new slash
commands; extend existing doc/status/retro paths only.

Operator detail: `docs/guides/workflows.md` (**Codebase Intelligence**);
`core/commands/sw-status.md` (last-artifact collectors).

### Project intelligence evidence and promotion stores (PRD 332 R6, R11, R17)

Gitignored operator-local stores for measured capability rollout and dispatch compression evidence.
`TriageEvidence@v1` freshness envelopes are computed in-process from producer artifacts — they are not
written to a separate envelope directory. Invalidation is digest-bound: envelope `digest` mismatch, explicit
invalidation metadata, or expiry excludes signals from merge (`excludedStale`).

| Surface | Canonical path | Writer | Retention / invalidation |
| --- | --- | --- | --- |
| Capability registry | `.cursor/capability-promotion-registry.json` | `scripts/capability_promotion.py` | Durable `CapabilityPromotion@v1`; rollback restores prior active revision + `evidenceRef` |
| Compression dispatch log | `.cursor/compression-dispatch-evidence.jsonl` | `scripts/dispatch_prompt.py` | Append-only `CompressionEvidence@v1`; feeds N-run promotion metrics |
| Compression cache | `.cursor/hooks/state/context-compress-cache/` | `scripts/context_compress.py` | Operator-local; lossless baseline + shadow outputs |
| Radar producer artifacts | `.cursor/sw-architecture-radar/` | `scripts/architecture_radar.py` | Read-only; referenced by triage evidence producer |
| Divergence producer artifacts | `.cursor/sw-vocabulary-divergence/` | `scripts/domain_vocabulary.py` | Read-only; referenced by exploration/triage producers |
| Workflow history signal | *(derived at read time)* | `scripts/workflow_intelligence.py` | No separate envelope store — freshness validated per producer contract |

**Ownership:** triage and doc-entry paths read producer artifacts and the registry; only promotion and
dispatch modules mutate registry rows or append compression evidence. Status collectors (`status_collect.py`)
are read-only.

**Generated-reference parity:** runtime modules mirror to `core/scripts/` and distribution zipapps through
the repository build chain — do not hand-edit `dist/` or `core/scripts/` copies of
`triage_evidence.py`, `capability_promotion.py`, `triage_lib.py`, `context_compress.py`, or
`dispatch_prompt.py`.

Operator detail: `docs/guides/workflows.md` (**Evidence-backed triage and planning entry**,
**Triage evidence and measured promotion**); `docs/guides/configuration.md` (**Project intelligence —
evidence and promotion**, **Terminology parity**).

### Verify `no-baseline` evidence matrix (planning#641 / #642, PRD 094 R7/R17)

Planning issues **#641** and **#642** share one `no-baseline` verification partition
(`verify_evidence_lib.NO_BASELINE_EVIDENCE_MATRIX`, partition id `planning-641-642`). Before closing
either issue, the suite partition must return a **conclusive** verdict without a logged override —
committed baselines plus runtime harness refuse, not isolation alone.

| Planning issue | Tracking unit | Suite partition | Signal hash | Root cause | Remediation |
| --- | --- | --- | --- | --- | --- |
| #641 | verify-override follow-up (641) | `scripts/unit_tests/w4/harness_improvement.py` verify-evidence attribution cases | `3b1b69a5e7ff67fe5e52c3e4a6d6347b` | verify/gate failure without attribution baseline → `inconclusiveClass: no-baseline` | Committed baselines under `scripts/test/fixtures/verify-evidence/baselines/planning-641-642/`; pass `--restore-committed-baseline` to `verify-evidence.py` when callers omit `--baseline-*` |
| #642 | verify-override follow-up (642) | *(shared with #641 — same partition)* | *(shared)* | *(shared)* | Runtime refuse: `capture_verify_override` / `override-add` refuse live issue-store writes under harness unless `SW_ALLOW_LIVE_PLANNING_STORE=1`; static lint remains defense-in-depth |

Recurrence on an existing verify-override unit increments
`.cursor/hooks/state/verify-override-recurrence/<signature>.json` so operators see repeat signal without a
duplicate tracking unit. Operator workflow detail also lives in `docs/guides/workflows.md` (absorb
close-out + verify sections).

## Operator worktree contract (PRD 049 R1)

Single authority for which checkout owns implementation versus conductor runtime during `/sw-deliver`.

| Checkout | Path / branch | Role |
| --- | --- | --- |
| Primary | Repo root (usually `defaultBaseBranch` after orchestrator provision) | Operator shell; **must not** accumulate tracked implementation commits during a deliver run |
| Orchestrator | `.sw-worktrees/<slug>-orchestrator` → `<type>/<slug>` | Conductor loop cwd; merge queue, living-doc reconcile, terminal retro/ship |
| Phase | `.sw-worktrees/<slug>-phase-*` → `<type>/<slug>-phase-<phase-slug>` | `/sw-ship` / `/sw-execute` implementation; isolated phase branch |
| Conductor runtime | Repo-root `.cursor/` (gitignored) | Canonical deliver state, locks, run logs — **not** feature implementation |

```text
repo-root/                          primary checkout (defaultBaseBranch)
├── .cursor/                        conductor runtime (canonical; gitignored)
│   ├── sw-deliver-runs/<runId>/    per-run deliver namespace (authoritative)
│   │   ├── state.json
│   │   ├── lease.json              ← run-local lease / target-lock digest
│   │   └── phases/<phaseId>/status.json
│   ├── sw-graph-runs/<runId>/      WorkflowGraph receipts + in-flight intents (R13/R17)
│   └── sw-target-locks/            ← target-branch exclusion (R19)
└── .sw-worktrees/
    ├── <slug>-orchestrator/        conductor-loop cwd (<type>/<slug>)
    └── <slug>-phase-<phase>/       ship/execute cwd (phase branch)
```

**Invariants:**

- Repo-root `.cursor/` updates during deliver are **expected** — agents must not treat them as
  implementation artifacts to commit.
- `status.json` copy direction is **phase worktree → repo root** (mirror for collection/merge only).
  Never a general root→worktree state sync.
- Ship and execute run in the **phase worktree**; the conductor loop runs from the **orchestrator
  worktree** (mandatory provisioning — not repo root as an alternate cwd).

## Living vs frozen layers

- **Frozen:** brainstorms, PRDs, task lists, amendments — immutable after `/sw-freeze`; change only via new amendments.
- **Living:** `INDEX.md`, `COMPLETION-LOG.md` — updated as work progresses; never frozen.
- **Gap backlog:** `GAP-BACKLOG.md` — under issue-store, issue-derived write-through projection only (PRD 045 R72); file-backend legacy projection until cutover; never hand-appendable; not frozen.
- **Generated install trees:** `dist/cursor/` and `dist/claude-code/` — committed outputs of `python3 -m sw generate`; edit `core/` then regenerate (freshness gate in `scripts/test/run_emitter_fixtures.py`). Not hand-edited except via emitter changes.


## Build-chain source of truth (PRD 038)

Machine-readable map: `core/sw-reference/build-chain-sot.json` (lint: `scripts/build-chain-sot-lint.py`).

| Tree | Role | Edit where |
| --- | --- | --- |
| `scripts/` | Harness SoT — runtime entrypoints (`wave.py`, gates, tests) | Repo root only |
| `core/scripts/` | Mirrored harness (excludes `test/`, `check-frozen.py`) | Via `copy-to-core` from `scripts/` |
| `commands/`, `skills/`, `rules/`, `agents/`, `providers/` | Emittable content SoT | Repo root → `copy-to-core` → `core/` |
| `.sw/` | Operator-edited sw-reference inputs (subset) | Repo root `.sw/` |
| `core/sw-reference/` | `.sw/` sync + `coreAuthoredAllowlist` artifacts | `.sw/` or allowlisted core paths |
| `dist/cursor/`, `dist/claude-code/` | Emitter output only | `python3 -m sw generate --all` after `core/` changes |
| `scripts/test/fixtures/parity/cursor-golden.manifest` | Committed golden parity | `scripts/snapshot-tree.py` after dist changes |

**Not in repo scope:** `~/.cursor/plugins/local/shipwright/` (plugin install path). `copy-to-core` reads
repo trees only — never the install path.

**Unified sync:** after editing `scripts/` or emittable roots, run:

```bash
python3 scripts/build-chain-sync.py
```

Runs `python3 -m sw generate --all` → golden re-snapshot when `dist/` changes → `copy-to-core.py`.
`copy-to-core --force` is **fixture/CI-only** (set `SW_BUILD_CHAIN_FORCE=1` or run under CI); operator
workflows must remediate via `.sw/` instead. Last-synced provenance lives at `.sw/build-chain-last-synced.json`.

### `.sw/` sw-reference artifact inventory (PRD 071 R2, R13)

Operator-edited artifacts under `.sw/` mirror into `core/sw-reference/` via `copy-to-core` (not
`coreAuthoredAllowlist`). Edit the `.sw/` source; never hand-edit the core mirror.

| Artifact | Source authority | Emit path | Sync |
| --- | --- | --- | --- |
| `memory-provider-catalog.json` | `.sw/memory-provider-catalog.json` | `core/sw-reference/memory-provider-catalog.json` | `copy-to-core` |

Golden parity fixture: `scripts/test/fixtures/memory-provider-catalog/golden.json` (sha256 + byte
identity; refuses core-only orphans).

**Plugin installs:** `sw generate` includes the catalog in the closed `SW_REFERENCE_CLOSED_EMIT` set
so `dist/*/core/sw-reference/memory-provider-catalog.json` ships with the plugin. Hook trust loads
`.sw/memory-provider-catalog.json` when present, else falls back to that emit path; `scripts/install.py`
also seeds `.sw/` from the emit after mirror so `beforeSubmitPrompt` validates registered providers.

### Refuse + `--check` (PRD 060 R11–R13)

- `copy-to-core` refuses when `core/sw-reference/` drifted without matching `.sw/` edits — remediate in `.sw/`, then re-run sync (not `--force`).
- `python3 scripts/build-chain-sync.py --check` — parity-only; failures emit `{"remediation":"python3 scripts/build-chain-sync.py"}`.
- Ship-time drift: `scripts/ship-build-chain-check.py` before commit when build-chain paths change.

### Post-merge closure + verify override (PRD 060 R7–R9)

- Preview: `python3 scripts/planning_store.py close-delivery-units --prd-unit <id> --dry-run`
- Apply: omit `--dry-run`; JSON includes `considered`, `closed`, `skipped`, `resumeCommand` when incomplete.
- Verify override (`no-baseline`/`unattributed`): `override-add` auto-files gap via `capture_verify_override`; identical signature → `action: reused`, else `action: created`.

### Merge-boundary close-out durable state (PRD 070 R10, R19, R29; PRD 274 R16)

Machine-readable close-out artifacts live under **`.sw/deliver-closeout/`** at the repo root — **gitignored
operator-local runtime** (committed `.gitignore` covers `.sw/deliver-closeout/` and
`core/sw-reference/deliver-closeout/`). Not feature implementation; never commit closure manifests or PR
maps from this tree. Written by `scripts/deliver_closeout.py` and read by `scripts/closeout_ci.py` /
`scripts/wave_terminal.py`.

`core_content_sync` treats `deliver-closeout/` as operator-local: sync **denylists** mirror copy and
**purges** stale `core/sw-reference/deliver-closeout/` destinations so build-chain sync does not leave
untacked mirror JSON on `main`.

| Artifact | Path | Writer | Role |
| --- | --- | --- | --- |
| Close-out index | `.sw/deliver-closeout/index.json` | `deliver_closeout.py` | `byPr` / `byPrdUnit` lookup into mapping files |
| PR-to-delivery map | `.sw/deliver-closeout/pr-delivery-map/pr-<n>.json` | `wave_terminal.py` at terminal-PR create | Immutable mapping from merged PR number to delivery identity (squash/rebase/MQ safe) |
| Closure manifest | `.sw/deliver-closeout/closure-manifests/<prd-unit-id>.json` | `deliver_closeout.py` after audit-pass | Full delivery set, merge SHA, prior state, closure provenance — units linked, never deleted |
| Close marker | `.sw/deliver-closeout/close-markers/<prd-unit-id>.json` | `deliver_closeout.py` post-audit (optional) | Short-circuit idempotency; re-verified before trust; crash between audit-pass and marker leaves units re-closable |

Filenames sanitize `prd-unit-id` (`/` → `_`). Revert reopen clears markers provenance-scoped via the manifest
delivery set (`deliver_closeout.py reconcile-safety`).

### Harness test hygiene (PRD 060 R10–R15)

- Deprecated surfaces: `core/sw-reference/deprecated-surface-manifest.json` + `scripts/deprecated_surface_freshness.py --check`
- Harness roots manifest: `core/sw-reference/harness-roots-manifest.json` (explicit scan roots)
- Shared config + baseline I/O + planning-store pollution: `scripts/harness_isolation_lint.py --check`
- Verify baselines: caller-owned per-phase/run paths (not shared `.shipwright/baseline.*`).

## Capability manifest + selector (PRD 021)

Authoring lives under `core/`; the emitter propagates manifest artifacts into both dist trees.

| Artifact | Role |
| --- | --- |
| `core/sw-reference/capability-manifest.schema.json` | JSON Schema for per-capability `capability` frontmatter |
| `core/sw-reference/capability-manifest.md` | Frontmatter, precedence, trust-boundary contract |
| `core/sw-reference/capability-index.json` | Emitter-generated aggregate (committed; freshness-gated) |
| `core/sw-reference/signal-context.schema.json` | Versioned selector inputs |
| `scripts/capability-select.py` | Deterministic selector primitive |
| `scripts/capability-manifest-lint.py` | Author-time precedence/conflict/anti-spoof lint |
| `scripts/doc-review-select.py` / `scripts/code-review-select.py` | Selection-family wrappers |

**Freshness:** `scripts/test/run_emitter_fixtures.py` fails when `capability-index.json` or dist trees drift
from current frontmatter. Regenerate after manifest edits: `python3 -m sw generate --all`.

**Pre-selection:** `wave_preflight` / selector entrypoints fail closed when the runtime index does not
reproduce from current sources.

## Config keys

`workflow.config.json`:

- `planningDir`: `"docs/planning"` — canonical planning-unit tree (post-cutover; pre-cutover may remain
  `docs/prds` until migration `--verify` passes).
- `prdsDir`: `"docs/prds"` — legacy PRD directory alias (defaults to `docs/prds` until `planningDir` cutover).
- `tasksDir`: `"docs/prds"` — frozen task-list alias (defaults to `prdsDir` until cutover).
- `decisionsDir`: `"docs/decisions"` — decision-record root (flat files + sibling `.amendments/` dirs).
- `delegation.mode`: `bind-only` | `heuristic` | `default` — selects delegate-by-default gate behavior
  (PRD 017; default `bind-only` until Phase-2 live acceptance, else `default`).
- `communication.routing` — `commands`, `skills`, and `agents` maps for caveman intensity; seeded from
  `core/sw-reference/communication-routing.defaults.json` via `/sw-setup`.
- `models.routing` — command/skill/agent model tier maps; resolve at dispatch via `resolve-model-tier.py`.

### Dispatch preflight artifacts (PRD 017 + A2 R38/R39)

Per-delegated-Task binding is recorded immediately before spawn:

```bash
python3 scripts/wave.py dispatch preflight --dispatch-id <id> --agent <agent-id> --command <sw-*> [--skill <name>]
python3 scripts/dispatch-check.py --agent <id> --command <sw-*> --parent-model <concrete-id> [--dispatch-id <id>]
```

**Keyed store (R38):** one JSON record per dispatch under
`.cursor/hooks/state/task-dispatch-preflight/<dispatch-id>.json` (legacy single-file
`task-dispatch-preflight.json` read fallback when exactly one unconsumed record exists). Each record carries
the full binding payload, `expiresAt` (TTL), and `consumedAt` after the hook consumes **only** the matching
`dispatchId`. Parallel persona panels require **N unique ids** — consuming record `A` leaves record `B` valid.

Model tier uses R39b precedence via `resolve-model-tier.py` / `dispatch-check.py` (explicit agent routing →
`--command` → `--agent`). The `preToolUse` hook (`core/hooks/before_task_dispatch.py`) denies bound `Task`
spawns lacking a fresh, matching record. Operator-facing deliver resume: `/sw-deliver run <frozen-task-list-path>`
— not raw `bash deliver-loop`.

### Pre-work memory search (PRD 019)

Work-performing commands (`/sw-execute`, `/sw-debug`, `/sw-prd`, `/sw-brainstorm`, `/sw-amend`,
`/sw-review`, `/sw-stabilize`) MUST run a scoped `memory-preflight` search before the first substantive
mutation. Record the breadcrumb mechanically:

```bash
python3 scripts/wave.py memory prework record --surface sw-execute --scope "<paths>" [--hit-count N]
```

Artifacts:

| Path | Role |
| --- | --- |
| `.cursor/hooks/state/memory-prework-search.json` | Redacted per-surface search record (or `memory:offline` / `memory:none`) |
| `.cursor/sw-deliver-runs/run.<slug>.log` | Per-deliver-run append-only audit breadcrumb (PRD 050 R4) |
| `.cursor/doc-review-runs/<dispatch-id>.json` | Per-dispatch token-estimate telemetry for `/sw-doc-review` persona panels (PRD 058 R28). **Cache-only / non-authoritative** (PRD 341) — cannot authorize open/complete; live body witnesses use stripped-hash exclusion from freeze inputs. |

The `preToolUse` hook (`core/hooks/before_task_dispatch.py`) denies the first file-mutating tool call
when no fresh record exists. Delegated work sub-agents inherit the obligation per
`rules/sw-subagent-dispatch.mdc` (perform-or-be-handed-redacted-result). Provider outage degrades open
via probe-gated `memory:offline` — never blocks work.

## Kernel classification, guidelines, and two-tier plan persistence (PRD 022)

| Artifact | Path / field | Writer | Role |
| --- | --- | --- | --- |
| Kernel classification | `core/sw-reference/kernel-classification.{json,md}` | docs/emitter | read-only at runtime |
| Guidelines | `core/sw-reference/guidelines.{schema.json,md,json}` | docs/emitter | read-only at runtime |
| Phase step plan | `.cursor/sw-deliver-runs/<runId>/phases/<phaseId>/phase-step-plan.json` | phase executor (`ship_phase_steps.py` / `plan_persist.py`) | per-phase run dir |
| Wave batching plan | `waveBatchingPlan` on run-scoped `state.json` | conductor only (`plan_persist.py`; `SW_CALLER_ROLE=conductor`) | shared run-state |
| Two-tier lifecycle | `twoTierLifecycle` on shared run-state | conductor | `wave-validated` → `phase-plan-pending` → `phase-plan-validated` |
| Plan validation | `python3 scripts/wave.py plan validate` → `scripts/wave_plan_validate.py` | mechanical gate | proposals only |

**Wave authority (single source of truth):** the conductor deliver loop reads `waveBatchingPlan` from shared
run-state when present (`wave_deliver_loop.effective_wave_plan`); otherwise it falls back to the frozen
`.cursor/sw-deliver-plan.json` waves. Phase execution reads `phase-step-plan.json` in the phase run dir as the
sole step authority (`ship_phase_steps.authoritative_chain`); canonical `SHIP_CHAIN` is the fallback only.

**Single-writer guard:** `save_deliver_state` and `plan_persist.guarded-state-save` refuse writes when
`SW_CALLER_ROLE=phase` (exit 20). Phase-scoped artifacts (`ship-steps.json`, `phase-step-plan.json`,
`status.json`) are written only under the phase slug's run dir.

**Invariants home:** `core/sw-reference/kernel-classification.md` — cross-link; do not duplicate the kernel
enumeration elsewhere.
### Three-tier plan lifecycle (PRD 053 — wave / phase / execute)

| Tier | Artifact | Proposer | Validate | Resume owner |
| --- | --- | --- | --- | --- |
| Wave | `waveBatchingPlan` on shared run-state | Conductor at wave entry | `wave.py plan validate --tier wave` | Conductor |
| Phase | `phase-step-plan.json` | Phase executor at phase entry | `wave.py plan validate --tier phase` | Phase executor (`ship_phase_steps.py`) |
| Execute | `execute-step-plan.json` | Phase executor before fan-out | `wave.py plan validate --tier execute` | Phase executor (`execute_plan.py`) |

Phase entry lifecycle (ordered): `phase-step-plan` validate → `execute-step-plan` validate (when
`execute.enabled`) → execute fan-out → per-ref integrate → resume phase chain at `sw-verify`.

| Artifact | Path | Writer | Role |
| --- | --- | --- | --- |
| Execute step plan | `.cursor/sw-deliver-runs/<runId>/phases/<phaseId>/execute-step-plan.json` | `execute_plan.py` / `wave_plan_validate.py` | Closed-world DAG of sub-task refs, batches, edges |
| Integrate journal | `.cursor/sw-deliver-runs/<runId>/phases/<phaseId>/integrate-journal.json` | `execute_integrate.py` | Append-only per-ref merge audit (separate from conductor `mergeQueue` / `mergeJournal`) |
| Per-ref execute status | `.cursor/sw-execute-runs/<sanitized-ref>/status.json` | `execute_task_status.py` | TDD + refactor rollup per sub-task ref |
| Supervised plan confirm | `.cursor/sw-deliver-runs/<runId>/phases/<phaseId>/execute-supervised-confirmed.json` | `execute_ship.py` | One halt marker per phase under `deliver.autonomy.mode: supervised` |

**Sub-branch naming:** `feat/<slug>-phase-<phase-slug>--task-<ref>` (sanitized ref; `countsTowardCeiling: false`).
Provisioned by `execute_plan.py provision-sub-branch`; torn down after successful integrate.

**Integrate vs merge-queue boundary:** `execute_integrate.py` (phase-executor scoped, single-flight per phase
worktree) merges sub-branch tips into the phase branch. Conductor `wave_merge.py` phase→target merge is
unchanged — execute integrate never enqueues on the conductor merge queue.

**`benefitMetric.decomposed.stepPlanAdaptivity` execute fields** (numeric only):

| Field | Type | Notes |
| --- | --- | --- |
| `refsParallelized` | int | Batches with width > 1 |
| `runtimeExpansions` | int | Synthetic child refs from runtime expansion |
| `skippedRefs` | int | Terminal `skipped` refs |
| `parallelBatchWidth` | int | Max batch width in execute plan |
| `refCount` | int | Total refs in execute plan |

## Deliver pilot run records (PRD 023)

| Artifact | Path / field | Writer | Role |
| --- | --- | --- | --- |
| Per-phase dispatch decisions | `.cursor/sw-deliver-runs/<runId>/phases/<phaseId>/dispatch-decisions.json` | phase executor | intra-phase fan-out audit (R17) |
| Intra-phase fan-out snapshot | `intraPhaseFanOut` on phase status / `phases.<id>` | phase executor | latest partition + worker count + cap state (R15–R17) |
| Per-phase benefit metric | `benefitMetric` on phase status / shared run-state `phases.<id>` | phase executor at terminal | R31 capture (numeric/enumerated only) |
| Run-level benefit rollup | `benefitMetric` on run-scoped `state.json` | conductor at terminal | paired-run aggregation input |
| Benefit report | `python3 scripts/wave.py plan benefit-report --pairs <path>` → `scripts/wave_plan_benefit.py` | operator / soak protocol | R31 decision rule (fail-closed to `canonical`) |

### `benefitMetric` object (R31 — numeric/enumerated only)

Recorded on per-phase status and optionally rolled up on shared deliver run-state. No transcripts, file
contents, secrets, or free-text blobs.

```json
{
  "planPolicy": "canonical",
  "kernelVerdict": {
    "terminalPhaseStatuses": ["green-merged"],
    "gateOutcome": "green",
    "mergeReadyCount": 1
  },
  "canonicalStepSet": ["sw-tmp-init", "sw-execute", "..."],
  "executedStepSet": ["sw-tmp-init", "sw-execute", "..."],
  "stepsSkippedWithoutRework": 0,
  "stabilizeReentries": [{"step": "sw-verify", "attributed": true}],
  "escapedDefectSignal": "none",
  "phaseWallClockMs": 120000,
  "decomposed": {
    "stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0},
    "waveSchedule": {"wallClockMs": 0},
    "intraPhase": {"wallClockMs": 0}
  }
}
```

| Field | Type | Notes |
| --- | --- | --- |
| `planPolicy` | `canonical` \| `proposed` | policy under measurement |
| `kernelVerdict` | object | equivalence tuple for stratum grouping |
| `canonicalStepSet` | string[] | baseline chain for the phase |
| `executedStepSet` | string[] | steps actually advanced |
| `stepsSkippedWithoutRework` | int | canonical − executed minus attributed stabilize re-entries |
| `stabilizeReentries` | `{step, attributed: bool}[]` | attributed re-entry zeroes credit for that skipped step |
| `escapedDefectSignal` | enum | `none`, `terminal_pr_ci_red`, `post_merge_stabilize`, `post_merge_revert` |
| `phaseWallClockMs` | int | phase wall-clock; secondary guard vs paired canonical |
| `decomposed` | object | category breakdown (`stepPlanAdaptivity`, `waveSchedule`, `intraPhase`) |

**Decision rule:** `wave.py plan benefit-report` compares paired `canonical` vs `proposed` metrics at
identical `kernelVerdict`. Primary signal: `stepsSkippedWithoutRework` net-of-rework must be strictly
positive per pair; wall-clock must not regress beyond ε at equal verdict; minimum N pairs per stratum.
Insufficient N or non-positive benefit **fails closed** to `canonical`.
### Deliver autonomy artifacts (PRD 063)

| Artifact | Role |
| --- | --- |
| `shipChain` on phase `status.json` | Consumability gate — `complete` only post canonical ship chain (R1) |
| Inline dispatch lease | Per-phase lease record; duplicate `dispatch-ship` refused while live (R7) |
| `driverHeartbeatAt` on deliver state | Re-adopt gate for `/sw-deliver run` (R6) |
| `livingDocDeferral` on deliver state | Lock-miss deferral payload + `resumeCommand` (R12) |
| Pre-PR smoke | `scripts/ship_pre_pr_smoke.py` before `sw-pr` in phase mode (R4) |

### `dispatch-decisions.json` (R17)

Append-only per-phase audit log written by `scripts/intra_phase_dispatch.py`.

```json
{
  "version": 1,
  "decisions": [{
    "timestamp": "2026-06-27T08:00:00Z",
    "signals": {"fileCount": 4, "derivedTags": ["docs"], "conductorMode": "inline", "phaseType": "ship"},
    "declaredPartition": [{"files": ["docs/guides/configuration.md"], "workerId": "w1"}],
    "chosenParallelism": {"workers": 1, "serialized": false},
    "degradeReason": null
  }]
}
```

### `intraPhaseFanOut` snapshot (R15–R17)

Latest validated fan-out state on phase status (not a substitute for the append-only decision log):

```json
{
  "activeWorkers": 1,
  "globalCap": 4,
  "parallelBudget": 2,
  "partitionSummary": ["docs/guides/configuration.md"]
}
```

### Phase terminal `status.json` (PRD 036 R13–R17)

Written only by `scripts/ship-phase-status.py` (or driver `canonical-reemit`). Key fields:

| Field | Role |
| --- | --- |
| `verdict` | `merge-ready-green` or `blocked` |
| `head` | Full 40-char phase branch tip SHA |
| `gate` | Diagnostic gate snapshot (not authorization) |
| `provenanceMarker` | SHA256 over canonical fields (excludes `writtenAt`) |
| `shipSteps` | Optional embedded step snapshot |
| `writtenAt` | UTC emission timestamp |

Per-head ship leases live under `.cursor/sw-deliver-locks/<hash>-<phase>.lock` (PRD 036 R2).

Recovery command: `/sw-ship --phase-mode --from <terminal-step>`; auto re-emit counter on deliver state:
`statusReemitAttempts`.

## Episodic orchestrator scratch (PRD 024 TR6 / R37)

Debug and feedback orchestrators use **ephemeral, per-invocation** namespaced scratch — not deliver-style
durable run state. Artifacts are abandoned on terminal halt; there is no crash-resume checkpoint and no
writes to deliver-scoped paths.

| Path | Role |
| --- | --- |
| `.cursor/sw-debug-runs/<runId>/run-meta.json` | Episodic debug run metadata (`crashResume: false`) |
| `.cursor/sw-debug-runs/<runId>/signal_context.json` | Entry snapshot before `plan validate` (TR3) |
| `.cursor/sw-debug-runs/<runId>/episodic-run-summary.json` | R21 surfacing (chosen plan, capability set, rejections) |
| `.cursor/sw-feedback-runs/<runId>/` | Same layout for `/sw-feedback` |
| `.cursor/sw-doc-runs/<runId>/signal_context.json` | Doc entry snapshot (durable handoff remains docs-worktree scoped) |

Mechanical primitives:

```bash
python3 scripts/orchestrator_signal_context.py . capture --orchestrator-type debug --run-id <id> --input '{"signal_type":"error"}'
python3 scripts/orchestrator_run.py . provision --orchestrator-type debug --run-id <id>
python3 scripts/orchestrator_run.py . teardown --orchestrator-type debug --run-id <id>
```

Cross-orchestrator isolation: episodic runs refuse writes under `.cursor/sw-deliver-state*`,
`.cursor/sw-deliver-runs/`, and other deliver-scoped paths (`scripts/orchestrator_run.py assert-write`).

## Per-task execute status (PRD 039 R2)

Per-task TDD + refactor rollup lives under `.cursor/sw-execute-runs/<sanitized-task-ref>/status.json`
(written by `scripts/execute_task_status.py`). Schema reference:
`core/skills/execute-discipline/references/refactor-status-schema.json`.

```json
{
  "taskRef": "2.1",
  "refactor": {
    "ran": true,
    "skipped": false,
    "skipReason": "",
    "signalRef": "/tmp/sw-quality.signal.json",
    "verdict": "clean",
    "metricDelta": { "coupling": "unavailable", "cohesion": "unavailable", "complexity": 0.0, "churn": 0 }
  }
}
```

| Field | Role |
| --- | --- |
| `refactor.ran` | Step executed (structural edit optional when signal is `none`/`clean`) |
| `refactor.skipped` | Operational skip — requires non-empty `skipReason` |
| `refactor.signalRef` | Path to quality harness signal consumed by the step |
| `refactor.verdict` | `clean`, `advise`, `poor`, `regressed`, `skipped`, or `none` |
| `refactor.metricDelta` | Delta vs pre-refactor harness snapshot; anti-gaming bar when hints non-empty |

Gate: `python3 scripts/refactor-gate.py --status <path> [--signal <signal-path>]`.


## Sizing & Split Suggestions (PRD 040)

Draft-only advisory block rendered by `python3 scripts/phase_sizing.py advisory <task-list>` into unfrozen
task lists. The block uses the heading `## Sizing & Split Suggestions`, carries structural sizing/split
guidance and a cost estimate, and **must be stripped before freeze** (`python3 scripts/phase_sizing.py
strip-advisory --inplace <path>`). Frozen artifacts reject the block via `phase_sizing.py check-frozen`,
`scripts/spec-rigor-check.py`, and `scripts/check_frozen_scan.py`.

| Artifact | Role |
| --- | --- |
| `core/sw-reference/phase-sizing.schema.json` | JSON Schema for deterministic sizing scorer output |
| `scripts/phase_sizing.py` | Scorer, split suggestion, advisory render/strip commands |

## Python entrypoint model (R32)

Harness scripts live under `scripts/*.py` and execute via `python3 scripts/<name>.py`.
The build chain is `python3 scripts/copy-to-core.py` → `python3 -m sw generate --all` with golden parity under `scripts/test/fixtures/parity/`.

### Consumer scripts resolution (PRD 078 R11, KD12)

| Context | `scripts/` tree | Consumer façade |
| --- | --- | --- |
| **Shipwright harness** (this repo) | Repo-root `scripts/` — harness SoT; edit here | N/A — full tree present |
| **Consumer project repo** | **None** — zero-footprint; no `scripts/sw` emit | Retired — `/sw-init` never creates forwarders |
| **Runtime entry (consumer)** | Resolved via plugin/bootstrap only | `python3 scripts/sw_bootstrap.py <helper> [-- ARGS]` |

**Precedence** (`sw_scripts_resolve.py`): self-repo working-tree → validated `SHIPWRIGHT_SCRIPTS` → plugin
install (local, then marketplace/cache). Operator docs and guides present bootstrap argv as the primary
copy-paste path; absolute plugin paths are troubleshooting-only.

Harness `scripts/` under this repo is **not** copied into consumer repos — it mirrors to `core/scripts/` and
ships in plugin installs under `dist/*/scripts/`. Consumers invoke helpers through bootstrap, not a repo-root
façade tree.

## Self-improving loop stores (PRD 041)

| Store | Path | Writer | Semantics |
| --- | --- | --- | --- |
| Meta inbox draft | `.cursor/sw-meta-inbox/{signalId}.json` | `scripts/sw_state_write.py` (`sw_state_write_lib`) | Redacted draft; schema `core/sw-reference/meta-inbox-draft.schema.json`; per-checkout projection |
| Failure signatures | `${GIT_DIR}/shipwright-failure-signatures.json` | `scripts/sw_state_write.py` | Shared-git-dir authority; append-only upsert via `failure_signature_record_lib`; schema `core/sw-reference/failure-signature.schema.json` |
| Loop health | `${GIT_DIR}/shipwright-loop-health.json` | `scripts/sw_state_write.py` | Shared-git-dir authority; diagnostic-only (`gating: false`); schema `core/sw-reference/loop-health.schema.json` |
| Root-cause records | `${GIT_DIR}/shipwright-root-cause-records.json` | `scripts/sw_state_write.py` | Shared-git-dir authority; escalation via `failure_signature_escalate_lib`; schema `core/sw-reference/root-cause-record.schema.json` |
| Anomaly pattern catalog | `core/sw-reference/anomaly-patterns.json` | repo-curated (read-only at runtime) | Recognition/annotation only; consumed by `rca-core` + read-only `/sw-debug` |

All writes pass through `memory_redact.redact` and schema validation; direct `write_json` to these paths is forbidden.
`index-merge` on `failure-signatures` merges linked worktree stores into the shared-git-dir authority.



## Primary-checkout guard convention (PRD 050 D6)

Scripts that mutate git state against the shared primary checkout MUST:

1. Resolve working root from `Path.cwd()` (never `__file__`-derived paths).
2. Call `scripts/primary_checkout_guard.py` `guard()` / `enforce_guard()` with `(resolved_root, artifact_branch)` before any checkout/commit.
3. Acquire `primary-checkout.lock` under `.cursor/sw-deliver-runs/` before mutating primary checkout HEAD.

## Issue-store migration journal (PRD 044 Phase 1)

Bidirectional file ⇄ issue migration records durable per-artifact state under hook ephemeral state:

| Path | Writer | Semantics |
| --- | --- | --- |
| `.cursor/hooks/state/issue-store-migration-journal.json` | `scripts/planning_migrate_issue_store.py` (`run_store_migration`) | Per-artifact state machine `pending` → `created` → `verified` → `source-removed`; idempotency key `source_path:content_hash`; verify-then-delete ordering |
| `.cursor/hooks/state/context-compress-cache/` | `scripts/context_compress.py` | Gitignored CCR cache keyed by full SHA-256 of redacted content; orchestrator-only `retrieve()` (PRD 058 R20–R22) |

Dry-run (no `--apply`) must not create or update this file. Command surface: `/sw-migrate` /
`scripts/planning_migrate.py` `store-files-to-issues` | `store-issues-to-files`.

## Planning backend and authority
> Planning body cache (planning-cache rename): replicated planning-cache backend lives under `.cursor/sw-planning-cache/planning-bodies/` (migrated from `.cursor/sw-memory/planning-bodies/`); implementation type `ReplicatedPlanningCacheBackend`.
 (PRD 082 R26/R27)

Authority resolution is **backend-neutral** — `scripts/planning_authority.py` returns `authorityState`
(`online` | `read-only` | `blocked`), `writeDisposition`, and `reason` for the **configured** backend only.
There is no silent substitution to a different backend id.

| Surface | Canonical path | Notes |
| --- | --- | --- |
| Planning package facade | `scripts/planning_store_facade.py` | Planning package facade boundary — sole implementation surface for store mutations; `scripts/planning_store.py` and `scripts/planning/cli.py` are shims that delegate here — callers must not bypass the facade |
| Authority policy matrix | `scripts/planning_authority_reasons.py` | Maps fallback reasons to the three authority states and write dispositions |
| Refusal ledger (operator-local) | `.cursor/sw-refusal-ledger` (default; override `planning.refusalLedger.path`) | Owner-only bounded store (`scripts/planning_ledger_store.py`); entries dir `entries/`; eviction journal `eviction-journal.json`; operator CLI `scripts/planning_refusal_ledger_cli.py` (`list`, `show`, `export`, `purge`) |

Reconciling a refused write after inspection is a **human decision** — ledger export surfaces operator-runnable
record commands only; purge is journaled and does not replay refused writes.

**Fail-closed remote sync (PRD 091 R2):** when `planning.store.backend` is `planning-cache` and `scripts/planning_authority.py` `has_configured_remote_planning_authority` is true, `ReplicatedPlanningCacheBackend` sync failures route into the projection outbox as blocking dirty/refused state (no silent local-only degrade). With no remote authority configured, local-only operation continues unchanged.

**Projection outbox (PRD 090 R5):** `scripts/planning_projection_ledger.py` records durable outbox delivery
events with derived dirty state. Mutating authority calls drain pending outbox destinations; refusal-ledger
writes map onto outbox destinations so projection catch-up survives outages/retries without silent drop.

## Golden templates (`core/sw-reference/templates/`)

Authoritative templates consumed by host adapters and init helpers. Edit under
`core/sw-reference/templates/`; build-chain SoT lists `templates/` in `coreAuthoredAllowlist`.

| Template | Path | Writer | Purpose |
| --- | --- | --- | --- |
| PR body | `core/sw-reference/templates/pr-body.md` | host `pr-create` | Required Summary/Test plan fields for PR descriptions |
| Merge commit | `core/sw-reference/templates/merge-commit.md` | host merge | Squash/merge commit body |
| CI stub (pull request) | `core/sw-reference/templates/ci-stub-pull-request.yml` | `init_ci_stub.py` `apply --confirm` (consent-gated) | Minimal unrestricted `pull_request` workflow seeded into `.github/workflows/` during greenfield init; never rewritten after apply |

## Credential machine-local records

Non-secret credential references live in committed config; secret backends and scope enforcement live in
operator-owned stores under the trusted config directory or git common dir. No secret-valued properties in
any artifact below.

| Record | Default path | Writer | Ownership / permissions |
| --- | --- | --- | --- |
| Selector | `$XDG_CONFIG_HOME/shipwright/credential-selector.json` | Operator (`sw-configure credential selector-add`, `/sw-init` migration) | User-owned; file `0600`, parent dir `0700`; no symlinks |
| Pairing | `$XDG_CONFIG_HOME/shipwright/credential-pairings.json` | Operator approval / trust-on-first-use flows | Same as selector |
| Provenance journal | `$XDG_CONFIG_HOME/shipwright/credential-provenance.journal.jsonl` | Pairing, scope-change, rotation audit append | Same as selector; append-only; metadata strings only |
| Resolution journal | `$XDG_CONFIG_HOME/shipwright/credential-resolution.journal.jsonl` | Credential broker on successful resolution | Same as selector; records ref + principal metadata only |
| CI selector | `.sw/credential-ci-selector.json` | `sw-configure credential declare-ci` | Committed repo file (non-secret); loaded with `skip_integrity` |
| Planning backend disable | `$GIT_COMMON_DIR/shipwright/planning-backend-disable.json` | `planning_backend_control.py disable` | User-owned; file `0600`, parent dir `0700`; no symlinks; repo-scoped by `owner/repo` |

Schema: `core/sw-reference/credential-selector.schema.json`. Layout contract for selector integrity modes
matches `credentials.selector_integrity` (`SELECTOR_FILE_MODE` / `SELECTOR_DIR_MODE`). Planning disable
records are enumerated by `planning_backend_control.py list` and surfaced in `planning-doctor.py` as
`backend-disable-record` when active for the current repository.

## Hook-state vs deliver durable state (PRD 050 A1 R31)

| State class | Canonical root |
| --- | --- |
| Deliver durable state (`.cursor/sw-deliver-state.<slug>.json`, locks, merge queue) | Repo root (primary checkout) |
| Hook ephemeral state (`.cursor/hooks/state/*`) | R20-resolved active root (worktree when aligned) |
**PRD 333 absorb closeout:** numeric absorb / ten-gap linkage remains on the facade boundary (planning_store_facade / planning_gap_capture); terminal finalize still fails closed on incomplete absorb audit.

<!-- currency: refreshed 2026-09-03T19:55:07Z for terminal prepare (synced dual-home) -->
