---
date: 2026-06-24
topic: first-run-onboarding-ux
brainstorm: docs/brainstorms/2026-06-24-first-run-onboarding-ux-requirements.md
frozen: true
frozen_at: 2026-06-24
---

# PRD 002 — First-Run Onboarding UX

## Overview

A first real run of `/sw-doc` surfaced three coupled defects that make Shipwright confusing and unsafe for new
users. (1) The documentation pipeline advanced through task generation and then implemented deliverables
directly on bare `main` with no worktree, because the doc→implementation boundary is advisory prose rather than
an enforced control, and `/sw-tasks` produces a deliberately partial task list gated behind an ambiguous "Go"
prompt that reads as "finish the work." (2) Review gating defaults to `coderabbit`, which hangs on repos not
onboarded to CodeRabbit. (3) The review opt-out is expressed two redundant ways (`review.provider: "none"` and
`review.enabled: false`) while the term "disabled" is overloaded across a config knob and a gate output state.

This PRD makes the doc→implementation boundary an explicit, configurable control with a non-negotiable worktree
invariant; makes `/sw-tasks` generate a complete task list in a single pass with no user intervention; sets a
safe out-of-box review default of `none`; and collapses the review opt-out to a single canonical expression with
de-overloaded vocabulary. It carries forward requirements R1–R25 from the frozen-pending brainstorm.

## Goals

- A first-run `/sw-doc` on a clean repo never leaves uncommitted implementation changes on `main`.
- The doc→implementation transition is one explicit, discoverable, configurable checkpoint — not two confusable
  ones.
- `/sw-tasks` always emits one complete task list; users never see a partial artifact or a "finish the list"
  prompt.
- A repo with no review provider configured runs the full workflow to a green gate without hanging and without
  any CodeRabbit dependency.
- There is exactly one canonical, documented way to disable review gating; no term means two different things.
- Existing repos upgrade with zero required config edits.
- **Outcome signal:** observed first-run sessions no longer reach implementation without a deliberate, explicit
  step, and no longer require the user to manually create a branch after code already exists on `main` — the
  falsifiable signal that the confusion is actually fixed, not relocated.

## Non-Goals

- No new review providers and no change to CodeRabbit adapter behavior beyond default/opt-out wiring.
- No change to `check-gate.py` verdict (pass/fail) logic beyond renaming the opt-out output state.
- No changes to memory, verify/CI, or worktree internals beyond enforcing the existing worktree invariant.
- No redesign of the broader `/sw-ship` implementation loop.
- No targeted in-place editor for an already-generated task list (see Decision Log DL5).

## Requirements

### Doc→implementation boundary

- **R1** A configuration key `doc.afterTasks` accepts exactly the values `stop`, `confirm`, and `auto`, and
  defaults to `confirm` when unset.
- **R2** In `confirm` mode the orchestrator presents the full frozen task list and then issues a runtime prompt
  that explicitly asks whether to begin implementation and states the exact expected token(s). Only a
  tightly-matched affirmative (case-insensitive `proceed` or `yes` to the implementation question) proceeds; the
  legacy token `Go`, silence, or any ambiguous reply maps to `stop` (no implementation).
- **R3** In `confirm` mode, a declined or absent acknowledgement results in `stop` behavior (no implementation).
- **R4** In `stop` mode the orchestrator halts after the task list is frozen and prints the frozen task-list path
  plus the exact next command(s) to begin implementation.
- **R5** In `auto` mode the orchestrator provisions a worktree/branch and **dispatches** the implementation loop
  (`/sw-worktree` → `/sw-start`, or `/sw-ship`) without a second prompt, emitting a one-line
  `implementing on branch <name>` notice first; the doc orchestrator does not itself perform implementation in
  any mode.
- **R6** Across all modes, no implementation file is written while on bare `main`; a worktree/branch is
  provisioned before any implementation begins, enforced by a deterministic fail-closed guard (R27) — not by
  orchestrator prose. This invariant is independent of `doc.afterTasks` and cannot be disabled by configuration.
- **R7** `/sw-setup` includes a step that sets the `doc.afterTasks` default and writes a schema-valid value.
- **R8** A per-run override `/sw-doc --after-tasks=<mode>` sets the boundary mode for that invocation, overriding
  the configured default. When an agent (not a human) supplies `--after-tasks=auto`, the choice is recorded in
  the run record so the bypass of the human checkpoint is attributable.
- **R9** `/sw-tasks` generates the complete task list (parent phases, executable sub-tasks, and the traceability
  table) in a single pass and freezes it, with no mandatory user-intervention gate, except the existing
  overwrite confirmation when a frozen task list already exists on re-run; the prior "Go" sub-task-expansion gate
  is removed.
- **R10** The `/sw-doc` orchestrator never performs implementation itself in any mode: `stop` halts,
  `confirm` halts until an explicit ack then dispatches, and `auto` dispatches the implementation loop. This
  preserves and is consistent with the existing "does not run implementation" guardrail (the orchestrator
  dispatches the implementation workstream; it does not inline implementation).
- **R26** The `/sw-doc` command contract and the always-applied `rules/sw-naming.mdc` documentation-orchestrator
  boundary are amended to permit the `auto`-mode auto-dispatch handoff (provision + dispatch), while keeping the
  invariant that the doc orchestrator does not inline implementation.
- **R27** A deterministic, fail-closed guard (`scripts/sw-assert-worktree.py` or an equivalent pre-write hook)
  aborts any implementation step when `HEAD` resolves to the default branch with no active worktree gitdir; a
  negative-path fixture asserts it blocks a simulated write on bare `main`. The guard must distinguish
  legitimately-allowed-on-main flows (e.g. hotfix/release paths) from doc→implementation work.

### Review default

- **R11** The config schema's default for `review.provider` is `none`.
- **R12** The `check-gate.py` fallback value for an absent `review.provider` is `none` (not `coderabbit`). A
  never-configured repo (provider resolved from the default, key unset) is reported as `unconfigured`
  ("review off by default — never configured"), distinct from an explicit opt-out — see R28.
- **R13** The canonical `.sw/workflow.config.example.json` sets `review.provider` to `none`; derived copies
  (`core/sw-reference/workflow.config.example.json` and any emitted `dist/` copy) are regenerated from canonical
  sources, not hand-edited.
- **R14** Command and reference docs (e.g. `sw-review.md`) no longer describe CodeRabbit as the default review
  provider; CodeRabbit is documented as an explicit opt-in.
- **R15** `/sw-setup` does not preselect `coderabbit`; the default review selection is `none`.

### Review opt-out clarity

- **R16** `review.provider: "none"` is documented as the single canonical way to disable review gating.
- **R17** `review.enabled: false` continues to opt out (back-compat) but emits a deprecation warning when used.
  The warning is emitted off the `check-gate.py` stdout JSON contract — via stderr and/or a `deprecations[]`
  field inside the verdict JSON and/or surfaced by `/sw-setup` doctor — never as stray stdout text that would
  corrupt JSON-parsing consumers (`/sw-watch-ci`, stabilize).
- **R18** The config schema marks `review.enabled` as deprecated, pointing to `review.provider: "none"`.
- **R19** `/sw-setup`'s review choice presents `coderabbit | none` only; no separate `disabled` option.
- **R20** The gate output state previously named `disabled` is renamed `off` at every literal-`disabled` site:
  the `check-gate.py` emitter (`CR_STATE`, `CR_STATUS`), the green-verdict reason switch (so opt-out/unconfigured
  never fall through to "review landed"), `providers/review/CAPABILITIES.md`, any normalizer/consumer, gate
  fixtures (incl. `scripts/test/run-gate-fixtures.sh` which asserts `state=disabled`), the schema description,
  README, and emitted `dist/` copies. A grep-based test asserts no `disabled` literal remains in gate code,
  consumers, or fixtures.
- **R21** Opt-out remains non-blocking and gate-green-compatible (pass/fail behavior unchanged); the opt-out
  verdict reason must explicitly read as "review gating off" and never as "review landed".
- **R28** The gate distinguishes an explicit opt-out (`off`) from a never-configured default (`unconfigured`):
  both are non-blocking, but neither reports "review landed", and their verdict reasons are worded distinctly so
  a fresh default repo is not labelled a deliberate opt-out.
- **R29** Human-facing surfaces (`/sw-ready`, `living-status`) echo the review state ("review: off" or
  "review: not configured") so a green gate with no review is not mistaken for a reviewed change.

### Cross-cutting

- **R22** Existing repo configs continue to validate and run without edits. Caveat: a repo onboarded to
  CodeRabbit but relying on the implicit `coderabbit` default (provider unset) flips to review-off after upgrade;
  this behavior change is called out in migration notes and surfaced by a `/sw-setup` doctor notice when the
  CodeRabbit CLI is present but `review.provider` is unset.
- **R23** User-facing documentation (README / getting-started / commands reference) is updated to describe the
  three boundary modes, the worktree invariant, single-pass task generation, the `none` review default, and the
  canonical opt-out.
- **R24** In the `/sw-doc` chain, the `doc.afterTasks` boundary is the sole human checkpoint between PRD freeze
  and implementation; task generation introduces no additional blocking prompt.
- **R25** Run standalone (outside `/sw-doc`), `/sw-tasks` outputs the complete frozen task list and stops without
  prompting the user (the overwrite confirmation in R9 is the only exception).
- **R30** `/sw-ship` accepts the same `--after-tasks=<mode>` flag with real effect: the PRD specifies the
  `/sw-ship` doc-chain integration point at which the flag applies (the boundary between a frozen task list and
  the `/sw-ship` implementation loop), so the parity flag is not inert.

## Technical Requirements

### Source-of-truth / build chain

- Canonical sources live at repo root (`.sw/`, `scripts/`, `commands/`, `skills/`, `providers/`, `rules/`).
  `core/` is regenerated from these by `scripts/copy-to-core.sh` (e.g. `.sw/` → `core/sw-reference/`), and
  `dist/cursor` + `dist/claude-code` are produced by the emitter (`python3 -m sw generate --all`). Edit canonical
  sources only; never hand-edit `core/` or `dist/`. Any change here must regenerate `core/` + `dist/` and refresh
  the parity golden manifest (`scripts/test/fixtures/parity/cursor-golden.manifest`) or the CI freshness/parity
  gates fail.

### Configuration surface

- Add a `doc` object to `.sw/config.schema.json` with property `afterTasks` (`enum: [stop, confirm, auto]`,
  `default: confirm`). Mirror into the canonical `.sw/workflow.config.example.json`; regenerate derived copies.
- Change the `review.provider` schema `default` to `none` and update the property description so `coderabbit` is
  described as opt-in.
- Mark `review.enabled` deprecated in the schema description (point to `review.provider: "none"`); keep it valid
  for back-compat. The existing `allowEmptyRules`-style deprecation phrasing is the precedent.
- `check-gate.py`: change the `REVIEW_PROVIDER` fallback from `coderabbit` to `none`; rename the emitted opt-out
  state string `disabled` → `off` (`CR_STATE`, `CR_STATUS`, JSON keys/consumers, **and the green-verdict reason
  switch** so opt-out/unconfigured never fall through to a "review landed" reason). Distinguish the
  never-configured default (`unconfigured`) from the explicit opt-out (`off`) per R28. Preserve
  `perHeadLanded: true` / non-blocking semantics. The R17 deprecation warning is emitted off the stdout JSON
  contract (stderr / `deprecations[]` field / `/sw-setup` doctor).

### Review-state vocabulary (prior-art interaction)

- The review-state model was defined in memory #2074 and `providers/review/CAPABILITIES.md` (states `landed`,
  `skipped`, `clean`, `absent`, `unconfigured`, `in-flight`, `disabled`). R20 renames only the opt-out state
  `disabled` → `off`; the `unconfigured` state is **retained and made reachable** for never-configured default
  repos (R28). All literal-`disabled` sites must be updated together: `check-gate.py` (emitter + green-reason
  switch), `CAPABILITIES.md`, normalizers, `scripts/test/run-gate-fixtures.sh` (currently asserts
  `state=disabled`), `config.schema.json` description, README, and emitted `dist/` copies — verified by a
  grep-based no-`disabled`-literal test.
- The adapter seam (`review.provider`, memory #2069/#2058) is unchanged; `none` remains a recognized non-adapter
  sentinel handled before adapter dispatch in `check-gate.py`.

### Orchestrator + tasks behavior

- `/sw-doc` reads `doc.afterTasks` (with `--after-tasks` override) after task freeze and branches into
  stop/confirm/auto. The orchestrator never inlines implementation: `auto` provisions a worktree and dispatches
  the implementation loop (R5/R10/R26). The worktree invariant (R6) is enforced by the deterministic guard (R27),
  not by orchestrator prose. `sw-doc.md` Procedure step 9 ("with Go gate") and step 10, and the Guardrails "Go"
  reference, are rewritten to the afterTasks branch + dispatch; `rules/sw-naming.mdc` doc-orchestrator boundary
  is amended for auto-dispatch (R26).
- `/sw-tasks` (command + `skills/tasks/SKILL.md`) removes the "pause for Go" step and the
  "Go gate is mandatory" guardrail; the collision policy is rewritten in single-pass terms ("first run:
  generate complete list; re-run: full overwrite requires confirmation") rather than the removed Go-resume
  phrasing. Sub-task expansion + traceability + freeze run in one pass.
- `/sw-ship` accepts the same `--after-tasks` flag with a specified doc-chain integration point so the flag is
  not inert (R30).

### Migration / back-compat

- Absent `doc.afterTasks` ⇒ `confirm` (R1). Absent `review.provider` ⇒ `none` (R11/R12). Existing
  `review.enabled: false` ⇒ opt-out + deprecation warning (R17). No config rewrite is required for existing repos
  (R22).

## Security & Compliance

- No new credentials or secrets are introduced. Review-provider API keys remain environment-sourced; the schema
  continues to store no credentials (verified by the security persona).
- The worktree invariant (R6) is now enforced by a deterministic fail-closed guard (R27), not prose — a net
  strengthening against unreviewed writes to bare `main` that closes the realized failure mode.
- **Default-off review posture (accepted, recorded trade-off):** defaulting `review.provider` to `none` means a
  fresh repo reaches a green gate with no AI review. This is accepted to remove the CodeRabbit hang, but is made
  honest: a never-configured repo reports `unconfigured` (not a deliberate opt-out), the verdict reason never
  says "review landed" (R21/R28), and the state is surfaced to humans (R29). The `auto` + `review:none`
  combination (no human gate and no AI review) is a deliberate power-user posture; `/sw-setup` and the auto-mode
  notice surface "no review gate active" when it applies.
- The redaction chokepoint, memory guardrails, and `check-frozen.py` enforcement are unaffected.

## Testing Strategy

- **Config schema:** fixtures validating that `doc.afterTasks` accepts only `stop|confirm|auto`, defaults to
  `confirm`; that `review.provider` defaults to `none`; and that `review.enabled` validates but is flagged
  deprecated.
- **Gate (`check-gate.py`):** fixtures asserting (a) never-configured default resolves to `none` and yields the
  `unconfigured` state with an honest reason (not "review landed", not a deliberate opt-out); (b) explicit
  `review.provider:"none"` / `review.enabled:false` yields `off`; (c) the opt-out/unconfigured green-verdict
  reason never reads "review landed"; (d) pass/fail verdict is unchanged from prior `disabled` behavior; (e) a
  grep test asserts no `disabled` literal remains in gate code, consumers, or fixtures (update
  `run-gate-fixtures.sh` `state=disabled` assertion → `off`).
- **Worktree guard (R27):** negative-path fixture asserting the deterministic guard aborts a simulated
  implementation write when `HEAD` is the default branch with no active worktree; positive fixture for an allowed
  on-main flow (hotfix/release).
- **Tasks single-pass:** a doc-pipeline fixture asserting `/sw-tasks` produces a complete task list (parents +
  sub-tasks + `## Traceability`) in one pass with no intervention prompt, and that `traceability-check.py` passes.
- **Boundary modes:** `stop` halts with next-command output and never implements; `confirm` requires a
  strictly-matched ack (`proceed`/`yes`) before any implementation and treats `Go`/silence/ambiguous as stop;
  `auto` dispatches the implementation loop on a worktree. The implementing paths (`auto`, `confirm`-after-ack)
  provision a worktree; `stop` and declined-`confirm` never touch bare `main`.
- **Deprecation channel (R17):** fixture asserting `review.enabled:false` keeps `check-gate.py` stdout valid
  single-object JSON while the warning surfaces off-stdout.
- **Migration:** a fixture with a legacy config (`review.enabled: false`, no `doc.afterTasks`) confirming
  correct behavior + deprecation warning, no required edits.
- **Build chain:** regenerate `core/` + `dist/` and the parity golden manifest; the emitter freshness gate
  (`run-emitter-fixtures.sh`) and parity gate must pass.
- Wire new fixture runners into `verify.test` in `workflow.config.json` alongside the existing
  `run-*-fixtures.sh` suite.

## Rollout Plan

1. Land schema + canonical example-config + `check-gate.py` changes (brainstorm decisions D4/D5/D6 — review
   default flip, opt-out canonicalization, gate-state rename incl. green-reason switch + `unconfigured` honesty)
   with gate fixtures — mechanically self-contained and back-compatible.
2. Land the deterministic worktree guard (R27) with its negative-path fixture (safety floor before behavior
   changes rely on it).
3. Land `/sw-tasks` single-pass change (remove Go gate, rewrite collision policy) with doc-pipeline fixtures.
4. Land `/sw-doc` boundary modes (stop/confirm/auto-dispatch) + `/sw-setup` review + `doc.afterTasks` steps +
   `--after-tasks` flag + `/sw-ship` integration; amend `rules/sw-naming.mdc` + `sw-doc.md` contract (R26).
5. Regenerate `core/` + `dist/` and refresh the parity golden manifest; emitter freshness + parity gates green.
6. Update user-facing docs (README / getting-started / commands) once behavior is final.
7. No data migration; deprecation of `review.enabled` is warn-only with no scheduled removal (DL4).

## Decision Log

- **DL1 (resolves Q1)** Config key is `doc.afterTasks` under a new top-level `doc` block — short, discoverable,
  and leaves room for future doc-pipeline knobs. Rejected `doc.handoff.mode` as over-nested for a single value.
- **DL2 (resolves Q2)** Runtime flag is `--after-tasks=<mode>` on `/sw-doc`; `/sw-ship` accepts the same flag
  with a specified doc-chain integration point (R30) so it is not inert. Name mirrors the config key.
- **DL3 (resolves Q3)** `auto` mode emits a one-line `implementing on branch <name>` notice before dispatching
  the implementation loop so the worktree provisioning is visible even without a prompt.
- **DL4 (resolves Q4)** `review.enabled` deprecation is warn-only indefinitely; no removal is scheduled in this
  PRD. Revisit when a major version bump is planned.
- **DL5 (resolves Q5)** Phase-structure correction after single-pass generation is: reject at the
  `doc.afterTasks` boundary, then re-run `/sw-tasks` (overwrite with confirmation) or `/sw-amend` the PRD. No
  targeted in-place task-edit affordance ships in v1 (YAGNI; revisit if friction is observed).
- **DL6 (carry-forward)** Brainstorm decisions D1–D7 are adopted as specified; D3 (remove the Go gate;
  single-pass generation) supersedes the earlier "disambiguate the wording" approach.
- **DL7 (prior-art)** The gate-state rename (R20) is constrained to the opt-out state only; the broader
  review-state model from #2074 / `CAPABILITIES.md` is otherwise unchanged, and the `unconfigured` state is made
  reachable for default repos (R28).
- **DL8 (doc-review: auto contradiction)** `auto` mode is redefined as auto-**dispatch** (provision worktree →
  dispatch `/sw-ship` or `/sw-start`), not in-orchestrator implementation, so it no longer contradicts the
  doc-orchestrator boundary. `rules/sw-naming.mdc` and `sw-doc.md` are amended to permit the dispatch handoff
  (R26). Rejected: keeping the orchestrator inlining implementation (would violate an always-applied rule);
  rejected: dropping `auto` entirely (the user wants the opt-in fast path, now made safe by dispatch + R27).
- **DL9 (doc-review: enforcement)** The worktree invariant is enforced by a deterministic fail-closed guard
  (R27), not orchestrator prose — directly closing the realized failure mode (an agent ignoring prose
  guardrails). Prose-only enforcement was rejected as the substrate that caused the original incident.
- **DL10 (doc-review: default mode)** Default `doc.afterTasks` stays `confirm`, but `confirm` now requires a
  strict ack grammar (`proceed`/`yes` to the implementation question; `Go`, silence, or ambiguous → stop)
  (R2). This addresses the panel's "reflexive affirmative" risk while keeping the friendlier default. The DL1
  rationale is corrected: `stop` (R4) is not silent — it prints the next command — so the trade-off is
  one-fewer-command (`confirm`) vs zero reflexive-ack risk (`stop`); `confirm` + strict grammar is chosen.
- **DL11 (doc-review: review honesty)** Default-off review is an accepted, recorded trade-off, made honest:
  never-configured repos report `unconfigured` (distinct from explicit `off`), no opt-out path reports "review
  landed" (R21/R28), and the state is surfaced to humans (R29).
- **DL12 (doc-review: scope bundling)** The boundary and review-config workstreams ship in one PRD because they
  share the `/sw-setup` touchpoint and a single first-run-session origin, and form one coherent onboarding-UX
  deliverable; the Rollout Plan sequences them as independently-landable steps so they can still be split across
  PRs if needed.

## Open Questions

None — all brainstorm open questions (Q1–Q5) are resolved in the Decision Log, and the doc-review panel's
manual trade-offs are resolved in DL8–DL12.
