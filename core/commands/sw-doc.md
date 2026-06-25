---
description: Orchestrate the doc pipeline through task freeze, then branch on doc.afterTasks before dispatching implementation. Does not inline implementation.
alwaysApply: false
---

# `/sw-doc`

Documentation orchestrator. Delegates to atomic `sw-` doc commands; does not reimplement them or perform
implementation itself.

## Chain (tier-gated)

```
/sw-triage → [Full: /sw-brainstorm] → /sw-prd → /sw-doc-review → spec-rigor → /sw-freeze → /sw-tasks → spec-rigor + traceability → /sw-freeze → [afterTasks boundary]
```

**Decision record entry** (cross-cutting, up-front):

```
/sw-prd --type decision → /sw-doc-review → spec-rigor → /sw-freeze
```

No brainstorm required; no task generation after freeze.

| Tier | Stages run |
|------|------------|
| Full | brainstorm → PRD → panel (signal-driven) → freeze → tasks |
| Standard | PRD → panel (signal-driven) → freeze → tasks |
| Quick | **not entered** — route to implementation workstream |

## Subsumed atomic commands

`/sw-triage`, `/sw-brainstorm`, `/sw-prd`, `/sw-doc-review`, `/sw-freeze`, `/sw-tasks`

Each remains independently runnable.

## Procedure

1. Run `/sw-triage` (or accept pre-classified tier).
2. If Quick → report handoff to implementation; stop.
3. If Full → `/sw-brainstorm`; halt on blocker.
4. `/sw-prd` per tier rules.
5. `/sw-doc-review` — tier gates whether panel runs (Quick skips); non-Quick uses signal-driven persona selection per `skills/doc-review/SKILL.md`.
6. Halt on `manual` or `gated_auto` trade-offs — do not auto-decide.
7. Run spec-rigor PRD gates (`skills/spec-rigor/SKILL.md`); halt on `fail`.
8. `/sw-freeze` on PRD (and brainstorm if applicable).
9. `/sw-tasks` — single-pass generation; traceability + analyze gates before task freeze.
10. `/sw-freeze` on the task list.
11. Resolve boundary mode: `doc.afterTasks` from `workflow.config.json`, overridden by `--after-tasks=<mode>` when set.
12. Present the frozen task-list path. Resolve `<type>/<slug>` via the shared deliver resolver (do **not**
    re-implement branch derivation in `/sw-doc`):
    ```bash
    bash scripts/wave.sh preflight --task-list <frozen-task-list-path> --skip-base-check
    ```
    Read `target.branch` from the JSON (`scripts/wave_deliver.py` — same resolver `/sw-deliver run` uses).
    Derive the PRD docs dir from the task-list parent: `docs/prds/<n>-<slug>/`.
13. Branch on `doc.afterTasks`:
    - **`stop`** — halt (print-only; **no repository mutation**). Print:
      1. The frozen task-list path.
      2. The target feature branch `<type>/<slug>` from preflight.
      3. The exact docs-only seed command (idempotent shared helper; never onto `main`):

         `bash scripts/wave.sh spec-seed --task-list <frozen-task-list-path>`

      4. The exact next command: `bash scripts/wave.sh deliver-loop --task-list <frozen-task-list-path>`.
      Do **not** recommend `/sw-worktree` → `/sw-start` → `/sw-execute` or standalone `/sw-ship` as the
      primary path.
    - **`confirm`** — present the full frozen task list, then ask explicitly whether to begin implementation
      and state the expected tokens. Only case-insensitive **`proceed`** or **`yes`** to that question continues.
      Legacy **`Go`**, silence, or any ambiguous reply maps to **`stop`** (print-only guidance per above; no
      dispatch). On ack:
      1. **Seed commit** — `bash scripts/wave.sh spec-seed --task-list <frozen-task-list-path>` (docs
         under `docs/prds/<n>-<slug>/` only; excludes `docs/brainstorms/**` and untracked/ignored paths;
         never `main`; idempotent).
      2. **Dispatch** `bash scripts/wave.sh deliver-loop --task-list <frozen-task-list-path>`.
    - **`auto`** — emit one line: `implementing on branch <type>/<slug>`, then
      `bash scripts/wave.sh spec-seed --task-list <frozen-task-list-path>`, then **dispatch**
      `bash scripts/wave.sh deliver-loop --task-list <frozen-task-list-path>`.
      No second prompt. When an **agent** (not a human) invoked `/sw-doc --after-tasks=auto`, record the override via
      `scripts/shipwright-state.sh override-add` (who/when/mode) and record the seed commit (branch + SHA) via
      `scripts/shipwright-state.sh write` **before** dispatch.
14. On `confirm`/`auto` dispatch paths only: never write implementation files inline — hand off to
    `deliver-loop` (phase worktrees + `/sw-ship` per phase).

## Flags

- `--from <stage>` — resume from a specific atomic stage.
- `--tier <quick|standard|full>` — skip triage when tier already known.
- `--after-tasks <stop|confirm|auto>` — per-run override of `doc.afterTasks` (R8).

## Guardrails

- `doc.afterTasks` is the **sole human checkpoint** between documentation freeze and implementation; `/sw-tasks` introduces no additional blocking prompt.
- Halts at manual trade-offs during doc review — do not auto-decide panel outcomes.
- Never inlines implementation — `stop` halts (print-only), `confirm` halts until explicit ack then seeds + dispatches, `auto` seeds + dispatches without a second prompt.
- Worktree invariant (R6/R27): implementation never starts on bare default branch; enforced by `scripts/sw-assert-worktree.sh` at implementation entry, not by orchestrator prose alone.
- Does not merge, ship, or run CI gate.
- Pattern: v1 `/ship` delegates-to-atomics model.
