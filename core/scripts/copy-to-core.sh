#!/usr/bin/env bash
# Refresh core/ workflow copies from repo-root scripts (content dirs live only under core/ post-U6).
#
# Usage: scripts/copy-to-core.sh
# Idempotent: re-run refreshes core/scripts from root harness scripts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/core"

mkdir -p "$CORE"

for dir in commands skills rules agents providers; do
  [ -d "$ROOT/$dir" ] || continue
  mkdir -p "$CORE/$dir"
  rsync -a --delete "$ROOT/$dir/" "$CORE/$dir/"
done

mkdir -p "$CORE/scripts"
rsync -a --delete \
  --exclude 'test/' \
  --exclude 'check-frozen.sh' \
  "$ROOT/scripts/" "$CORE/scripts/"
# Harness-only: CI freeze check stays at repo root, not emitted via core/dist.
rm -f "$CORE/scripts/check-frozen.sh"

if [ -d "$ROOT/.pf" ]; then
  mkdir -p "$CORE/sw-reference"
  rsync -a --delete "$ROOT/.pf/" "$CORE/sw-reference/"
elif [ -d "$ROOT/.sw" ]; then
  mkdir -p "$CORE/sw-reference"
  # Preserve JSON defaults authored only under core/sw-reference/ (PRD 006/008).
  rsync -a --delete \
    --exclude 'model-routing.defaults.json' \
    --exclude 'communication-routing.defaults.json' \
    --exclude 'verify-presets.json' \
    --exclude 'pr-test-plan.manifest.json' \
    --exclude 'planning-unit.schema.json' \
    --exclude 'inflight-signal.schema.json' \
    --exclude 'model-tier-hook-feasibility.md' \
    --exclude 'models-tiering.md' \
    --exclude 'capability-manifest.md' \
    --exclude 'capability-manifest.schema.json' \
    --exclude 'capability-index.json' \
    --exclude 'signal-context.schema.json' \
    --exclude 'kernel-classification.json' \
    --exclude 'kernel-classification.md' \
    --exclude 'guidelines.schema.json' \
    --exclude 'guidelines.json' \
    --exclude 'guidelines.md' \
    --exclude 'deterministic-regen-paths.json' 

    --exclude 'templates/' \
    "$ROOT/.sw/" "$CORE/sw-reference/"
fi

echo "copy-to-core: synced emittable content -> $CORE"
