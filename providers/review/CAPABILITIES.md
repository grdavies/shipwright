# Review provider capabilities (R36)

Neutral contract for AI code-review adapters. Deterministic consumers (`scripts/check-gate.sh`) call the
**executable** adapter (`providers/review/<id>.sh`). Agent-mediated consumers (`/pf-review`, stabilize) read
the markdown adapter (`providers/review/<id>.md`).

## Required capability: per-head review state

Adapters **must** expose whether review has settled for the **current PR head**. Providers that cannot answer
this are **gate-incompatible** — the gate stays `yellow` (never `green`).

### Normalized per-head state (`perHeadState`)

| Value | Meaning | `perHeadLanded` |
|-------|---------|-----------------|
| `landed` | Review completed for current head | `true` |
| `skipped` | Provider explicitly skipped head (incremental/no-op) | `true` |
| `clean` | Provider absent / not installed (past grace) | `true` |
| `absent` | Alias for `clean` in gate output | `true` |
| `unconfigured` | No provider signal past grace — repo likely not onboarded | `true` |
| `in-flight` | Review pending for current head | `false` |
| `disabled` | Gate-only state when review gating is opted out (not adapter-emitted) | `true` |

`unconfigured` is non-blocking (the gate will not hang waiting for a review that may never arrive) but is
reported distinctly so the verdict reason is honest. Within the grace window the state is `in-flight`
(genuinely unknown); only past grace with zero signal does it become `unconfigured`.

## Opt-out

A repo can disable review gating entirely via `workflow.config.json`:

- `review.provider: "none"`, or
- `review.enabled: false`

When opted out the gate skips the adapter, sets state `disabled` (non-blocking), and `/pf-review` reports
review is disabled rather than invoking the provider CLI. Use this for repos not onboarded to any review
provider.

### Executable adapter JSON (stdout)

```json
{
  "capabilities": { "perHeadState": true },
  "perHeadState": "landed",
  "perHeadLanded": true,
  "reviewedHead": "abc123…",
  "statusContext": "SUCCESS",
  "inProgressMarker": false,
  "skipped": false,
  "minutesSinceHeadPush": 3
}
```

When `capabilities.perHeadState` is `false`, the gate treats review as permanently unsettled (`in-flight`).

### Normalized findings (agent-mediated)

Findings shape for stabilize (markdown adapters document fetch procedure):

- `inlineThreads[]` — `{ path, line, body, threadId, resolved }`
- `nonInline[]` — `{ path, line, body, category }` (summary/walkthrough bodies)

## Config

`review.provider` in `workflow.config.json` selects `providers/review/<id>.sh` + `<id>.md`.
