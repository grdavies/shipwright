#!/usr/bin/env python3
"""PRD 338 phase 11 — distribution bundle acceptance harness (R23–R31)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
    src = _patch_source(_SOURCE, root)
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# PRD 338 phase 11 — bundle acceptance across docs, version, trust, installer, currency.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

DIST_CURSOR="$ROOT/dist/cursor"
DIST_CLAUDE="$ROOT/dist/claude-code"
DOC_GUIDE="$ROOT/docs/guides/getting-started.md"
CORE_DOC="$ROOT/core/documentation/getting-started.md"
README="$ROOT/README.md"

# --- install-root-docs-emitted (R23) ---
for platform in cursor claude-code; do
  if [[ ! -f "$ROOT/dist/$platform/documentation/getting-started.md" ]]; then
    bad "install-root-docs-emitted: dist/$platform/documentation/getting-started.md missing"
  fi
done
[[ "$FAIL" -eq 0 ]] && ok "install-root-docs-emitted"

# --- public-redirect-stubs (R23) ---
if grep -qi 'Redirect' "$DOC_GUIDE" && grep -qi 'install-root' "$DOC_GUIDE"; then
  ok "public-redirect-stubs"
else
  bad "public-redirect-stubs"
fi

# --- consumer-examples-install-root (R25) ---
BOOTSTRAP_FAIL=0
while IFS= read -r -d '' f; do
  if grep -q 'scripts/sw_bootstrap.py' "$f" 2>/dev/null; then
    bad "consumer-examples-install-root: $(echo "$f" | sed "s|$ROOT/||") references scripts/sw_bootstrap.py"
    BOOTSTRAP_FAIL=1
  fi
done < <(find "$ROOT/core/documentation" -type f -name '*.md' -print0 2>/dev/null)
[[ "$BOOTSTRAP_FAIL" -eq 0 ]] && ok "consumer-examples-install-root"

# --- pure-install-version-metadata (R27) ---
for platform in cursor claude-code; do
  if [[ ! -f "$ROOT/dist/$platform/version.txt" ]]; then
    bad "pure-install-version-metadata: dist/$platform/version.txt missing"
  fi
done
[[ "$FAIL" -eq 0 ]] && ok "pure-install-version-metadata"

# --- dist-trust-anchors-present (R28) ---
if [[ -f "$ROOT/scripts/graph/packages/trust.py" ]] && \
   python3 -c "import sys; sys.path.insert(0,'$ROOT/scripts'); from graph.packages import trust; assert hasattr(trust, 'resolve_dist_trust_verdict')" 2>/dev/null; then
  ok "dist-trust-anchors-present"
else
  bad "dist-trust-anchors-present"
fi

# --- claude-installer-entrypoint (R29) ---
if grep -q 'claude-code' "$ROOT/core/scripts/install.py" && \
   grep -q 'claude-code' "$ROOT/platforms/claude-code/emitter.py"; then
  ok "claude-installer-entrypoint"
else
  bad "claude-installer-entrypoint"
fi

# --- docs-currency-profiles (R31) ---
if grep -q 'PROFILE_CONSUMER' "$ROOT/scripts/docs-currency-gate.py" && \
   grep -q 'PROFILE_PLUGIN_SELF' "$ROOT/scripts/docs-currency-gate.py"; then
  ok "docs-currency-profiles"
else
  bad "docs-currency-profiles"
fi

# --- canonical-core-doc-home (R23) ---
if [[ -f "$CORE_DOC" ]] && grep -qi '/sw-init' "$CORE_DOC"; then
  ok "canonical-core-doc-home"
else
  bad "canonical-core-doc-home"
fi

# --- readme-adopter-landing (R23/R25) ---
if grep -qi 'install-root' "$README" || grep -qi 'documentation/' "$README"; then
  ok "readme-adopter-landing"
else
  bad "readme-adopter-landing"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "run-prd338-bundle-acceptance: FAIL"
  exit 1
fi
echo "run-prd338-bundle-acceptance: PASS"

"""

if __name__ == "__main__":
    raise SystemExit(main())
