# Shipwright commands reference

User-facing summary of key `sw-` commands. Full procedure text lives in `core/commands/` (installed via `dist/`).

## Setup and config

| Command | Purpose |
|---------|---------|
| `/sw-setup` | Scaffold or doctor `.cursor/workflow.config.json` — writes `doc.afterTasks` (default `confirm`) and review choice (`coderabbit` \| `none`, default **`none`**). |
| `/sw-triage` | Classify work tier; does not start implementation. |

## Documentation pipeline

| Command | Purpose |
|---------|---------|
| `/sw-doc` | Doc orchestrator: brainstorm → PRD → review → freeze → **single-pass** `/sw-tasks`; then `doc.afterTasks` (`stop` \| `confirm` \| `auto`). |
| `/sw-tasks` | Generate the complete frozen task list in **one pass** (no Go gate); standalone run stops without implementation prompt. |
| `/sw-freeze` | Freeze PRD/amendment artifacts. |

`doc.afterTasks` is the sole human checkpoint between PRD freeze and implementation when using `/sw-doc`.

## Implementation loop

| Command | Purpose |
|---------|---------|
| `/sw-worktree` | Provision an isolated worktree (required before impl on bare `main`). |
| `/sw-start` | Create a phase branch; invokes worktree guard before writes. |
| `/sw-execute` | Implement one phase; worktree guard runs before implementation writes. |
| `/sw-ship` | Full ship chain; accepts `--after-tasks=<mode>` at the frozen-task-list boundary. |

**Worktree invariant:** never write implementation files on bare `main` — use a worktree + phase branch.

## Merge readiness

| Command | Purpose |
|---------|---------|
| `/sw-verify` | Run local verification commands from config. |
| `/sw-review` | Local + optional external review (`review.provider`; default **`none`**). |
| `/sw-watch-ci` | Poll PR checks via `check-gate.sh`. |
| `/sw-ready` | Terminal merge-readiness report; echoes `review: off` or `review: not configured` from gate JSON. |
| `/sw-stabilize` | Fix CI/review blockers on the current PR. |

## Review providers

- **Default:** `review.provider: "none"` — review gating off; CI can still pass without external review.
- **Opt-in:** `review.provider: "coderabbit"` — enable CodeRabbit for phase-2 `/sw-review` and CI review barrier.
- **Canonical opt-out:** `review.provider: "none"` (single supported disable path; `review.enabled: false` is deprecated).

See [Getting started](getting-started.md) for boundary modes and worktree rules.
