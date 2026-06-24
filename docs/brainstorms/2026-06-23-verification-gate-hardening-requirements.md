---
date: 2026-06-23
topic: verification-gate-hardening
origin: docs/plans/2026-06-23-001-feat-loop-improvement-program-plan.md
---

# Verification-Gate Hardening

## Summary

The verification gate shipped in the loop-improvement program (`skills/verification-gate/SKILL.md` +
`scripts/verify-evidence.sh`, plan 001 U1/U2) is now a trust anchor: `pf-commit`/`pf-ship` block on its
verdict and other steps consume it. A post-ship `ce-doc-review` of plan 001 found the gate is **fail-open by
construction** and built on an **untrusted evidence substrate**, so several realistic conditions let a real
regression reach `verified`/`inconclusive` and pass the pre-CI boundary. This brainstorm scopes the
hardening work (TB1–TB5 from the plan's Post-Ship Review Findings) into testable requirements: tighten verdict
attribution, close the fail-open paths, secure the `/tmp` evidence substrate, specify the override audit
record, and make the "gate required when a PR exists" condition self-verifying rather than caller-asserted.

The gate's complementary relationship to `check-gate.sh` is unchanged and out of scope: `check-gate.sh` stays
the sole green oracle, and none of this work may turn the gate into a CI override.

## Problem Frame

Plan 001's KTD1 made the gate "evidence over claims" and KTD7 made it load-bearing at the pre-CI "done"
boundary, blocking only on a **fresh, attributable `not-verified`** while `inconclusive` logs and continues.
The adversarial and security personas read the shipped `scripts/verify-evidence.sh` and found that the
combination of (a) coarse attribution, (b) `inconclusive`-on-missing-evidence, and (c) a predictable,
unauthenticated `/tmp` substrate means the blocking verdict is far weaker than the prose implies:

- **`not-verified` rarely fires.** It requires a pre-captured baseline, but no producer/owner for the baseline
  was shipped (`--baseline-*` is a manual flag and "no baseline run exists"). Absent a baseline, the verdict
  degrades to `inconclusive` → continue.
- **Skipping beats failing.** A producer that simply does not run yields "missing" → `inconclusive` → continue,
  which is *more lenient* than running and failing. The cheapest path through the gate is to not produce
  evidence at all.
- **Attribution can't see a swapped failure.** The verify fingerprint is `{exitCode, status}` and discards the
  per-command names the schema already carries, so "test_A fixed, test_B broke" looks identical to the baseline
  and is classed "pre-existing unchanged."
- **The substrate is forgeable.** Fixed-path `/tmp/*.status.json` files have no permission/ownership/integrity
  model, and R41 redaction is bound only to the *memory* edge — raw logs/diffs land in `/tmp` first, in
  plaintext, with no cleanup.

The throughline: the gate is a trust anchor on an untrusted substrate, and its single blocking state is
reachable only under conditions that rarely hold in practice.

## Key Decisions

- **Harden, don't re-architect (D1).** Keep the three-state verdict (`verified`/`not-verified`/`inconclusive`),
  the skill+script split, and the complementary-to-`check-gate.sh` posture. The fixes are to attribution,
  evidence presence/typing, substrate trust, and audit — not a new gate.
- **`inconclusive` must stop being a silent pass at the blocking boundary (D2).** The pre-CI gate's tolerance of
  `inconclusive` is the core fail-open. Resolve by distinguishing *benign* inconclusive (genuinely no
  baseline available, first run) from *suspicious* inconclusive (required evidence that should exist is
  missing/stale, or a producer that should have run did not). Suspicious-inconclusive must not silently
  continue — minimally it surfaces a loud, logged prompt; ideally it blocks like `not-verified`.
- **Attribution must use the names the schema already carries (D3).** Fingerprint on the per-command identity
  set, not just `{exitCode, status}`, so a swapped failure (one test fixed, another broken) is attributable as
  new. No new evidence format is required — the data is already present and discarded.
- **A baseline needs an owner (D4).** Either ship a baseline producer (capture against merge-base / pre-change
  head as part of the verify/gate flow) or make "no baseline" a first-class, loudly-surfaced state rather than
  a silent downgrade to `inconclusive` → continue.
- **The substrate must be trusted before its verdict is (D5).** Evidence files get an integrity/ownership model
  (e.g., run-scoped private temp dir, restrictive perms, per-run nonce, or content signature the consumer
  checks), redaction moves to the *write* edge of any persisted evidence (not only the memory edge), and a TTL
  / cleanup removes plaintext evidence after consumption. Prefer the data-pointer variant over the
  symlink-to-latest-log option (symlink-follow vector).
- **The PR-evidence requirement must be self-verifying (D6).** "Gate required when a PR exists" cannot depend on
  a caller-supplied `--require-gate` flag; the helper (or its caller contract) must detect the PR condition so
  a forgotten flag can't silently drop the requirement.
- **The override must be a real audit record (D7).** The R42-style human override (and any KTD7 "lightweight
  path for trivial changes") needs a specified record: location, fields (who, when, which verdict was
  overridden, reason), and tamper-resistance. An unlogged lightweight path is not acceptable — it would be a
  bypass strictly more attractive than the audited override.

## Requirements

| R-ID | TB | Requirement | Acceptance signal |
| --- | --- | --- | --- |
| R1 | TB1 | Verdict attribution fingerprints the per-command identity set, not just `{exitCode, status}` | Fixture: baseline `{test_A:fail}`, head `{test_A:pass, test_B:fail}` → `not-verified` (attributed as new), not `inconclusive` |
| R2 | TB2 | `inconclusive` is split into benign vs suspicious; suspicious does not silently continue at the blocking boundary | Fixture: required-but-missing evidence and "producer did not run" → suspicious → blocks or loud-logged prompt; genuine no-baseline first run → benign → continues |
| R3 | TB2/D4 | Baseline has an owner: either a producer captures it, or "no baseline" is a loud first-class state | Fixture: no baseline present → state is surfaced/logged distinctly, never a silent `inconclusive` pass |
| R4 | TB3 | Evidence substrate has an integrity/ownership model; redaction at the write edge; TTL/cleanup; no symlink-follow | Test: forged/foreign-owned `/tmp` status file is rejected or re-derived; persisted evidence is redacted at write; plaintext evidence is removed after consumption |
| R5 | TB5/D6 | The "gate required when a PR exists" condition is self-verifying, not caller-asserted | Fixture: PR context present but `--require-gate` omitted → requirement still enforced (no silent drop) |
| R6 | TB4/D7 | Override (and any lightweight path) writes a specified, tamper-resistant audit record | Test: an override produces a record with who/when/verdict/reason; no unlogged lightweight path exists |

## Scope Boundaries

### In scope

- `scripts/verify-evidence.sh`: attribution by per-command identity (R1), benign-vs-suspicious `inconclusive`
  (R2), baseline-owner / loud no-baseline state (R3), substrate integrity checks + redaction-at-write +
  TTL/cleanup (R4), self-verifying PR-evidence requirement (R5).
- `skills/verification-gate/SKILL.md` + `references/verdict-schema.json`: document the hardened contract and any
  new verdict sub-states.
- `commands/pf-commit.md` / `commands/pf-ship.md`: honor suspicious-`inconclusive` behavior and the audited
  override/lightweight-path record (R6).
- `scripts/test/run-improvement-fixtures.sh` + `fixtures/verify-evidence/*`: add the R1–R6 fixtures above.

### Out of scope / deferred

- Re-architecting the three-state verdict model or the skill+script split (D1).
- Any change that lets the gate override `check-gate.sh` / CI — it stays complementary, never authoritative.
- E2E/smoke provider behavior (`providers/verify/`, plan 001 U10) beyond the evidence it emits into the gate.
- The broader "ship-all-at-once" and "done overstates completion" findings (TB6/TB7) — process retrospectives,
  not gate code; tracked in plan 001's Post-Ship Review Findings, not here.

## Open Questions

- **Block vs loud-prompt for suspicious `inconclusive` (R2).** Does suspicious-inconclusive hard-block the
  pre-CI boundary, or surface a single logged human decision? Leaning block for "required evidence missing,"
  loud-prompt for "producer didn't run" — resolve at planning.
- **Substrate mechanism (R4).** Run-scoped private temp dir + perms vs. content signature vs. per-run nonce —
  pick the lightest mechanism that defeats forgery/TOCTOU without a daemon.
- **Baseline capture point (R3).** Merge-base vs pre-change head, and which command owns capturing it
  (`pf-verify` vs the gate vs CI) without adding a frequent mid-chain pause.

## Sources & Research

- Origin plan: `docs/plans/2026-06-23-001-feat-loop-improvement-program-plan.md` — KTD1 (gate design), KTD7
  (friction/override), U1/U2 (gate build + wiring), and the **Post-Ship Review Findings** section (TB1–TB8).
- Shipped artifacts reviewed: `scripts/verify-evidence.sh`, `skills/verification-gate/SKILL.md`,
  `skills/verification-gate/references/verdict-schema.json`.
- Guardrails honored: `scripts/check-gate.sh` (sole green oracle), `scripts/memory-redact.sh` (R41 redaction),
  R42 human-gated override.
- `ce-doc-review` panel (2026-06-23): adversarial (ADV-1–4), security-lens (SEC-1–6) findings against the
  shipped gate.
