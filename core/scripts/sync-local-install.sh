#!/usr/bin/env bash
# Sync this plugin repo into the local Cursor plugin install directory.
#
# Cursor's plugin loader does NOT reliably follow a symlink whose target is on an
# external/removable volume (it may not be mounted when Cursor launches), so local
# plugins are installed as a real directory copy on the internal disk. Run this after
# changing the plugin, then "Developer: Reload Window" in Cursor.
#
# Usage: scripts/sync-local-install.sh [dest]
#   dest defaults to ~/.cursor/plugins/local/phase-flow-v2
set -euo pipefail

SRC="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/dist/cursor}"
DEST="${1:-$HOME/.cursor/plugins/local/phase-flow-v2}"

if [ -L "$DEST" ]; then
  echo "Removing stale symlink at $DEST"
  rm "$DEST"
fi

mkdir -p "$DEST"
rsync -a --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude 'scripts/sync-local-install.sh' \
  "$SRC/" "$DEST/"

echo "Synced phase-flow-v2 -> $DEST"
echo "Now run 'Developer: Reload Window' in Cursor to pick up changes."
