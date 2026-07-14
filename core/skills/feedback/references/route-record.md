# Feedback route record (compounding contract)

Written after routing via `memory-preflight` (redacted). Consumed by `/sw-compound` (R42 human-gated).

```json
{
  "category": "decision",
  "tags": ["surface:feedback-route", "route:<debug|gap-amend|gap-task|brainstorm>"],
  "route": "debug | gap-amend | gap-task | brainstorm",
  "signalId": "<from normalized signal>",
  "sourceClass": "production | review | retro",
  "dedupKey": "<class-tagged key>",
  "target": "/sw-debug | /sw-amend | /sw-brainstorm | docs/planning/<gap-unit-id>/",
  "originatingSignalRef": "redacted one-line summary — no secrets",
  "relatedFiles": [],
  "calibration": {
    "invoked": false,
    "convergedPrinciple": null,
    "converged": null
  }
}
```

`calibration` is present only when `skills/calibration-loop/SKILL.md` was invoked to resolve an ambiguous-scope
call; omit or leave `invoked: false` on the ordinary conservative-default path.

Never store raw `untrusted_payload` in memory — summary + refs only.
