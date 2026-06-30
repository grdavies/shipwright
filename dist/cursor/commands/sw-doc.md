---
description: Orchestrate the doc pipeline through task freeze, then branch on doc.afterTasks before dispatching implementation. Does not inline implementation.
alwaysApply: false
---

# `/sw-doc`

Documentation orchestrator. Delegates to atomic `sw-` doc commands; does not reimplement them or perform
implementation itself.

Load `skills/conductor/SKILL.md` and enforce `rules/sw-conductor.mdc` — **single source** for in-turn
continuation on `doc.afterTasks: auto`, consolidated halt reports, and legitimate halts (R18). Do not
re-implement loop or halt policy in this file.

## Conductor adoption (DOC-A1..A2)

| ID | Requirement | Contract clause |
| --- | --- | --- |
| DOC-A1 | `doc.afterTasks: auto` runs `spec-seed` + `/sw-deliver run` in-turn with recorded agent override when applicable — no second prompt | In-turn self-continuation; legitimate-halt set |
| DOC-A2 | On spec-rigor/traceability failure, emit consolidated halt report — no per-gate re-prompts | Legitimate-halt set; consolidated report (R12) |

Human gates unchanged: `doc.afterTasks: confirm` / `stop`, doc-review `gated_auto` / `manual` trade-offs,
Quick tier handoff.

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

### Docs-on-a-branch (R28–R29)

Before step 1 when starting a **new** documentation effort:

```bash
bash scripts/docs_worktree.sh provision --topic <topic>
```

Operate inside the provisioned worktree (`.sw-worktrees/docs-<topic>/`) on branch `docs/<topic>`.
Never commit brainstorm/PRD artifacts on the protected default branch. See `skills/git-workflow/SKILL.md`.

After doc freeze, durability paths diverge (R32):

- **Docs branch** — `bash scripts/wave_spec_seed.py <root> docs-commit --topic <topic>` (brainstorms + PRDs)
- **Feature handoff** — `bash scripts/wave.sh spec-seed --task-list <frozen-task-list-path>` (PRD 013)
- **Merge docs to trunk** — `bash scripts/docs_pr.sh --topic <topic>` (docs-only PR)

0. Load `skills/conductor/SKILL.md`; enforce `rules/sw-conductor.mdc`.
1. Run `/sw-triage` (or accept pre-classified tier).
2. If Quick → report handoff to implementation; stop.
3. If Full → `/sw-brainstorm`; halt on blocker.
4. `/sw-prd` per tier rules.
5. `/sw-doc-review` — tier gates whether panel runs (Quick skips); non-Quick PRD drafts use
   `scripts/doc-review-select.sh` over the capability manifest (`core/sw-reference/capability-manifest.md`).
6. Halt on `manual` or `gated_auto` trade-offs — do not auto-decide.
7. Run spec-rigor PRD gates (`skills/spec-rigor/SKILL.md`); on `fail`, emit consolidated halt report (DOC-A2)
   with `resumeCommand` — do not re-prompt per gate.
8. `/sw-freeze` on PRD (and brainstorm if applicable).
9. `/sw-tasks` — single-pass generation; traceability + analyze gates before task freeze.
10. `/sw-freeze` on the task list.
10a. **Planning reconciler hook (R15):** when doc artifacts may affect the planning graph (INDEX `derived`
    region, gap edges, or unit linkage), run the mechanical reconciler before the implementation boundary:

    ```bash
    bash scripts/planning-graph.sh reconcile --dry-run
    ```

    Commit on the docs/feature branch only (`--commit`; never on bare default branch). Living-status also
    invokes this via `scripts/wave.sh living-docs reconcile`. Resolve artifact paths via
    `bash scripts/planning_paths.sh` (PRD 031) — do not hardcode `docs/planning/` roots.
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

      4. The exact next command: `/sw-deliver run <frozen-task-list-path>`.
      Do **not** recommend `/sw-worktree` → `/sw-start` → `/sw-execute` or standalone `/sw-ship` as the
      primary path. (`/sw-deliver run` invokes the underlying `bash scripts/wave.sh deliver-loop` driver — do
      not print the raw script as the primary operator command.)
    - **`confirm`** — present the full frozen task list, then emit the **Implementation checkpoint** block
      (see below) and halt. Only case-insensitive **`proceed`** or **`yes`** to the checkpoint question
      continues. Legacy **`Go`**, silence, or any ambiguous reply maps to **`stop`** (print-only guidance per
      above; no dispatch). On ack:
      1. **Seed commit** — `bash scripts/wave.sh spec-seed --task-list <frozen-task-list-path>` (docs
         under `docs/prds/<n>-<slug>/` only; excludes `docs/brainstorms/**` and untracked/ignored paths;
         never `main`; idempotent).
      2. **Dispatch** `/sw-deliver run <frozen-task-list-path>`.
    - **`auto`** — emit one line: `implementing on branch <type>/<slug>`, then in-turn (DOC-A1):
      `bash scripts/wave.sh spec-seed --task-list <frozen-task-list-path>`, then **dispatch**
      `/sw-deliver run <frozen-task-list-path>`.
      No second prompt. When an **agent** (not a human) invoked `/sw-doc --after-tasks=auto`, record the override via
      `scripts/shipwright-state.sh override-add` (who/when/mode) and record the seed commit (branch + SHA) via
      `scripts/shipwright-state.sh write` **before** dispatch.
14. On `confirm`/`auto` dispatch paths only: never write implementation files inline — hand off to
    `/sw-deliver run` (phase worktrees + `/sw-ship` per phase via the durable driver).

### Implementation checkpoint (`confirm` mode output contract)

When `doc.afterTasks: confirm`, emit this dedicated block **after** the frozen task list summary — not buried
in closing prose:

```text
## Implementation checkpoint

Implementation is **paused** awaiting your acknowledgement. The frozen task list is ready; nothing has been
dispatched yet.

Begin implementation on `<type>/<slug>`? Reply with **proceed** or **yes** (case-insensitive) to continue.

| Reply | Result |
|-------|--------|
| `proceed` / `yes` | Seed docs (if needed), then dispatch `/sw-deliver run <frozen-task-list-path>` |
| `Go`, silence, ambiguous, or unrelated message | `stop` — print-only guidance (no dispatch); re-emit this checkpoint on the next turn while still un-acked |
| Any other text | Treated as unrelated → same as silence (`stop` + re-emit checkpoint) |
```

**Re-emit rule:** If the user returns with an unrelated message (e.g. `/sw-memory-sync`, a doc question)
while a `confirm` halt is pending and has not sent `proceed`/`yes`, map to **`stop`** (no dispatch) and
**re-emit the Implementation checkpoint block** so the pending acknowledgement is visible again.

## Planning command surface (PRD 035 D6 / R15)

The planning surface **extends `/sw-doc`** — no top-level `/sw-plan`. Commands resolve paths via the PRD 031
helper (`bash scripts/planning_paths.sh`); the graph shell exposes thin wrappers for operator ergonomics.

| Entry | Command |
| --- | --- |
| Mechanical reconciler | `bash scripts/planning-graph.sh reconcile [--dry-run] [--commit]` |
| Graph-driven scheduler | `/sw-deliver next` → `python3 scripts/wave_deliver.py <repo> next` (also `planning-graph.sh next`) |
| Autonomy posture | `planning.autonomy` in `workflow.config.json` (`maintenance-only` default \| `full-conductor`) |
| Posture readback | `bash scripts/planning-graph.sh posture` |

**Scheduler:** `/sw-deliver next` picks the highest-priority eligible frozen task list from the planning graph
(PRD 033). Under `planning.autonomy: maintenance-only`, an explicit `--task-list` that skips a higher-priority
unit soft-enforces a confirm prompt (see `core/commands/sw-deliver.md` **Planning scheduler**).

**Posture:** `maintenance-only` runs mechanical bookkeeping (reconcile, edge status, INDEX `derived`) without
prompts; content decisions (pull-in, amendment, priority) stay human-gated. `full-conductor` opt-in elevates
only gap/absorption-class decisions under bounded conductor limits (`planning.fullConductor`).

## Flags

- `--from <stage>` — resume from a specific atomic stage.
- `--tier <quick|standard|full>` — skip triage when tier already known.
- `--after-tasks <stop|confirm|auto>` — per-run override of `doc.afterTasks` (R8).

**Communication intensity:** inherit

**Model tier:** inherit — resolve delegated atomics via `bash scripts/resolve-model-tier.sh --command <child-slug>`; do not dispatch on bare `--command sw-doc`.

## Delegated atomics

| Step | Delegate via | Skill / agent binding |
| --- | --- | --- |
| `/sw-brainstorm` | Task | `--command sw-brainstorm` |
| `/sw-prd` | Task | `--command sw-prd` |
| `/sw-doc-review` personas | Task per persona (parallel) | `--command sw-doc-review --agent <persona-id>` |
| `/sw-tasks` | Task | `--command sw-tasks` |
| `/sw-deliver run` (`auto`/`confirm` ack) | Orchestrator dispatch | `--command sw-deliver --skill conductor` |

## Delegated Task binding contract

Before any delegated Task spawn from `/sw-doc`:

1. `bash scripts/wave.sh dispatch preflight --dispatch-id <id> --agent <agent-id> --command sw-doc --skill <active-skill>`
2. `bash scripts/dispatch-check.sh --agent <agent-id> --command sw-doc --skill <active-skill> --parent-model <parent-concrete-id> [--dispatch-id <id>]`
3. Pass explicit `model: <resolved-concrete-id>` on Task input (never `inherit`).

Resolve model: `bash scripts/resolve-model-tier.sh --command <child-slug>` (or `--agent` for doc-review personas).
Resolve intensity: `bash scripts/resolve-intensity.sh --command <child-slug>` (or `--agent|--skill`).

## Inline allowlist (closed)

`/sw-doc` may remain inline only for:

- Triaging doc tier and boundary mode selection.
- Rendering frozen artifact summaries/checkpoint prompts.
- Writing bookkeeping state (`shipwright-state` override/seed records).
- Dispatch handoff preparation to `/sw-deliver run`.

All other substantive work delegates.

## Dispatch context redaction contract

Before building a Task prompt, route non-config context through `bash scripts/memory-redact.sh` and embed
external payloads only inside fenced `untrusted_payload` blocks. Never forward raw transcripts or provider
memory payloads.

## Guardrails

- `doc.afterTasks` is the **sole human checkpoint** between documentation freeze and implementation; `/sw-tasks` introduces no additional blocking prompt.
- Halts at manual trade-offs during doc review — do not auto-decide panel outcomes.
- Never inlines implementation — `stop` halts (print-only; **no implementation dispatch**), `confirm` halts until explicit ack then seeds + dispatches, `auto` seeds + dispatches without a second prompt.
- Worktree invariant (R6/R27): implementation never starts on bare default branch; enforced by `scripts/sw-assert-worktree.sh` at implementation entry, not by orchestrator prose alone.
- Does not merge, ship, or run CI gate.
- Pattern: v1 `/ship` delegates-to-atomics model.
