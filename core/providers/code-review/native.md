# Native local review adapter (Shipwright panel)

Markdown companion for phase 1 of `/sw-review` and `/sw-ship`. Dispatches a fixed always-on core panel plus
deterministic signal-gated specialists via the Task tool. Reviewer subagents are **read-only** with respect to
the repo; they return structured findings only. Shipwright-owned apply machinery (`code-review-apply-check.sh` +
pf edit) performs mutations after deterministic rails pass.

## No external dependency (R2)

Does **not** invoke compound-engineering `ce-code-review` or any external plugin. Runs entirely on
Shipwright-dispatched subagents and the session model. Repos that explicitly set `review.local.provider:
"ce-code-review"` keep that adapter (R3).

## Report-and-apply boundary (R4)

1. **Report** — spawn core + gated specialists; normalize to `CAPABILITIES.md` contract (`status`, `verdict`,
   `findings[]`).
2. **Apply** — auto-apply eligible findings only when `review.local.apply` resolves to `auto` and
   `code-review-apply-check.sh` returns eligible (P0 never; security-sensitive never; P1 only when validated;
   P2/P3 when rails pass).
3. **Re-verify** — bounded `/sw-verify` per applied fix; revert failed fixes.
4. **Gate** — `code-review-gate.sh` with additive `review.local.gate` (surface-only default).

Reviewer subagents MUST NOT write to the working tree.

## Normalized result contract

Conforms to `core/providers/code-review/CAPABILITIES.md`. Fail-closed: `skipped | failed | degraded` without
`findings` is never a clean pass (R5/R66).

## Config resolution (R14–R16, R61)

Resolved by `scripts/review-local-resolve.sh` (schema-default merged):

```
enabled  = config.review.local.enabled  ?? true
provider = config.review.local.provider ?? "native"
apply    = config.review.local.apply    ?? "auto"
fire phase-1 iff (enabled == true AND provider != "none")
independent of config.review.provider (incl. "none")
```

## Selection signal table (authoritative — R7, R8, R42, R47, R51, R53, R60, R73)

**Core (always-on, R6):** `correctness`, `maintainability`, `scope-fidelity`, `testing`, `security`.

`previous-comments` is **excluded** from phase 1 (R9).

| Specialist | Fires when (deterministic signal) |
|------------|-----------------------------------|
| `performance` | hot-path / loop / query / index keywords in added lines, or `**/*.sql` changes |
| `api-contract` | public API / route / handler / OpenAPI / proto / GraphQL schema file paths or markers |
| `data-migration` | migration paths (`**/migrations/**`, `**/migrate/**`), schema dumps (`**/schema.sql`), backfill scripts (`*backfill*`) |
| `reliability` | error-handling / retry / timeout / concurrency markers; silent-failure lens folded in (R41) |
| `adversarial` | ≥50 changed executable code lines (R60) OR auth / payments / data-mutation / external-API keywords |
| `ui-ux` | globs per R73 (see UI/UX section) |
| `type-design` | `*.d.ts` or added/changed lines with `interface` / `type` / `class` / `struct` / `enum` / schema-model markers |
| `comment-accuracy` | changed comment / docstring lines (`//`, `#`, `/*`, `*`, `"""`, `'''`) or `*.md` / `*.mdx` doc files |
| `ai-native` | AI-surface paths (`commands/**`, `core/commands/**`, `skills/**`, `core/skills/**`, `rules/**`, `providers/**`, prompt-declaring `*.md`) or untrusted-LLM markers (`openai`, `anthropic`, `llm`, `prompt`, `chat.completions`) |

Runtime engine: `scripts/code-review-select.sh` (identical diff → identical roster; R33/R61). Every fired
signal is announced in the panel activation record (R10).

## Executable-code-line counting algorithm (R60)

Used for the `adversarial` ≥50-line threshold (`ADVERSARIAL_EXECUTABLE_LINE_THRESHOLD = 50`).

**Input:** added lines only (unified-diff `+` lines or `added_lines[]` in diff JSON). Deleted lines are
ignored for the threshold.

**Exclude** (line is not executable):

- blank / whitespace-only
- brace-only: `{`, `}`, `{ }`, `(`, `)`, `[`, `]`
- import / include / require lines: `import …`, `from … import`, `#include`, `using …`, `require(`, `use …`
- comment-only: `//`, `#` (not `#!`), `/*`, leading `*`, `--`, `<!--`

**Language coverage:** JS/TS, Python, Go, Rust, Java/Kotlin, C/C++, Ruby, PHP, Shell — generic heuristics above.

**Boundary fixtures:** 49 → no adversarial line trigger; 50 → fires; 51 → fires.

## Fix-size bound (R60)

Auto-apply rejects fixes exceeding **any** bound (all checked by `code-review-apply-check.sh`):

| Bound | Value |
|-------|-------|
| `MAX_FIX_CHARS` | 2000 characters in `suggested_fix` |
| `MAX_FIX_LINES` | 15 non-blank lines in `suggested_fix` |
| `MAX_FIX_HUNKS` | 3 unified-diff hunk headers (`@@`); inline fixes count as 1 hunk |

## Security-sensitive deny-list (R21, R48, R55)

Surface-only at every severity. Matched case-insensitively on repo-relative path **or** content markers in
changed diff lines **or** `suggested_fix` (match on either → surface-only).

### Path globs

`**/auth/**`, `**/authz/**`, `**/*secret*`, `**/*credential*`, `**/.env*`, `**/.github/workflows/**`,
`**/*.pem`, `**/*.key`, `**/*.p12`, `**/*.pfx`, `**/*.jks`, `**/*.keystore`, `**/.ssh/**`, `**/id_rsa*`,
`**/id_ed25519*`, `**/*.asc`, `**/*.gpg`, `**/.npmrc`, `**/.netrc`, `**/.pypirc`, `**/.dockercfg`,
`**/.docker/config.json`, `**/*.tf`, `**/*.tfvars`, `**/Dockerfile*`, `**/.gitlab-ci.yml`, `**/.circleci/**`,
`**/Jenkinsfile`, `**/azure-pipelines.yml`, `**/.drone.yml`, `**/bitbucket-pipelines.yml`

### Content markers

`password`, `secret`, `token`, `apikey`, `api_key`, `private_key`, `authorization`, `set-cookie`,
`-----BEGIN`, `client_secret`, `_authToken`

### Security-control markers (R56)

Surface-only regardless of path when changed lines or `suggested_fix` match: `authorize`, `permission`, `role`,
`isAdmin`, `verifyToken`, `verifySignature`, `verifyPassword`, `hmac`, `jwt`, `session`, `cookie`, `csrf`,
`cors`, `bcrypt`, `crypto`

Also surface-only when `security_reviewer_touched: true` on the finding.

## Apply path validation (R57)

Before write: realpath-canonicalize target; require canonical path within repo root; reject any symlink path
component; reject `.git/**`; re-validate immediately before write (TOCTOU); reject patch whose internal target
differs from validated `finding.file` (`--patch-target`).

## P1 validation wave (R22, R49, R62)

Independent **fresh-context** second-opinion subagent at deep / session tier **before** P1 auto-apply:

- **Input:** diff + neutral location (`file`, `line`) only — never first reviewer's `title`, `suggested_fix`, or
  reasoning.
- **Memory:** validator MUST NOT read the same memory entries the first reviewer used.
- **Same-model limit:** same-model validation cannot catch correlated false positives — documented limitation.
- **Outcome:** confirming validation + `--validated` flag admits P1 to apply-check; non-confirming or degraded
  validation surfaces P1 only.
- Deterministic gates (deny-list, symlink, fix-size) always run regardless of validator confirmation (R58).

## Native UI/UX checklist (R72, R73)

WCAG 2.2 AA-anchored baseline (native-only default; enrichment opt-in via `review.local.ui.enrich`):

- contrast (1.4.3 / 1.4.11)
- visible focus + focus order (2.4.3 / 2.4.7)
- keyboard operability — no traps; Enter / Escape semantics (2.1.1 / 2.1.2)
- name / role / value — ARIA roles, accessible names, landmarks (4.1.2)
- `prefers-reduced-motion` (2.3.3)
- minimum target size — 2.5.5 / 2.5.8
- semantic structure / heading hierarchy (1.3.1)
- form-label / error association (3.3.2)
- touch / interaction states; layout / responsive; composition / boolean-prop hygiene

May draw on local `accessibility-a11y` skill as a non-network authoring source.

### `ui-ux` selection signals (R73)

File globs: `*.tsx`, `*.jsx`, `*.vue`, `*.svelte`, `*.css`, `*.scss`, `*.less`, `*.styles.ts`, `*.css.ts`,
`*.swift`, `*.kt`, `**/res/layout/*.xml`, `*.dart`, `*.storyboard`, `*.xib`.

Directory globs: `**/components/**`, `**/ui/**`, `**/styles/**`, `**/theme/**`.

CSS-in-JS markers in `.ts`/`.js` added lines: `styled`, `` css` ``, `makeStyles`, `createGlobalStyle`.

### `review.local.ui.enrich` (R52/R73)

Enum: `off` (default, native checklist only) | `ui-ux-pro-max` | `vercel-web-guidelines`.

Enrichment augments but never overrides the native baseline. Bounded fetch timeout; announce on use /
degradation; absence or failure never blocks review.

## scope-fidelity (R11, R12)

Advisory only — flags silent defers, stubs, marker-commented incomplete work, omissions vs stated intent.
MUST NOT emit a binding completeness verdict; `gap-check` remains authoritative at `/sw-ship`.

## Verify scope (R63)

`/sw-verify` is necessary but not sufficient vs `check-gate.sh`. Auto-apply restricted to fix classes the
configured verify can validate.

## Model tiering (R27)

`correctness`, `security`, `adversarial`, and P1 validation wave inherit deep tier; others mid-tier. Tiers from
`models.tiers` only — no semantic tier in agent frontmatter.

## Config

`review.local.provider: "native"` (schema default). See `CAPABILITIES.md` and `workflow.config.json`.
