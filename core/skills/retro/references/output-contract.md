# `/sw-retro` output contract (pinned for `/sw-feedback`)

Minimal shape `/sw-feedback` reads when `sourceClass == retro`. Distilled only — no raw transcripts.

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
      "prdRef": "docs/prds/NN-slug/PRD.md or null",
      "newScope": false
    }
  ]
}
```

`/sw-retro` emits markdown matching this structure; `/sw-feedback` maps each `item` to a normalized
signal with `dedupKey: retro:<runId>:<itemId>`.
