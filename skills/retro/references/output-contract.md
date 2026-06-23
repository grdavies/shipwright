# `/pf-retro` output contract (pinned for `/pf-feedback`)

Minimal shape `/pf-feedback` reads when `sourceClass == retro`. Distilled only — no raw transcripts.

```json
{
  "runId": "retro-YYYYMMDD-HHMM or PR number",
  "shippedRef": "merge commit or PR URL",
  "items": [
    {
      "itemId": "retro-item-1",
      "kind": "well | painful | change",
      "summary": "one-line distilled observation",
      "relatedFiles": ["optional/paths"],
      "extendsPriorPr": true,
      "prdRef": "prds/NN-slug/PRD.md or null",
      "newScope": false
    }
  ]
}
```

`/pf-retro` emits markdown matching this structure; `/pf-feedback` maps each `item` to a normalized
signal with `dedupKey: retro:<runId>:<itemId>`.
