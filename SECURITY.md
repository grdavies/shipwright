# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| latest release on `main` | yes |
| older tags | no |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report security issues privately to the repository owner via GitHub's
[private vulnerability reporting](https://github.com/grdavies/shipwright/security/advisories/new)
(if enabled) or by contacting the maintainer through their GitHub profile.

Include:

- A description of the issue and potential impact
- Steps to reproduce
- Affected versions or commits, if known
- Any suggested fix or mitigation

We aim to acknowledge reports within a few business days and will coordinate disclosure timing with you.

## Scope notes

Shipwright runs as a local Cursor/Claude Code plugin. Reports about third-party services (Recallium,
CodeRabbit, GitHub Actions upstream actions) may be redirected to those projects when the issue is not
introduced by this repository.
