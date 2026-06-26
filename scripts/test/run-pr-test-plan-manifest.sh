#!/usr/bin/env bash
# Run the standard FEAT PR test-plan fixture set from the single-sourced manifest (PRD 016 R1–R3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MANIFEST="${PR_TEST_PLAN_MANIFEST:-$ROOT/core/sw-reference/pr-test-plan.manifest.json}"

if [[ ! -f "$MANIFEST" ]]; then
  echo "FAIL pr-test-plan-manifest: missing manifest at $MANIFEST" >&2
  exit 1
fi

python3 - "$MANIFEST" "$ROOT" <<'PY'
import json, subprocess, sys

manifest_path, root = sys.argv[1], sys.argv[2]
with open(manifest_path, encoding="utf-8") as f:
    data = json.load(f)

fixtures = data.get("fixtures") or []
if not fixtures:
    print("FAIL pr-test-plan-manifest: empty fixtures list", file=sys.stderr)
    sys.exit(1)

valid = {"required", "advisory"}
for entry in fixtures:
    for key in ("id", "script", "classification", "ciJobName"):
        if key not in entry or not str(entry[key]).strip():
            print(f"FAIL pr-test-plan-manifest: fixture missing {key!r}: {entry!r}", file=sys.stderr)
            sys.exit(1)
    if entry["classification"] not in valid:
        print(
            f"FAIL pr-test-plan-manifest: invalid classification {entry['classification']!r} "
            f"for {entry['id']}",
            file=sys.stderr,
        )
        sys.exit(1)

print(f"OK  pr-test-plan-manifest: {len(fixtures)} fixtures loaded from {manifest_path}")
PY

while IFS= read -r line; do
  id="${line%%|*}"
  script="${line#*|}"
  script="${script%%|*}"
  args="${line#*${script}|}"
  echo "==> pr-test-plan/$id: bash $script $args"
  # shellcheck disable=SC2086
  bash "$ROOT/$script" $args
done < <(
  python3 - "$MANIFEST" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    for entry in json.load(f).get("fixtures") or []:
        args = " ".join(entry.get("args") or [])
        print(f"{entry['id']}|{entry['script']}|{args}")
PY
)

echo "OK  pr-test-plan-manifest: all fixtures passed"
