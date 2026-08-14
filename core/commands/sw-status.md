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

Progress payloads include `runId`, `verdict`, per-state `counts`, ordered `nodes[]`, and a `legend`.

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

### Compact mode and JSON / plain-text contract

| Flag | Behavior |
| --- | --- |
| default `--format json` | Stable JSON object (progress or explain shape) |
| `--format text` | Deterministic plain-text render (no color-only encoding) |
| `--compact` | Short text summary; under JSON, embeds a `text` field with the compact render |

Unknown / completed / cached / failed / inaccessible runs have defined empty or degraded payloads from
`scripts/graph/observability.py` — status never invents a second safety kernel.

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

