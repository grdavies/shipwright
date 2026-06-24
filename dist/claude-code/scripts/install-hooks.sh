#!/usr/bin/env bash
# Bootstrap git hooks for phase-flow v2 doc-freeze local warning.
# Sets core.hooksPath to plugin hooks/ (relative to repo root).
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
# shellcheck source=pf-resolve-plugin-root.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pf-resolve-plugin-root.sh"
PLUGIN_ROOT="$(pf_resolve_plugin_root "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")"
HOOKS_REL="$(realpath --relative-to="$ROOT" "$PLUGIN_ROOT/hooks" 2>/dev/null || python3 -c "import os,sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$PLUGIN_ROOT/hooks" "$ROOT")"

cd "$ROOT"
chmod +x "$PLUGIN_ROOT/scripts/check-frozen.sh" "$PLUGIN_ROOT/hooks/pre-commit-frozen.sh" "$PLUGIN_ROOT/hooks/pre-commit" 2>/dev/null || true
git config core.hooksPath "$HOOKS_REL"

echo "Installed hooks: core.hooksPath=$HOOKS_REL"
echo "Local freeze hook is early-warning only; CI check-frozen.sh is authoritative."
