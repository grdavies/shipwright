---
date: 2026-06-26
topic: pervasive-subagent-delegation
prd: docs/prds/017-pervasive-subagent-delegation/017-prd-pervasive-subagent-delegation.md
frozen: true
frozen_at: 2026-06-26
---

# Tasks — PRD 017 Pervasive sub-agent delegation with per-task model + caveman binding

Generated from the frozen PRD spec union (R1–R29; amendment A1 adds R29 — in-loop deliver resume
command mapping). Phases are dependency-ordered per the reliability-first Rollout Plan:
binding/enforcement foundation → deliver reliability (hard gate) → per-orchestrator adoption →
docs/dist/fixtures.

> Refreshed 2026-06-26 to apply amendment A1 (R29, in-loop deliver resume command mapping) into
> the task list.

## Tasks

### 1. Binding + enforcement foundation — M

Dispatch policy, per-task model + caveman binding, the fail-closed mechanical gate, override audit, and
dispatch-context redaction. No deliver-loop behavior change in this phase.

- [ ] 1.1 Rewrite dispatch policy to delegate-by-default + closed inline exception sets
  - **File:** `core/rules/sw-subagent-dispatch.mdc`; inline-allowlist blocks in `core/commands/sw-doc.md`, `sw-ship.md`, `sw-deliver.md`, `sw-debug.md`, `sw-feedback.md`
  - **Expected:** standing gate is delegate-by-default honoring `delegation.mode`; heuristics demoted to granularity guidance; each command enumerates a closed bookkeeping allowlist (no open "trivial" category)
  - **R-IDs:** R1, R2, R3
- [ ] 1.2 Add `delegation.mode` knob (`bind-only|heuristic|default`)
  - **File:** `core/sw-reference/config.schema.json`, `.sw/config.schema.json`, `/sw-setup` seeding, `core/sw-reference/model-routing.defaults.json` adjacency
  - **Expected:** knob selects gate behavior; default value wired per DL-9 (`default` gated on Phase-2 live acceptance, else `bind-only`)
  - **R-IDs:** R3
- [ ] 1.3 Extend `communication.routing` with skills+agents maps, resolver, and sessionStart precedence
  - **File:** `core/sw-reference/communication-routing.defaults.json`, `.sw/config.schema.json`, `scripts/resolve-intensity.sh`, `guardrail_core` session-context assembly
  - **Expected:** schema accepts `skills`/`agents`; resolver returns intensity for `--command|--skill|--agent` with command→skill→agent→default precedence; dispatch-bound intensity overrides sessionStart caveman for delegated sub-agents
  - **R-IDs:** R5, R6, R7, R24
- [ ] 1.4 Bind concrete model on dispatch; keep hook forward-compatible
  - **File:** orchestrator command dispatch blocks; `core/hooks/before_task_dispatch.py`
  - **Expected:** every delegated `Task` passes an explicit resolved `model:` (no `inherit`); hook stays registered and no-op-tolerant on Cursor (deny works, inject does not)
  - **R-IDs:** R4, R8
- [ ] 1.5 Generalized dispatch-check with structured cause enum
  - **File:** `scripts/dispatch-check.sh`; `scripts/reviewer-dispatch-check.sh` (thin wrapper)
  - **Expected:** validates resolved model + intensity (`--command|--skill|--agent`); builder floor only for reviewer/persona agents; emits `binding:no-model`/`binding:no-intensity`/`harness:capacity`; `binding:*` halts regardless of retry, only `harness:*` retried
  - **R-IDs:** R9, R10
- [ ] 1.6 Mechanical pre-`Task` preflight nonce + `preToolUse` deny
  - **File:** `scripts/wave.sh` (`dispatch preflight`), `core/hooks/before_task_dispatch.py`
  - **Expected:** preflight records resolved model+intensity+nonce immediately before a bound `Task`; hook denies a bound `Task` spawn lacking a fresh preflight record
  - **R-IDs:** R23
- [ ] 1.7 `--override` durable audit record
  - **File:** `scripts/shipwright-state.sh` (`override-add`), `scripts/dispatch-check.sh`
  - **Expected:** `--override` refused without a durable record capturing actor/timestamp/dispatch-id/skipped-fields written before dispatch; override never bypasses redaction or push/merge chokepoints
  - **R-IDs:** R26
- [ ] 1.8 Dispatch-context redaction + untrusted-input fencing
  - **File:** orchestrator dispatch-prompt assembly; `scripts/memory-redact.sh` integration
  - **Expected:** all non-config context (feedback, Sentry, diffs, run-log excerpts, memory-preflight results) passes `memory-redact.sh` and untrusted blobs are fenced before dispatch; raw transcript/memory payloads never forwarded
  - **R-IDs:** R25

### 2. Deliver reliability (hard gate before Phase 3) — L

Parallel batch driver, conductor loop guarantees, safe eager teardown, and in-loop resume command mapping
on `/sw-deliver`. Phase-2 fixtures plus a supervised live-acceptance run MUST pass before Phase 3.

- [ ] 2.1 Parallel batch dispatch primitive in the deliver driver
  - **File:** `scripts/wave_deliver_loop.py` (`compute_next_action`, `persist_cursor`)
  - **Expected:** a wave with N independent ready phases returns ONE batch action marking all N `in-flight` atomically and instructing the conductor to spawn N background Tasks — not one `dispatch-ship` per phase
  - **R-IDs:** R22
- [ ] 2.2 Conductor concurrent dispatch + ceiling + collect-all-ready + background-task failure handling
  - **File:** `core/skills/conductor/SKILL.md`, `scripts/wave_deliver_loop.py`, `scripts/wave_merge.py`
  - **Expected:** conductor spawns ≥2 background Tasks per batch up to `parallelCeiling`; intra-step agents excluded from the ceiling; `collect-all-ready` enqueues simultaneous greens deterministically; a crashed/never-writing background Task → `blocked`, not stuck `in-flight`
  - **R-IDs:** R11, R12, R27
- [ ] 2.3 Conductor-only merge/lock + phase push chokepoint
  - **File:** `core/rules/sw-conductor.mdc`, `core/skills/conductor/SKILL.md`, `scripts/git-push.sh` references
  - **Expected:** phase sub-agents cannot `merge`/`lock acquire`; no raw `git push`; phase pushes route through `scripts/git-push.sh` (secret-scan preserved)
  - **R-IDs:** R13
- [ ] 2.4 Conductor in-turn loop guarantees
  - **File:** `core/skills/conductor/SKILL.md`, `core/rules/sw-conductor.mdc`, `core/commands/sw-deliver.md`; post-turn linter fixture
  - **Expected:** categorical no-status-pause while `verdict: running`; `merge-ready-green` complete regardless of remediation path and no scope-pause during in-flight remediation with budget; no user-visible text after `dispatch-ship` until terminal phase `status.json`; only driver-detected ambiguity/destructive conditions halt inline
  - **R-IDs:** R14, R15, R16, R28
- [ ] 2.5 Safe eager phase-worktree teardown
  - **File:** `scripts/wave_merge.py` (`merge-run-next`), `scripts/wave_lifecycle.py`, `scripts/wave_deliver_loop.py`
  - **Expected:** `green-merged → teardown-pending → teardown-complete` after verify + dependent forward-merge; dependent-reference and retained-ref (branch + final `status.json`) guards; `phaseWorktrees[id]` cleared on complete; orchestrator worktree persists; `git worktree remove`+`prune` only
  - **R-IDs:** R17
- [ ] 2.6 Operator-facing deliver resume/handoff emits `/sw-deliver run`, not raw `bash` (R29)
  - **File:** `scripts/wave_failure.py` (`resume_deliver_command()`), `core/skills/conductor/SKILL.md` (halt-report examples + output contract), `core/skills/deliver/SKILL.md` (orchestrator restart guidance), `core/commands/sw-deliver.md` (entry/resume illustration)
  - **Expected:** `resume_deliver_command()` returns `/sw-deliver run <source_task_list>` when `source_task_list` is present; the `resumeCommand` field in `report blockers` / `report terminal` matches `^/sw-deliver run `; conductor + deliver skills and `sw-deliver.md` show `/sw-deliver run <path>` as the user-facing resume; bash `deliver-loop` demoted to clearly-labelled internal-driver footnote; raw `bash ... deliver-loop` retained only for conductor in-turn mechanical re-invocation, agent-internal steps, and labelled footnotes
  - **R-IDs:** R29

### 3. Per-orchestrator adoption — M

Apply delegation + binding + halts per the PRD 009 adoption audit, bounded to the audit IDs. Depends on the
Phase-2 hard gate.

- [ ] 3.1 Adopt the conductor contract across the five orchestrators
  - **File:** `core/commands/sw-ship.md`, `sw-debug.md`, `sw-doc.md`, `sw-feedback.md`; reference `core/skills/conductor/SKILL.md`
  - **Expected:** each orchestrator references the single-source conductor contract (no duplicated loop prose) and delegates its substantive atomics with bound model+intensity per SHIP-A1..A4 / DBG-A1..A2 / DOC-A1..A2 / FB-A1..A2; human gates unchanged
  - **R-IDs:** R18

### 4. Docs + dist + fixtures — M

- [ ] 4.1 Regenerate `dist/` and pass the freshness gate
  - **File:** `dist/cursor/**`, `dist/claude-code/**` via `python3 -m sw generate --all`
  - **Expected:** `scripts/test/run-emitter-fixtures.sh` passes; `dist/` parity with `core/`
  - **R-IDs:** R19
- [ ] 4.2 Author the fixture suite (integration-style for concurrency/binding)
  - **File:** `scripts/test/run-*-fixtures.sh` (delegation, dispatch, deliver-loop, conductor suites)
  - **Expected:** all Testing-Strategy fixtures present and green, including per-orchestrator delegation, runtime concurrency/binding observation (not doc-grep-only), and `resumeCommand` matches `^/sw-deliver run ` when `source_task_list` present
  - **R-IDs:** R20, R29
- [ ] 4.3 Update documentation
  - **File:** `core/rules/sw-subagent-dispatch.mdc`, `core/skills/conductor/SKILL.md`, the five orchestrator commands, `core/sw-reference/communication-routing.defaults.json`, `core/sw-reference/models-tiering.md`, `.sw/layout.md`, relevant guides
  - **Expected:** delegate-by-default, per-task model+caveman binding, extended routing maps, enforcement floor, conductor hardening, and `/sw-deliver run` as user-facing resume documented
  - **R-IDs:** R21

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 2 |
| 4 | 3 |

## Traceability

| R-ID | Task | Test scenario |
| --- | --- | --- |
| R1 | 1.1 | `delegation-default-invariant` |
| R2 | 1.1 | `delegation-default-invariant` (closed exception set) |
| R3 | 1.1, 1.2 | `dispatch-rule-default-gate`; `delegation-mode-knob` |
| R4 | 1.4 | `dispatch-binds-model` |
| R5 | 1.3 | `dispatch-binds-intensity` |
| R6 | 1.3 | `intensity-routing-extended` |
| R7 | 1.3 | `intensity-routing-extended` |
| R8 | 1.4 | `dispatch-hook-forward-compat` |
| R9 | 1.5 | `dispatch-check-fail-closed` |
| R10 | 1.5 | `dispatch-check-cause-enum` |
| R11 | 2.2 | `parallel-peak-concurrency-runtime` |
| R12 | 2.2 | `ceiling-slot-accounting` |
| R13 | 2.3 | `conductor-only-merge-lock`; `phase-push-chokepoint` |
| R14 | 2.4 | `conductor-no-status-pause` |
| R15 | 2.4 | `conductor-post-remediation-complete` |
| R16 | 2.4 | `conductor-reinvoke-after-dispatch-ship` |
| R17 | 2.5 | `phase-teardown-eager-safe` |
| R18 | 3.1 | `conductor-single-source` |
| R19 | 4.1 | `delegation-emitter-freshness` |
| R20 | 4.2 | `orchestrator-delegation-per-command` |
| R21 | 4.3 | `delegation-docs-presence` |
| R22 | 2.1 | `parallel-batch-driver` |
| R23 | 1.6 | `dispatch-preflight-nonce-gate` |
| R24 | 1.3 | `intensity-precedence-no-double-resolve` |
| R25 | 1.8 | `dispatch-prompt-redacted` |
| R26 | 1.7 | `dispatch-override-audited` |
| R27 | 2.2 | `parallel-collect-all-ready`; `parallel-background-task-failure` |
| R28 | 2.4 | `conductor-driver-detected-halt-only` |
| R29 | 2.6, 4.2 | `deliver-resume-command-is-sw`; `deliver-resume-docs-sw-form` |

## Relevant Files

- `core/rules/sw-subagent-dispatch.mdc` — delegate-by-default standing gate + closed exceptions
- `core/rules/sw-conductor.mdc`, `core/skills/conductor/SKILL.md` — loop guarantees, parallel dispatch, single source
- `scripts/wave_deliver_loop.py`, `scripts/wave_merge.py`, `scripts/wave_lifecycle.py` — batch driver, merge, teardown
- `scripts/wave_failure.py` — `resume_deliver_command()` resume string (R29)
- `scripts/dispatch-check.sh`, `scripts/reviewer-dispatch-check.sh`, `scripts/wave.sh` (`dispatch preflight`) — enforcement
- `scripts/resolve-intensity.sh`, `core/sw-reference/communication-routing.defaults.json`, `.sw/config.schema.json` — intensity binding
- `core/hooks/before_task_dispatch.py` — forward-compatible model hook + deny gate
- `core/commands/sw-doc.md`, `sw-ship.md`, `sw-deliver.md`, `sw-debug.md`, `sw-feedback.md` — orchestrator adoption
- `core/skills/deliver/SKILL.md` — orchestrator restart guidance (R29)

## Notes

- Phase 2 is a hard gate: its fixtures plus a supervised live-acceptance run (≥2 concurrent phase worktrees,
  no status-pause to the terminal gate, logged per-phase model IDs) must pass before Phase 3 adoption.
- `delegation.mode` shipped default follows DL-9 (`default` gated on the live-acceptance pass; else `bind-only`).
- Caveman binding (R5) is best-effort (prompt-level); only model binding (R4) is mechanically enforced (R23).
- R29 (A1): `resumeCommand` must match `^/sw-deliver run ` in all operator-facing halt reports; raw
  `bash deliver-loop` is retained only for mechanical in-turn re-invocation and labelled footnotes.
