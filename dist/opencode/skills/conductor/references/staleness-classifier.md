# Staleness classifier (R32)

Before treating an in-flight background phase as watchdog-stale, classify liveness with
`scripts/phase_staleness_lib.py` using four signals:

| Signal | Source |
| --- | --- |
| `lastToolCallAt` | Agent tool-call heartbeat |
| `lastCommitAt` | Phase worktree `git log -1` |
| `lastStatusWriteAt` | `.cursor/sw-deliver-runs/<phase>/status.json` mtime |
| `pendingHumanReply` | Legitimate-halt checkpoint awaiting operator input |

```bash
python3 -c "
import json, sys
sys.path.insert(0, 'scripts')
from pathlib import Path
import phase_staleness_lib as lib
root = Path('.').resolve()
signals = {
  'lastToolCallAt': '2026-07-11T00:04:00Z',
  'lastCommitAt': '2026-07-11T00:03:00Z',
  'lastStatusWriteAt': '2026-07-11T00:05:00Z',
  'pendingHumanReply': True,
}
print(json.dumps(lib.classify_staleness(signals, root=root), indent=2))
"
```

Output tiers: `waiting-on-human`, `actively-working`, `genuinely-stuck`, `indeterminate` — each with
`confidenceTier` (`high`/`medium`/`low`) and `confidenceScore`. When `waiting-on-human` at high/medium
confidence, defer `phase-timeout` until the checkpoint clears; when `genuinely-stuck` at high confidence,
route to consolidated halt. No new dispatch mechanism — classification informs existing watchdog polling only.

See `rules/sw-dispatch-background-phase.mdc` for background-phase posture.

