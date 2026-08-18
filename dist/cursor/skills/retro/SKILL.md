---
name: retro
description: Post-ship retrospective — what went well, painful, and should change; learning candidates for compounding. Use when running /sw-retrospective after phase or merge milestones. Report-only by default; does not auto-apply rules.
---
# Retrospective

Run after a human merge (or at end of `/sw-ship` merge gate when user merges).


**Model tier:** mid — resolve via `python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill retro`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Procedure

1. `git log --oneline -20` on shipped branch / merged PR.
2. Identify: went well, painful, process changes.
3. Compare against memory + doctrine (read-only unless user approves edits). Default exclude `status: superseded`, `resolved`, tombstone (`inactive: true`) nodes from compounding input — use `traverse --edge supersedes` when reconciling superseded decision pointers.
4. **Execution telemetry advisory (R30)** — load phase run-state telemetry and draft an
   advisory phase-authoring-improvement suggestion for human review (never auto-apply to frozen task lists):

```bash
python3 scripts/execution_telemetry.py summary
python3 scripts/execution_telemetry.py draft-suggestion
```

Surface the drafted `phase-authoring-suggestion.json` in the retrospective narrative. `autoApply` is
always false; operators apply edits to task authoring manually after review.

4. Run `python3 scripts/loop_health.py --summary` (when `loopHealth.enabled`) and fold the diagnostic loop-health summary into the retro narrative — metrics are not gating.

6. **Rule adversarial verification (R7)** — for each **rule-class** promotion candidate surfaced to compound
   write, run verifier → skeptic before the human promotion gate (unchanged):

```bash
python3 scripts/rule_verification.py verifier-brief --rule /tmp/rule.json --evidence /tmp/evidence.json
python3 scripts/rule_verification.py skeptic-brief --rule /tmp/rule.json --verifier-result /tmp/verifier.json
python3 scripts/rule_verification.py evaluate --verifier-result /tmp/verifier.json --skeptic-result /tmp/skeptic.json
```

See `references/rule-adversarial-verification.md`. `promotionReady` is advisory only — never auto-promote.

7. Output **distilled learning candidates** for the compound write step in `/sw-retrospective` — no raw transcripts.
8. Run output through `scripts/memory-redact.py` before any persistence.

Structured output for `/sw-feedback` must conform to `references/output-contract.md`.

## Planning closeout decisions (PRD 275)

These decisions are operator-facing contracts — implementation lives in planning closeout scripts, not in
this skill's report-only retro step.

### D1 — Re-pin freeze on close (#697)

When post-merge `close-delivery-units` closes a frozen planning issue, the issue-store backend appends the
newest `sw-freeze-record` hash computed from the **post-close** body including state and labels. Do not
weaken tamper detection by excluding close mutations from the hash. Partial apply (close succeeded, re-pin
failed) returns not-ready with `resumeCommand`; retry is idempotent.

### D2 — Gap-only resolver (#706)

`resolve_planning_issue_ref_to_gap` enforces `artifact_type=gap` using named authoritative evidence order
(labels → native type → body marker → content inference). Conflicting type evidence fails closed. Non-gap
refs return typed skip without freeze-check; provider/scope/auth failures are not-ready, not silent skip.

### PRD 278 closeout hardening (post-merge)

When `close-delivery-units` runs after merge detection, PRD 278 surfaces affect closure audit outcomes:

- **Numeric absorb (R6–R8):** bare issue-number absorb refs must resolve to exactly one eligible open gap;
  partial discovery or ambiguous mapping returns `not-ready` — surface the printed `resumeCommand` in retro
  narrative when closure audit fails.
- **Prefer-run-scoped adopt (R3–R5):** unrelated to retro report content; affects resume only when legacy
  slug-scoped state is adopted mid-run.
- **Phase-ship hygiene (R1–R2):** per-phase auto-repair runs during `/sw-ship --phase-mode`; retro does not
  re-run hygiene — closure evidence must already be binding from ship terminal status.

See `core/commands/sw-retrospective.md` **Closeout hardening implications** and
`core/sw-reference/layout.md` **PRD 278 closeout surfaces** (absorb map #730/#731/#739).

### Optional painful → gap handoff (when config enabled)

After emitting structured retro output, when `retrospective.gapCapture.enabled` is true, hand off painful
items to `python3 scripts/planning_gap_capture.py retro-capture --retro-json <path>` — drafts only.
Confirm and materialize are separate operator steps with digest-bound ack (see `references/output-contract.md`
and `/sw-retrospective` PRD 275 section). Default config leaves this path disabled.

## Guardrails

- Report-only — no `agentsFile`/doctrine edits without approval.
- No secrets or verbatim transcripts in output.
- Does not auto-write memory (hand off to `/sw-retrospective` compound write step).
