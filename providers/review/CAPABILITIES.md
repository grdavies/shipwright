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
| `in-flight` | Review pending for current head | `false` |

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
