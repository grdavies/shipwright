---
name: feedback-closure
description: Consume GAP-BACKLOG into implementation loop and close routed signals after verification-gate confirms fix shipped. Human-gated.
---

# Feedback closure loop (IM8)

Closes the loop from `/sw-feedback` trivial-gap routing → `docs/prds/GAP-BACKLOG.md` → implementation → verified
ship. Complements `skills/feedback` (intake/route) and `skills/gap-check` (plan vs diff).


**Model tier:** mid — resolve via `python3 scripts/resolve-model-tier.py --skill feedback-closure`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Backlog entry format

```markdown
- [ ] source:feedback pr:#42 signal:fb-2026-06-001 — Add retry to webhook handler
```

Closed:

```markdown
- [x] source:feedback pr:#42 signal:fb-2026-06-001 — Add retry … (closed: 2026-06-23)
```

## Consumption (implementation loop)

| Surface | When |
| --- | --- |
| `/sw-execute` | Load open items via `feedback-backlog.py list`; treat PR/PRD-linked items as supplemental scope |
| `gap-check` | Include open backlog rows in plan mapping (alongside task checklist) |
| `living-status` | Already surfaces backlog read-only |

```bash
python3 scripts/feedback-backlog.py list --open-only --backlog docs/prds/GAP-BACKLOG.md
```


## Meta vs product routing (PRD 041)

- **Product gaps** — `gap-capture` destination writes tracked planning units immediately (PRD 033).
- **Meta/dogfood** (`destination: meta-shipwright`, `gapClass: plugin-self`) — inbox draft only until
  `planning_gap_capture.py confirm`; materialize creates the gap unit under `docs/planning/gap/`.
  Closure and consumption paths for meta units remain human-gated; never auto-close plugin-self items.

## Closure (post-verify ship)

Runs when local evidence shows the fix is verified **and** the backlog item is still open:

1. **Human confirmation** — same bar as `/sw-feedback` dispatch; never auto-close without explicit user OK.
2. **Eligibility gate** — `python3 scripts/feedback-closure-gate.py`:
   - `--backlog`, `--signal-id`, `--verify-status` (required)
   - Optional `--gate-json` + `--require-gate` when a PR exists
3. On `closable`, `python3 scripts/feedback-backlog.py close --signal-id … --backlog …`
4. `memory-preflight` write closure record (redacted); tag `surface:feedback-closure`.

### Closure verdict contract

| Verdict | Meaning | Exit |
| --- | --- | --- |
| `closable` | Open backlog item + verify passing (+ gate when required) | `0` |
| `inconclusive` | Missing/stale verify or gate evidence | `10` |
| `not-closable` | Signal not open in backlog or verify failed | `20` |

Reuses `skills/verification-gate` evidence shapes — does not override `check-gate.py` at merge.

## Integration

| Command | Role |
| --- | --- |
| `/sw-feedback-close` | Atomic closure after human confirm |
| `/sw-ship` | Offers closure step after `sw-ready` on live green (optional `--signal-id`) |
| `/sw-execute`, `gap-check` | Consume open backlog |

## Guardrails

- R41 on closure records and persisted summaries.
- Never close without human confirmation.
- Never mutate frozen PRDs/task lists — backlog only.
- Dedup: already-closed signals are `not-closable`.
