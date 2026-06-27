---
date: 2026-06-27
topic: git-host-portability-and-workflow-standardization
prd: docs/prds/026-git-host-portability-and-workflow-standardization/026-prd-git-host-portability-and-workflow-standardization.md
frozen: true
frozen_at: 2026-06-27
---

# Tasks — PRD 026 Git host portability + workflow standardization

Generated from the frozen PRD spec union **R1–R42** (no amendments). Five dependency-ordered phases mirror the
PRD rollout: a host-adapter + rate-limit foundation (Phase 1) underpins the GitHub REST gate refactor
(Phase 2), the no-remote local mode (Phase 3), the GitLab/Bitbucket adapters + PR-automation fixes (Phase 4),
and the git-workflow / docs-branch standardization (Phase 5). Phases 2, 3, and 5 are parallel-eligible once the
foundation lands; Phase 4 follows the GitHub gate abstraction. Every phase ships behind passing fixtures
registered in `core/sw-reference/pr-test-plan.manifest.json` and is independently mergeable.

## Tasks

### 1. Host adapter + rate-limit foundation — L

- [x] 1.1 Host config schema (`host.*` incl. `host.rateLimit`) (R1, R41)
  - **File:** `.sw/config.schema.json`, `.cursor/workflow.config.json`
  - **Expected:** schema validates `host.provider`, `host.remote`, `host.tokenEnv`, `host.baseUrl`,
    `host.apiBaseUrl`, and a `host.rateLimit` object (max attempts, base/cap backoff, jitter, near-limit
    threshold); unknown provider rejected closed-world. `host-provider-select` resolves the configured adapter.
  - **R-IDs:** R1, R41
- [x] 1.2 Adapter contract + capability flags (R2, R3)
  - **File:** `core/providers/host/CAPABILITIES.md`, `core/providers/host/github.md`, `core/providers/host/none.md`
  - **Expected:** stable host-operation verb set documented (`pr-create`, `pr-view`, `pr-list`, `pr-head`,
    `checks`, `review-threads`, `repo-meta`, `merge`); each adapter declares capability frontmatter; missing
    capability surfaces a typed degraded result, not a crash. `host-verb-capability-flags` asserts the matrix.
  - **R-IDs:** R2, R3
- [x] 1.3 Provider auto-detection + configurable remote (R6, R7)
  - **File:** `scripts/host-detect.sh`, `scripts/host_lib.py`
  - **Expected:** provider auto-detected from the configured remote URL for public hosts; `host.remote`
    (default `origin`) replaces every hard-coded `origin` literal in the R7 script set.
    `remote-url-autodetect` maps URLs→providers; `origin-literal-guard` greps the scripts for stray `origin`.
  - **R-IDs:** R6, R7
- [x] 1.4 Token resolution + missing-token degradation (R8)
  - **File:** `scripts/host_token.sh`
  - **Expected:** tokens referenced by env-var name (`host.tokenEnv` + per-provider override); resolved at
    call time, never written to argv/state/logs; absent token degrades to a typed warning verdict.
    `missing-token-degrades` proves no crash and no token leakage.
  - **R-IDs:** R8
- [x] 1.5 Shared rate-limit retry wrapper (R35, R36, R37, R38, R39, R42)
  - **File:** `scripts/host_transport.sh`, `scripts/host_ratelimit.py`
  - **Expected:** wrapper detects throttling (`403`/`429` + remaining/reset or `Retry-After`); computes wait
    in priority order (`Retry-After` → reset header when remaining `0` → jittered exponential backoff);
    bounds retries by max attempts and cumulative wait, then returns a retriable `rate-limited` halt; reads
    rate headers each response and pre-emptively pauses near the limit; issues calls serially; logs
    attempt/wait/reason only (no token/body). Fixtures: `throttle-detect-not-fail`, `wait-priority-order`,
    `bounded-retry-exhaustion-halt`, `near-limit-preemptive-pause`, `serial-and-paced-requests`,
    `backoff-log-redaction`.
  - **R-IDs:** R35, R36, R37, R38, R39, R42
- [x] 1.6 Doctor/setup check + GitHub migration parity (R33, R34)
  - **File:** `core/commands/sw-init.md`, `scripts/host-doctor.sh`
  - **Expected:** `/sw-init` (and `sw-configure`) validate provider, token presence, and reachability;
    degraded capability reported as a warning; an existing GitHub repo works with only a token env var set.
    `github-migration-token-only` and `doctor-degraded-warns`.
  - **R-IDs:** R33, R34

### 2. GitHub gate abstraction over REST — M

- [x] 2.1 GitHub REST verb implementation + `gh` removal (R4, R5)
  - **File:** `core/providers/host/github.md`, `scripts/host_github.sh`
  - **Expected:** the GitHub adapter implements the full verb set over REST (plus GraphQL only for
    review-thread resolution); every direct `gh` invocation in runtime scripts is replaced; no host CLI is a
    prerequisite. `gh-removal-guard` greps for zero `gh` calls and `gh-absent-path` runs with `gh` off `PATH`.
  - **R-IDs:** R4, R5
- [x] 2.2 `check-gate.sh` over the verb set (R14)
  - **File:** `scripts/check-gate.sh`
  - **Expected:** PR number, CI checks, unresolved review threads, and repo metadata obtained via host verbs;
    no direct `gh`. `check-gate-verbset` asserts identical verdicts against recorded REST fixtures.
  - **R-IDs:** R14
- [x] 2.3 Terminal flow over the verb set (R15)
  - **File:** `scripts/wave_terminal.py`, `scripts/wave_compound.py`, `scripts/cleanup_lib.py`, `scripts/reconcile-status.sh`
  - **Expected:** PR prepare/create/list/view/head go through host verbs across the terminal, compound,
    cleanup, and reconcile paths. `terminal-flow-verbset` exercises the flow on mocked REST.
  - **R-IDs:** R15
- [x] 2.4 `stabilize-merge-sync.sh` over the verb set (R16)
  - **File:** `scripts/stabilize-merge-sync.sh`
  - **Expected:** PR metadata + conflict probe run through host verbs. `stabilize-sync-verbset` on fixtures.
  - **R-IDs:** R16
- [x] 2.5 Command/skill prose + install docs de-`gh` (R17, R5)
  - **File:** `core/commands/sw-watch-ci.md`, `core/commands/sw-stabilize.md`, `core/commands/sw-pr.md`, `core/commands/sw-ready.md`, `core/commands/sw-cleanup.md`, `README.md`
  - **Expected:** agent-facing prose references host verbs (not `gh`); installation/setup docs drop the `gh`
    prerequisite and document `host.tokenEnv`. `prose-gh-free` guard + `install-docs-currency`.
  - **R-IDs:** R17, R5

### 3. No-remote local mode — M

- [ ] 3.1 Local-only host adapter (R9)
  - **File:** `core/providers/host/none.md`, `scripts/host_local.sh`
  - **Expected:** `host.provider: none` (or no detected remote) activates a local adapter whose PR/CI verbs
    resolve to local-evidence equivalents. `noremote-local-adapter` asserts selection + verb behavior.
  - **R-IDs:** R9
- [ ] 3.2 Generalize `local_evidence_authorizing` to the terminal tier + artifact (R10)
  - **File:** `scripts/check-gate.sh`, `scripts/local_merge_gate.py`
  - **Expected:** local-evidence path extends feature→trunk; writes a local-merge-gate artifact.
    `terminal-local-evidence-gate` asserts artifact contents.
  - **R-IDs:** R10
- [ ] 3.3 Local-mode human merge halt (R11)
  - **File:** `scripts/wave_terminal.py`
  - **Expected:** final merge into trunk halts for explicit human action by default; no auto-merge.
    `local-merge-human-halt`.
  - **R-IDs:** R11
- [ ] 3.4 CI-watch degradation without host CI (R12)
  - **File:** `core/commands/sw-watch-ci.md`, `scripts/watch_ci_lib.py`
  - **Expected:** CI-watch degrades to local checks-gate evidence and reports degraded mode.
    `ci-watch-local-degrade`.
  - **R-IDs:** R12
- [ ] 3.5 `check-gate.sh` local-evidence verdict (R13)
  - **File:** `scripts/check-gate.sh`
  - **Expected:** returns a local-evidence verdict instead of the blocked "no open PR" path in no-remote mode.
    `check-gate-local-verdict`.
  - **R-IDs:** R13

### 4. GitLab + Bitbucket adapters + PR-automation fixes — L

- [ ] 4.1 GitLab adapter over REST (merge requests) (R18)
  - **File:** `core/providers/host/gitlab.md`, `scripts/host_gitlab.sh`
  - **Expected:** verb set implemented over the GitLab MR REST API incl. its rate-limit signal mapping.
    `gitlab-adapter-verbs` on recorded responses.
  - **R-IDs:** R18
- [ ] 4.2 Bitbucket adapter + backoff-by-default (R19, R40)
  - **File:** `core/providers/host/bitbucket.md`, `scripts/host_bitbucket.sh`
  - **Expected:** verb set over the Bitbucket PR REST API; because Bitbucket Cloud often omits `Retry-After`
    and a reset header on `429`, the adapter falls back to jittered exponential backoff by default.
    `bitbucket-adapter-verbs` + `bitbucket-backoff-default`.
  - **R-IDs:** R19, R40
- [ ] 4.3 Phase-mode PR base = integration branch, fail-closed (R20)
  - **File:** `scripts/wave_terminal.py`, `scripts/wave_deliver.py`
  - **Expected:** in phase mode, PR/MR creation targets `<type>/<slug>` and fails closed on base mismatch.
    `phase-pr-base-integration`.
  - **R-IDs:** R20
- [ ] 4.4 Close superseded phase PRs by branch identity (R21)
  - **File:** `scripts/wave_merge.py`
  - **Expected:** at `green-merged` and terminal assembly, superseded phase PRs close keyed on branch
    identity regardless of ancestry. `superseded-pr-close-by-branch-identity`.
  - **R-IDs:** R21
- [ ] 4.5 Cleanup not blocked by open phase-head PR (R22)
  - **File:** `scripts/cleanup_lib.py`
  - **Expected:** cleanup proceeds for phases recorded `green-merged` even with an open phase-head PR.
    `cleanup-not-blocked-by-open-pr`.
  - **R-IDs:** R22

### 5. Git-workflow skill + docs-branch standardization — L

- [x] 5.1 Native `git-workflow` skill + single-source conventions (R23, R27)
  - **File:** `skills/git-workflow/SKILL.md`
  - **Expected:** sw-namespaced skill (informed by + crediting netresearch) defines branch/commit/PR
    conventions once; documented in the skill and a dedicated reference. `git-workflow-skill-present` +
    `conventions-single-source`.
  - **R-IDs:** R23, R27
- [x] 5.2 `branch-name-guard` enforcement (R24)
  - **File:** `scripts/branch-name-guard.sh`, `scripts/worktree_lib.py`
  - **Expected:** wired into worktree/branch creation; rejects non-conforming names. `branch-name-guard-reject`.
  - **R-IDs:** R24
- [x] 5.3 Commit-message validator (Conventional Commits) (R25)
  - **File:** `scripts/commit-msg-guard.sh`, `hooks/commit-msg`
  - **Expected:** enforces Conventional Commit types from a single source; rejects invalid messages.
    `commit-msg-validator-reject`.
  - **R-IDs:** R25
- [x] 5.4 PR/merge templates + host application (R26)
  - **File:** `core/sw-reference/templates/pr-body.md`, `core/sw-reference/templates/merge-commit.md`
  - **Expected:** standardized PR/MR description + merge-commit body templates; host adapter applies them and
    enforces required fields. `pr-template-required-fields`.
  - **R-IDs:** R26
- [x] 5.5 Docs-on-a-branch policy + worktree provisioning (R28, R29)
  - **File:** `core/commands/sw-doc.md`, `scripts/docs_worktree.sh`
  - **Expected:** brainstorm/PRD/doc authoring occurs on a `docs/<topic>` branch (never the default branch);
    tooling creates/resumes a docs worktree + branch. `docs-branch-no-main-commit` + `docs-worktree-provision`.
  - **R-IDs:** R28, R29
- [x] 5.6 Docs PR to default + brainstorm durability + PRD-013 reconcile (R30, R31, R32)
  - **File:** `scripts/wave_spec_seed.py`, `scripts/docs_pr.sh`
  - **Expected:** docs reach the default branch via a docs-only PR (branch-protection-safe); brainstorms are
    committed and durable on the docs branch (closing the data-loss window); the durability model reconciles
    with PRD 013 (feature-branch spec-seed retained for implementation handoff). `docs-pr-to-default` +
    `brainstorm-durable-commit` + `durability-reconcile-prd013`.
  - **R-IDs:** R30, R31, R32

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | 1 |
| 3 | 1 |
| 4 | 2 |
| 5 | 1 |

## Traceability

| R-ID | Task | Test scenario |
|------|------|---------------|
| R1 | 1.1 | host-provider-select |
| R2 | 1.2 | host-verb-capability-flags (adapter files) |
| R3 | 1.2 | host-verb-capability-flags |
| R4 | 2.1 | gh-removal-guard |
| R5 | 2.1, 2.5 | gh-absent-path / install-docs-currency |
| R6 | 1.3 | remote-url-autodetect |
| R7 | 1.3 | origin-literal-guard |
| R8 | 1.4 | missing-token-degrades |
| R9 | 3.1 | noremote-local-adapter |
| R10 | 3.2 | terminal-local-evidence-gate |
| R11 | 3.3 | local-merge-human-halt |
| R12 | 3.4 | ci-watch-local-degrade |
| R13 | 3.5 | check-gate-local-verdict |
| R14 | 2.2 | check-gate-verbset |
| R15 | 2.3 | terminal-flow-verbset |
| R16 | 2.4 | stabilize-sync-verbset |
| R17 | 2.5 | prose-gh-free |
| R18 | 4.1 | gitlab-adapter-verbs |
| R19 | 4.2 | bitbucket-adapter-verbs |
| R20 | 4.3 | phase-pr-base-integration |
| R21 | 4.4 | superseded-pr-close-by-branch-identity |
| R22 | 4.5 | cleanup-not-blocked-by-open-pr |
| R23 | 5.1 | git-workflow-skill-present |
| R24 | 5.2 | branch-name-guard-reject |
| R25 | 5.3 | commit-msg-validator-reject |
| R26 | 5.4 | pr-template-required-fields |
| R27 | 5.1 | conventions-single-source |
| R28 | 5.5 | docs-branch-no-main-commit |
| R29 | 5.5 | docs-worktree-provision |
| R30 | 5.6 | docs-pr-to-default |
| R31 | 5.6 | brainstorm-durable-commit |
| R32 | 5.6 | durability-reconcile-prd013 |
| R33 | 1.6 | github-migration-token-only |
| R34 | 1.6 | doctor-degraded-warns |
| R35 | 1.5 | throttle-detect-not-fail |
| R36 | 1.5 | wait-priority-order |
| R37 | 1.5 | bounded-retry-exhaustion-halt |
| R38 | 1.5 | near-limit-preemptive-pause |
| R39 | 1.5 | serial-and-paced-requests |
| R40 | 4.2 | bitbucket-backoff-default |
| R41 | 1.1 | host-ratelimit-config |
| R42 | 1.5 | backoff-log-redaction |

## Notes

- Relevant existing files to refactor (not exhaustive): `scripts/check-gate.sh`, `scripts/wave_terminal.py`,
  `scripts/wave_merge.py`, `scripts/stabilize-merge-sync.sh`, `scripts/wave_compound.py`,
  `scripts/cleanup_lib.py`, `scripts/reconcile-status.sh`.
- New provider family lives under `core/providers/host/` mirroring the memory/review adapter pattern.
- All new fixtures register in `core/sw-reference/pr-test-plan.manifest.json` and run in `verify.test`.
