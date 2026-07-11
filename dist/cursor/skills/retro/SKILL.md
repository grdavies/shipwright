---
name: retro
description: Post-ship retrospective — what went well, painful, and should change; learning candidates for compounding. Use when running /sw-retrospective after phase or merge milestones. Report-only by default; does not auto-apply rules.
---
# Retrospective

Run after a human merge (or at end of `/sw-ship` merge gate when user merges).


**Model tier:** mid — resolve via `python3 scripts/resolve-model-tier.py --skill retro`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## Procedure

1. `git log --oneline -20` on shipped branch / merged PR.
2. Identify: went well, painful, process changes.
3. Compare against memory + doctrine (read-only unless user approves edits).
4. Run `python3 scripts/loop_health.py --summary` (when `loopHealth.enabled`) and fold the diagnostic loop-health summary into the retro narrative — metrics are not gating.
5. Output **distilled learning candidates** for the compound write step in `/sw-retrospective` — no raw transcripts.
6. Run output through `scripts/memory-redact.py` before any persistence.

Structured output for `/sw-feedback` must conform to `references/output-contract.md`.

## Guardrails

- Report-only — no `agentsFile`/doctrine edits without approval.
- No secrets or verbatim transcripts in output.
- Does not auto-write memory (hand off to `/sw-retrospective` compound write step).
