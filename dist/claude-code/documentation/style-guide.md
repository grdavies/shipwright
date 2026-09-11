# Shipwright documentation style guide

This guide sets how Shipwright writes **adopter-facing** docs under `docs/guides/` and the root
`README.md`. Planning artifacts (`docs/prds/`, decision logs, changelogs) follow their own conventions
and may cite internal IDs.

## Base layer: Google Developer Documentation Style Guide

Follow the [Google Developer Documentation Style Guide](https://developers.google.com/style) for:

- Second person (“you”) and active voice
- Present tense for current behavior; future tense only for upcoming steps
- Short sentences; one idea per paragraph
- Sentence case for headings
- Code font for commands, paths, config keys, and literals
- Link with descriptive text (avoid “click here”)

## Structure: Diátaxis

Organize guides by reader intent ([Diátaxis](https://diataxis.fr/)):

| Type | Job | Shipwright home |
|------|-----|-----------------|
| **Tutorials** | Learn by doing | [Getting started](getting-started.md) adoption arc |
| **How-to guides** | Achieve a goal | [Commands](commands.md), [Workflows](workflows.md) |
| **Reference** | Look up facts | [Configuration](configuration.md), [Glossary](glossary.md), [Decision tree](decision-tree.md) |
| **Explanation** | Understand why | Positioning sections in getting-started; decision logs for maintainers |

Do not mix a long explanation into a how-to. Link across types instead.

## What stays out of user prose

In `README.md` and `docs/guides/*`:

- Do **not** cite PRD numbers, requirement IDs (R-IDs), or gap IDs
- Do **not** narrate internal process provenance (“as of the deliver-hardening wave…”)
- Put that provenance in changelogs, decision logs, or planning docs

## Naming: slug vs title

| Surface | Rule | Example |
|---------|------|---------|
| **Slug** | kebab-case; stable in paths, branches, unit ids | `operator-surface-reliability-craft-ux` |
| **Title** | Human sentence case; may change without renaming the slug | “Operator surface reliability and craft UX” |
| **Branch** | `<type>/<slug>` from Conventional Commits types | `feat/operator-surface-reliability-craft-ux` |
| **Command** | Always `sw-` prefix | `/sw-deliver` |

Never rename a slug casually once frozen artifacts or issues reference it.

## Commits and pull requests

[Conventional Commits](https://www.conventionalcommits.org/) remain the authoritative format gate
(`type(scope): description`). The style guide only asks for clarity:

- Prefer a subject that states the user-visible why
- Keep PR bodies scannable: summary, test plan, risk notes
- Squash-merge titles must still pass commitlint

## Cross-links

- Prefer relative links within `docs/guides/`
- Link the [glossary](glossary.md) on first use of coined terms in a guide
- Route “which command?” questions to the [decision tree](decision-tree.md)

## Checklist before merging guide edits

1. Diátaxis type is clear from the opening paragraph
2. No PRD / R-ID / gap tokens in user prose
3. Commands use full `/sw-…` names
4. New coined terms appear in the glossary
5. Links resolve (`python3 scripts/docs-link-check.py` when available)
