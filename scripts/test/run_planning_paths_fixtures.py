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
        p for p in (str(root / "scripts"), env.get("PYTHONPATH", "")) if p
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
# Planning path resolution fixtures (PRD 031 phase 4 — R23/R7).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/scripts/planning_paths.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -f "$PY" ]] || { bad "planning_paths.py missing"; exit 1; }

# --- realpath-containment-reject-escape (R23) ---
FIX=$(mktemp -d)
trap 'rm -rf "$FIX" "$CFG_FIX"' EXIT

(
  cd "$FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p safe
  echo ok > safe/file.txt
  OUT=$(python3 "$PY" "$FIX" resolve --path safe/file.txt 2>/dev/null || true)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"
) && ok "realpath-containment-allows-contained" || bad "realpath-containment-allows-contained"

(
  cd "$FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p inside
  echo x > inside/x.txt
  OUT=$(python3 "$PY" "$FIX" resolve --path ../outside 2>/dev/null || true)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail'"
) && ok "realpath-containment-reject-escape" || bad "realpath-containment-reject-escape"

(
  cd "$FIX"
  git init -q
  OUT=$(python3 "$PY" "$FIX" resolve --path 'docs/prds/../../etc/passwd' 2>/dev/null || true)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail'"
) && ok "realpath-containment-reject-dotdot" || bad "realpath-containment-reject-dotdot"

# --- no-hardcoded-prds-literal (R23) ---
if python3 "$PY" "$ROOT" scan-literals 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
  ok "no-hardcoded-prds-literal"
else
  bad "no-hardcoded-prds-literal"
fi

# --- paths-resolve-through-config (R7) ---
CFG_FIX=$(mktemp -d)
(
  cd "$CFG_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo init > README.md
  git add README.md
  git commit -q -m init
  mkdir -p .cursor custom/prds custom/decisions custom/planning
  cat > .cursor/workflow.config.json <<'JSON'
{
  "prdsDir": "custom/prds",
  "tasksDir": "custom/prds",
  "decisionsDir": "custom/decisions",
  "planningDir": "custom/planning"
}
JSON
  OUT=$(python3 "$PY" "$CFG_FIX" living-paths)
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
paths=d.get('paths',[])
assert paths==['custom/prds/INDEX.md','custom/prds/COMPLETION-LOG.md','custom/prds/GAP-BACKLOG.md'], paths
"
  OUT2=$(python3 "$PY" "$CFG_FIX" contention-default)
  echo "$OUT2" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ser=d.get('serialized',[])
assert ser[0]=='custom/prds/INDEX.md' and ser[1]=='custom/decisions/INDEX.md', ser
"
  export ROOT
  python3 - "$CFG_FIX" <<'PY'
import os
import sys
from pathlib import Path

root = Path(sys.argv[1])
ship = Path(os.environ["ROOT"]) / "scripts"
sys.path.insert(0, str(ship))
import wave_living_docs as wld

paths = wld.living_paths(root)
assert paths[0].startswith("custom/prds/"), paths
print("ok")
PY
) && ok "paths-resolve-through-config" || bad "paths-resolve-through-config"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
