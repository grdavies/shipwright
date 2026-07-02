---
id: gap-005-freeze-commit-spec-seed-cwd-dependent-repo-root-
type: gap
status: resolved
schedule: PRD 050
resolvedBy: PRD 050
title: freeze-commit/spec-seed cwd-dependent repo-root resolution can target the shared primary checkout (extends GAP-077/078 to /sw-doc and /sw-amend)
visibility: public
tags: [source:feedback, signal:feedback-freeze-commit-cwd-primary-checkout-risk-2026-06-30]
---

# freeze-commit/spec-seed cwd-dependent repo-root resolution can target the shared primary checkout (extends GAP-077/078 to /sw-doc and /sw-amend)

_Captured from feedback signal `feedback-freeze-commit-cwd-primary-checkout-risk-2026-06-30`._

## Relationship to GAP-077/078 (GAP-BACKLOG.md, PR #264)

GAP-077/078 (captured by a different concurrent `/sw-feedback` session, merged via PR #264) document
`wave_lifecycle.py:assert_primary_off_target` doing an unscoped `git checkout` against the shared primary
checkout as a side effect of `/sw-deliver`'s orchestrator-provision step, and the conductor skill's own
("repo root with state synced") cwd ambiguity. Both are scoped specifically to `/sw-deliver`.

While freezing PRD 045 A1 / PRD 046 A1 in this same session, the **same risk class was found at a second,
unrelated call site reachable from `/sw-doc` and `/sw-amend`**, not just `/sw-deliver`: `/sw-freeze`'s
freeze-time commit helper.

## Evidence

`scripts/check-frozen.py freeze-commit` resolves its working root **from `__file__`, not from the operator's
actual cwd**:

```6:21:scripts/check-frozen.py
SCRIPT_DIR = Path(__file__).resolve().parent
...
root = SCRIPT_DIR.parent
...
proc = subprocess.run([sys.executable, str(SCRIPT_DIR/"wave.py"), "spec-seed", "--artifact", artifact],
                       capture_output=True, text=True, cwd=str(root))
```

That `root` is then forced as the subprocess `cwd`, so `scripts/wave.py spec-seed`'s own `repo_root()` (which
normally correctly resolves via `git -C <Path.cwd()> rev-parse --show-toplevel`, i.e. the *caller's* cwd) is
overridden — `wave_spec_seed.py:cmd_spec_seed` then runs `top = git_toplevel(root)` and does
`git_run(["checkout", "-B", branch, base_ref], top)` (`wave_spec_seed.py:356`) against whichever physical
directory `SCRIPT_DIR.parent` happened to resolve to.

Each `git worktree` has its own independent, non-symlinked copy of `scripts/check-frozen.py`, so `__file__`
resolution is safe **only when the script is invoked via a path that actually lives under the intended
worktree**. The unsafe case is exactly the common operator-error path: Cursor's default shell `cwd` is the
**workspace root** (the primary checkout), so any agent that runs `python3 scripts/check-frozen.py
freeze-commit --artifact <path>` (or the equivalent `wave.py spec-seed` call) **without first `cd`-ing into the
dedicated worktree** silently resolves `root`/`top` to the primary checkout, not the worktree holding the
actual frozen-artifact diff — `branch`/`base_ref` get checked out (`git checkout -B`) in the **shared primary
checkout**, exactly the GAP-077 risk class, via a different trigger (`/sw-freeze`, hence `/sw-doc`'s
brainstorm/PRD/tasks freeze steps and `/sw-amend`'s amendment freeze step) that GAP-077/078 do not name.

**Reproduced live in this session (2026-06-30):** while freezing PRD 045 A1 / PRD 046 A1 from inside the
dedicated worktree, this exact risk was identified before invoking the helper for real
(`check-frozen.py freeze-commit` has no `--dry-run` passthrough, so it cannot be safely test-run) — the helper
was deliberately skipped in favor of performing the freeze steps (frontmatter stamp, INDEX update, commit)
directly inside the worktree, specifically to avoid this collision. No actual corruption occurred precisely
*because* this was caught and avoided manually, with no mechanical guard preventing the next session from
hitting it for real.

## Lineage

- Same defect class as GAP-077/078 (unscoped `git checkout` against a shared resource under concurrency) and
  the broader gap-002 finding (multiple primitives assume "always run on a docs/feature branch" without
  enforcing it) — different call site (`/sw-freeze` → `check-frozen.py`/`wave_spec_seed.py`, not
  `wave_lifecycle.py`).
- Reachable from `/sw-doc` (brainstorm/PRD/tasks freeze) and `/sw-amend` (amendment freeze), neither of which
  GAP-077/078 mention — so "have we sufficiently captured concurrent top-level command interference" was **not**
  fully true before this gap.

## Suggested remediation

1. `check-frozen.py freeze-commit` and `wave_spec_seed.py:cmd_spec_seed` should resolve `root`/`top` from the
   **caller's actual cwd** (`Path.cwd()`), never from `__file__`-derived `SCRIPT_DIR.parent` — matching the
   already-correct pattern in `wave.py:repo_root()`.
2. Add an explicit guard: if the resolved `top` equals the primary checkout's path (`git worktree list`
   first entry) while a dedicated worktree exists for the artifact's branch, fail closed rather than silently
   checking out there — same shape as `assert_primary_off_target`, reusable across both call sites (GAP-077's
   own suggested remediation #2 already proposes a shared primitive; this gap is evidence that primitive needs
   to cover `wave_spec_seed.py` too, not just `wave_lifecycle.py`).
3. Add a regression fixture: invoking `freeze-commit`/`spec-seed` with cwd forced to the primary checkout while
   the target artifact only exists in a sibling worktree must fail closed, never checkout/commit in the
   primary checkout.

