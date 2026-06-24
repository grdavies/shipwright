---
description: Classify work into Quick, Standard, or Full tiers from deterministic signals. Does not run brainstorm, PRD, freeze, or implementation phases.
alwaysApply: false
---

# `/sw-triage`

Deterministic tier classifier for the documentation pipeline. Routes work before ceremony starts.

## Scope

- Input: feature description, file/scope estimate, optional `--tier` override, optional `--re-score`.
- Output: tier decision + matched signals (auditable).
- Does **not** draft docs, freeze artifacts, or start implementation.

## Procedure

1. Load `skills/triage/SKILL.md` — apply the scoring rubric verbatim.
2. Gather inputs: file count (user estimate or diff scope), description text, flags.
3. Score deterministically per the rubric algorithm.
4. Report tier, all matched signals, and the recommended next command.
5. On `--re-score`, note prior Quick classification if promoting.

## Guardrails

- Risk triggers are a **hard floor** — auth/payments/migration/public-API work never lands Quick.
- Mixed or insufficient signals default to **Standard** (conservative).
- Manual `--tier` override is recorded in output; rubric signals still reported for audit.
- Triage is reproducible — document the matched signals every run.
