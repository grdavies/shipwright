---
id: gap-007-inflight-signal-run-complete-commits-index-on-ma
type: gap
status: open
title: inflight_signal run-complete commits INDEX on main during finalize-completion
visibility: public
tags: [source:feedback, signal:feedback-inflight-run-complete-main-index-2026-06-30]
---

# inflight_signal run-complete commits INDEX on main during finalize-completion

_Captured from feedback signal `feedback-inflight-run-complete-main-index-2026-06-30`._

## Relationship to gap-002 and PRD 046 A1/A2

This is a **third distinct call path** in the same defect class as gap-002 (unguarded INDEX commit on
`defaultBaseBranch` during deliver). gap-002 documents `wave_living_docs.py:git_commit_living_docs` and
`reconcile_lib.py:set_index_status`. PRD 046 A1 (R95–R97) guards the **future** R80 projection write path
and documents upstream primitive hardening as a dependency. **PRD 046 A2** (drafted from this gap) closes the
dependency for the **current** deliver terminal path: `inflight_signal.py` via `finalize-completion`.

## Evidence (validated in code, reproduced live)

During `/sw-deliver` for PRD 039 (`loop-quality-gates`), `finalize-completion` chains to
`inflight_signal run-complete` after `completion finalize-if-merged`:

```1975:1995:scripts/wave_deliver_loop.py
    if action == "finalize-completion":
        ...
        clear_args = ["run-complete"]
        ...
        clear_ec, clear_data = run_inflight_signal(root, *clear_args)
```

`run_inflight_signal` runs with `cwd=str(root)` (the shared primary checkout). `run-complete` delegates to
`cmd_clear`, which clears the `inFlight` tuple and commits by default (`--commit` injected):

```586:591:scripts/inflight_signal.py
def cmd_run_complete(root: Path, args: list[str]) -> None:
    if "--commit" not in args:
        args = [*args, "--commit"]
    if "--reason" not in args:
        args = [*args, "--reason", "deliver-run-complete"]
    cmd_clear(root, args)
```

`git_commit_inflight` has **no** `defaultBaseBranch` check:

```392:407:scripts/inflight_signal.py
def git_commit_inflight(root: Path, unit_id: str, dry_run: bool) -> str | None:
    ...
    subprocess.run(["git", "-C", str(root), "add", rel], check=True, env=env)
    proc = subprocess.run(
        ["git", "-C", str(root), "commit", "-m", msg],
```

**Live reproduction (2026-06-30):** while the primary checkout was on `main`, `/sw-deliver finalize-completion`
for the `loop-quality-gates` run modified `docs/prds/INDEX.md` outside any feature/orchestrator worktree.
`.cursor/sw-deliver-state.loop-quality-gates.json` records `overrideAudit: { action: clear, why:
deliver-run-complete }` at the same timestamp — correlating the INDEX mutation to `inflight_signal
run-complete`, not `living-docs reconcile --commit`.

## Remediation

Implemented via **PRD 046 A2** (`amendments/A2-inflight-signal-default-branch-commit-safety.md`): R98–R99
wire the A1 R96 shared guard into `git_commit_inflight` and name `finalize-completion` as a guarded surface.
