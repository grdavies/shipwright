---
name: simplify
description: Behavior-preserving cleanup pass (reuse, quality, efficiency, AI-slop removal) after review. Use when /sw-ship runs post-review deslop before gap-check. Re-verified via simplify-gate; does not skip verify.
---
# Simplification / deslop pass (IM7)

Post-review, pre-commit cleanup on the uncommitted delta. **Behavior-preserving only** — no new features, no
scope expansion, no weakened tests. Complements `/sw-review` (findings) and `gap-check` (requirements); does
not replace either.


**Model tier:** mid — resolve via `python3 scripts/resolve-model-tier.py --skill simplify`. When using the Task tool for subagent dispatch, resolve concrete model IDs from `models.tiers` in config (never semantic tier names in subagent `model:` frontmatter).

## When it runs

- Default-on in `/sw-ship` after `/sw-review`, before `gap-check`.
- Standalone: `/sw-simplify` anytime on uncommitted work.
- Skip: `/sw-ship --fast` (with gap-check) or explicit `--skip-simplify`.

## Pass categories

Apply only when removal/simplification cannot change observable behavior:

| Category | Examples |
| --- | --- |
| **Reuse** | Inline duplicate → existing helper; collapse copy-paste branches |
| **Quality** | Dead code, unused imports, unreachable branches |
| **Efficiency** | Redundant work (double fetch, needless re-parse) without semantic change |
| **AI slop** | Obvious comments (`// increment i`), filler docstrings, over-wrapped one-liners, defensive try/catch that only rethrows |

## Procedure

1. **Baseline evidence** — copy `/tmp/sw-verify.status.json` → `/tmp/sw-verify.pre-simplify.json` when present.
2. **Scope** — `git diff` + `git diff --cached`; if empty, report `skipped` and stop.
3. **Simplify** — edit delta only; honor `agentsFile` doctrine; no test assertion weakening.
4. **Re-verify** — run `/sw-verify` (or equivalent config commands); refresh `/tmp/sw-verify.status.json`.
5. **Behavior gate** — `python3 scripts/simplify-gate.py`:
   - `--baseline-verify /tmp/sw-verify.pre-simplify.json`
   - `--post-verify /tmp/sw-verify.status.json`
6. Emit `/tmp/sw-simplify.status.json` with `{verdict, baseline, post, findings}`.
7. Hand off to `gap-check` / `/sw-commit` on `preserved` or `inconclusive`; **halt** on `regressed`.

## Verdict contract (`scripts/simplify-gate.py`)

| Verdict | Meaning | Exit |
| --- | --- | --- |
| `preserved` | Baseline and post verify both pass | `0` |
| `inconclusive` | Missing baseline or pre-simplify verify was not passing | `10` |
| `regressed` | Baseline passed but post verify failed | `20` |

Pairs with `skills/verification-gate` — simplify-gate is **behavior-preservation across the cleanup**, not CI
truth (`check-gate.py` remains authoritative at merge).

## Guardrails

- No commits, push, PR, or merge from this step.
- Never auto-delete tests or loosen assertions to green.
- Security-sensitive surfaces (auth, secrets, CI config) — surface for human review; do not bulk-simplify.
- Persisted summaries through `python3 scripts/memory-redact.py` (R41).
- Slots alongside future local code-review (`providers/code-review/`) — does not duplicate persona review.


## Refactor-vs-simplify boundary (PRD 039 R7)

`/sw-simplify` is **post-review, phase-level deslop** on the uncommitted delta. The per-task **refactor** step
in `skills/execute-discipline` runs earlier (after green, before stage-1 review) and consumes the quality
harness signal. This skill does not replace or inline refactor.
