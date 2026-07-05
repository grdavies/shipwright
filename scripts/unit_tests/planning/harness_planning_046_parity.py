#!/usr/bin/env python3
"""PRD 046 R92 — semantic parity between file-store and issue-derived INDEX."""
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
    completed = subprocess.run(["bash", "-c", src], cwd=str(root), env=env, shell=False)
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
PY="$ROOT/scripts/planning_index_gen.py"
FIX_SRC="$ROOT/scripts/test/fixtures/planning-index"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p docs/planning .cursor
  cp -R "$FIX_SRC/units/"* docs/planning/
  cat > .cursor/workflow.config.json <<'CFG'
{"version":1,"planning":{"store":{"backend":"issue-store","issuesProvider":"github-issues","projectKey":"parity046"}},"host":{"provider":"github"}}
CFG
  export SW_ISSUES_FIXTURE=1 SW_DISCOVER_SOURCE=file
  python3 "$PY" "$TMP" generate >/dev/null
  FILE_JSON=$(python3 "$PY" "$TMP" parse)
  python3 - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import get_fixture_store
from planning_canonical import compose_issue_body, project_label, type_label
from planning_discover import discover_units_file
root = Path("$TMP")
store = get_fixture_store(root)
store.clear()
cfg_project = "parity046"
for unit in discover_units_file(root):
    body_path = root / unit.body_path
    content = body_path.read_text(encoding="utf-8")
    artifact_type = unit.type
    body = compose_issue_body(cfg_project, artifact_type, unit.id, content)
    labels = sorted({project_label(cfg_project), type_label(artifact_type), "sw:visibility:public"})
    if artifact_type == "gap":
        labels.append("sw:gap-open")
    store.create(title=f"[sw] {artifact_type}:{unit.id}", body=body, labels=labels,
                 project_key=cfg_project, artifact_type=artifact_type, unit_id=unit.id)
PY
  export SW_DISCOVER_SOURCE=issue
  python3 "$PY" "$TMP" generate >/dev/null
  ISSUE_JSON=$(python3 "$PY" "$TMP" parse)
  FILE_JSON="$FILE_JSON" ISSUE_JSON="$ISSUE_JSON" python3 -c "
import json, os
file_d = json.loads(os.environ['FILE_JSON'])
issue_d = json.loads(os.environ['ISSUE_JSON'])
f = file_d['regions']['structural']
i = issue_d['regions']['structural']
for uid in ('gap-045-parser-parity', 'prd-031-planning-unit-model'):
    assert uid in f and uid in i, uid
assert 'Parser parity gap' in f and 'Parser parity gap' in i
"
) && ok "issue-derived-index-semantic-parity" || bad "issue-derived-index-semantic-parity"

(
  cd "$TMP"
  echo ".cursor/hooks/state/" >> .gitignore
  git add .gitignore
  git commit -q -m "gitignore generation state" --allow-empty 2>/dev/null || true
  python3 -c "from pathlib import Path; import sys; sys.path.insert(0,'$ROOT/scripts'); import planning_index_gen as pig; r=Path('$TMP'); g1=pig.bump_generation(r); g2=pig.bump_generation(r); assert g2>g1; assert pig.validate_generation(r,g1)"
) && ok "generation-token-monotonic" || bad "generation-token-monotonic"

(
  cd "$TMP"
  python3 "$ROOT/scripts/planning_cutover.py" "$TMP" doctor >/dev/null
) && ok "cutover-dual-source-doctor-clean" || bad "cutover-dual-source-doctor-clean"

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
