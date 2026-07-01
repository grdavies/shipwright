# Gap backlog (living, append-only)

Committed trivial in-scope gaps written out-of-loop by `/sw-feedback` (Phase 2). Unlike frozen task
lists, this file is hand-appendable and not subject to the freeze CI check.

**Status contract (ternary):**

| Status | Meaning |
|--------|---------|
| `open` | Not closed and **not yet scheduled** — needs triage to a PRD, amendment, `deferred`, or config knob. |
| `scheduled` | Not closed; **Schedule** names the owning unit (`PRD NNN`, `PRD NNN A<k>`, `deferred (…)`, `config: <knob>`). |
| `resolved` | Closed — fix shipped or accepted policy/config documented. |

**Remainder query:** gaps that still need scheduling = **open** count only. **scheduled** = committed backlog
pull-in; **resolved** = done. No `partially resolved`, `planned`, or embedding schedule in Status prose.

## Index

Stable IDs (`GAP-NNN`) are assigned at append time — **never reuse**. Cross-link gaps as `GAP-NNN`, not
table row numbers. When appending, use the next ID: **`GAP-089`**.

| Status | Count |
|--------|------:|
| resolved | 28 |
| scheduled | 60 |
| open | 0 |
| ID | Status | Schedule | Title |
|----|--------|----------|-------|
| GAP-001 | resolved | — | Pre-push secret scan: `sk_live_` fixture string reached `git push` and w |
| GAP-002 | resolved | — | Scoped history-redaction guardrail: removing a secret from history must |
| GAP-003 | resolved | — | Phase `status.json` written under the phase worktree's `.cursor/` but `w |
| GAP-004 | resolved | — | `merge run-next` assumes a per-phase PR (`gate-check` → "no open PR"); l |
| GAP-005 | resolved | — | Orchestrator merges into its own worktree checkout; the primary checkout |
| GAP-006 | resolved | — | `core/scripts/` mirror drift: |
| GAP-007 | resolved | — | `doc.afterTasks` guidance stale in `sw-doc.md`: |
| GAP-008 | resolved | — | `doc.afterTasks: confirm` checkpoint easy to miss: |
| GAP-009 | scheduled | PRD 024 A2 | Model tier routing not bound at Task dispatch (R9 procedural only): |
| GAP-010 | resolved | — | CI link-check automation (v1 non-goal): |
| GAP-011 | scheduled | PRD 003 (frozen deferred v2 surface; not started) | PRD 003 not started — deferred v2 surface entirely open: |
| GAP-012 | scheduled | PRD 035 A1 | `/sw-deliver` v1 deferrals still open: |
| GAP-013 | scheduled | deferred (native review panel follow-ons; evidence-gated) | Native review panel follow-on deferrals (post-PR #61): |
| GAP-014 | scheduled | deferred (PRD 008 non-goal: platforms dual-map + interactive model picker) | Model tier config deferrals (distinct from runtime R9 gap): |
| GAP-015 | resolved | — | `/sw-cleanup` confirm step is a manual bash hand-off, not an agent-drive |
| GAP-016 | scheduled | PRD 035 A1 | Frozen PRDs are not auto-committed to `main`, creating a data-loss windo |
| GAP-017 | resolved | — | `deliver-loop` supports only one concurrent PRD; parallel product-area w |
| GAP-018 | resolved | — | Provider-conditional source of truth (R32 / KTD3 revisit): |
| GAP-019 | resolved | — | `/sw-compound` naming does not match operator mental model: |
| GAP-020 | resolved | — | `/sw-compound` + `/sw-compound-ship` overlap looks like an oversight: |
| GAP-021 | scheduled | PRD 035 A1 | Retrospective/compounding not auto-run before terminal PR in `/sw-delive |
| GAP-022 | scheduled | PRD 035 A1 | Terminal PR + CI watch + stabilize should run autonomously; merge to `ma |
| GAP-023 | resolved | — | Manual PR test plans are not enforced by CI — `/sw-watch-ci` cannot catc |
| GAP-024 | scheduled | PRD 035 A1 | `/sw-compound-ship` still has human approval gates that block full auton |
| GAP-025 | scheduled | PRD 035 A1 or config `cleanup.autonomy` | `/sw-cleanup` still requires explicit human confirm before apply: |
| GAP-026 | scheduled | PRD 035 A1 | during PRD 012 phase-mode deliver, the agent halted with `Resume: bash |
| GAP-027 | scheduled | PRD 035 A1 | Conductor paused after post-remediation green-merged phase ("status-paus |
| GAP-028 | resolved | — | `compoundShip` / `record-premerge` writes orchestrator worktree state bu |
| GAP-029 | scheduled | PRD 035 A1 | Conductor paused mid-phase during `dispatch-ship` (incomplete ship work |
| GAP-030 | scheduled | PRD 035 A1 | Phase worktrees not torn down immediately after `green-merged` — linger |
| GAP-031 | resolved | — | Pre-work memory search not a categorical, enforced obligation (consisten |
| GAP-032 | resolved | — | `copy-to-core.sh` destructive sync vs split source-of-truth — closed by SoT manifest + fail-closed orphans |
| GAP-033 | resolved | — | `/sw-cleanup` apply order deletes branches before worktrees — predictabl |
| GAP-034 | resolved | — | `merged_status()` in `cleanup_lib.py` classifies branches via ancestor- |
| GAP-035 | resolved | — | Phase-mode `/sw-ship` opens orphan PR to `main` — deliver merges locally |
| GAP-036 | resolved | — | No review persona ensures documentation artifacts affected by a change a |
| GAP-037 | resolved | — | Dangling phase-mode PRs recur — TWO distinct non-close modes confirmed ( |
| GAP-038 | resolved | — | No spec-mutation safety when a PRD/task list is being implemented in ano |
| GAP-039 | scheduled | PRD 024 A2 | `core/hooks/before_task_dispatch.py` validates bound reviewer / native- |
| GAP-040 | scheduled | PRD 024 A2 | `resolve-model-tier.py` returns different tiers for `--command` vs `--ag |
| GAP-041 | scheduled | PRD 035 A1 | Terminal `retrospective` pause after all waves — `all_phases_merged` vs |
| GAP-042 | scheduled | PRD 035 A1 | Phase `status.json` path edge case recurs — background dispatch + relati |
| GAP-043 | scheduled | PRD 035 A2 | Backlog status feedback loop not mechanical — `planned` rows stay stale |
| GAP-044 | scheduled | PRD 035 A2 | Stable gap IDs + index for cross-reference (manual contract): |
| GAP-045 | scheduled | PRD 035 A2 | Model-dependent doc formatting breaks PRD/amendment/task automation — strict regex parsers vs free-form generation; parsers also disagree |
| GAP-046 | scheduled | PRD 035 A2 | Gap absorption into a PRD/amendment does not mechanically flip status (open → planned) — upstream half of GAP-043 |
| GAP-047 | resolved | — | Doc-review `design` persona selector substring-matches `UI` inside `Requirements` → false-positive design review on PRDs; INDEX 037 → `complete` (PR #222) |
| GAP-048 | scheduled | PRD 035 A1 | Concurrent dual-ship duplicate-PR **race** — parent + background subagent both ship same phase head → two open PRs (different bases) within minutes (variant beyond resolved GAP-035/037) |
| GAP-049 | scheduled | PRD 035 A1 | `verify:failed` regression can't reach remediation — `merge-run-next` hard-exits (exit 20); only `verify:environmental` (exit 10) routes `remediate`; `conductor:no-progress` then pre-empts `remediate → /sw-stabilize` |
| GAP-050 | scheduled | PRD 035 A1 | Premature partial merge before parallel-wave batch completion (R44 enforcement gap) → predictable golden-manifest conflict on a later batch sibling |
| GAP-051 | scheduled | PRD 035 A1 | No auto-remediation path for deterministic `merge-queue:conflict` (golden-manifest / `dist` regen) — manual-only halt blocks wave advancement |
| GAP-052 | scheduled | PRD 035 A1 | Non-terminal hand-authored `status.json` is non-consumable — driver never gets `merge-ready-green` though CI green; terminal status must be emitted via `/sw-ship --phase-mode` / `sw-ready`, never hand-edited |
| GAP-053 | scheduled | PRD 033 A1 (INDEX `complete` derivation; R29/R35) | PRD-unit INDEX status staleness (merged-to-`main` units marked `not-started`: 013/017/018/023) is a **distinct surface** from GAP-043/046 (gap-rows) — covered only *implicitly* by PRD 033 R2/R22; plus a COMPLETION-LOG post-merge logging gap (018 missing PR #87 line) that would defeat any log-based `complete` derivation — **absorbed by PRD 033 A1 (R29/R35)** |
| GAP-054 | scheduled | PRD 035 A1 | `scripts/`↔`core/scripts/` parity wired into CI + verify.test; one-shot resync cleared latent drift |
| GAP-055 | scheduled | PRD 033 A1 (post-merge finalize guard; R33–R35) | Post-merge completion-state bypass disables `finalize-if-merged` and cascades to manual `reconcile` on `main` (PRD 036) — **absorbed by PRD 033 A1 (R33–R35)** |
| GAP-056 | scheduled | PRD 033 A3 (operator worktree contract) | Repo-root `.cursor/` writes during deliver look like `main` mutations — intentional canonical state vs cwd/isolation bugs (PRD 036) |
| GAP-057 | scheduled | PRD 035 A1 | No sanctioned post-merge refresh path for an already-merged frozen task list when an amendment adds requirements — `check-frozen.py` blocked it (PRD 013's pre-merge refresh worked only because the task list was an added file). Bridged by two scoped `check-frozen.py` exceptions (format-normalization-only; amendment-companion task-list); durable design (re-freeze contract + PRD 031 tokenizer) deferred |
| GAP-058 | scheduled | PRD 035 A1 | PRD 033 deliver: conductor ends turn on `awaitAgent: true` instead of same-turn `deliver-loop` re-invoke (R13 recurrence) |
| GAP-059 | scheduled | PRD 035 A1 | PRD 033 deliver: parallel waves 6+7 golden-manifest / generated CI workflow conflict — union fixture jobs + regen on integration |
| GAP-060 | scheduled | PRD 035 A1 | PRD 033 deliver: `currentWave` past `plan.waves.length` → empty batch + `await-in-flight` stall |
| GAP-061 | scheduled | PRD 035 A1 | PRD 033 deliver: post-merge `verify:environmental` fixture drift (`deliver-terminal-autonomy-knob`, `deliver-resume-command-is-sw`) |
| GAP-062 | scheduled | PRD 035 A1 | PRD 033 deliver: `conductor:no-progress` on stuck merge queue / identical `nextAction` — manual `noProgressStreak` reset |
| GAP-063 | resolved | — | PRD 033 deliver: orchestrator `.cursor/sw-deliver-state.*.json` stale vs repo-root canonical state before terminal steps |
| GAP-064 | scheduled | PRD 035 A1 | PRD 033 deliver: `wave_terminal.py` terminal PR create `fail()` TypeError + commitlint reject on uppercase `PRD` in title |
| GAP-065 | scheduled | PRD 033 A1 (`terminalPr.number` squash detection; R29) | PRD 033 deliver: post-merge `finalize-if-merged` squash not detected via git ancestry — needs `terminalPr.number` / host signal |
| GAP-066 | scheduled | PRD 033 A1 (refuse bare `reconcile` on `main`; R31) | PRD 033 deliver: `finalize-if-merged` triggered full `reconcile-status.py reconcile` on `main`, regressing INDEX (PR #207 partial) |
| GAP-067 | scheduled | PRD 033 A1 (living-doc commits off default branch) | PRD 033 deliver: local `main` dirty — in-loop living-doc commit + unstaged full-reconcile on primary checkout |
| GAP-068 | scheduled | PRD 035 A1 | PRD 033 deliver: `living-docs reconcile --commit` / legacy projection wiped hand-maintained INDEX + GAP-BACKLOG |
| GAP-069 | resolved | — | PRD 033 deliver: untracked `.cursor/planning-legacy-projection-stamp.json` after projection run — gitignore (PR #208) |
| GAP-070 | scheduled | PRD 033 A1 (post-merge `main` ff playbook) | PRD 033 deliver: local-main divergence cascade (living-doc on main → stale ff → reconcile INDEX regression) |
| GAP-071 | scheduled | PRD 035 A1 | PRD 034 deliver: build-chain not enforced at phase boundaries — `cursor-golden-vs-dist` + emitter freshness fail every phase |
| GAP-072 | scheduled | PRD 035 A1 | PRD 034 deliver: post-merge integration verify fails — remediation budget exhausted per phase |
| GAP-073 | scheduled | PRD 035 A1 | PRD 034 deliver: stabilize moves integration past `batchIntegrationHead` without state reconcile |
| GAP-074 | scheduled | PRD 035 A1 | PRD 034 deliver: cross-run parallel ceiling — stale worktrees + concurrent deliver orchestrators |
| GAP-075 | resolved | — | PRD 052 ship: `suite-registry.json` single-source + drift fixtures (`run_suite_registry_fixtures.py`); CONTRIBUTING `doc` lane guarded |
| GAP-076 | scheduled | PRD 051 | No code-coverage tool exists for `scripts/`; introducing `pytest`/`coverage.py` conflicts with stdlib-first policy (R11/R12/R31 — `scripts/_sw/depmanifest.json` allows zero non-stdlib imports) — needs triage to a future brainstorm on approach (custom stdlib coverage vs. scoped `depmanifest.json` exception vs. status quo) before any implementation |
| GAP-077 | scheduled | PRD 050 | `cmd_orchestrator_provision`'s `assert_primary_off_target` (`scripts/wave_lifecycle.py`) performs `git checkout <default_branch>` directly against the single shared **primary checkout** as a side effect of provisioning a *different* deliver run's orchestrator worktree; there is no cross-run lock around this check, so provisioning `/sw-deliver` for branch B can silently switch the primary checkout's HEAD (or hard-fail if dirty) while a concurrent `/sw-deliver` session/human is actively using that same primary checkout for branch A — PRD 013 R6–R9 scopes only the deliver state/lock *files* per branch, not the primary checkout's working tree/HEAD itself |
| GAP-078 | scheduled | PRD 050 | `skills/conductor/SKILL.md` ("**Orchestrator worktree:** run `deliver-loop` from `.sw-worktrees/<slug>-orchestrator` (**or repo root with state synced**)") explicitly sanctions running the top-level conductor loop with `cwd` = the shared primary checkout, contradicting `core/commands/sw-deliver.md`'s own R53 framing ("Orchestrator worktree (R53): `orchestrator provision` on `<type>/<slug>`") which implies mandatory provisioning; two local agent sessions each running `/sw-deliver` for a different PRD from the primary checkout path would not be isolated from each other for any conductor-level command/side-effect that depends on `cwd`. Related: GAP-056 carries `Schedule: PRD 036`, but PRD 036's frozen scope (read 2026-06-30) contains no R-ID addressing repo-root/cwd ambiguity and explicitly non-goals "multi-PRD parallel deliver-loop scoping (GAP-017)" — the GAP-056 schedule pointer appears stale and this concern remains unscheduled |
| GAP-079 | scheduled | PRD 050 | `.cursor/sw-deliver-runs/run.log` (per `skills/conductor/SKILL.md` durable-artifacts table) is documented as a single un-scoped path, unlike `.cursor/sw-deliver-state.<slug>.json` (R6), `.cursor/sw-deliver-<slug>.lock` (R7), and `.cursor/sw-deliver-runs/<phase-slug>/status.json` — concurrent deliver runs for different PRDs append to one shared log with no per-run separation, undermining the "every live scoped run" auditability promised by PRD 013 R10/TR5 (minor: append-only, not corruption-risk, but worth scoping alongside GAP-077/078) |
| GAP-080 | scheduled | PRD 050 | **Live reproduction of GAP-077/078 during this triage (2026-06-30 ~14:28–14:30):** the primary checkout (`/Volumes/External Storage/GitHub/shipwright`, branch `main`, otherwise clean) had a tracked file mutated in place and two new untracked tracked-path directories appear, all uncommitted, while at least 4 concurrent `/sw-deliver` runs were independently live (`.cursor/sw-deliver-state.{cross-platform-python-standardization,issue-backed-planning-store,loop-quality-gates}.json` + legacy un-scoped `.cursor/sw-deliver-state.json`, plus 10+ phase-slug dirs and a single shared 180KB+ `.cursor/sw-deliver-runs/run.log` spanning 07:49–14:30 same day): (1) `.cursor/workflow.config.json` was rewritten in place (`worktree.parallelCeiling` 4→10, `intraPhase.parallelBudget`/`harnessLimit` 2/8→4/10, `verify.lint`/`typecheck`/`test` commands changed) with no commit; (2) `docs/prds/gap/gap-002-living-doc-reconcile-commits-bypass-r31-default-/` and `docs/prds/gap/gap-003-gap-doc-feedback-capture-has-two-unreconciled-fi/` (tagged `source:feedback`, signals `feedback-living-doc-main-commit-2026-06-30` / `feedback-gap-store-duplication-2026-06-30` — i.e. a *different concurrent `/sw-feedback` session*) appeared untracked and uncommitted. This /sw-feedback session deliberately scoped all of its own writes to a dedicated `docs_worktree.py`-provisioned worktree (`docs/deliver-concurrency-isolation-gaps`) specifically to avoid colliding with this in-flight, uncommitted state in the shared primary checkout — confirming GAP-077/078 are not theoretical |
| GAP-081 | scheduled | PRD 050 | PRD 041 deliver: failed phase provision leaves orphan worktree path without `phaseWorktrees` state → `worktree path already exists` + `conductor:no-progress` |
| GAP-082 | scheduled | PRD 050 | PRD 041 deliver: durable state cleared before `finalize-completion`; resume on bare `main` fails; manual docs PR #285 for INDEX |
| GAP-083 | scheduled | PRD 050 | PRD 041 deliver: **regression** of GAP-062 — `conductor:no-progress` on identical `provision-phase` / `merge-enqueue` loops |
| GAP-084 | scheduled | PRD 050 | PRD 041 phase PR #280: stale GitHub `IN_PROGRESS` + workflow `success` → check-gate yellow while UI all green; stuck-stale blocked until manual empty commit |
| GAP-085 | scheduled | PRD 050 | PRD 041 terminal PR #284: `terminal_pr_body` skips `git_template_lib` validation — manual `gh pr create` workaround |
| GAP-086 | scheduled | PRD 050 | PRD 041 deliver: capability-trust fixtures reverted to `check-gate.sh` on primary checkout (PRD 042 python-first regression) |
| GAP-087 | scheduled | PRD 050 | PRD 041: `all-private` profile needs `visibility: public` at spec-seed (`tracked-private-body`), not only assert-entry (Recallium #2282/#2285) |
| GAP-088 | scheduled | PRD 048 | `living-status-gap-resolve.py` R51 flip is never invoked automatically on PRD completion — GAP-021/022/043/046/062/etc. still `scheduled` against `complete` PRD 035 A1/A2 despite `absorbs:`/outcome-table claims of `resolved`; `/sw-feedback` also names amendment targets without a consumer-status pre-check, surfacing dead-end `/sw-amend` dispatches to already-`complete` PRDs (027/034/035/036/042) |
