---
description: Derive and reconcile PRD living status from git facts. Does not modify frozen PRDs or merge PRs.
alwaysApply: false
---

# `/sw-status`

Git-derived living status over `docs/prds/INDEX.md` and `docs/prds/COMPLETION-LOG.md`.

Load `skills/living-status/SKILL.md`.

## Procedure

1. **Planning-store unit status (R2, PRD 059)** — for a single planning unit, query the unified
   status surface (no `docs/prds/INDEX.md` read, no ad hoc `gh issue view`):
   ```bash
   python3 scripts/planning-graph.py status --unit-id <unit-id>
   # or, under issue-store:
   python3 scripts/planning-graph.py status --issue <issue-number>
   ```
   Returns one of `backlog`, `planned`, `in-progress`, `complete`, or `unauthorized` — the same value
   `/sw-status` reports for planning-unit queries regardless of backend.
2. **DecisionGraph frontier (PRD 280 R20)** — for a planning unit with a linked DecisionGraph:

   ```bash
   python3 scripts/status_collect.py decision-frontier --unit-id <unit-id>
   ```

   Returns `readyCount`, `ready[]`, and `blockedHumanActions[]` (open human-action nodes lacking
   verified receipts). Optional `--run-id <decisionRunId>` scopes receipt lookup to one journal under
   `.cursor/sw-decision-runs/<runId>/`.
1. **Codebase Intelligence last artifacts (PRD 280 R14)** — read-only summaries of the latest radar scan
   and vocabulary divergence check (never mutates artifacts):

   ```bash
   python3 scripts/status_collect.py architecture-radar-last
   python3 scripts/status_collect.py vocabulary-divergence-last
   ```

   | Field | Meaning |
   | --- | --- |
   | `present` | Whether a last artifact exists on disk |
   | `readOnly` | Always true — collectors never mutate artifacts |
   | `artifactPath` | Repo-relative path to the last artifact JSON |
   | `scanId` / `scannedAt` | Latest radar scan identity and timestamp when `present` |
   | `candidateCount` | Candidate rows from the linked candidates artifact when readable |
   | `checkedAt` | UTC timestamp of the last divergence check when `present` |
   | `maxSeverity` | Highest divergence severity (`info` / `warn` / `error`) |
   | `divergenceCount` | Number of divergence rows in the last artifact |

   Missing artifacts return `present: false` with `verdict: pass` — status does not treat absence as an error.
1. **Triage recommendation explain** — read-only advisory intelligence for tier
   classification (never mutates evidence or registry stores; **no new slash command**):

   ```bash
   python3 scripts/status_collect.py triage-recommendation-explain \
     [--unit-id <unit-id>] [--description "<work>"] [--file-count N] [--query "<text>"]
   ```

   | Field | Meaning |
   | --- | --- |
   | `readOnly` | Always true — collectors never mutate artifacts or registry |
   | `authority` | Always `non-authoritative` — recommendations do not override deterministic triage |
   | `productAuthority` | Always false — status explain is not a product decision surface |
   | `recommendation.appliedTier` | Final tier after mechanical scoring, safety veto, and promotion-gated advisory |
   | `recommendation.deterministicTier` | Mechanical/file-count/risk/ambiguity tier before advisory merge |
   | `recommendation.advisoryTier` | Weighted advisory tier when computable |
   | `recommendation.vetoTier` | Safety-floor veto tier when fresh safety evidence requires a floor |
   | `recommendation.floorTier` | Risk-keyword floor tier when present |
   | `contributions[]` | Per-producer weighted contributions to the advisory score |
   | `absent[]` | Producers unavailable with explicit reasons (not numeric zero) |
   | `excludedStale[]` | Signals excluded by freshness, expiry, or digest mismatch |
   | `promotion.capabilityId` / `revision` / `state` | Active registry binding (`shadow`, `candidate`, `active`, `rolled_back`) |
   | `promotion.evidenceRef` | Digest-bound evidence reference for the active revision |
   | `evidenceTimestamp` | `computedAt` from the evidence explain payload when present |

   Advisory recommendations remain non-authoritative: deterministic gates, safety-floor vetoes, and required
   workflow gates are unchanged. Configuration and storage layout: `docs/guides/configuration.md`,
   `.shipwright/layout.md`, `docs/guides/workflows.md` (**Evidence-backed triage and planning entry**).
1. **Exploration summary and explain-decision (PRD 331 R23, R45)** — read-only exploration status
   projections (never mutate canonical maps or persistence stores):

   ```bash
   python3 scripts/status_collect.py exploration-summary --map-id <exploration-map-id>
   python3 scripts/status_collect.py explain-decision --map-id <exploration-map-id> --decision-id <node-id>
   python3 scripts/exploration_projection.py project --map-id <exploration-map-id>
   ```

   | Field | Meaning |
   | --- | --- |
   | `readOnly` | Always true — collectors never mutate canonical exploration state |
   | `explorationMapId` / `revision` | Live map identity and optimistic revision |
   | `readiness` | Derived `PlanningReadiness@v1` summary (`readyForDocHandoff`, invalidation) |
   | `degradation` | Optional intelligence hook degradation (`degradedSources`, non-blocking) |
   | `frontier` | Open frontier nodes from `exploration_projection.py` (below canonical semantics) |
   | `projection.textFallback` | Accessible plain-text fallback when provider visualization is unavailable |
   | `interactionState` | Current ask/decide/confirm interaction state when present on the map |
   | `explain-decision.reason` | Active/superseded rationale without mutating the map |
   | `explain-decision.successorDecisionIds` | Successor decisions when a node was superseded |

   Provider-backed visualizations remain redacted projections via `exploration_security.py`; local text
   fallback is always available when visualization is absent or degraded.
1. **Measurement and learning (PRD 280 R10)** — read-only rule effectiveness summaries and workflow
   intelligence cohort drill-down (never mutates telemetry stores):

   ```bash
   python3 scripts/wave_status.py rule-effectiveness-summary
   python3 scripts/wave_status.py cohort-drill-down [--cohort-key <sha256>]
   python3 scripts/wave_status.py measurement-learning [--cohort-key <sha256>]
   ```

   | Field | Meaning |
   | --- | --- |
   | `readOnly` | Always true — collectors never mutate stores |
   | `present` | Whether underlying measurement artifacts exist |
   | `recommendationCount` | Advisory rule lifecycle recommendations observed |
   | `safetyRefusals` | Safety-tagged rules blocked from autonomous retire |
   | `cohortCount` / `cohorts[]` | Summaries when no `--cohort-key` filter |
   | `aggregate` / `recentRuns[]` | Drill-down for a single cohort key |

   Missing data returns `present: false` with `verdict: pass`. Analysis CLI queries remain on
   `python3 scripts/workflow_intelligence.py compare|trend|top-rework` (JSON-only; R8).
2. `python3 scripts/reconcile.py derive` — show per-PRD status + task/PR linkage.
2. On user request or post-merge: `reconcile` to update INDEX Status column.
3. After shipped phase: `append-log` for completion log entry.
4. Include gap-unit index echo from `docs/planning/INDEX.md` (derived region) and legacy GAP-BACKLOG projection summary (read-only).
5. **Verify-unconfigured (R28)** — run `python3 scripts/verify-unconfigured.py`; include signal + CTA (`run /sw-init`) when unconfigured.
6. **Config drift (R32)** — run `python3 scripts/sw-configure.py drift-check`; surface stale notice when applicable.
7. **Review echo (R29)** — when the current branch has an open PR, run `scripts/check-gate.py` and include in
   the status summary:
   - `coderabbitState: off` → `review: off`
   - `coderabbitState: unconfigured` → `review: not configured`
   - otherwise → `review: <coderabbitState>` (per `skills/living-status/SKILL.md`).
8. **Deliver runs (R10)** — `python3 scripts/reconcile.py deliver-runs` lists every live scoped deliver
   run (slug, target branch, verdict, lock holder). `derive --json` embeds the same `deliverRuns` array and
   refreshes `.cursor/sw-deliver-runs/index.json`.
8a. **Dependency-gate override drift (PRD 033 R28)** — echo recent `dependency-gate` overrides from deliver state / shipwright.json (who/when/why/blocking units).
8b. **Authoring handoffs (PRD 032 R6)** — ;  embeds  for pull-in scan.
9. **Live phase status (R15)** — when a deliver run is `running`, `derive --json` includes `livePhaseStatus`
   (per-phase status, remediation attempt, blocker). Also available via
   `python3 scripts/wave_living_docs.py <root> phase-status-live`.

## Graph live progress and node explain (PRD 269 R11/R17)

When a deliver (or other orchestrator) run is executing on WorkflowGraph, `/sw-status` surfaces live
node state and per-node explain on the **existing** command — not `/sw-graph-*`. Mechanical entrypoints:

```bash
# Live progress (JSON default; --format text; --compact for short counts)
python3 scripts/status_integrity.py graph-progress --run-id <runId> [--graph-json <path>] [--journal-root <path>] [--format json|text] [--compact]

# Per-node explain (blocker hierarchy + canonical next-action)
python3 scripts/status_integrity.py explain <nodeId> --run-id <runId> [--graph-json <path>] [--journal-root <path>] [--format json|text] [--compact]
```

### Live states (mutually exclusive)

`completed` · `cached/skipped` · `failed` · `retrying` · `running` · `dependency-blocked` ·
`pool-queued` · `awaiting-human-gate`

Progress payloads include `runId`, `verdict`, per-state `counts`, ordered `nodes[]`, `executionMode`
(`serial-only` | `concurrent` | `unknown`), and a `legend`.

### Cache provenance (PRD 271 R4/R15)

Cache hits are provenance-stamped on receipts and graph-progress — do not infer reuse from chat or from
run journals alone. The canonical cache store lives at `.cursor/sw-graph-cache/` (distinct from
`.cursor/sw-graph-runs/<runId>/receipts/`).

| Field | Meaning |
| --- | --- |
| `cacheSource` | `cache` when served from the canonical cache store |
| `cacheKey` | Content-addressed identity for the cache entry |
| `originalRunId` | Run that first produced the cached artifact (scope ladder applies) |

`/sw-status` graph-progress and explain surface these fields when present. Run-scope dogfood default
does not treat intra-run memoization as “cross-run cache” — see `graphExecution.cache.scope`.

### Blocker hierarchy

Explain orders blockers actionable-first, then passive waits:

| Kind | Class | Meaning |
| --- | --- | --- |
| `failed-predecessor` | actionable | Predecessor (or self) failed |
| `human-gate` | actionable | Awaiting human confirmation / merge gate |
| `pool-capacity` | passive-wait | Ready but queued/parked on a resource pool |
| `dependency` | passive-wait | Waiting on unsettled predecessors |
| `unknown` | passive-wait / actionable | Fallback when no richer classifier applies |

Each explain payload includes `nextAction` (`action`, optional resume `command`, `detail`).
When append-only timing events exist, explain also includes `timingAttribution` (per-category
host-measured waits and execution — bookkeeping excluded from execution time) and `serialOnly`
when the run observed serial-only execution (`executionMode: serial-only` on progress).

### Measured critical-path attribution (PRD 271 R11/R28/R29)

Host-measured timing is derived from append-only `timing-events.jsonl` under the run journal
(not reconstructed from final receipts alone). Categories: `fan-in-wait`, `ready`, `queue-wait`,
`resource-wait`, `contention-wait`, `execution` — plus `bookkeeping` recorded separately and
**excluded** from node execution attribution (pairs with cache R4c bookkeeping).

| Surface | Attribution |
| --- | --- |
| `/sw-status` graph-progress | Live progress + `executionMode` |
| `/sw-status explain <nodeId>` | Per-node waits + `timingAttribution` |
| `/sw-deliver --explain-plan` | **Estimate-only** — never measured events (R29) |

Measured critical path uses a causal wall-clock longest-path algorithm over attributed intervals
(no double-count of overlapping sibling waits). When `maxConcurrency: 1` or no overlapping
execution intervals were observed, progress and explain label the run `serial-only`.

### Compact mode and JSON / plain-text contract

| Flag | Behavior |
| --- | --- |
| default `--format json` | Stable JSON object (progress or explain shape) |
| `--format text` | Deterministic plain-text render (no color-only encoding) |
| `--compact` | Short text summary; under JSON, embeds a `text` field with the compact render |

Unknown / completed / cached / failed / inaccessible runs have defined empty or degraded payloads from
`scripts/graph/observability.py` — status never invents a second safety kernel.

## Durable-background graph run ownership (PRD 271 R18/R1b)

WorkflowGraph execution runs are **durable** — they survive chat session detach and operator re-entry.
Session end does **not** cancel an in-flight graph run; only an explicit operator cancel does.

Mechanical surfaces:

```bash
# Live progress for a durable run (same as graph-progress above)
python3 scripts/status_integrity.py graph-progress --run-id <runId> [--journal-root <path>]

# Ownership sidecar (detach / re-entry metadata)
# <journal-root>/<runId>/ownership.json — written by scripts/graph/run_ownership.py
```

Operator contract:

| Event | Run behavior |
| --- | --- |
| Session detach / chat close | Run continues; ownership record `detached: true` |
| `/sw-status` re-entry | Reattach session; progress + explain unchanged |
| Explicit operator cancel | `cancelRequested` on ownership; scheduler cancel fencing |

`/sw-status` deliver-run listing (`reconcile.py deliver-runs`) and graph-progress remain the
re-entry surfaces — no `/sw-graph-*` commands.

## PRD 270 stable reason codes and outcomes (R1–R7)

When a WorkflowGraph run is active, graph status and explain delegate to
`scripts/graph/observability.py`. Every PRD 270 optimizer, routing, composition, artifact-schema, and
convergence outcome emits a stable **`reasonCode`**, **`verdict`**, responsible node or artifact,
**`explanation`**, and canonical **`nextAction`** on the existing `/sw-status` surfaces — not a
parallel command.

### Outcome payload shape

`explain <nodeId>` promotes graph outcomes onto the explain payload; run-level `status` / `live`
aggregates `outcomes[]` when present:

| Field | Meaning |
| --- | --- |
| `outcome.requirement` | PRD 270 area: `R1`–`R7` |
| `reasonCode` | Stable dotted code (top-level on explain when an outcome is present) |
| `verdict` | Outcome verdict (`pass`, `fail`, `halt`, `partial`, …) |
| `responsible` | Node id, artifact kind, pool, or structured attribution |
| `explanation` | Human-readable summary |
| `nextAction` | Canonical operator step: `{ action, command?, detail }` |
| `progressOnPriorFindings` | When set — duplicate-rate stops must show progress on previously reported findings |

**R1–R6** outcomes are recorded in receipt `coverage.prd270Outcome` by the responsible graph node
(immutable-policy rejection, shadow refusal, fragment digest mismatch, judgment quorum failure,
routing-regret calibration, schema-version mismatch, etc.). **R7** convergence outcomes map from
`coverage.convergence` or an explicit `prd270Outcome` with `requirement: R7`. `/sw-status` surfaces
codes verbatim — it does not invent alternate reason codes or next actions.

Plain-text explain (`--format text`) includes `reasonCode=` when an outcome is present; compact mode
echoes `next` and `cmd` from `nextAction`.

### R7 convergence reason codes

Convergence loop outcomes (`scripts/graph/convergence_loop.py`) use the `r7.convergence.*` prefix.
Canonical `nextAction` values are defined in `scripts/graph/observability.py`:

| `reasonCode` | Typical `verdict` | Canonical `nextAction.action` | Operator detail |
| --- | --- | --- | --- |
| `r7.convergence.dry-clean` | `pass` | `none` | Loop settled on a dry-clean round |
| `r7.convergence.dry-error` | `fail` / `halt` | `inspect-and-rerun` | Round-health attestation failed — not success |
| `r7.convergence.max-rounds-exceeded` | `halt` | `resume-with-partial` | `max_rounds` ceiling — partial fingerprints preserved |
| `r7.convergence.token-budget` | `halt` | `raise-budget-or-accept-partial` | Token budget stop with outstanding findings |
| `r7.convergence.finding-budget` | `halt` | `raise-budget-or-accept-partial` | Finding budget exhausted |
| `r7.convergence.marginal-value` | `pass` | `none` | Discretionary early stop after productive rounds |
| `r7.convergence.duplicate-rate` | `pass` | `none` | Discretionary stop — prior findings show progress |
| `r7.convergence.discovery-error` | `fail` | `inspect-and-rerun` | Discovery errored upstream |
| `r7.convergence.truncated` | `fail` / `halt` | `inspect-and-rerun` | Discovery truncated — not dry-clean |
| `r7.convergence.rate-limited` | `halt` | `wait-and-rerun` | Rate-limited — wait and resume deliver run |

Shadow comparison output and digest-bound promotion confirmation on `/sw-deliver`:
`core/commands/sw-deliver.md` (Workflow optimizer). Term definitions:
`docs/guides/graph-domain-terminology.md` (`dry-clean`, `dry-error`, `max_rounds`).

## Detector evidence and false-positive correction (PRD 272 R8)

Mechanical detector injections surface on `/sw-status` **graph-progress** and **explain**
payloads (see **Graph live progress and node explain** above) when `metadata.detectorResults`
is present on the active WorkflowGraph. Every injected `requiredCapabilityId` MUST show the
evidence paths and rule that produced it.

| Field | Meaning |
| --- | --- |
| `injections[].capabilityId` | Typed `requiredCapabilityId` admitted through compile |
| `injections[].detectorId` / `detectorVersion` | Source detector id + version |
| `injections[].ruleId` | Mechanical rule that fired |
| `injections[].evidencePaths` | Paths/hashes from the realized diff |
| `overrides[]` | Auditable false-positive corrections (`learning:false-positive-override`) |

False-positive correction is operator-initiated and recorded on the run receipt — overrides are
labeled learning data and never silently drop mechanical requirements without an auditable record.
Mechanical re-detect returning `no-fire` with matching diff digest is the only automated reduction
path (see PRD 272 R7).

## TraceRef and CoverageEdge evidence predicates (PRD 272 R24)

`/sw-status` graph-progress and explain payloads may include `traceRefs` and `coverageEdges`
serialized from `scripts/graph/traceability.py`. A coverage edge **passes** only when the
observed verifier class matches the edge binding **at the current `headSha`**. Stale or
wrong-class evidence is **blocking** when `blocking: true` and **advisory** when `advisory: true`.

| Field | Meaning |
| --- | --- |
| `traceRefId` | Stable id from `stable_trace_ref_id(requirementId, verifierClass, headSha)` |
| `requirementId` | PRD R-ID or AC binding |
| `verifierClass` | Expected attestation class (`mechanical`, `human`, `agent`, `gate`, `verifier`) |
| `headSha` | Git head the evidence must match |
| `blocking` / `advisory` | Whether a failed predicate blocks merge-ready surfaces |

Mechanical evaluation: `evaluate_evidence_predicate` / `evaluate_coverage_edges` in
`scripts/graph/traceability.py`.

## TraceRef / CoverageEdge evidence predicate (PRD 272 R24)

WorkflowGraph status surfaces include stable `TraceRef` ids and `CoverageEdge` rows when run
receipts expose verification evidence. Mechanical entrypoint:

```bash
python3 -m graph.traceability  # library — consumed by status_integrity graph-progress payloads
```

| Field | Meaning |
| --- | --- |
| `traceRefId` | Stable id (`trace:<requirement>:<digest>`) |
| `requirementId` | Covered requirement / R-id |
| `headSha` | Git HEAD the evidence attests |
| `verifierClass` | `mechanical` · `evidence` · `judgment` · `synthesis` |
| `blocking` / `advisory` | Blocking edges require non-advisory pass at current headSha |

**Predicate:** pass only when `verdict=pass`, `verifierClass` matches the edge requirement, and
`headSha` equals the run's current HEAD. Stale head or advisory-only rows do **not** satisfy
blocking coverage — `/sw-status` labels advisory vs blocking on the payload.

**Communication intensity:** ultra

**Model tier:** cheap — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --command sw-status`.

## Guardrails

- Frozen artifacts never modified.
- Task checkboxes are derivation inputs only.
## Post-merge playbook (A1)

After target merge: use `set-index-status` + `append-log-idempotent` on a **docs branch** for single-unit INDEX updates. Never run full-corpus `scripts/reconcile.py reconcile` on `main`. Terminal derived status is monotonic (`complete`/`superseded` do not downgrade). `merged-complete` is set only via `python3 scripts/wave.py completion finalize-if-merged`.

**Auto-flip on `complete` (PRD 048 R1):** `set-index-status --status complete` auto-invokes
`gap_backlog.resolve_for_prd()` in-process after the INDEX write — absorbed `scheduled`/`open` GAP-BACKLOG rows
flip to `resolved` idempotently with no separate manual step. Echo `flipped` in the JSON summary when present.

**`verdict: partial` retry (R1):** when the INDEX write succeeds but the gap flip raises, the CLI returns
`{"verdict": "partial", ...}` (exit 21) instead of `pass` — the INDEX row is **not** rolled back. Surface this
in the status summary as a recoverable operator signal: retry with
`living-status-gap-resolve.py --absorbing-prd <NNN>` (optionally `--scope-note <text>` for narrower-than-described
fixes) or inspect `gap_backlog.py check` before re-running `set-index-status`.

