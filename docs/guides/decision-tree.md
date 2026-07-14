# Decision tree

Quick routing for the `sw-` command surface and per-worktree state. Pair with the [glossary](glossary.md).

## Which entry command?

```mermaid
flowchart TD
  start([What do you need?]) --> newScope{New product scope<br/>or unclear design?}
  newScope -->|yes| doc["/sw-doc<br/>(or /sw-brainstorm → … → /sw-tasks)"]
  newScope -->|no| bug{Production bug<br/>or incident signal?}
  bug -->|yes| debug["/sw-debug"]
  bug -->|no| feedback{Inbound feedback<br/>to classify?}
  feedback -->|yes| fb["/sw-feedback"]
  feedback -->|no| frozen{Frozen task list<br/>ready to implement?}
  frozen -->|yes| deliver["/sw-deliver run"]
  frozen -->|no| single{Single-leaf ship<br/>already on a branch?}
  single -->|yes| ship["/sw-ship"]
  single -->|no| status["/sw-status<br/>or /sw-init"]
  doc --> deliver
  debug --> routeDbg{Small fix?}
  routeDbg -->|yes| deliver
  routeDbg -->|no| doc
```

## Per-worktree state machine (deliver / ship)

```mermaid
stateDiagram-v2
  [*] --> Provisioned: worktree + phase branch
  Provisioned --> Executing: /sw-execute
  Executing --> Verifying: tests + gates
  Verifying --> Reviewing: local / external review
  Reviewing --> PROpen: /sw-commit + /sw-pr
  PROpen --> Watching: /sw-watch-ci
  Watching --> Stabilizing: /sw-stabilize if red
  Stabilizing --> Watching: push fix
  Watching --> MergeReady: CI green + ship chain complete
  MergeReady --> MergedToIntegration: deliver merge onto integration
  MergedToIntegration --> [*]: next phase or terminal PR gate
  Watching --> Blocked: exhausted remediation
  Blocked --> [*]: resume via /sw-deliver run
```

## Operator reminders

- Not sure which command? Run bare `/sw` — it reads worktree/planning state and proposes the one next action
  with confirm, rather than making you walk this chart by hand.
- Prefer `/sw-deliver run` for a frozen task list—do not hand-roll phase worktrees while the driver can advance.
- `/sw-ship` never merges to the default branch; humans own that gate.
- After merge, `/sw-cleanup` dry-runs removals until you confirm.

## Consult and capture (outside the pipeline)

`/sw-ask`, `/sw-become`, `/sw-note`, and `/sw-guide` never join the flowchart above — they are read-only or
local-capture surfaces you can reach for at any point without affecting pipeline state. `/sw-ask` and
`/sw-guide` never write; `/sw-note` writes only to your local notebook until you explicitly graduate an item;
`/sw-become` writes only a new persona file after you confirm the draft.

## Deprecated aliases

`/sw-setup` and `/sw-compound`/`/sw-compound-ship` remain as one-release delegating aliases to `/sw-init` and
`/sw-retrospective` respectively — see [commands](commands.md#deprecated-command-aliases-closed-rename-table)
for the closed rename table. Retire call sites onto the replacement name before the alias window closes.
