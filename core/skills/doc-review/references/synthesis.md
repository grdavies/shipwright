# Synthesis pipeline

Post-persona merge for `/sw-doc-review`. Transport-aware: file-store collects in-IDE JSON; issue-store reads
marker-delimited `sw-doc-review` comments under a review-round manifest (PRD 341).

## Review-round identity (R37)

In-loop synthesis (same panel, same `roundId`, bounded to two passes) is **not** a new facade round.
Reuse the open round's `roundId` through collect → verify → synthesize → complete/close.

Open a **new** `roundId` when any of these apply:

- verify refuses or detects drift and recovery needs a fresh snapshot
- a late persona retry arrives after the round is closed/completed
- a newly selected panel runs

A completed round is not reopenable under the same `roundId`. Freeze stays blocked until the latest
expected round has a completion receipt (GitHub v1 also requires closed body status).

## Review-round manifest — issue-store only

### New rounds (post-then-open / complete)

**Sequence:** persona `doc-review-round-post`(s) → `doc-review-round-open` →
`doc-review-round-read` + `doc-review-round-verify` → synthesis steps below → `doc-review-round-close`
(`complete_review_round`). Findings use `apiVersion` `DocReviewFinding` envelopes; pins use
`body-sha256/v1`.

At synthesis checkpoint:

1. **Post** — each `doc-review-round-post` adds a brokered `sw-doc-review` comment (no body pin yet).
2. **Open** — `doc-review-round-open` writes the etag-guarded body witness with exhaustive pins.
3. **Read-back** — `doc-review-round-read` returns pinned rows; binding is re-checked on every refreshed read.
4. **Verify** — `doc-review-round-verify` checks bot authorship, marker/envelope consistency,
   manifest binding, and pin parity; fail closed with `doc-review-comment-drift`. Manifest mutations are one
   etag-guarded update per verb — `revision-conflict` halts without automatic retry; re-run the whole verb.
5. **Synthesize** — only after verify passes; apply autofix routing below. Keep the same `roundId`.
6. **Complete** — `doc-review-round-close` after synthesis (verify runs again before close + receipt).

### In-flight bootstrap rounds (#1070 — open-then-post / close)

Rounds opened before facade mapping finish on the shipped path: `doc-review-round-open` →
persona `doc-review-round-post`(s) that append `updated_at` pins → verify → synthesize →
`doc-review-round-close`. Accept shipped finding envelopes `{round, persona, payload}` (R43).
Do not mix bootstrap envelopes into a **new** round open — that is `doc-review-mixed-schema`.

Unsupported providers halt with `doc-review-provider-unsupported` / transport refusal — do not
synthesize from issue comments.

Manifest pins are excluded from PRD 043 R35 canonicalization (`sw-doc-review` marker comments).

## Steps

1. **Collect** — gather JSON findings from each dispatched persona (in-IDE JSON or issue-store comments under manifest).
2. **Validate** — drop findings that fail `findings-schema.json`.
3. **Dedup/merge** — same section + same issue from multiple personas → single finding (highest severity wins).
4. **Route by `autofix_class`:**
   - `safe_auto` — apply `suggested_fix` silently to the PRD draft.
   - `gated_auto` — present fix; apply only after user confirms.
   - `manual` — surface as trade-off; halt orchestrator until user decides.
5. **Docs-currency findings** (`sw-docs-currency-reviewer`) — recommended documentation-artifact updates
   (path + required change) fold into PRD requirements / tasks on acceptance via `gated_auto` or `manual`.
   Never silent auto-edit of docs or the parent file; never a hard freeze/ship block.
6. **Report** — list applied fixes, gated items, manual trade-offs, residual risks.

## Disposition disputes (calibration-loop)

When two personas assign different `autofix_class` to the same deduped finding, or the operator pushes back
on a `gated_auto`/`manual` disposition the synthesizer assigned, do not silently pick one side and do not
re-ask the same abstract "which disposition?" question. Load `skills/calibration-loop/SKILL.md`: frame the
dispute as an A/B tension (e.g. "auto-apply mechanical rewording" vs "always gate wording changes near
requirements text"), present concrete finding instances, and converge on a principle. Record the converged
principle in the synthesis report alongside the disputed finding's final disposition; it also informs
disposition for any later same-class finding in the same review round.

## Bounded loop (R29 / R37)

- Max **2** synthesis passes on the **same** `roundId`.
- Stop early if a pass produces zero new applicable findings (no-progress).
- Never exceed max passes — surface remaining items as deferred.
- A new panel or post-close retry starts a new `roundId`.

## Partial panel failure

If a persona sub-agent fails, log the failure and proceed with partial coverage. Do not block the entire panel.

## Amendment review

When reviewing amendments (U7), coherence + scope-guardian + docs-currency always run against the frozen parent:

- Verify every `supersedes`/`retracts` target exists in parent.
- Reject targets already retracted.
- Flag undeclared contradictions with parent requirements.
- Parent file is read-only — edits apply only to the amendment draft.
