# Provenance manifest

Tracks **external** upstream repositories and **runtime dependencies** Shipwright integrates with.
Native Shipwright components are not listed here. Refresh pins via `/sw-upstream` is deferred.

## External repositories (vendored patterns)

Adapted workflow patterns — not runtime plugin dependencies. Shipwright is self-contained at install time.

| Area | Source | Pin | Notes |
|------|--------|-----|-------|
| Persona panel doc review | [compound-engineering-plugin](https://github.com/everyinc/compound-engineering-plugin) | cache `2648200ed2352b6e19a93dcfffc764efe70b6a1b` | `/sw-doc-review` + seven `sw-*-reviewer` agents; findings schema + synthesis |
| Brainstorm dialogue | [compound-engineering-plugin](https://github.com/everyinc/compound-engineering-plugin) | cache `2648200ed2352b6e19a93dcfffc764efe70b6a1b` | `/sw-brainstorm`; one-question dialogue + synthesis checkpoint |
| Retro + compounding | [compound-engineering-plugin](https://github.com/everyinc/compound-engineering-plugin) | cache `2648200ed2352b6e19a93dcfffc764efe70b6a1b` | `/sw-retro`, `/sw-compound`; writes through memory seam only |
| Debug RCA + routing | [compound-engineering-plugin](https://github.com/everyinc/compound-engineering-plugin) | cache `2648200ed2352b6e19a93dcfffc764efe70b6a1b` | `ce-debug`-style phased RCA; `/sw-debug` routes by fix size |
| Local code review (report-only) | [compound-engineering-plugin](https://github.com/everyinc/compound-engineering-plugin) | cache `2648200ed2352b6e19a93dcfffc764efe70b6a1b` | `ce-code-review` adapter in `core/providers/code-review/`; Shipwright owns apply + gate |
| Communication compression | [caveman](https://github.com/juliusbrussee/caveman) | `~/.agents/skills/caveman/SKILL.md` | Ultra-compressed chat intensity (lite / full / ultra) bundled as `core/communication/caveman-core.md`; `/sw-caveman` exposes the override surface |

## Runtime dependencies (external services & tools)

Configured per repo via `.cursor/workflow.config.json` (or zero-config in-repo memory). Credentials
stay in the environment / secret store — never committed.

| Dependency | Role | Required when | Docs / adapter |
|------------|------|---------------|----------------|
| [CodeRabbit CLI](https://docs.coderabbit.ai/) | AI PR + local review | `review.provider: coderabbit` (default) | `core/providers/review/coderabbit.{sh,md}` |
| [Recallium](https://recallium.ai/) MCP | Durable memory provider | `memory.provider: recallium` | `core/providers/recallium.md` |
| [Sentry](https://docs.sentry.io/) MCP | Production signal enrichment | `/sw-debug` with Sentry context | `core/skills/debug/references/sentry.md` |
| [GitHub CLI](https://cli.github.com/) (`gh`) | CI gate, PR head, review state | `/sw-watch-ci`, `/sw-stabilize`, gate scripts | `core/scripts/check-gate.sh` |
| [Playwright](https://playwright.dev/) | Browser verification adapter | `verify.provider: playwright` | `core/providers/verify/playwright.{sh,md}` |

Optional at install: none of the above are required to install the plugin. `/sw-setup` validates
what your selected providers need.

## Update policy

When adapting upstream compound-engineering changes:

1. Record the new pin in the table above.
2. Note behavioral deltas in the PR that ports the change.
3. Run the relevant fixture suite for the affected seam.

When adding a new external dependency:

1. Add a row under **Runtime dependencies** with adapter paths.
2. Document config keys in `core/sw-reference/config.schema.json`.
