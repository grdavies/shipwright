# Synthesis pipeline

Post-persona merge for `/sw-doc-review`. Transport-aware: file-store collects in-IDE JSON; issue-store reads
marker-delimited `sw:doc-review` comments under a review-round manifest (R69).

## Review-round manifest (R69) — issue-store only

At synthesis checkpoint open (PRD 043 R33 exclusive checkpoint):

1. **Pin** — record ordered persona-comment IDs + revisions in a review-round manifest (checkpoint-scoped).
2. **Read-back** — paginated, concurrency-checked fetch of pinned comments only.
3. **Verify** — each comment: bot authorship + `sw:doc-review` marker present; forged/non-bot comments rejected.
4. **Fail closed** — any add/edit/delete to pinned comments before synthesis completes **fail closed** with
   `doc-review-comment-drift`.
5. **Exclude from freeze hash** — `sw:doc-review` marker comments are excluded from PRD 043 R35 canonicalization.

Manifest shape mirrors PRD 043 R9 freeze-record pinning (ordered IDs + revisions at checkpoint open).

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

## Bounded loop (R29)

- Max **2** synthesis rounds.
- Stop early if round produces zero new applicable findings (no-progress).
- Never exceed max rounds — surface remaining items as deferred.

## Partial panel failure

If a persona sub-agent fails, log the failure and proceed with partial coverage. Do not block the entire panel.

## Amendment review

When reviewing amendments (U7), coherence + scope-guardian + docs-currency always run against the frozen parent:

- Verify every `supersedes`/`retracts` target exists in parent.
- Reject targets already retracted.
- Flag undeclared contradictions with parent requirements.
- Parent file is read-only — edits apply only to the amendment draft.
