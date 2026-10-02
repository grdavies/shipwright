# Troubleshooting

Operator diagnostics for common Shipwright failure modes. Prefer these recipes over
ad-hoc retries when a command already emitted a typed halt and `resumeCommand`.

## Pre-push secret scan denial

`secret-scan: deny pattern match — push blocked` means the scan retained a
finding (exit `1`). An acquisition error or incomplete baseline exits `2`; fix
that error and rerun the complete scan. Exit `0` means no findings were retained,
not approval of an arbitrary future push or export.

Choose the response from the actual committed source:

1. **Real credential:** rotate or revoke it, then remove it from the affected
   source and outgoing history. Keep any history redaction scoped to the approved
   range; do not bypass the pre-push gate.
2. **Public or synthetic example:** request human review of the exact occurrence
   in its complete committed file, repository and path. Pattern shape, localhost,
   a test filename or an apparent forwarding/null expression cannot approve it.
   The existing stock local database URL approval covers only its exact reviewed
   tuple. Keeping that approved example and a separately authorized
   document correction are distinct choices; a correction changes the source identity and
   must be reviewed again if it still matches. There is no general URL exemption.
3. **Previously reviewed source changed:** a source edit, moved occurrence, copied
   path/repository, new literal or new match ordinal needs fresh exact review.
   A changed file digest invalidates the old occurrence identity even when the
   matching text looks unchanged. Any qualifying replacement catalog/release also
   needs independent security review and separately authorized enrollment of its
   actual digests. A package update never carries enrollment forward to a new digest.
4. **Expected approval but still denied:** check the installed release and scanner
   enrollment using [scanner exact occurrence enrollment](trust-anchors.md#scanner-exact-occurrence-enrollment).
   Package dispatch trust permits the runtime to run; it does not approve source
   occurrences. Recover a tampered or mismatched install from a trusted release,
   and ensure source modules match that release before considering new digest
   approval. Missing, corrupt or mismatched trust, catalog, archive or module bytes
   grant no exceptions. A missing marker after clear/reclone requires explicit
   operator reenrollment, including authorization for its fixed common-directory
   marker write; scans never create or repair it. Partial marker/trust state also
   grants no exceptions. Unsafe owners, modes or ancestors and unsupported secure
   filesystem/ACL checks fail closed; do not loosen permissions or alter a shared
   volume to bypass them. Establishing a secure operator-controlled location is a
   separate prerequisite, not a scan repair.
5. **Exact approval is unavailable:** keep the denial. The first implementation
   release has an empty catalog, so all six candidate occurrences remain denied.
   Packaging evidence alone neither completes the empty-release gate nor approves
   a populated release or real operator enrollment.

Rerun the supported `secret_scan.py pre-push` entry after resolving the cause;
see the linked enrollment section for source, direct-archive and emitted
`sw-run.py` command forms and the separately authorized `enroll-exact` inputs.
Ordinary file/stdin scans and uncommitted fallbacks receive no new exceptions.

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

## Incomplete issue-store freeze

A PRD marked `sw:frozen` and `sw:freeze-incomplete` has not completed its required
freeze work. Preserve its body, closed review witness, receipt history and failure
output. Retry the same `planning_store.py freeze --unit-id <unit> --body-path <path>`
command under the ordinary defaults after fixing the reported dependency failure.
Do not manually clear the label, repin the hash, reopen the review or unlock/relock
the issue. Complete frozen units still return `already-frozen`.

Recovery requires a fresh full provider read proving the native issue lock is
strictly `true`; a frozen label or the legacy effective `locked` value cannot prove
that. Missing, false or unsupported native-lock evidence refuses recovery. Only an
incomplete PRD with one original freeze receipt, matching identity and destination,
and an unchanged canonical snapshot after projecting away the incomplete label can
resume. Raw body and witness bytes are preserved; retained closed review pins and
completion evidence are checked without replaying the already applied review.
V1 review evidence may bind only the unit: an omitted optional `bodyPath` does not
imply a historical default filename. Canonical facade resolution still applies,
and any explicitly retained witness or completion path must match the request.

Recovery repeats required distillation and absorb-linkage checks. It requires exactly
one linked canonical brainstorm; missing, retargeted or ambiguous search evidence
keeps the incomplete gate. An exact memory pointer is reused, and brainstorm closure
uses a fresh ETag after pointer publication.
A closed brainstorm needs that matching pointer. Cache notices remain literal: HTTP
404 with local-cache fallback does not establish remote durability. Configured remote
planning authority failures keep recovery incomplete.

Only after these steps pass does a fresh guarded write remove the incomplete label;
the original matching receipt remains unchanged. Fresh reads immediately before and
after this write recheck native lock and body/witness evidence. These are point-in-time
observations, since provider ETags do not bind native lock. A detected post-write loss
attempts one identity/body-checked OCC restoration of the incomplete label. If that
restoration conflicts or cannot safely preserve the current body, the command reports
`freeze-recovery-partial-apply` with `partialApply: true`; preserve the actual evidence
and resolve the conflict before another supported attempt. A crash before removal
leaves the incomplete gate; a crash after removal does not itself prove final checks
succeeded. No force, relock or retry loop repairs concurrent edits.

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
