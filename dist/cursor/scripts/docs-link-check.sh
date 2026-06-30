#!/usr/bin/env bash
# Advisory offline markdown link checker (PRD 011 — R11–R13).
#
# Usage: docs-link-check.py [--strict] [--include-prds]
# Scans README.md and docs/guides/** (optionally docs/prds/**) for repo-relative links.
# Exit: 0 advisory (even with findings); 20 strict with broken links; 2 error
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/docs_link_check.py" "$@"
