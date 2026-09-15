# Getting started with Shipwright

Shipwright structures agentic development: frozen specs, a gated ship loop, and compounding memory.
**The default path is the packaged install** — you do not need to clone this repository to adopt
Shipwright in a project.

Contributor cloning remains supported and is documented explicitly below. Style and structure
conventions live in the [style guide](style-guide.md). Coined terms are in the
[glossary](glossary.md). Unsure which command to run? Use the [decision tree](decision-tree.md).

## Default: packaged install + single init

Initialization steps (canonical — must match `packaged_init_steps()` in
`scripts/sw-configure.py`):

1. Install the packaged console entry point (use `uv tool` or `pipx` — see below).
2. In the project repository, run `shipwright init --integration <host>`.
3. Reload the editor. On Cursor/Claude Code run `/sw-init` only if priority-zero surfaces still need confirm. On Codex invoke `$sw-init` (no slash-command palette) after fully quitting ChatGPT/Codex.
4. Start a small loop (`/sw-doc` or `/sw-deliver run <frozen-task-list>`).

**Install options** (use isolated environments to avoid PEP 668 conflicts on modern systems):

```bash
# Option 1: uv tool (recommended) — replace vX.Y.Z with desired release tag
uv tool install shipwright --from git+https://github.com/grdavies/shipwright.git@vX.Y.Z

# Option 2: pipx
pipx install git+https://github.com/grdavies/shipwright.git@vX.Y.Z

# Option 3: From a release wheel
uv tool install shipwright --from /path/to/shipwright_workflow-X.Y.Z-py3-none-any.whl
# or: pipx install /path/to/shipwright_workflow-X.Y.Z-py3-none-any.whl

# Option 4: Explicit venv (if uv/pipx unavailable)
python3 -m venv ~/.shipwright
~/.shipwright/bin/pip install git+https://github.com/grdavies/shipwright.git@vX.Y.Z
# Add ~/.shipwright/bin to PATH or symlink ~/.shipwright/bin/shipwright to ~/bin/
```

See [releases](https://github.com/grdavies/shipwright/releases) for available versions.

Then configure each project repository:

```bash
cd /path/to/your-project
shipwright init --integration cursor
# or
shipwright init --integration claude-code
# or
shipwright init --integration codex
```

That single invocation mirrors the host plugin onto the machine and configures the repository
(`.shipwright/` state root, host files, optional CI stub). Prefer `--dry-run` first to enumerate
every path the real run would touch. For many repos the packaged init already leaves a workable
baseline; `/sw-init` is only needed when priority-zero surfaces still require confirm.

**Codex:** there is no `/sw-init` slash command. `shipwright init --integration codex` registers the
personal marketplace, enables `shipwright@personal` in `~/.codex/config.toml`, and projects `$sw-init`
as a plugin skill. Fully quit ChatGPT/Codex, start a **new** chat, then invoke `$sw-init` (or ask
Shipwright to run the init interview) if you still need the guided doctor. Trust plugin hooks if
prompted.

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
python3 scripts/install.py --integration cursor   # or --integration codex
/sw-init   # Cursor/Claude Code. On Codex: $sw-init after restarting ChatGPT.
```

Run **Developer: Reload Window** in Cursor after install (or fully quit ChatGPT/Codex). The installer
mirrors the plugin locally and installs the editable `shipwright` console entry point. `/sw-init` (or
`$sw-init` on Codex) is the contributor configure step after clone — not the packaged `shipwright init`
adopter path.

This path remains fully supported; it is the **contributor** path, not the default adopter path.
The installer never configures projects for you automatically — `/sw-init` completes repo setup.

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

1. Install via `uv tool` or `pipx` (see install options above).
2. In your project repo: `shipwright init --integration cursor` (or `claude-code` / `codex`).
3. Reload the editor (Codex: fully quit ChatGPT, then `$sw-init` / `$sw-doc`); run a small loop.
4. Stop at the merge gate — do not force-merge to the default branch from the agent.

### Week two

1. Prefer `/sw-deliver run` for multi-phase work instead of manually chaining `/sw-ship`.
2. Tune only what hurts: `deliver.autonomy`, `review.provider`, `memory.provider` (catalog-registered id —
   see [configuration](configuration.md#step-1-memory-provider)).
3. After merges, let `/sw-cleanup` dry-run, then confirm removals.
4. Run `shipwright self check` periodically; upgrade when available.
5. Skim [workflows](workflows.md) for the doc → deliver → ship path you actually use.

Packaged installs resolve shipped issues providers from `dist/<host>/core/sw-reference/provider-conformance/`
under the installed wheel (see [self-upgrade](self-upgrade.md#packaged-provider-conformance)). After
`shipwright init`, operator workflow config is preserved across reinstall when any config candidate already
exists — `/sw-init` adjacent packaged path uses the same skip-overwrite policy.

### After a month

1. Use issue-store or file-store planning deliberately (configuration guide).
2. Rely on `/sw-status` and living planning indexes instead of tribal chat summary.
3. Route production signals through `/sw-feedback` / `/sw-debug` rather than patching on `main`.
4. Keep user docs free of internal planning IDs ([style guide](style-guide.md)).

## Scripts access (consumer repos)

Consumer project repos stay **zero-footprint** — init does not write repo-local Shipwright script
façades (`scripts/sw`, deliver forwarders, or `.cursor/sw-scripts-facade.json`). Helpers resolve through
the installed plugin install root via `scripts/sw-run.py`:

```bash
python3 "${CURSOR_PLUGIN_ROOT}/scripts/sw-run.py" wave_deliver.py -- --help
python3 "${CURSOR_PLUGIN_ROOT}/scripts/sw-run.py" check-gate.py
```

**Precedence:** self-repo working-tree `scripts/` (Shipwright source only) → validated `SHIPWRIGHT_SCRIPTS` →
plugin install (`sw_scripts_resolve.py`). Re-run `/sw-init` as doctor to detect and remove legacy forwarders
(confirm-gated — see [configuration — Scripts resolution](configuration.md#scripts-resolution-consumer-repos)).

Use `CLAUDE_PLUGIN_ROOT` on Claude Code installs. Absolute install paths (for example
`~/.cursor/plugins/local/shipwright/scripts/sw-run.py`) are **troubleshooting-only** — prefer the env-var
form in everyday docs and runbooks.

## Doc → implementation boundary (`doc.afterTasks`)

After `/sw-tasks` freezes the task list, `doc.afterTasks` controls what happens next (default **`confirm`**):

| Mode | Behavior |
|------|----------|
| `stop` | Halt after the frozen task list; print the docs-only seed command and `/sw-deliver run …`. |
| `confirm` | Show the task list and an **Implementation checkpoint**; require `proceed` or `yes`; then seed and deliver. |
| `auto` | Seed and dispatch `/sw-deliver run …` without a second prompt. |

Override per run: `/sw-doc --after-tasks=<mode>`.

## Agent-driven `/sw-cleanup`

After merge, `/sw-cleanup` enumerates merged branches and stale worktrees in **dry-run** mode. The agent
presents the `wouldRemove` set and asks you to confirm before applying removals. Declined or ambiguous
replies leave the dry-run report as-is.

## Worktree invariant

**No implementation files are written on bare `main`.** `/sw-deliver` provisions worktrees automatically.
For manual paths, use `/sw-worktree` and `/sw-start`. `scripts/sw-assert-worktree.py` enforces this at
implementation entry.

## Issue-store adopters

Opt-in via `planning.store.backend: issue-store` in `.cursor/workflow.config.json` (default unchanged).
Under issue-store, planning units and progress live in the issue provider; file-store users keep on-disk
planning trees. See [configuration](configuration.md) and [workflows](workflows.md).

## Single-pass `/sw-tasks`

`/sw-tasks` generates the **complete** frozen task list in one pass (phases, executable sub-tasks, and
traceability). Standalone, it outputs the list and stops without prompting for implementation.

## Review gating (canonical opt-out)

The schema default for `review.provider` is **`none`** (review gating off). CodeRabbit is **opt-in** —
set `review.provider: "coderabbit"` explicitly. The **canonical way to disable** external AI review is
`review.provider: "none"`.

## Deliver autonomy and living docs

- **`deliver.autonomy`** — default `autonomous`; runs `/sw-deliver` to the terminal gate without routine
  re-prompts. Set `supervised` for extra acknowledgement halts.
- **`legitimate.halt`** — only terminal default-branch merge, exhausted remediation, destructive git,
  configured checkpoints, phase timeout, external-wait exhaustion, or run-level budget.
- **Living-doc currency** — generated planning INDEX (`docs/planning/INDEX.md` derived region), legacy
  projections (`docs/prds/INDEX.md`, `GAP-BACKLOG.md`), and `COMPLETION-LOG.md` stay accurate via the
  maintenance reconciler on the feature branch; terminal merge is blocked on drift.
- **Frontmatter traceability** — Full-tier planning docs carry `brainstorm:`; `/sw-prd` and `/sw-freeze` enforce
  resolvable `brainstorm:` / `prd:` links.

## Plan policy (advanced)

`orchestration.planPolicy` defaults to `canonical`. The `proposed` path is pilot-only and refuses silent
opt-in toward shared `main`. See [configuration](configuration.md) and [workflows](workflows.md).

## Persona paths (after setup)

| Persona | Start with |
|---------|------------|
| Feature delivery | `/sw-doc` → freeze → `/sw-deliver run` |
| Quick fix on an existing branch | `/sw-ship` (still halts at merge) |
| Incident / production signal | `/sw-feedback` or `/sw-debug` |

## Next reading

- [Commands](commands.md) — orchestrators vs atomics
- [Workflows](workflows.md) — end-to-end paths
- [Configuration](configuration.md) — knobs including `delegation.mode`
- [Testing](testing.md) — verify and gate expectations
