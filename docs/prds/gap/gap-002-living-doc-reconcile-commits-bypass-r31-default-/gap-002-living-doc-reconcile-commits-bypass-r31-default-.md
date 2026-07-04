---
id: gap-002-living-doc-reconcile-commits-bypass-r31-default-
type: gap
status: scheduled
title: Living-doc reconcile commits bypass R31 default-branch refusal (wave_living_docs.py / reconcile.py set-index-status)
visibility: public
tags: [source:feedback, signal:feedback-living-doc-main-commit-2026-06-30]
schedule: PRD 055
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

## Addendum (2026-06-30, second `/sw-feedback` pass): remediation #4 is still unowned, and the risk is no longer theoretical

PRD 046 A1 (drafted from this gap, see `045-issue-native-dev-tracking`/`046-issue-store-planning-graph`
amendments) explicitly scopes its new R95–R97 guard to **PRD 046's own future R80 write path only** and
declares the upstream primitives (`reconcile_lib.py:set_index_status`, `wave_living_docs.py:git_commit_living_docs`)
a **Non-Goal**: "tracked as a dependency, not delivered here" (A1 R97 / DL-A1-2). So after PRD 046 A1 ships,
the actual primitives this gap names in remediation #1 are **still unguarded** — remediation #4's "operator
decision" was deferred, not resolved.

That deferred decision is no longer hypothetical. Independently, **GAP-080** (GAP-BACKLOG.md, captured by a
different concurrent `/sw-feedback` session, merged via PR #264, 2026-06-30 ~14:30) reproduced this *exact*
class of live defect in real time: `.cursor/workflow.config.json` rewritten in place with no commit, plus two
gap-unit directories appearing untracked, while 4+ concurrent `/sw-deliver` runs were live against the shared
primary checkout. This session's own original evidence above (two unpushed `chore: living-doc reconcile`
commits on local `main`) is the same defect, reproduced independently a second time the same day.

Given two independent live reproductions in one day and zero PRDs currently committed to closing the upstream
primitives, this `/sw-feedback` pass initially proposed routing remediation #4 to a new PRD 036 amendment
("complete" but thematically the closest existing home, vs. PRD 033 A1's own origin point) — **and then found,
while drafting it, that this exact routing pattern is precisely how PRD 033's own most recent amendment (A3,
absorbing GAP-056) went unimplemented**: frozen 2026-06-29, marked `complete` in `INDEX.md`, and its R39
requirement is the **near-identical fix** (a fail-closed in-flight cwd guard on `wave_living_docs --commit`
and other operator-command entry points) — never built. See the new canonical gap unit **gap-006** for the
full evidence. Per operator decision (2026-06-30), remediation #4 stays a **gap-only** finding — not a new
PRD 036 amendment — until there is an active implementation vehicle for either this gap or PRD 033 A3 itself.
The two should not be implemented independently of each other; whoever picks this up should read both gap-002
and gap-006 first.

Also note: GAP-077–080 are filed in the legacy `docs/prds/GAP-BACKLOG.md`, not as canonical `docs/prds/gap/*`
units — independent corroboration of gap-003's finding that the two-namespace split is live and actively
causing inconsistent practice across concurrent sessions, not just a one-off in this session.

