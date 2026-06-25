---
description: Sync merge-base when the PR conflicts, then consume failing checks and unresolved threads before the next push. Does not merge the PR to main.
alwaysApply: false
trigger: "/sw-stabilize" or "stabilize the current PR"
---

# `/sw-stabilize`

Post-PR stabilization for the current branch. Prefer honest incremental progress over "clearing" large
automated-review thread lists. **Merge conflicts, failing checks, and unresolved review threads** are
**one** triangulation surface — conflicts are evaluated first because they block CI from running.

This is the single-pass stabilizer. The opt-in goal-loop wrapper (keep stabilizing until the gate is
green) is the `stabilize-loop` skill, added in a later phase.

## Config

Read `.cursor/workflow.config.json`:

- `checks` — drives the gate via the `checks-gate` skill (all checks by default).
- `coderabbit.noDefer` — when `true`, **no deferrals**: every blocker is `fix-now`,
  `resolve-with-evidence`, or `already-fixed-with-evidence`. Do not use `defer-*` buckets.
- `verify` — the verification commands to re-run after fixes.
- `agentsFile`, `prdsDir`, `tasksDir` — for context and (when deferrals are allowed) issue cross-refs.

## Preconditions

```bash
PR_JSON=$(gh pr view --json number,url,headRefName,headRefOid,baseRefName,state,isDraft)
PR_NUMBER=$(jq -r .number <<<"$PR_JSON")
HEAD_SHA=$(jq -r .headRefOid <<<"$PR_JSON")
```

Stop if no PR exists.

### 0. Merge-base sync (pre-CI)

GitHub will not run required checks while `mergeable == CONFLICTING`. Resolve this **before** harvesting
threads or interpreting a vacuous gate.

```bash
bash scripts/stabilize-merge-sync.sh fetch-base
STATUS=$(bash scripts/stabilize-merge-sync.sh status)
echo "$STATUS" | jq .
```

When `verdict` is `conflicting`:

1. Classify every path in `conflictingFiles` as ledger bucket **`fix-now`** (blocks all other work).
2. Merge the PR base into the current branch — default `git merge origin/<baseRefName>` (preserve branch
   history; do not rebase unless repo policy requires it).
3. Resolve conflicts with minimal, correctness-first edits:
   - **`docs/prds/INDEX.md`** — union PRD rows from both sides; never drop a numbered entry.
   - **`core/**` command/skill/rule sources** — keep both sides' intent; prefer the branch's feature work
     plus main's additive changes.
   - **`dist/**`** — do not hand-merge emitted copies; resolve `core/` then run
     `bash scripts/copy-to-core.sh` and `python3 -m sw generate --all`.
4. Re-run scoped `verify` on the touched surface; one focused commit; `bash scripts/git-push.sh` once.
5. Re-run `stabilize-merge-sync.sh status` — must be `mergeable` before step 1 below.

When `verdict` is `mergeable`, continue to harvest.

Build the blocker surface for **this** `HEAD_SHA` before changing code (after any merge-base sync).

1. Fetch **all** review-thread pages to `/tmp/sw-stabilize-threads.json` via `gh api graphql`
   (paginate `reviewThreads` with `after` until `hasNextPage` is false). Write each GraphQL response to
   a temp **file** before `jq` — multiline thread bodies break naive stdin pipelines.
2. **Harvest non-inline review findings** (the surface that has no thread to reply/resolve). CodeRabbit
   posts actionable findings inside collapsible `<details>` sections of its **review summary body** and
   its **PR-level walkthrough comment**, not only as inline threads. These never appear in
   `reviewThreads`, so fetch the bodies too:

   ```bash
   OWNER_REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
   gh api "repos/$OWNER_REPO/pulls/$PR_NUMBER/reviews" --paginate > /tmp/sw-stabilize-reviews.json
   gh api "repos/$OWNER_REPO/issues/$PR_NUMBER/comments" --paginate > /tmp/sw-stabilize-issue-comments.json
   ```

   From the bot-authored bodies, extract every finding under sections such as **"Outside diff range
   comments"**, **"Additional comments"**, and **"Nitpick comments"** into `/tmp/sw-stabilize-noninline.md`,
   keyed by `path:line` + the suggested change. Treat each as a first-class blocker — identical priority
   to an inline thread — the **only** difference is there is no reply/resolve handle (see the ledger).
3. Compute the check gate with **`scripts/check-gate.sh`** (canonical — do not hand-roll `gh` verdicts).
   Tee stdout to `/tmp/sw-stabilize-gate.json` for the RCA pass. Consume its JSON + exit code via the
   **`checks-gate`** skill (all checks, neutral allowlist applied). Pull failure logs for failing checks.
4. Run a `memory-preflight` read: known CI failures, review-bot false positives, prior stabilization
   decisions, and file-linked context for the PR paths. Memory informs triage; it never replaces
   verification against current code.

## RCA pass (R35)

After harvest, before the blocker ledger, run **one** bounded analysis step via
`skills/rca-core/SKILL.md` (**stabilize entry**). It consumes the artifacts above — it does **not**
re-fetch threads, reviews, or the gate.

- Inputs: `/tmp/sw-stabilize-threads.json`, `/tmp/sw-stabilize-noninline.md`, `/tmp/sw-stabilize-gate.json`
- Output: ranked hypotheses + causal chain for **`fix-now`** candidates only
- **Not a nested loop** — `stabilize-loop` owns the R29 iteration budget; this pass runs once per
  `/sw-stabilize` invocation
- **Bypass:** `resolve-with-evidence`, `already-fixed-with-evidence`, and defer buckets skip the
  causal-chain gate — classify them straight into the ledger

## Blocker ledger

Classify **each** item — inline thread **and** non-inline finding — into exactly one bucket:

- `fix-now` — valid, reproducible, feasible in this pass (prefer a small subset if the surface is large).
- `resolve-with-evidence` — invalid/stale/not-applicable; cite code, policy, or a prior commit.
- `already-fixed-with-evidence` — fixed on current `HEAD`; cite file/lines or commit.
- `defer-with-reason` — **only when `coderabbit.noDefer` is false.** Requires an inline rationale; sub-classify
  as `defer-inline` (non-extensive, reply-only) or `defer-issue` (extensive rework → GitHub issue).

### Inline threads vs non-inline findings

The bucket logic is the same for both, but the resolution mechanism differs:

- **Inline threads** have a thread ID → reply-before-resolve via GraphQL (below).
- **Non-inline findings** (`/tmp/sw-stabilize-noninline.md`: "Outside diff range comments", etc.) have
  **no thread ID** — they cannot be replied to or resolved. Triage and **fix them in code** exactly like
  threads, verify, then record their disposition in the pass summary (path:line → fixed-in `<sha>` /
  resolved-with-evidence / deferred-with-reason). Never skip a finding solely because it lacks a
  reply/resolve handle.

### Deferral issue threshold (only relevant when deferrals are allowed)

Create a tracking issue only for genuine extensive rework: cross-PR/cross-module refactor, new
component/schema/migration/API-contract change, architectural/pattern/doctrine decision, work owned by a
different unit of work, or coordinated multi-commit scope. Never open issues for nits, micro-refactors,
or trivial follow-ups — those are `defer-inline` (reply + resolve) or `resolve-with-evidence`.

## Procedure

0. **Merge-base sync** — `stabilize-merge-sync.sh status`; when `conflicting`, merge base, resolve,
   verify, push, re-probe. Do not harvest checks/threads until `mergeable`.
1. **RCA pass** — `Load skills/rca-core/SKILL.md` (stabilize entry) on the harvested artifacts; use its
   output to inform triage. Then classify every item into the ledger (below).
2. Triage all **unresolved** threads, all **non-inline findings** (`/tmp/sw-stabilize-noninline.md`), and
   all **failing** checks (under the gate) into exactly one ledger bucket.
3. **Verify** every item you intend to resolve against current code — no exceptions. Unverified items
   stay unresolved.
4. Implement `fix-now` items for this pass only. Do not expand scope to "finish the bot."
5. When deferrals are allowed and an item is `defer-issue`: search existing issues
   (`gh issue list --search`), then create one with a `## Relationships` section (`Blocked by:` /
   `Blocks:` / `Related:`, using `none` where empty) and mirror the dependency on referenced issues.
   Add the issue number to the ledger before replying to those threads.
6. **Threads (strict):** reply before resolve, with specific evidence (commit SHA, file paths, behavior).
   Use thread-level GraphQL only: `addPullRequestReviewThreadReply(input: { pullRequestReviewThreadId, body })`
   then `resolveReviewThread(input: { threadId })`. Resolve **only** verified `resolve-with-evidence`,
   `already-fixed-with-evidence`, or (when allowed) `defer-inline`/`defer-issue` items. Never mass-resolve.
   For multi-line reply bodies, pass the body via a file — inline shell heredocs with backticks break
   `gh api graphql`.
7. **Non-inline findings:** apply the `fix-now` code changes the same as for threads. There is no
   reply/resolve API, so do **not** attempt one — instead record each finding's disposition in the pass
   summary (and `memory-preflight` write where durable). Their "resolution" is the verified code change
   landing on `HEAD`; the next pass re-harvests the bodies and confirms the section no longer recurs.
8. Re-run `verify` commands from config across the touched surface; log to `/tmp/sw-stabilize-verify.log`.
9. If fixes were made: stage, create **one** focused commit for this pass, `bash scripts/git-push.sh`
   once (never raw `git push`; secret scan runs pre-push — R41/R50).
10. Store concise `memory-preflight` writes for durable learnings (recurring bot false positives, accepted
   review patterns, non-obvious CI fixes, file-specific debug context) with `relatedFiles`. No raw thread
   dumps, secrets, or routine pass/fail logs.
11. Return the PR URL, the ledger summary (counts of still-unresolved threads **and** still-open
    non-inline findings, and — when deferrals are allowed — `defer-inline` vs `defer-issue` with issue
    links), the gate verdict, and hand off to `/sw-watch-ci`.

**Communication intensity:** full

**Model tier:** build — resolve via `bash scripts/resolve-model-tier.sh --command sw-stabilize`.

## Guardrails

- Merge conflicts are **fix-now** and block check/thread triage until `mergeable` — never interpret
  "checks awaiting conflict resolution" as green or yellow.
- Failing checks, unresolved threads, non-inline review findings, and merge conflicts are **one**
  triangulation surface, evaluated in that order.
- Non-inline findings have no reply/resolve API — never invent one; their resolution is the verified code
  change on `HEAD`, confirmed by re-harvesting the review bodies on the next pass.
- When `coderabbit.noDefer` is true, do not defer — resolve with evidence or fix.
- Never resolve a thread you did not verify against current code (or tie to a concrete rationale/issue).
- Never mass-resolve to "clear the queue" or hit a thread-count target.
- Use thread-level reply APIs only (not `/pulls/comments/{id}/replies`, `addPullRequestReviewComment`,
  or top-level `gh pr comment`). Resolve only after the reply succeeds.
- Do not rerun workflows, merge, or dismiss failures automatically.
- Do not push without re-running verification on the fixes made this pass.
- Expect multiple passes to drain a large bot thread list — that is normal.
