# Getting started with Shipwright

Shipwright structures agentic development: frozen specs, a gated ship loop, and compounding memory.
**The default path is the packaged install** — you do not need to clone this repository to adopt
Shipwright in a project.

Contributor cloning remains supported and is documented explicitly below.

## Default: packaged install + single init (R50)

1. Install the packaged console entry point (from a release or local build of this package):

```bash
pip install shipwright
# or, from a checked-out release tag / wheel:
# pip install .
```

2. In the **project** repository you want to configure, run one init for your host:

```bash
shipwright init --integration cursor
# or
shipwright init --integration claude-code
```

That single invocation mirrors the host plugin onto the machine and configures the repository
(`.shipwright/` state root, host files, optional CI stub). Prefer `--dry-run` first to enumerate
every path the real run would touch.

3. Reload the editor, then run `/sw-init` (or your host's equivalent) only if the interview still
has priority-zero surfaces to confirm. For many repos the packaged init already leaves a workable
baseline.

4. Start a small loop: `/sw-doc` on a tiny idea, or `/sw-deliver run <frozen-task-list>`.

### Self-check and self-upgrade

```bash
shipwright self check     # installed vs available; degraded if origin unreachable
shipwright self upgrade   # apply update after integrity verification
```

`self check` resolves upgrade manifests from the **distribution origin recorded in the artifact's
version stamp** (not a hard-coded URL), so forks use the same mechanism. If the origin is
unreachable, the check is reported as **degraded** — never as "up to date".

### Integrity threat model (same words the code reports)

Distributed artifacts carry a SHA-256 integrity marker. A failed check **refuses the upgrade** and
names **corruption in transit or on disk**. The marker does **not** assert authenticity, provenance,
or tamper detection — an attacker who controls the distribution origin is out of scope.

### `.shipwright/` layout

After init, Shipwright-owned configuration and run state live under **`.shipwright/`** in the
consumer repository (harness-neutral). Host-convention directories (for example Cursor rules) receive
only host-required files produced through emitters — not ad-hoc workflow writes.

## Contributor path: clone this repository

Use the clone path when you are developing Shipwright itself or need a working tree of scripts:

```bash
git clone https://github.com/grdavies/shipwright
cd shipwright
python3 scripts/install.py
# then in a consumer repo:
shipwright init --integration cursor
```

This path remains fully supported; it is the **contributor** path, not the default consumer path.

## Positioning

| Need | Shipwright | Ad-hoc agent chat |
|------|------------|-------------------|
| Spec → tasks → merge gate | Frozen task lists and `/sw-deliver` | Easy to lose the thread |
| Isolation | Linked worktrees; no bare-`main` implementation | Easy to commit on the wrong branch |
| CI truth | Deterministic check-gate before “ready” | Easy to declare green early |
| Memory | Provider-routed, redacted writes | Easy to paste secrets into chat history |

Shipwright optimizes for **repeatable delivery**, not for skipping human merge judgment.

## Adoption arc

### First session (packaged default)

1. `pip install shipwright` (or install a release wheel).
2. In your project repo: `shipwright init --integration cursor` (or `claude-code`).
3. Reload the editor; run a small `/sw-doc` or `/sw-deliver run …` loop.
4. Stop at the merge gate — do not force-merge to the default branch from the agent.

### Week two

1. Prefer `/sw-deliver run` for multi-phase work instead of manually chaining `/sw-ship`.
2. Tune only what hurts: `deliver.autonomy`, `review.provider`, `memory.provider`.
3. After merges, let `/sw-cleanup` dry-run, then confirm removals.
4. Run `shipwright self check` periodically; upgrade when available.

### After a month

1. Use issue-store or file-store planning deliberately (configuration guide).
2. Rely on `/sw-status` and living planning indexes instead of tribal chat summary.
3. Route production signals through `/sw-feedback` / `/sw-debug` rather than patching on `main`.

## Scripts access (consumer repos)

Consumer project repos stay **zero-footprint** — init does not write repo-local Shipwright script
façades. Helpers resolve through the installed plugin / packaged console.

## Worktree invariant

**No implementation files are written on bare `main`.** `/sw-deliver` provisions worktrees
automatically. For manual paths, use `/sw-worktree` and `/sw-start`.

## Next reading

- [Commands](commands.md) — orchestrators vs atomics
- [Workflows](workflows.md) — end-to-end paths
- [Configuration](configuration.md) — knobs including `delegation.mode`
- [Testing](testing.md) — verify and gate expectations
