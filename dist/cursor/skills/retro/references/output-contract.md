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

## Retro painful gap capture (PRD 275 D3–D4)

**D3 — Supervised retro gaps:** `retrospective.gapCapture` defaults **disabled**. When enabled, only
`kind: painful` items enter the gap draft path; materialization requires persisted per-item digest-bound
confirm — unattended and `compound.autonomy: auto` never auto-mint gap units.

**D4 — Brainstorm FM cluster pointers:** populate `prdRef` and `relatedFiles` with repo-relative paths to
the delivery brainstorm cluster (for example `docs/brainstorms/...-requirements.md` or issue-store brainstorm
unit ids). On materialize, these become **Related units** pointers in the enriched gap body — not raw
transcripts. PRD 275 absorb brainstorms:

- `brainstorm-2026-08-16-close-delivery-units-freeze-repin-requirements` (#697)
- `brainstorm-2026-08-16-planning-issues-gap-only-resolver-requirements` (#706)
- `brainstorm-2026-08-16-retro-painful-auto-gap-capture-requirements` (#700)

Per-item digest (confirm/materialize binding):

```bash
python3 -c "import json,sys; from planning_gap_capture import retro_item_digest; print(retro_item_digest(json.load(sys.stdin)))"
```

Pass the printed digest to `retro-confirm` / `retro-materialize` for that `itemId` only.
