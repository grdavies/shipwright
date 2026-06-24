# Synthesis pipeline

Post-persona merge for `/sw-doc-review`.

## Steps

1. **Collect** — gather JSON findings from each dispatched persona.
2. **Validate** — drop findings that fail `findings-schema.json`.
3. **Dedup/merge** — same section + same issue from multiple personas → single finding (highest severity wins).
4. **Route by `autofix_class`:**
   - `safe_auto` — apply `suggested_fix` silently to the PRD draft.
   - `gated_auto` — present fix; apply only after user confirms.
   - `manual` — surface as trade-off; halt orchestrator until user decides.
5. **Report** — list applied fixes, gated items, manual trade-offs, residual risks.

## Bounded loop (R29)

- Max **2** synthesis rounds.
- Stop early if round produces zero new applicable findings (no-progress).
- Never exceed max rounds — surface remaining items as deferred.

## Partial panel failure

If a persona sub-agent fails, log the failure and proceed with partial coverage. Do not block the entire panel.

## Amendment review

When reviewing amendments (U7), coherence + scope-guardian always run against the frozen parent:

- Verify every `supersedes`/`retracts` target exists in parent.
- Reject targets already retracted.
- Flag undeclared contradictions with parent requirements.
- Parent file is read-only — edits apply only to the amendment draft.
