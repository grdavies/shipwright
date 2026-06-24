# Local code-review provider capabilities

Neutral contract for **local** multi-agent code-review adapters (`review.local.provider`). Agent-mediated
consumers (`/sw-review` phase 1) read the markdown adapter (`providers/code-review/<id>.md`). Deterministic
fixtures and gates call `scripts/code-review-normalize.sh` and `scripts/code-review-gate.sh`.

External provider review (CodeRabbit, phase 2) remains under `providers/review/` — different seam.

## Opt-out

Disable local review via `workflow.config.json`:

- `review.local.provider: "none"`, or
- `review.local.enabled: false`

When opted out, `/sw-review` skips phase 1 and proceeds directly to the external provider (phase 2).

## Soft dependency

Default adapter `ce-code-review` requires the compound-engineering skill installed. When unavailable, phase 1
**skips with a clear message** (fail-closed) and phase 2 still runs. The `native` no-dependency panel is
deferred (YAGNI).

## Normalized review result (phase 1)

```json
{
  "status": "complete | skipped | failed | degraded",
  "verdict": "ready | ready-with-fixes | not-ready",
  "reason": "optional — required for skipped | failed | degraded",
  "findings": [
    {
      "severity": "P0 | P1 | P2 | P3",
      "file": "path/relative/to/repo",
      "line": 0,
      "title": "terse issue summary",
      "suggested_fix": "concrete fix or empty string",
      "confidence": 0,
      "requires_verification": true
    }
  ]
}
```

### Status enum

| Value | Meaning | Consumer behavior |
|-------|---------|-------------------|
| `complete` | Local review finished | Process `findings` + `verdict` |
| `skipped` | Skill absent, config off, or explicit skip | Surface `reason`; **never** treat as clean pass |
| `failed` | Adapter or skill error before findings | Surface `reason`; skip phase 1 |
| `degraded` | Partial failure (e.g. all reviewers failed) | Surface `reason`; skip phase 1 |

**Fail-closed:** `skipped | failed | degraded` without a `findings` array is **not** a clean review. Missing
`findings` must not deserialize to "0 findings → pass."

### Verdict enum

| CE source string | Normalized |
|------------------|------------|
| `Ready to merge` | `ready` |
| `Ready with fixes` | `ready-with-fixes` |
| `Not ready` | `not-ready` |

### Requirements authority

`gap-check` owns requirements completeness. Adapters **post-filter** requirement-stage findings (unaddressed
R-IDs, implementation units, plan completeness) before normalized output reaches pf's gate. The adapter may be
requirements-*aware* (intent summary in) but emits **no completeness verdict**.

## Severity gate (`review.local.gate`)

| Mode | Config | Behavior |
|------|--------|----------|
| Surface-only (default rollout) | `surface: ["P0","P1","P2","P3"]`, `haltOn: []` | Log validated severities; continue to phase 2 |
| Halting (promoted) | `haltOn: ["P0","P1"]` | Validated P0/P1 halt `/sw-ship`; P2/P3 surface and continue |

Only **validated** P0/P1 (post `ce-code-review` Stage 5b) are halt-eligible. `check-gate.sh` remains the sole
CI oracle — this gate is additive.

## Untrusted apply boundary

Adapter `suggested_fix` / `file` fields are untrusted at auto-apply. pf validates before applying:

- `file` resolves **within the repo** (no path traversal)
- Fix size bounded
- Security-sensitive targets (auth, secrets, credentials, CI config) **never** auto-applied

Auto-apply: P2/P3 only, concrete `suggested_fix`, `requires_verification: false`. P0/P1 never auto-fixed.

## Config

`review.local` in `workflow.config.json` selects `providers/code-review/<id>.md`.
