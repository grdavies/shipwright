---
date: 2026-06-25
topic: orchestrator-ux-and-doc-polish
frozen: true
frozen_at: 2026-06-25
---

# PRD 011 — Orchestrator UX and documentation polish

## Overview

Four open `GAP-BACKLOG.md` items share one theme: the workflow *behaves* correctly but the
**user-facing command surface and command documentation are stale or awkward**, so operators are nudged
toward raw scripts, can miss a soft halt, or must hand-run a confirm step. This PRD consolidates those
low-risk command/doc fixes into one Standard-tier delivery:

1. `/sw-doc`'s post-freeze guidance still prints raw `bash scripts/wave.sh deliver-loop` as the primary
   next command, while PRD 005 frozen amendments A1/A2 pin `/sw-deliver run <frozen-task-list>` as the
   user-facing implementation entry (GAP row: PRD 005).
2. The `doc.afterTasks: confirm` checkpoint is emitted as prose at the tail of a long pipeline summary, so
   the soft halt is easy to miss and a returning user is never re-prompted (GAP row: PRD 002).
3. `/sw-cleanup`'s confirm step tells the operator to run `python3 scripts/cleanup.py --confirm --yes`
   themselves instead of the agent asking for consent and running the apply step on their behalf
   (GAP row: PRD 004).
4. PRD 001 deferred automated link verification; README + guides still rely on manual link checks
   (GAP row: PRD 001).

These are presentation, command-doc, and tooling changes. They do **not** alter `/sw-deliver`,
`/sw-doc`'s ack grammar, `/sw-cleanup`'s fail-closed protections, or any freeze/merge gate behavior.

## Goals

1. The post-freeze command `/sw-doc` shows (stop) and dispatches (confirm/auto) is `/sw-deliver run
   <frozen-task-list-path>`, matching PRD 005 A1/A2 and the user guides — never raw `wave.sh deliver-loop`
   as the recommended user command.
2. The `confirm` checkpoint is visually prominent and re-announced when an un-acked user returns, so a
   pending implementation halt is never silently lost.
3. `/sw-cleanup`'s confirm becomes an agent-driven consent prompt that, on explicit ack, runs the apply
   step for the user while preserving every existing protection.
4. An optional, deterministic, offline repo-link checker closes PRD 001's manual link-check debt without
   becoming a hard ship gate.

## Non-Goals

- Changing `/sw-deliver` behavior or the `deliver-loop` driver mechanics (PRD 004/007 scope).
- Changing the `doc.afterTasks` ack grammar (case-insensitive `proceed`/`yes` only) or the
  `stop`/`confirm`/`auto` mode contract — this PRD changes presentation, not semantics.
- Weakening any `/sw-cleanup` fail-closed protection or introducing auto-apply without explicit human ack.
- Verifying external (http/https) links or adding any network dependency to the link checker.
- Making the link checker a blocking ship gate by default.

## Requirements

### `/sw-doc` post-freeze command surface (PRD 005 A1/A2 alignment)

- **R1** `core/commands/sw-doc.md` MUST present `/sw-deliver run <frozen-task-list-path>` as the primary
  user-facing post-freeze implementation entry in all three modes: printed as the next command on `stop`,
  dispatched after human ack on `confirm`, and dispatched on `auto` — satisfying PRD 005 A1 R76/R77.
- **R2** The boundary MUST retain the idempotent docs-only spec-seed step (printed on `stop`; executed
  before dispatch on `confirm`/`auto`) via the shared helper, preserving PRD 005 A2 R80–R83 semantics:
  docs-only, committed onto `<type>/<slug>` and never `main`, idempotent, excluding `docs/brainstorms/**`.
- **R3** Any place in `sw-doc.md` that prints raw `bash scripts/wave.sh deliver-loop ...` as the *primary*
  next/dispatch command MUST be replaced by `/sw-deliver run <frozen-task-list-path>`; the raw driver verb
  MAY remain documented only as the underlying mechanism, not the recommended operator command.
- **R4** The existing `doc-afterTasks-*` fixtures MUST be extended (not forked) to assert `/sw-deliver run`
  is the printed command on `stop` and the dispatch target on `confirm`/`auto`, and MUST pass.

### `confirm` checkpoint prominence (PRD 002)

- **R5** The `confirm`-mode output contract in `sw-doc.md` MUST render the proceed request as a dedicated,
  visually prominent block — its own heading, a direct yes/proceed question, and an explicit statement that
  implementation is paused awaiting acknowledgement — rather than a trailing sentence on a long summary.
- **R6** When a user returns to a pending `confirm` halt with an unrelated message (for example
  `/sw-memory-sync`), the orchestrator MUST treat it as `stop` (no dispatch) AND re-emit the checkpoint
  block, so the pending acknowledgement is surfaced again rather than silently dropped.
- **R7** The acknowledgement grammar MUST stay unchanged: only case-insensitive `proceed` or `yes`
  continues; `Go`, silence, or any ambiguous reply maps to `stop` with print-only guidance. This PRD
  changes presentation, not the ack rule.

### `/sw-cleanup` agent-driven confirm (PRD 004)

- **R8** `core/commands/sw-cleanup.md` MUST replace the "run `python3 scripts/cleanup.py --confirm --yes`
  yourself" hand-off with an agent-driven flow: after the dry-run report, the agent asks the operator to
  confirm, and on explicit ack the agent runs the apply step on their behalf (via
  `python3 scripts/cleanup.py --confirm --yes` or `SW_CLEANUP_CONFIRM=1`).
- **R9** The agent-driven apply MUST preserve every fail-closed protection unchanged: current branch,
  default branch, unmerged branches, active or locked worktrees, in-flight deliver run-state, indeterminate
  squash-merge status, and the no-`rm -rf` worktree teardown. The apply MUST delete only the `wouldRemove`
  set the operator reviewed in the immediately-preceding dry run.
- **R10** A declined, silent, or ambiguous reply MUST NOT apply any removals (dry-run stays terminal). The
  manual `python3 scripts/cleanup.py --confirm --yes` invocation MUST remain documented as an escape hatch but
  is no longer the primary path.

### Optional repo link-check (PRD 001)

- **R11** Add `scripts/docs-link-check.py` that verifies repo-relative markdown links and in-repo heading
  anchors across `README.md` and `docs/guides/**` (and optionally `docs/prds/**`), emitting a stable JSON
  verdict on stdout (`pass` or `broken-links` with the offending file, link, and reason).
- **R12** The checker MUST be advisory by default: a `verify.test` or doctor wiring runs it in non-blocking
  mode (exit 0 with logged findings) and exposes a `--strict` opt-in (exit non-zero on broken links) so it
  closes PRD 001 R16 manual-only debt without becoming a hard ship gate unless explicitly requested.
- **R13** Validation MUST be deterministic and offline: only repo-relative file links and intra-document
  anchors are checked; external `http`/`https` links are explicitly out of scope (no network access).

### Cross-cutting

- **R14** All `core/` changes (commands, scripts) MUST be propagated to `dist/cursor` and
  `dist/claude-code` via `python3 -m sw generate --all`, with the emitter freshness gate
  (`scripts/test/run-emitter-fixtures.sh`) passing.
- **R15** New behaviors MUST be covered by fixtures — deliver-run command surface, confirm-prominence
  output shape, cleanup agent-confirm flow, and link-check pass/broken verdicts — wired into the
  `verify.test` harness.
- **R16** User guides (`docs/guides/getting-started.md`, `docs/guides/configuration.md`,
  `docs/guides/workflows.md`) MUST agree with the updated post-freeze command, the prominent confirm
  checkpoint, and the agent-driven `/sw-cleanup` confirm wherever they reference those flows.

## Technical Requirements

- **TR1 — `sw-doc.md` command surface.** Rewrite the `doc.afterTasks` branch prose so the printed
  (`stop`) and dispatched (`confirm`/`auto`) command is `/sw-deliver run <frozen-task-list-path>`; keep the
  `bash scripts/wave.sh spec-seed --task-list <path>` seed step on the boundary; demote any raw
  `deliver-loop` mention to "underlying driver" context (R1–R3).
- **TR2 — Confirm checkpoint block.** Add a dedicated `confirm`-mode output template to `sw-doc.md` (own
  heading, direct question, paused-state statement) and a re-emit rule for un-acked returns; leave the ack
  grammar table intact (R5–R7).
- **TR3 — `sw-cleanup.md` agent-confirm.** Rewrite the procedure so step 3 is an agent consent prompt
  followed by the agent running `python3 scripts/cleanup.py --confirm --yes` (or `SW_CLEANUP_CONFIRM=1`) on
  ack; retain the protections section verbatim and keep the manual command as a documented escape hatch
  (R8–R10). No change to `scripts/cleanup.py` behavior.
- **TR4 — `scripts/docs-link-check.py`.** New script: parse markdown for `[text](path)` relative links and
  `#anchor` fragments, resolve against the repo tree and generated heading slugs, emit JSON
  (`{"verdict":"pass|broken-links","findings":[...]}`); default advisory exit 0, `--strict` exit 20 on
  findings; no network calls (R11–R13).
- **TR5 — Harness wiring.** Add `scripts/docs-link-check.py` to the doctor/`verify.test` path in advisory
  mode; add fixtures under a `run-doc-link-fixtures.sh`-adjacent suite or a new `run-ux-polish-fixtures.sh`
  and register it in `workflow.config.json` `verify.test` (R12, R15).
- **TR6 — Emitter propagation.** Regenerate `dist/` via `python3 -m sw generate --all`; freshness gate
  must pass (R14).
- **TR7 — Guides.** Update the three named guides to match the new command surface, confirm checkpoint,
  and cleanup confirm UX (R16).

## Security & Compliance

- No new secrets, credentials, or network calls are introduced; the link checker is offline by design (R13).
- `/sw-cleanup` protections are preserved exactly; the only change is *who* triggers the already-gated
  apply after explicit human ack (R9). No destructive git behavior is added.
- The spec-seed step retains its docs-only, never-`main`, brainstorm-excluded constraints (R2).

## Testing Strategy

All fixtures extend the existing harness invoked by `workflow.config.json` `verify.test`.

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `doc-afterTasks-stop-deliver-run` | `sw-doc.md` stop branch prints `/sw-deliver run <path>` (not raw `deliver-loop`) | R1, R3 |
| `doc-afterTasks-confirm-auto-deliver-run` | confirm/auto dispatch target is `/sw-deliver run`; spec-seed retained on boundary | R1, R2 |
| `doc-afterTasks-deliver-run-fixtures-pass` | extended `doc-afterTasks-*` fixtures present and green | R4 |
| `confirm-checkpoint-prominent` | `sw-doc.md` confirm output has a dedicated heading + direct question + paused-state line | R5 |
| `confirm-reemit-on-unacked-return` | un-acked unrelated return maps to stop and re-emits the checkpoint block | R6 |
| `confirm-ack-grammar-unchanged` | only `proceed`/`yes` continues; `Go`/silence/ambiguous → stop | R7 |
| `cleanup-agent-confirm-flow` | `sw-cleanup.md` confirm is an agent prompt → agent runs apply on ack | R8, R10 |
| `cleanup-protections-preserved` | protections + no-`rm -rf` + reviewed-set-only deletion intact | R9 |
| `docs-link-check-pass` | clean repo links produce `verdict: pass` | R11 |
| `docs-link-check-broken` | a broken relative link/anchor produces `broken-links` with file + reason | R11 |
| `docs-link-check-advisory-default` | advisory mode exits 0 with findings; `--strict` exits non-zero | R12 |
| `docs-link-check-offline` | external `http`/`https` links are skipped; no network access | R13 |
| `ux-polish-emitter-freshness` | `dist/` regenerated and fresh | R14 |
| `ux-polish-guides-aligned` | the three guides name `/sw-deliver run`, the prominent confirm, and agent cleanup confirm | R16 |

R15 is satisfied by this fixture set itself and its `verify.test` registration. Per-R traceability is
finalized in `/sw-tasks`.

## Rollout Plan

- **Single feature branch** `docs/orchestrator-ux-and-doc-polish` (docs/command/script-only; no runtime
  driver changes), delivered in dependency-ordered phases: (1) `sw-doc.md` command surface + confirm
  prominence; (2) `sw-cleanup.md` agent-confirm; (3) `scripts/docs-link-check.py` + harness wiring;
  (4) guides + emitter + fixtures.
- **Backward compatible.** No config schema change is required; the link checker defaults to advisory, so
  existing `verify.test` runs stay green. `--strict` is opt-in.
- **Emitter.** Regenerate `dist/` after every `core/` change; freshness gate enforces parity.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-1 | Consolidate four command/doc gaps into one Standard PRD rather than four micro-PRDs | They share a theme (command surface + doc polish), low risk, and a single fixture/emitter pass; mirrors the PRD 007 consolidation precedent. |
| DL-2 | Post-freeze primary command = `/sw-deliver run`; raw `deliver-loop` demoted to mechanism | PRD 005 A1 R76/R77 already froze `/sw-deliver run` as the user-facing entry; `sw-doc.md` drifted. Aligns command with guides. |
| DL-3 | Confirm fix is presentation-only; ack grammar untouched | PRD 002 gap is "easy to miss", not "wrong semantics". Changing grammar would risk the human gate (scope-guardian lens). |
| DL-4 | Re-emit the confirm checkpoint on un-acked return | Closes the "silently waiting" failure the gap describes without auto-dispatching (adversarial lens: returning user must not lose the pending state). |
| DL-5 | `/sw-cleanup` apply stays human-gated; only the trigger moves from operator-bash to agent-on-ack | Preserves the fail-closed contract (R9) while removing the manual terminal step (product lens). |
| DL-6 | Link checker is offline + advisory-by-default with `--strict` opt-in | PRD 001 deferred this as a non-blocking convenience; a network or hard-gate design would exceed the deferred scope (scope-guardian + feasibility lenses). |

## Open Questions

None. The PRD 005 A2-vs-`main` seeding question does not arise here: R2 explicitly preserves the existing
`<type>/<slug>`, never-`main` seed semantics (the freeze-to-`main` durability question is owned by PRD 013).
