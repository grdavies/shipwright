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

## Supervised retro → gap capture (PRD 275, D3–D4)

### D3 — Supervised retro gaps (#700)

Retro gap capture is **supervised only**. Automatic behavior may create **redacted drafts** in the gap inbox;
it must **never** mint public gap units without persisted human acknowledgement. Unattended hook dispatch
fail-closed on materialize. Lifecycle per painful item:

1. **Draft** — inbox entry with `signalId`, `dedupKey`, content `digest`, `status: draft`
2. **Confirm** — operator ack stores `confirmedDigest` matching the draft digest
3. **Materialize** — mint gap unit only when status is `confirmed` and digest matches

Batch presentation is allowed; each materialization still requires its own digest-bound confirm (D7).

Only items with `"kind": "painful"` are eligible for auto-draft when `retrospective.gapCapture.enabled`
is true. `"well"` and `"change"` must not enter the gap draft path.

### D4 — Brainstorm frontmatter cluster pointers

PRD 275 frontmatter links the retro painful primary brainstorm and the three closeout-hygiene clusters
(manual 2026-08-16). When authoring or extending retro gap capture docs, preserve these pointers:

| Cluster id | Absorbed issue | Typical brainstorm path |
| --- | --- | --- |
| `retro-painful-auto-gap-capture` | #700 | `docs/brainstorms/2026-08-16-retro-painful-auto-gap-capture-requirements.md` (primary) |
| `close-delivery-units-freeze-repin` | #697 | `docs/brainstorms/2026-08-16-close-delivery-units-freeze-repin-requirements.md` |
| `planning-issues-gap-only-resolver` | #706 | `docs/brainstorms/2026-08-16-planning-issues-gap-only-resolver-requirements.md` |

Issue-store unit ids follow `brainstorm-2026-08-16-*-requirements` under the planning project when
materialized on the store — file paths above are the in-repo FM anchors.
