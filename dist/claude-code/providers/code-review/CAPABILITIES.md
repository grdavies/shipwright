---
metadata:
  shipwright-capability:
    version: 1
    triggers:
      -
        type: config_flag
        selectionFamily: providers
        key: review.local.provider
        equals: native
    metadata:
      providerFamily: code-review
      adapterId: contract
      selectionFamily: providers
      gateRef: check-gate.py
---

# Local code-review provider capabilities

Neutral contract for **local** multi-agent code-review adapters (`review.local.provider`). Agent-mediated
consumers (`/sw-review` phase 1) read the markdown adapter (`providers/code-review/<id>.md`). Deterministic
fixtures and gates call `scripts/code-review-normalize.py`, `scripts/code-review-select.py`,
`scripts/review-local-resolve.py`, and `scripts/code-review-gate.py`.

External provider review (CodeRabbit, PR-Agent, phase 2) remains under `providers/review/` — different seam.

## Opt-out

Disable local review via `workflow.config.json`:

- `review.local.provider: "none"`, or
- `review.local.enabled: false`

When opted out, `/sw-review` skips phase 1 and proceeds directly to the external provider (phase 2). Phase 1
fires **independently** of `review.provider` (including `"none"`) unless explicitly opted out above (R14/R15).

## Provider defaults (R3, R32)

| Provider | Role |
|----------|------|
| `native` | Schema default — Shipwright-native panel (`native.md`); no external plugin dependency |
| `ce-code-review` | Selectable legacy adapter; requires compound-engineering skill (soft dependency) |
| `none` | Disable phase 1 |

## Soft dependency (`ce-code-review` only)

The `ce-code-review` adapter requires the compound-engineering skill installed. When unavailable, phase 1
**skips with a clear message** (fail-closed) and phase 2 still runs. The `native` adapter has no soft
dependency.

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
| `degraded` | Partial failure (e.g. all reviewers failed, unattested empty) | Surface `reason`; skip phase 1 |

**Fail-closed:** `skipped | failed | degraded` without a `findings` array is **not** a clean review. Missing
`findings` must not deserialize to "0 findings → pass."

### Verdict enum

| CE source string | Normalized |
|------------------|------------|
| `Ready to merge` | `ready` |
| `Ready with fixes` | `ready-with-fixes` |
| `Not ready` | `not-ready` |

### Requirements authority & advisory scope-fidelity (R12, R13)

`gap-check` owns **binding** requirements completeness at `/sw-ship`. Adapters **post-filter**
requirement-stage findings (unaddressed R-IDs, implementation units, plan completeness) before normalized
output reaches pf's gate.

The `native` adapter's `scope-fidelity` reviewer MAY emit an **advisory** local completeness signal (silent
defers, stubs, omissions) labeled non-binding. This signal MUST NOT alter `gap-check`'s exclusive ownership of
the binding verdict.

## Severity gate (`review.local.gate`)

| Mode | Config | Behavior |
|------|--------|----------|
| Surface-only (default rollout) | `surface: ["P0","P1","P2","P3"]`, `haltOn: []` | Log validated severities; continue to phase 2 |
| Halting (promoted) | `haltOn: ["P0","P1"]` | Validated P0/P1 halt `/sw-ship`; P2/P3 surface and continue |

Only **validated** P0/P1 are halt-eligible. `check-gate.py` remains the sole CI oracle — this gate is additive.

## Untrusted apply boundary

Adapter `suggested_fix` / `file` fields are untrusted at auto-apply. `scripts/code-review-apply-check.py`
validates before applying:

- `file` resolves **within the repo** (no path traversal; realpath; no symlink component; no `.git/**`)
- Fix size bounded (chars, lines, hunks — pinned in `native.md` R60)
- Security-sensitive targets (deny-list path globs + content markers, R48/R55) **never** auto-applied
- Security-control markers and `security`-reviewer-touched findings **never** auto-applied (R56)
- `behavior_altering` findings (logic / control-flow / invariant changes) surface only (R59)
- Patch internal target must match validated `finding.file` (R57)

Apply policy (`review.local.apply`, default `auto`):

- **`off`** / **`surface`** — never auto-apply (review + surface only, R68)
- **P0** — never auto-applied (surface only)
- **P1** — validated P1 auto-applied only after independent validation (`--validated`); unvalidated P1
  surfaced only; **phase-mode** blocks even validated P1 (R67)
- **P2/P3** — auto-applied when concrete `suggested_fix`, rails pass, `requires_verification: false`

## Config

`review.local` in `workflow.config.json` selects `providers/code-review/<id>.md`. Resolved at runtime by
`scripts/review-local-resolve.py`.
