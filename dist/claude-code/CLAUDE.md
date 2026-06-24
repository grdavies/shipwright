# phase-flow v2


## pf-freeze-guardrail

---
description: Never edit a file with frozen: true in frontmatter. Post-freeze changes use /pf-amend only.
alwaysApply: true
---

# Frozen artifact guardrail

Files with `frozen: true` in YAML frontmatter are **immutable**. Do not edit, rename, or delete them.

## If change needed

1. Run `/pf-amend` to create a sibling amendment file.
2. Review via `/pf-doc-review` (coherence + scope-guardian always run against parent).
3. Freeze the amendment via `/pf-freeze`.

## Enforcement layers

- This rule — agent instruction (early warning).
- `hooks/pre-commit-frozen.sh` — local commit block (bypassable with `--no-verify`).
- `scripts/check-frozen.sh` — CI required-check (authoritative; not bypassable).

There is **no unfreeze** command.


## pf-naming

---
description: pf- command namespace, orchestrator vs atomic boundaries, and naming conventions for phase-flow v2.
alwaysApply: true
---

# pf- naming and command boundaries

All plugin commands, skills exposed as commands, and user-facing workflow entry points use the **`pf-`**
prefix (e.g. `/pf-review`, `/pf-stabilize`, `/pf-memory-sync`). This namespace is distinct from phase-flow
v1 (unprefixed) and compound-engineering (`ce-`).

## Orchestrators vs atomic commands

- **Orchestrators** chain multiple phases:
  - `/pf-doc` — brainstorm → PRD → persona panel → freeze → tasks (tier-gated; see documentation workstream).
  - `/pf-ship` — execute → verify → review → gaps → commit → pr → watch-ci → stabilize → ready (halts at merge gate).
  - `/pf-debug` — triage signal → Sentry enrich (optional) → RCA core (debug entry) → route by fix size; does not implement or merge.
  - `/pf-feedback` — normalize + redact inbound signals → route to debug, gap-capture, or brainstorm; does not analyze or author.
  Their descriptions must state the full chain and which atomic commands they subsume.
- **Atomic commands** perform one bounded step (e.g. `/pf-watch-ci`, `/pf-memory-sync`, `/pf-triage`). Their descriptions
  must state what they do **and what they do not do** (e.g. "polls CI; does not merge or fix failures").

## Triage boundary

`/pf-triage` classifies tier only — it does not draft docs, freeze artifacts, or start implementation. Routing after triage is explicit in the triage output.

## Documentation orchestrator boundary

`/pf-doc` delegates to atomic doc commands; it does not reimplement their procedures. Each atomic (`/pf-brainstorm`, `/pf-prd`, `/pf-doc-review`, `/pf-freeze`, `/pf-tasks`) remains independently runnable.

## Debug orchestrator boundary

`/pf-debug` diagnoses via `skills/rca-core` (debug entry) and routes — it does not run `/pf-execute`, `/pf-ship`, or patch on bare `main`. Small fixes hand off to `/pf-worktree` + `/pf-start`; substantial fixes hand off to `/pf-brainstorm` or `/pf-amend`. `/pf-stabilize` remains the in-loop PR blocker surface.

## Feedback orchestrator boundary

`/pf-feedback` normalizes and routes inbound signals — it does not run `/pf-debug` analysis, `/pf-amend` authoring, or task execution. Production signals with error/crash/regression markers dispatch to `/pf-debug`; PR-extending work splits to `/pf-amend` or `docs/prds/GAP-BACKLOG.md`; new scope dispatches to `/pf-brainstorm`. Human confirmation required before dispatching any route (including agent callers).

## Naming rules

1. Prefix every command file with `pf-` (e.g. `commands/pf-review.md`).
2. Skill directories use descriptive kebab-case without the prefix (e.g. `skills/checks-gate/`).
3. Rules use `pf-` when they encode plugin-specific guardrails (e.g. `pf-naming.mdc`, `pf-guardrails.mdc`).
4. Provider adapters live under `providers/`; executable adapters use `.sh` (e.g. `providers/review/coderabbit.sh`).

## Description contract

Every command frontmatter `description` must be one sentence on scope plus one on explicit non-goals when
ambiguity is likely.

## Model tier floor (R9)

Semantic tiers (`cheap`/`build`/`deep`) live in `workflow.config.json` `models.tiers` only — not in agent
`model:` frontmatter. Reviewer agents use `model: inherit` or a concrete platform ID. Validated by
`scripts/model-tier-check.sh` (config + concrete models); runtime R9 for `inherit` reviewers is enforced at
dispatch by `/pf-doc-review` and `rules/pf-subagent-dispatch.mdc`. See `.pf/models-tiering.md`.

