#!/usr/bin/env bash
# Docs-only PR to default branch (PRD 026 R30). Never pushes directly to trunk.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

topic=""
dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --topic) topic="${2:-}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help)
      echo "usage: docs_pr.sh --topic <topic> [--dry-run]" >&2
      exit 2
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$topic" ]] || { echo "usage: docs_pr.sh --topic <topic>" >&2; exit 2; }

branch="$(python3 "$ROOT/scripts/worktree_lib.py" docs-branch "$topic")"
default="$(python3 - <<'PY' "$ROOT"
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
for rel in ('.cursor/workflow.config.json', 'workflow.config.json'):
    p = root / rel
    if p.is_file():
        try:
            b = json.loads(p.read_text()).get('defaultBaseBranch')
            if b:
                print(b); raise SystemExit(0)
        except json.JSONDecodeError:
            pass
print('main')
PY
)"

if [[ "$branch" == "$default" ]]; then
  echo '{"verdict":"fail","error":"refused: cannot PR docs branch that equals trunk"}' >&2
  exit 20
fi

if [[ "$dry_run" -eq 1 ]]; then
  printf '{"verdict":"pass","action":"docs-pr","dry_run":true,"head":"%s","base":"%s"}\n' "$branch" "$default"
  exit 0
fi

if ! git -C "$ROOT" show-ref --verify --quiet "refs/heads/$branch"; then
  echo "{\"verdict\":\"fail\",\"error\":\"docs branch not found: $branch\"}" >&2
  exit 1
fi

summary="Documentation: ${topic}"
test_plan="- [ ] Review doc-only diff
- [ ] feat-test-plan-doc-fixtures green"
body="$(python3 "$ROOT/scripts/git_template_lib.py" render pr-body --context-json "$(SUMMARY="$summary" TOPIC="$topic" TEST_PLAN="$test_plan" python3 -c 'import json,os; print(json.dumps({"summary":os.environ["SUMMARY"],"test_plan":os.environ["TEST_PLAN"],"prd_slug":os.environ["TOPIC"]}))')")"

if ! python3 "$ROOT/scripts/git_template_lib.py" validate pr-body --body "$body" >/dev/null 2>&1; then
  echo '{"verdict":"fail","error":"rendered PR body failed template validation"}' >&2
  exit 3
fi

host_remote="$(python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" remote-name 2>/dev/null || echo origin)"
git -C "$ROOT" push -u "$host_remote" "$branch" 2>/dev/null || git -C "$ROOT" push "$host_remote" "$branch"

if command -v gh >/dev/null 2>&1; then
  existing="$(gh pr list --head "$branch" --base "$default" --json number --jq '.[0].number' 2>/dev/null || true)"
  if [[ -n "$existing" && "$existing" != "null" ]]; then
    gh pr edit "$existing" --body "$body" >/dev/null
    url="$(gh pr view "$existing" --json url --jq .url)"
    printf '{"verdict":"pass","action":"docs-pr","pr":"%s","url":"%s","head":"%s","base":"%s"}\n' "$existing" "$url" "$branch" "$default"
  else
    url="$(gh pr create --head "$branch" --base "$default" --title "docs: ${topic}" --body "$body" 2>/dev/null)"
    pr="$(gh pr view "$url" --json number --jq .number 2>/dev/null || echo "")"
    printf '{"verdict":"pass","action":"docs-pr","pr":"%s","url":"%s","head":"%s","base":"%s"}\n' "$pr" "$url" "$branch" "$default"
  fi
else
  printf '{"verdict":"degraded","action":"docs-pr","reason":"no-pr-cli","head":"%s","base":"%s","note":"branch pushed; open PR manually"}\n' "$branch" "$default"
fi
