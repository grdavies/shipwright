#!/usr/bin/env bash
# Fail-closed brainstorm↔PRD frontmatter traceability gate (PRD 009 A1 — R54/R55).
# Usage: doc-link-check.sh --path <prd-or-brainstorm> [--tier full|standard]
# Exit: 0 pass, 20 fail, 2 error
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/doc_link.py" check "$@"
