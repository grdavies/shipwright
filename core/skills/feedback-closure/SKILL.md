---
name: feedback-closure
description: Consume GAP-BACKLOG into implementation loop and close routed signals after verification-gate confirms fix shipped. Human-gated.
---

# Feedback closure loop (IM8)

Closes the loop from `/pf-feedback` trivial-gap routing → `docs/prds/GAP-BACKLOG.md` → implementation → verified
ship. Complements `skills/feedback` (intake/route) and `skills/gap-check` (plan vs diff).

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
| `/pf-execute` | Load open items via `feedback-backlog.sh list`; treat PR/PRD-linked items as supplemental scope |
| `gap-check` | Include open backlog rows in plan mapping (alongside task checklist) |
| `living-status` | Already surfaces backlog read-only |

```bash
bash scripts/feedback-backlog.sh list --open-only --backlog docs/prds/GAP-BACKLOG.md
```

## Closure (post-verify ship)

Runs when local evidence shows the fix is verified **and** the backlog item is still open:

1. **Human confirmation** — same bar as `/pf-feedback` dispatch; never auto-close without explicit user OK.
2. **Eligibility gate** — `bash scripts/feedback-closure-gate.sh`:
   - `--backlog`, `--signal-id`, `--verify-status` (required)
   - Optional `--gate-json` + `--require-gate` when a PR exists
3. On `closable`, `bash scripts/feedback-backlog.sh close --signal-id … --backlog …`
4. `memory-preflight` write closure record (redacted); tag `surface:feedback-closure`.

### Closure verdict contract

| Verdict | Meaning | Exit |
| --- | --- | --- |
| `closable` | Open backlog item + verify passing (+ gate when required) | `0` |
| `inconclusive` | Missing/stale verify or gate evidence | `10` |
| `not-closable` | Signal not open in backlog or verify failed | `20` |

Reuses `skills/verification-gate` evidence shapes — does not override `check-gate.sh` at merge.

## Integration

| Command | Role |
| --- | --- |
| `/pf-feedback-close` | Atomic closure after human confirm |
| `/pf-ship` | Offers closure step after `pf-ready` on live green (optional `--signal-id`) |
| `/pf-execute`, `gap-check` | Consume open backlog |

## Guardrails

- R41 on closure records and persisted summaries.
- Never close without human confirmation.
- Never mutate frozen PRDs/task lists — backlog only.
- Dedup: already-closed signals are `not-closable`.
