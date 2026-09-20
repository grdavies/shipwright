# Synthesis pipeline

Post-persona merge for `/sw-doc-review`. Transport-aware: file-store collects in-IDE JSON; issue-store reads
marker-delimited `sw-doc-review` comments under a review-round manifest (PRD 341).

## Review-round identity (R37)

In-loop synthesis (same panel, same `roundId`, bounded to two passes) is **not** a new facade round.
Reuse the open round's `roundId` through collect → verify → synthesize → complete → apply.

Open a **new** `roundId` when any of these apply:

- a late persona retry arrives after the round is closed/completed
- a newly selected panel runs

While a round witness is **open**, do **not** open a fresh `roundId` to recover from verify drift.
After R3-corrected verify (exhaustive permutation vs provider chronology is not reorder drift), recovery is
`complete_review_round` on the **same** `roundId` — not supersession and not skip-verify.

A completed round is not reopenable under the same `roundId`. Freeze stays blocked until the latest
expected round has a completion receipt (GitHub v1 also requires closed body status).

## Review-round manifest — issue-store only

### New rounds (post-then-open / complete)

**Sequence:** persona `doc-review-round-post`(s) → `doc-review-round-open` →
`doc-review-round-read` + `doc-review-round-verify` → synthesis steps below → `doc-review-round-close`
(`complete_review_round`). Findings use `apiVersion` `DocReviewFinding` envelopes; pins use
`body-sha256/v1`.

At synthesis checkpoint (issue-store — complete then apply):

1. **Post** — each `doc-review-round-post` adds a brokered `sw-doc-review` comment (no body pin yet).
2. **Open** — `doc-review-round-open` writes the etag-guarded body witness with exhaustive pins.
3. **Read-back** — `doc-review-round-read` returns pinned rows; binding is re-checked on every refreshed read.
4. **Verify** — `doc-review-round-verify` checks bot authorship, marker/envelope consistency,
   manifest binding, and pin parity; fail closed with `doc-review-comment-drift`. Manifest mutations are one
   etag-guarded update per verb — `revision-conflict` halts without automatic retry; re-run the whole verb.
5. **Synthesize** — only after verify passes; merge/dedup findings **in memory** and decide dispositions.
   Do **not** mutate the issue body here — completion re-verifies the closed witness. Keep the same `roundId`.
6. **Complete** — `doc-review-round-close` against the **unchanged** witness (verify runs again before close +
   receipt). Bounded-loop extra passes on the same `roundId` merge findings only and must finish before complete.
7. **Apply** — on a **fresh read** after complete, apply `safe_auto` / gate `gated_auto` / `manual` while
   preserving the closed witness on the body. Do not call verify or complete again on that `roundId`.

### In-flight bootstrap rounds (#1070 — open-then-post / close)

Rounds opened before facade mapping finish on the shipped path: `doc-review-round-open` →
persona `doc-review-round-post`(s) that append `updated_at` pins → verify → synthesize →
`doc-review-round-close` → fresh-read apply. Accept shipped finding envelopes `{round, persona, payload}` (R43).
Do not mix bootstrap envelopes into a **new** round open — that is `doc-review-mixed-schema`.

**GitHub** and **Linear** issue-store transports are live when `docReviewComments` preflight passes.
**Jira** and **Notion** are fixture-enabled-not-dogfooded — not operator-live; halt with
`doc-review-provider-unsupported` when preflight refuses. Do not synthesize from issue comments when
transport preflight fails.

Manifest pins are excluded from PRD 043 R35 canonicalization (`sw-doc-review` marker comments).
**Stripped-hash / body-drift:** the live `sw-doc-review-round` witness remains on the issue body but is
excluded from `body-sha256/v1` and frozen hash inputs — never delete the live witness from the body to
“fix” a hash. Drift that changes stripped body bytes fails verify as body-drift.

**Cache-only run artifacts:** `.cursor/doc-review-runs/` (and related prompt scratch) are gitignored and
non-authoritative — synthesis authority is the issue-store facade + draft under review, not cache files.

## Steps

1. **Collect** — gather JSON findings from each dispatched persona (in-IDE JSON or issue-store comments under manifest).
2. **Validate** — drop findings that fail `findings-schema.json`.
3. **Dedup/merge** — same section + same issue from multiple personas → single finding (highest severity wins).
4. **Route by `autofix_class` (disposition only until apply time):**
   - `safe_auto` — mark for silent apply of `suggested_fix` to the PRD draft.
   - `gated_auto` — present fix; apply only after user confirms.
   - `manual` — surface as trade-off; halt orchestrator until user decides.
   Do **not** mutate a body that will be re-verified at complete (issue-store). File-store has no closed
   witness — apply after the synthesis report per `SKILL.md` Dispatch.
5. **Docs-currency findings** (`sw-docs-currency-reviewer`) — recommended documentation-artifact updates
   (path + required change) fold into PRD requirements / tasks on acceptance via `gated_auto` or `manual`.
   Never silent auto-edit of docs or the parent file; never a hard freeze/ship block.
6. **Report** — list dispositions, gated items, manual trade-offs, residual risks (and applied fixes once
   the transport-appropriate apply step has run).

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
