---
capability:
  version: 1
  triggers:
    - type: config_flag
      selectionFamily: providers
      key: review.provider
      equals: "coderabbit"
  metadata:
    providerFamily: review
    adapterId: coderabbit
    selectionFamily: providers
    gateRef: check-gate.py
---

# CodeRabbit review adapter (agent-mediated)

Markdown companion to `coderabbit.py` (gate path). Route local review via `/sw-review`; gate per-head state via
the executable adapter.

## Per-head signals (gate)

See `skills/checks-gate/SKILL.md` — status context, review→commit association, summary-comment markers,
grace window (`coderabbit.reviewGraceMinutes`).

## Local delta review (`/sw-review`)

```bash
coderabbit review -t uncommitted
```

Stage new untracked files before review (`git add`). Credentials from env — never config.

## Findings harvest (stabilize)

- Inline: GraphQL `reviewThreads` (paginate).
- Non-inline: `host transport repos/<owner>/<repo>/pulls/<n>/reviews` + issue comments (walkthrough/summary bodies).

Normalize to `CAPABILITIES.md` findings shape before stabilize RCA input.
