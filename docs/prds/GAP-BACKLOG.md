# Gap backlog (living, append-only)

Committed trivial in-scope gaps written out-of-loop by `/pf-feedback` (Phase 2). Unlike frozen task
lists, this file is hand-appendable and not subject to the freeze CI check.

| Date | Source | PRD | Gap | Status |
|------|--------|-----|-----|--------|
| 2026-06-25 | /sw-deliver PRD 005 run | 004 | Pre-push secret scan: `sk_live_` fixture string reached `git push` and was caught only by GitHub push protection (last line, not first). Add a deny-pattern scan (`sk_(live\|test)_`, `ghp_`, PEM, etc.) to `/sw-stabilize` or terminal-PR prep so secrets fail locally before push. | open |
| 2026-06-25 | /sw-deliver PRD 005 run | 004 | Scoped history-redaction guardrail: removing a secret from history must be range-scoped (`git filter-branch <base>..<branch>` or `git rebase -i`); a bare-branch `filter-branch` rewrote shared main commits under new SHAs and produced spurious PR conflicts. Add a `rules/` guardrail + doc note. | open |
| 2026-06-25 | /sw-deliver PRD 005 run | 004 | Phase `status.json` written under the phase worktree's `.cursor/` but `wave.sh status collect` reads the orchestrator-root path; required manual copy per phase. `status collect` should resolve the durable phase-worktree path directly (R38 intent). | open |
| 2026-06-25 | /sw-deliver PRD 005 run | 004 | `merge run-next` assumes a per-phase PR (`gate-check` → "no open PR"); local phase-mode has no PRs, forcing manual `merge exec` fallback every phase. Add a no-PR local-merge path for phase-mode. | open |
| 2026-06-25 | /sw-deliver PRD 005 run | 004 | Orchestrator merges into its own worktree checkout; the primary checkout's `<type>/<slug>` ref needed manual `git merge --ff-only` after each phase. Deliver should advance/sync the primary ref automatically. | open |
