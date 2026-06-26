#!/usr/bin/env bash
# True when the repo root contains the .shipwright-dev sentinel (PRD 018 R13).
set -euo pipefail
ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
[[ -f "$ROOT/.shipwright-dev" ]]
