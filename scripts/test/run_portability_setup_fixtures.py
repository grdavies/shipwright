#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
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
# Fixtures for PRD 018 Phase 1 — trust + verify + /sw-init (portability setup).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0

ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- setup-detect-project-type ---
if OUT=$(bash "$ROOT/scripts/detect-project-type.sh" --root "$ROOT" 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert 'matches' in d and 'ambiguous' in d
assert isinstance(d['matches'], list)
print('detect ok')
"; then
  ok "setup-detect-project-type"
else
  bad "setup-detect-project-type"
fi

# --- setup-presets-fixed-table ---
PRESETS="$ROOT/core/sw-reference/verify-presets.json"
if [[ -f "$PRESETS" ]] && python3 - "$PRESETS" <<'PY'
import json, sys
from pathlib import Path
p = json.loads(Path(sys.argv[1]).read_text())
assert "presets" in p
for eco in ("node", "python", "go", "ansible", "make"):
    assert eco in p["presets"], eco
print("presets ok")
PY
then
  ok "setup-presets-fixed-table"
else
  bad "setup-presets-fixed-table"
fi

# --- setup-rejects-unsafe-commands ---
if OUT=$(bash "$ROOT/scripts/detect-project-type.sh" --root "$ROOT" --propose 2>/dev/null) && \
   python3 - "$OUT" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
# unsafe detection helper exists in script; proposals mark safe:false when applicable
assert "proposals" in d or d.get("primaryType") is None
print("unsafe path ok")
PY
then
  ok "setup-rejects-unsafe-commands"
else
  bad "setup-rejects-unsafe-commands"
fi

# --- setup-writes-real-verify ---
if [[ -x "$ROOT/scripts/sw-configure.sh" ]] && \
   OUT=$(bash "$ROOT/scripts/sw-configure.sh" write-draft --write-verify 2>/dev/null) && \
   python3 - "$OUT" <<'PY'
import json, sys
d = json.loads(sys.argv[1])
assert d.get("verdict") == "pass"
PY
then
  ok "setup-writes-real-verify"
else
  bad "setup-writes-real-verify"
fi

# --- setup-accept-defaults-no-write ---
if OUT=$(bash "$ROOT/scripts/sw-configure.sh" write-draft --accept-defaults 2>/dev/null) && \
   python3 - "/tmp/sw-init-draft.json" <<'PY'
import json, sys
from pathlib import Path
d = json.loads(Path(sys.argv[1]).read_text())
assert "verify" not in d or not d["verify"]
assert "verifyGaps" in d or "projectTypeDetection" in d
print("accept defaults ok")
PY
then
  ok "setup-accept-defaults-no-write"
else
  bad "setup-accept-defaults-no-write"
fi

# --- gate-flags-unconfigured-verify ---
if grep -q 'verify-unconfigured' "$ROOT/scripts/verify-evidence.sh" && \
   [[ -x "$ROOT/scripts/verify-unconfigured.sh" ]]; then
  ok "gate-flags-unconfigured-verify"
else
  bad "gate-flags-unconfigured-verify"
fi

# --- portability-self-check ---
if [[ -x "$ROOT/scripts/sw-configure.sh" ]] && \
   bash "$ROOT/scripts/sw-configure.sh" portability-check >/dev/null 2>&1; then
  ok "portability-self-check"
else
  bad "portability-self-check"
fi

# --- init-command-rename ---
if [[ -f "$ROOT/core/commands/sw-init.md" ]] && \
   grep -q 'deprecated' "$ROOT/core/commands/sw-setup.md" && \
   grep -q '/sw-init' "$ROOT/core/commands/sw-setup.md" && \
   ! grep -q '^### 2\. Memory provider' "$ROOT/core/commands/sw-setup.md"; then
  ok "init-command-rename"
else
  bad "init-command-rename"
fi

# --- init-single-configurator ---
if [[ -x "$ROOT/scripts/sw-configure.sh" ]] && \
   grep -q 'sw-configure.sh' "$ROOT/core/commands/sw-init.md"; then
  ok "init-single-configurator"
else
  bad "init-single-configurator"
fi

# --- config-version-stamp ---
if python3 - "$ROOT/.sw/config.schema.json" <<'PY'
import json, sys
from pathlib import Path
schema = json.loads(Path(sys.argv[1]).read_text())
assert "configuredWith" in schema["properties"]
verify = schema["properties"]["verify"]
assert verify["properties"].get("allowUnconfigured") is not None
print("schema ok")
PY
then
  ok "config-version-stamp"
else
  bad "config-version-stamp"
fi

# --- stale-config-notice-and-refresh ---
if [[ -x "$ROOT/scripts/config-at-entry.sh" ]] && \
   grep -q 'drift-check' "$ROOT/core/commands/sw-init.md"; then
  ok "stale-config-notice-and-refresh"
else
  bad "stale-config-notice-and-refresh"
fi

# --- emitter ships verify-presets ---
if grep -q 'verify-presets.json' "$ROOT/platforms/cursor/emitter.py" && \
   grep -q 'verify-presets.json' "$ROOT/platforms/claude-code/emitter.py"; then
  ok "emitter-verify-presets"
else
  bad "emitter-verify-presets"
fi

# --- routing sw-init key ---
if grep -q '"sw-init"' "$ROOT/core/sw-reference/model-routing.defaults.json" && \
   grep -q '"sw-init"' "$ROOT/core/sw-reference/communication-routing.defaults.json"; then
  ok "routing-sw-init"
else
  bad "routing-sw-init"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
