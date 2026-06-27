#!/usr/bin/env bash
# Golden tests for capability manifest lint (R11, R25, R27).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LINT="$ROOT/scripts/capability-manifest-lint.sh"
FIX="$ROOT/scripts/test/fixtures/capability-lint"
FAIL=0

chmod +x "$LINT"

run_expect() {
  local name="$1" expect_ec="$2"
  shift 2
  set +e
  OUT=$("$@" 2>&1)
  EC=$?
  set -e
  if [ "$EC" -eq "$expect_ec" ]; then
    echo "OK  $name exit=$EC"
  else
    echo "FAIL $name expected exit=$expect_ec got exit=$EC"
    echo "$OUT"
    FAIL=1
  fi
}

# Real repo must pass author-time lint
run_expect real-manifest-lint 0 "$LINT"

# --- precedence-conflict-lint-fails-closed (ambiguous triggers, equal precedence) ---
CONFLICT="$FIX/precedence-conflict"
CONFLICT_CORE="$CONFLICT/core"
CONFLICT_INDEX="$CONFLICT/capability-index.json"
rm -rf "$CONFLICT_CORE"
mkdir -p "$CONFLICT_CORE/skills/conflict-a" "$CONFLICT_CORE/skills/conflict-b" "$CONFLICT_CORE/sw-reference"
cat >"$CONFLICT_CORE/skills/conflict-a/SKILL.md" <<'YAML'
---
name: conflict-a
capability:
  version: 1
  triggers:
    - type: path_glob
      selectionFamily: doc-review
      globs:
        - "docs/**/*.md"
---
YAML
cat >"$CONFLICT_CORE/skills/conflict-b/SKILL.md" <<'YAML'
---
name: conflict-b
capability:
  version: 1
  triggers:
    - type: path_glob
      selectionFamily: doc-review
      globs:
        - "docs/**/*.md"
---
YAML
python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from capability_index import build_index
from pathlib import Path
index = build_index(Path('$CONFLICT_CORE'))
Path('$CONFLICT_INDEX').write_text(json.dumps(index, indent=2) + '\n')
"
run_expect precedence-conflict-lint-fails-closed 1 \
  python3 "$ROOT/scripts/capability_manifest_lint.py" \
  --root "$CONFLICT" --core "$CONFLICT_CORE" --index "$CONFLICT_INDEX"

# --- passing-after: precedence resolution present (override tier wins) ---
RESOLVED="$FIX/precedence-resolved"
RESOLVED_CORE="$RESOLVED/core"
RESOLVED_INDEX="$RESOLVED/capability-index.json"
rm -rf "$RESOLVED_CORE"
mkdir -p "$RESOLVED_CORE/skills/resolved-a" "$RESOLVED_CORE/skills/resolved-b" "$RESOLVED_CORE/sw-reference"
cat >"$RESOLVED_CORE/skills/resolved-a/SKILL.md" <<'YAML'
---
name: resolved-a
capability:
  version: 1
  precedence:
    tier: override
    priority: 0
  triggers:
    - type: path_glob
      selectionFamily: doc-review
      globs:
        - "docs/**/*.md"
---
YAML
cat >"$RESOLVED_CORE/skills/resolved-b/SKILL.md" <<'YAML'
---
name: resolved-b
capability:
  version: 1
  triggers:
    - type: path_glob
      selectionFamily: doc-review
      globs:
        - "docs/**/*.md"
---
YAML
python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from capability_index import build_index
from pathlib import Path
index = build_index(Path('$RESOLVED_CORE'))
Path('$RESOLVED_INDEX').write_text(json.dumps(index, indent=2) + '\n')
"
run_expect precedence-conflict-lint-passing-after 0 \
  python3 "$ROOT/scripts/capability_manifest_lint.py" \
  --root "$RESOLVED" --core "$RESOLVED_CORE" --index "$RESOLVED_INDEX"

# --- capability-kind-spoof-rejected ---
SPOOF="$FIX/kind-spoof"
SPOOF_CORE="$SPOOF/core"
SPOOF_INDEX="$SPOOF/capability-index.json"
rm -rf "$SPOOF_CORE"
mkdir -p "$SPOOF_CORE/providers/review" "$SPOOF_CORE/sw-reference"
cat >"$SPOOF_CORE/providers/review/spoof.md" <<'YAML'
---
capability:
  version: 1
  triggers:
    - type: config_flag
      key: review.provider
      equals: spoof
---
YAML
python3 -c "
import json
from pathlib import Path
index = {
  'version': 1,
  'capabilities': [{
    'id': 'provider.review.spoof',
    'kind': 'skill',
    'sourcePath': 'core/providers/review/spoof.md',
    'executable': False,
    'capability': {
      'version': 1,
      'triggers': [{'type': 'config_flag', 'key': 'review.provider', 'equals': 'spoof'}],
    },
  }],
}
Path('$SPOOF_INDEX').write_text(json.dumps(index, indent=2) + '\n')
"
run_expect capability-kind-spoof-rejected 1 \
  python3 "$ROOT/scripts/capability_manifest_lint.py" \
  --root "$SPOOF" --core "$SPOOF_CORE" --index "$SPOOF_INDEX"

exit "$FAIL"
