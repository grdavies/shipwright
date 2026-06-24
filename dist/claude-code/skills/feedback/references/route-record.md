# Feedback route record (compounding contract)

Written after routing via `memory-preflight` (redacted). Consumed by `/pf-compound` (R42 human-gated).

```json
{
  "category": "decision",
  "tags": ["surface:feedback-route", "route:<debug|gap-amend|gap-task|brainstorm>"],
  "route": "debug | gap-amend | gap-task | brainstorm",
  "signalId": "<from normalized signal>",
  "sourceClass": "production | review | retro",
  "dedupKey": "<class-tagged key>",
  "target": "/pf-debug | /pf-amend | /pf-brainstorm | docs/prds/GAP-BACKLOG.md",
  "originatingSignalRef": "redacted one-line summary — no secrets",
  "relatedFiles": []
}
```

Never store raw `untrusted_payload` in memory — summary + refs only.
