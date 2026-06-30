---
id: gap-002-living-doc-reconcile-commits-bypass-r31-default-
type: gap
status: open
title: Living-doc reconcile commits bypass R31 default-branch refusal (wave_living_docs.py / reconcile.py set-index-status)
visibility: public
tags: [source:feedback, signal:feedback-living-doc-main-commit-2026-06-30]
---

# Living-doc reconcile commits bypass R31 default-branch refusal (wave_living_docs.py / reconcile.py set-index-status)

_Captured from feedback signal `feedback-living-doc-main-commit-2026-06-30`._

## Evidence (validated in code, reproduced live)

`docs/prds/033-lifecycle-dependencies-and-scheduler/amendments/A1-post-merge-index-reconcile-safety.md`
already added **R31**: "the maintenance reconciler and any legacy `reconcile-status.py reconcile` shim it
replaces MUST refuse to commit when the current git branch is `defaultBaseBranch`" — and named the sanctioned
escape valve: "single-unit post-merge bookkeeping uses scoped primitives (`set-index-status` +
`append-log-idempotent`) **on a docs branch**." That guard is implemented, but only for the full-corpus path:

```221:234:scripts/reconcile_lib.py
def reconcile_prd_index(root: Path, *, dry_run: bool = False, require_merge: bool = False, allow_default: bool = False) -> dict[str, Any]:
    ...
    if not dry_run and not allow_default and branch_name == base:
        return {"verdict": "fail", "error": "reconcile refuses default branch commits (R31)", ...}
```

R31's own sanctioned alternative — `set-index-status` — has **no such guard**, and neither does the
automated caller that chains it to a commit:

```136:155:scripts/wave_living_docs.py
def git_commit_living_docs(worktree: Path, prd: str, dry_run: bool, repo_root: Path | None = None) -> str | None:
    ...
    subprocess.run(["git", "-C", str(top), "add", *living_paths(top)], check=True)
    msg = f"chore: living-doc reconcile for PRD {prd}"
    proc = subprocess.run(["git", "-C", str(top), "commit", "-m", msg], ...)
```

`resolve_worktree()` defaults to `root.resolve()` when no `--worktree`/`--orchestrator-worktree` is supplied,
so `python3 scripts/wave.py living-docs reconcile --commit` — the path the deliver conductor invokes after
each phase merge — commits straight to whatever branch is checked out, with **no check that it isn't
`defaultBaseBranch`**. R31's guard assumed the scoped primitives would always be run "on a docs branch"; it
never enforced that assumption at the primitive itself.

**Reproduced live** on 2026-06-30: local `main` carried two unpushed commits produced this exact way
(`chore: living-doc reconcile for PRD 043`, `chore: living-doc reconcile for PRD 039`), each a direct,
non-PR, single-parent commit to `docs/prds/INDEX.md` sitting 2 ahead of `origin/main`.

## Lineage

This is a residual/incomplete-closure recurrence of **GAP-053** (PRD 033 A1, "INDEX complete derivation;
R29/R35") and the PRD 036 post-merge corruption it was written to prevent — same defect class (uncontrolled
INDEX commit on `main`), different call path (the automated `living-docs reconcile --commit` chain vs. the
bare `reconcile-status.py reconcile` shim that A1 closed).

## Why this matters for the upcoming program

PRD 046 (issue-store planning-graph, not started) adds a **new** committed-INDEX write path: R80/D22 commit
the deliver-owned `inFlight` tuple as a read-only projection into the committed INDEX region, for both
file-derived and issue-derived projections. If R80's implementation reuses `git_commit_living_docs()` (or its
pattern) without first closing this gap, PRD 046 ships with the defect built in from day one.

## Suggested remediation

1. Apply the same `branch == defaultBaseBranch` refusal in `wave_living_docs.py:cmd_reconcile` /
   `cmd_append_terminal` / `git_commit_living_docs`, and in `reconcile_lib.py:set_index_status` (currently
   un-guarded — only the full-corpus `reconcile_prd_index` path is guarded).
2. Add a regression fixture: invoking `living-docs reconcile --commit` with the resolved worktree checked
   out on `defaultBaseBranch` must fail closed, never commit — closing the gap R31 left open.
3. PRD 046 (proposed amendment, R95) should explicitly require its new committed-`inFlight`/INDEX write path
   inherit this guard rather than re-deriving its own commit safety.
4. The underlying primitive fix (#1/#2) is upstream of PRD 043's program and may warrant its own immediate
   fix or a further PRD 033/035 amendment — flagged for operator decision, out of scope for the 043-047
   amendments proposed here.

