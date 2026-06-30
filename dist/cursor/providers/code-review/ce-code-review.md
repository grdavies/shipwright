---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: review.local.provider
      equals: "ce-code-review"
  metadata:
    providerFamily: review.local
    adapterId: ce-code-review
    selectionFamily: providers
    gateRef: check-gate.sh
---

# ce-code-review local adapter (agent-mediated)

Markdown companion for phase 1 of `/sw-review`. Invokes compound-engineering `ce-code-review` in **report-only**
mode, normalizes output via `scripts/code-review-normalize.sh`, and hands findings to sw-owned apply + gate.

## Soft dependency

Requires `ce-code-review` skill installed (compound-engineering plugin). When absent:

1. Report: `Local review skipped — ce-code-review skill not available.`
2. Proceed to phase 2 (external provider) — **never** treat as clean pass.

## Invocation

```
ce-code-review mode:agent base:<parentBranch> grouping:auto
```

- `base:` = per-worktree `parentBranch` from phase state (merge-base diff).
- Do **not** pass `plan:` — requirements completeness stays with `gap-check`; adapter post-filters
  requirement-stage findings from normalized output.
- Skill is report-only (`mode:agent`) — pf owns apply through its edit machinery.

## Parse pipeline

1. Run `ce-code-review mode:agent` — primary response is one bare JSON object (no markdown fence).
2. Optionally read `review.json` under `artifact_path` when stdout parse fails.
3. Normalize:

   ```bash
   scripts/code-review-normalize.sh --input /tmp/sw-local-review-raw.json --repo-root "$PWD"
   ```

4. `status: skipped|failed|degraded` (no findings) → surface `reason` + skip phase 1 (fail-closed).
5. Post-filter requirement-stage findings is built into the normalize script (heuristic until upstream
   `plan:none` affordance exists).

### Verdict mapping

| ce-code-review `verdict` | Normalized |
|--------------------------|------------|
| `Ready to merge` | `ready` |
| `Ready with fixes` | `ready-with-fixes` |
| `Not ready` | `not-ready` |

## Run-dir scrub (persist edge)

`ce-code-review` writes cleartext artifacts to `/tmp/compound-engineering/ce-code-review/<run-id>/`
(`full.diff`, evidence, `review.json`, `report.md`). After parsing normalized JSON:

```bash
RUN_DIR="$(Python json -r '.artifact_path // empty' /tmp/sw-local-review-raw.json)"
[[ -n "$RUN_DIR" && -d "$RUN_DIR" ]] && rm -rf "$RUN_DIR"
```

Scrub **before** any `memory-preflight` write. Durable learnings only via redacted memory path.

## Handoff to pf apply + gate (U4)

Normalized JSON flows to:

1. **Apply** — auto-apply eligible P2/P3 via pf edit machinery after `code-review-apply-check.sh`.
2. **Re-verify** — one bounded `sw-verify` pass after applies; circuit-breaker on 3 identical failures.
3. **Gate** — `code-review-gate.sh` with `review.local.gate` config (surface-only default).

Untrusted-output validation (mandatory before apply):

- `file` in-repo, no traversal
- Fix size bounded (`--max-fix-chars`)
- Security-sensitive paths never auto-applied
- P0/P1 never auto-fixed

## Memory

- **Read:** `memory-preflight` for known false-positives before invoking skill.
- **Write:** redacted learnings only (`scripts/memory-redact.sh` chokepoint) — no raw bot dumps.

## Config

`review.local.provider: "ce-code-review"` in `workflow.config.json`.

See `CAPABILITIES.md` for the normalized contract enum.
