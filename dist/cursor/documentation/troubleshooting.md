# Troubleshooting

Operator diagnostics for common Shipwright failure modes. Prefer these recipes over
ad-hoc retries when a command already emitted a typed halt and `resumeCommand`.

## Consumer delivery initialization and crash recovery

A newly provisioned orchestrator may exist before its first plan or run identity.
Deliver binds an explicitly supplied, frozen task list before adoption only when no
run identity or phase state exists and the task list matches the recorded target.
Existing run identity is never overwritten by this recovery.

Kernel classification, planning guidelines and execute dependency rules resolve
through the shared packaged reference resolver. Consumer repositories do not need a copy of Shipwright's
`core/sw-reference` tree. A malformed local artifact remains an error.

On resume, a recorded lease held by a previous driver is passed through normal
acquisition checks. Reclaim requires a stale heartbeat and dead same-host PID;
a live owner remains protected and generation fencing advances on reclaim.
A different recorded host still requires explicit operator acknowledgement via
the run-lease acquisition command's `--cross-host-ack` option. Do not delete lock
files or fabricate run IDs to bypass these checks.

## Consumer review reports a missing capability index

`code-review-select.py --repo-root <consumer>` keeps review policy and reviewer
metrics in that consumer repository. Capability manifests and their freshness
check belong to the selected Shipwright runtime. Consumers without a capability
bundle resolve that runtime through the trusted scripts resolver, including an
explicit `SHIPWRIGHT_SCRIPTS` binding. They do not need copied `core/sw-reference`
files, and `--repo-root` must not be changed to the Shipwright checkout to make
review selection succeed.

A source runtime checks its `core/` frontmatter; an installed bundle checks its
installed layout. A missing, malformed or stale index in the selected runtime
still stops selection. An invalid or untrusted `SHIPWRIGHT_SCRIPTS` also stops
selection. Repair or reinstall that runtime; do not disable freshness or silently
switch to a different bundle.

A consumer with its own capability index or authored capability tree retains
that authority, including failures for an incomplete or stale local bundle.
Explicit index overrides remain bound to the consumer's frontmatter. Runtime
fallback applies only when the consumer has no local capability bundle.

## Linear recognized-but-not-shipped on packaged install 

Symptom: planning discovery or `gitignore-generate --write` refuses Linear with
**recognized-but-not-shipped** while doctor/credentials/schema succeed — common on consumer repos without
a Shipwright source checkout.

| Check | Action |
| --- | --- |
| Host bundle layout | Confirm `dist/<host>/core/sw-reference/provider-conformance/linear.ok.json` exists under the installed package (not only `core/sw-reference/…` at package root). |
| Active host | Ensure the integration host env (`CURSOR_PLUGIN_ROOT`, `CODEX_PLUGIN_ROOT`, etc.) points at the expected `dist/<host>/` bundle. |
| Present-and-fail | Corrupt active-host evidence stays fail-closed; sibling green does not override — fix or reinstall the active host bundle. |
| Stale install | Run `shipwright self check` / upgrade; see [self-upgrade](self-upgrade.md#packaged-provider-conformance). |

## Issue-store projection timeout and rate limits

Post-merge living-doc projection (`wave living-docs reconcile`, including the path used by
`/sw-retro --post-merge`) searches the planning issue-store via the GitHub Issues search API.
Under load that search can stall or return HTTP 429. Shipwright bounds the work instead of
hanging indefinitely.

### What you will see

| Halt / exception | Meaning | Retryable |
| --- | --- | --- |
| `projection-search-timeout` / `IssueSearchTimeout` | A single search call exceeded `planning.store.issues.rateLimit.searchTimeoutSeconds` (default 30s; override with `SW_ISSUES_SEARCH_TIMEOUT`) | yes |
| `projection-rate-limited` / `IssueRateLimited` | Search exhausted 429 retry/backoff within `searchMaxCumulativeWaitMs` (capped near 30s for actionable diagnostics) | yes |

Successful interrupts persist partial progress under `.cursor/sw-projection-state/` and attach an
operator-facing `resumeCommand` on the halt payload (also echoed in deliver/living-docs JSON).

### Resuming after an interrupt

1. Read `resumeCommand` from the halt report (do not invent a new reconcile invocation).
2. Typical form:

 ```bash
 wave living-docs reconcile --commit
 ```

 When projection was scoped to a non-primary worktree, the command includes
 `--orchestrator-worktree <path>`.
3. Re-run the printed command from the same worktree context. Completed steps (`index`, then
 `gap-resolve`) are skipped; only pending work runs.
4. On full success the projection state file is cleared automatically.

### Configuration knobs

Under `planning.store.issues.rateLimit` in `.cursor/workflow.config.json`:

| Key | Role |
| --- | --- |
| `searchTimeoutSeconds` | Per-request timeout for GitHub **search** calls |
| `searchMaxCumulativeWaitMs` | Cap on cumulative 429 backoff for search |
| `searchMaxAttempts` / `baseBackoffMs` / `capBackoffMs` | Retry budget and exponential backoff |
| `jitter` | Set `false` in fixtures; leave default on for production |

Environment override: `SW_ISSUES_SEARCH_TIMEOUT` (seconds) wins over config for the per-request
timeout.

### Primary checkout vs worktree

Projection on the primary checkout can contend with other post-merge traffic. When a
non-primary worktree is available (`SW_ORCHESTRATOR_WORKTREE` / explicit
`--orchestrator-worktree`), living-docs prefers that worktree for state and reconcile so
primary stays responsive. Resume commands preserve that scoping.

### Validation fixture

Hermetic reproduction of a post-merge rate-limit scenario lives in
`scripts/unit_tests/planning/test_projection_performance.py`
(`post_merge_rate_limit_scenario`). It does not call the live API.
