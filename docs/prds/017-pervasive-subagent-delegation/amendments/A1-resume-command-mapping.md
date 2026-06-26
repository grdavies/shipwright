---
date: 2026-06-26
amends: docs/prds/017-pervasive-subagent-delegation/017-prd-pervasive-subagent-delegation.md
frozen: true
frozen_at: 2026-06-26
---

# Amendment A1: in-loop deliver resume emits `/sw-deliver run`, not raw `bash`

## Overview

Parent PRD 017 hardens the conductor in-turn loop so spurious turn-boundary pauses stop: R14 forbids the
status-note-plus-scope-confirmation **prose pattern** while `verdict: running`, and R16 forbids user-visible
text after `dispatch-ship` until a terminal `status.json`. Those requirements govern **whether** a turn may
end and **what framing** is prohibited. They do **not** govern the **string content** of the resume command
that a *legitimate* halt (`report blockers` / `report terminal` with `halt: true`) surfaces to the operator.

GAP-BACKLOG row 33 reports that this residual is still raw-`bash`-first: a legitimate mid-run deliver halt
emits `Resume: bash scripts/wave.sh deliver-loop --task-list …` rather than the invokable `/sw-deliver run …`
a user can paste into chat. PRD 011 R1–R4 fixed exactly this asymmetry for the **post-freeze** `/sw-doc` path
(user-facing handoffs use `/sw-*`; bash kept only as a documented underlying-driver footnote), but the
**in-loop deliver resume** path was never converted.

This amendment adds one requirement (R29) that makes every user-facing deliver resume/handoff string a
`/sw-*` command, while preserving raw `bash` for conductor in-turn mechanical re-invocation and labelled
internal-driver footnotes. It is **additive and complementary** to R14/R16 — it specifies the resume string
at the legitimate halt those requirements already permit; it contradicts no parent requirement.

## Context

The residual lives in surfaces PRD 017 does **not** edit:

- `scripts/wave_failure.py` `resume_deliver_command()` returns
  `bash scripts/wave.sh deliver-loop --task-list <source_task_list>`, which becomes the `resumeCommand` field
  in `report blockers` / `report terminal` payloads.
- `core/skills/conductor/SKILL.md` halt-report example shows `resumeCommand` as
  `bash scripts/wave.sh deliver-loop --task-list <path>`.
- `core/skills/deliver/SKILL.md` and `core/commands/sw-deliver.md` illustrate the bash `deliver-loop`
  invocation as the entry/resume rather than `/sw-deliver run`.

PRD 017's frozen task surfaces (`wave_deliver_loop.py`, `wave_merge.py`, `wave_lifecycle.py`,
`sw-conductor.mdc`) do **not** include `wave_failure.py` or the `resumeCommand` string mapping, so this is a
genuine gap, not a re-spec.

## Goals

1. Every deliver resume/handoff string presented to a human (or pasted into chat) is an invokable `/sw-*`
   command — specifically `/sw-deliver run <source_task_list>`.
2. Raw `bash scripts/wave.sh deliver-loop …` survives only as conductor in-turn mechanical re-invocation and
   explicitly-labelled internal-driver footnotes — never as user copy-paste resume text.
3. Parity with the PRD 011 R1–R4 post-freeze convention, closing the in-loop half it left open.

## Non-Goals

- Changing **when** a turn may end or **what framing** is prohibited — that is parent R14/R16/R28, unchanged.
- Converting conductor in-turn **mechanical** driver re-invocation (the agent re-running the loop in the same
  turn) to a `/sw-*` form — that is an internal step, not operator-facing text.
- Touching `/sw-ship`, `/sw-status`, `/sw-debug`, `/sw-cleanup` resume strings (already `/sw-*` per row 33
  audit) or the `/sw-doc` post-freeze path (already fixed, PRD 011 R1–R4).
- Renaming or aliasing `/sw-deliver run` (it is already the documented alias for `deliver-loop --task-list`).

## Requirements

Continue the parent namespace (parent max R28).

- **R29** Every deliver resume/handoff string that is **operator-facing** (surfaced in a halt report, printed
  as a "Resume:" line, or otherwise intended for a human to read or paste) MUST be the invokable
  `/sw-deliver run <source_task_list>` form, never a raw `bash scripts/wave.sh deliver-loop …` string.
  Concretely:
  - **R29a** `scripts/wave_failure.py` `resume_deliver_command()` MUST return `/sw-deliver run
    <source_task_list>` when `source_task_list` is present, and `/sw-deliver run` (path omitted) only when the
    durable state already carries `source_task_list` such that resume is unambiguous. The `resumeCommand`
    field emitted by `report blockers` / `report terminal` MUST therefore match `^/sw-deliver run `.
  - **R29b** `core/skills/conductor/SKILL.md` halt-report examples and the agent output contract, and
    `core/skills/deliver/SKILL.md` orchestrator restart guidance, MUST show `/sw-deliver run <path>` as the
    user-facing resume — not `bash scripts/wave.sh deliver-loop`.
  - **R29c** `core/commands/sw-deliver.md` MUST surface `/sw-deliver run` (and resume-via-state) as the
    user-facing entry/resume and demote the bash `deliver-loop` invocation to a clearly-labelled
    internal-driver footnote.
  - **R29d** Raw `bash scripts/wave.sh deliver-loop …` is RETAINED only for (i) conductor in-turn mechanical
    re-invocation within the same turn, (ii) agent-internal steps, and (iii) explicitly-labelled "underlying
    driver" footnotes. It MUST NOT appear as operator copy-paste resume text. This complements parent R14/R16
    (which forbid the resume **prose pattern**) by fixing the resume **string** at a legitimate halt.

## Testing Strategy

| Fixture | Asserts | R-IDs |
|---------|---------|-------|
| `deliver-resume-command-is-sw` | `resume_deliver_command()` / `resumeCommand` matches `^/sw-deliver run ` when `source_task_list` present; never emits a raw `bash … deliver-loop` operator-facing resume | R29, R29a |
| `deliver-resume-docs-sw-form` | conductor + deliver skills and `sw-deliver.md` show `/sw-deliver run` as the user-facing resume; bash only as a labelled internal-driver footnote | R29b, R29c, R29d |

These extend the existing `run-deliver-loop-fixtures.sh` / conductor + deliver doc-presence suites. Emitter
propagation (`dist/`) and the docs-presence updates fold into **parent R19/R21** on task regeneration — no new
doc/dist phase.

## Implementation note (task integration)

This amendment adds R29 (with sub-points R29a–R29d) to the PRD 017 spec union. The frozen task list
`tasks-017-pervasive-subagent-delegation.md` MUST be regenerated against the union (R1–R29) before
implementation so R29 carries a task + traceability. R29 attaches to **Phase 2 (Deliver reliability)** —
naturally adjacent to task 2.4 (conductor loop guarantees) since it edits the conductor/deliver output
contract and `wave_failure.py`; its doc/emitter work merges into the parent R19/R21 tasks (Phase 4). No new
feature branch — same `feat/pervasive-subagent-delegation`.

## Decision Log

| ID | Decision | Rationale |
|----|----------|-----------|
| DL-12 | Amend PRD 017 (not PRD 011, not a standalone PRD) | 017 owns the conductor/deliver output contract and edits the same conductor + deliver surfaces; the resume **string** is a one-requirement delta over R14/R16, while PRD 011 is already complete/shipped. Co-locating avoids touching the same files in two PRs. |
| DL-13 | R29 is additive/complementary to R14/R16, not a supersede | R14/R16 govern turn-end framing and the re-invoke obligation; R29 governs the resume **string** at the legitimate halt those rules permit. No parent requirement is contradicted, so no `supersedes`/`retracts` directive is needed. |
| DL-14 | Keep raw `bash deliver-loop` for mechanical in-turn re-invocation and labelled footnotes | Conductor self-continuation and internal driver notes are not operator copy-paste text; converting them would misrepresent an internal mechanical step as a chat command. Mirrors PRD 011 R1–R4's bash-as-footnote convention. |

## Open Questions

None.
