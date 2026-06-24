#!/usr/bin/env bash
# Install Shipwright into the local Cursor plugin directory.
#
# Cursor's plugin loader does NOT reliably follow a symlink whose target is on an
# external/removable volume (it may not be mounted when Cursor launches), so the
# plugin is installed as a real directory copy on the internal disk.
#
# For end users:   clone the repo, then run this script directly.
# For developers:  run `python3 -m sw generate --all` after editing core/, then re-run.
#
# Usage: scripts/install.sh [dest]
#   dest defaults to ~/.cursor/plugins/local/shipwright
#   Run "Developer: Reload Window" in Cursor after installing.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${SW_INSTALL_SRC:-$REPO/dist/cursor}"
DEST="${1:-$HOME/.cursor/plugins/local/shipwright}"

# Pre-flight: source tree must exist
if [ ! -d "$SRC" ]; then
  echo "error: dist/cursor/ not found at $SRC" >&2
  echo "       Run: python3 -m sw generate --all" >&2
  exit 1
fi

# Pre-flight: rsync is required
if ! command -v rsync >/dev/null 2>&1; then
  echo "error: rsync not found — install it and retry" >&2
  exit 1
fi

# Show version being installed
VERSION_FILE="$REPO/version.txt"
if [ -f "$VERSION_FILE" ]; then
  VERSION="$(cat "$VERSION_FILE")"
  echo "Installing shipwright v$VERSION -> $DEST"
else
  echo "Installing shipwright -> $DEST"
fi

# Replace any stale symlink with a real directory
if [ -L "$DEST" ]; then
  echo "Removing stale symlink at $DEST"
  rm "$DEST"
fi

mkdir -p "$DEST"
rsync -a --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  "$SRC/" "$DEST/"

echo "Done. Run 'Developer: Reload Window' in Cursor to pick up changes."
