#!/usr/bin/env bash
# Mechanical docs-only batched PR + CI-gated auto-merge (PRD 035 R10/R13/R14/R24).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/scripts/two_track_lib.py"
HOST="$ROOT/scripts/host_lib.py"

cmd="${1:-}"
shift || true

dry_run=0
embedded_hash=""
pr_number=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run=1; shift ;;
    --hash) embedded_hash="${2:-}"; shift 2 ;;
    --pr) pr_number="${2:-}"; shift 2 ;;
    -h|--help)
      echo "usage: docs-merge.sh {open|merge-if-ready|premerge-check|direct-trunk} [--dry-run] [--hash H] [--pr N]" >&2
      exit 2
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

load_default_branch() {
  python3 -c "
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
" "$ROOT"
}

mechanical_branch() {
  python3 -c "
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
for rel in ('.cursor/workflow.config.json', 'workflow.config.json'):
    p = root / rel
    if p.is_file():
        try:
            cfg = json.loads(p.read_text())
            docs = cfg.get('docs') or {}
            two = docs.get('twoTrack') or {}
            print(two.get('mechanicalBranch') or 'docs/mechanical-maintenance')
            raise SystemExit(0)
        except json.JSONDecodeError:
            pass
print('docs/mechanical-maintenance')
" "$ROOT"
}

current_hash() {
  python3 "$PY" "$ROOT" content-hash | python3 -c "import json,sys; print(json.load(sys.stdin)['hash'])"
}

protection_route() {
  python3 "$HOST" --root "$ROOT" branch-protection-probe | python3 -c "import json,sys; print(json.load(sys.stdin).get('route','pr'))"
}

premerge_check() {
  local diff_file
  diff_file="$(mktemp)"
  trap 'rm -f "$diff_file"' RETURN
  git -C "$ROOT" diff --cached >"$diff_file" 2>/dev/null || true
  if [[ ! -s "$diff_file" ]]; then
    git -C "$ROOT" diff HEAD >"$diff_file" 2>/dev/null || true
  fi
  OUT=$(python3 "$PY" "$ROOT" validate-mechanical-diff --diff-file "$diff_file" 2>/dev/null) || true
  if ! echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' else 1)"; then
    echo "$OUT"
    return 3
  fi
  if ! bash "$ROOT/scripts/secret-scan.sh" stdin <"$diff_file" >/dev/null 2>&1; then
    echo '{"verdict":"fail","error":"secret-scan-deny"}' >&2
    return 4
  fi
  echo '{"verdict":"pass","action":"premerge-check"}'
}

[[ -n "$cmd" ]] || { echo "usage: docs-merge.sh <command>" >&2; exit 2; }

DEFAULT="$(load_default_branch)"
MECH="$(mechanical_branch)"

case "$cmd" in
  premerge-check)
    if [[ "$dry_run" -eq 1 ]]; then
      printf '{"verdict":"pass","action":"premerge-check","dry_run":true}\n'
      exit 0
    fi
    premerge_check
    ;;
  open)
    HASH="$(current_hash)"
    MARKER="<!-- two-track-index-hash: ${HASH} -->"
    if [[ "$dry_run" -eq 1 ]]; then
      printf '{"verdict":"pass","action":"open","dry_run":true,"head":"%s","base":"%s","hash":"%s","route":"%s"}\n' \
        "$MECH" "$DEFAULT" "$HASH" "$(protection_route)"
      exit 0
    fi
    ROUTE="$(protection_route)"
    if [[ "$ROUTE" == "direct" ]]; then
      echo '{"verdict":"pass","action":"open","route":"direct","note":"use direct-trunk subcommand"}' 
      exit 0
    fi
    if ! git -C "$ROOT" show-ref --verify --quiet "refs/heads/$MECH"; then
      git -C "$ROOT" branch "$MECH" "$DEFAULT" 2>/dev/null || git -C "$ROOT" checkout -b "$MECH" "$DEFAULT"
    fi
    summary="chore(docs): mechanical planning maintenance batch"
    test_plan="- [ ] feat-test-plan-two-track-fixtures green"
    body="$(python3 "$ROOT/scripts/git_template_lib.py" render pr-body --context-json "$(python3 -c "import json; print(json.dumps({'summary':'$summary','test_plan':'$test_plan','prd_slug':'mechanical-maintenance'}))")")"
    body="${body}

${MARKER}"
    host_remote="$(python3 "$HOST" --root "$ROOT" remote-name 2>/dev/null || echo origin)"
    git -C "$ROOT" push -u "$host_remote" "$MECH" 2>/dev/null || git -C "$ROOT" push "$host_remote" "$MECH" || true
    if command -v gh >/dev/null 2>&1; then
      existing="$(gh pr list --head "$MECH" --base "$DEFAULT" --json number --jq '.[0].number' 2>/dev/null || true)"
      if [[ -n "$existing" && "$existing" != "null" ]]; then
        gh pr edit "$existing" --body "$body" >/dev/null 2>&1 || true
        pr="$existing"
      else
        url="$(gh pr create --head "$MECH" --base "$DEFAULT" --title "docs: mechanical maintenance batch" --body "$body" 2>/dev/null || true)"
        pr="$(gh pr view "$url" --json number --jq .number 2>/dev/null || echo "")"
      fi
      printf '{"verdict":"pass","action":"open","pr":"%s","head":"%s","base":"%s","hash":"%s","route":"pr"}\n' "$pr" "$MECH" "$DEFAULT" "$HASH"
    else
      printf '{"verdict":"degraded","action":"open","reason":"no-gh","head":"%s","base":"%s","hash":"%s"}\n' "$MECH" "$DEFAULT" "$HASH"
    fi
    ;;
  merge-if-ready)
    HASH_AT_OPEN="${embedded_hash:-}"
    [[ -n "$HASH_AT_OPEN" ]] || HASH_AT_OPEN="$(current_hash)"
    LIVE_HASH="$(current_hash)"
    if [[ "$LIVE_HASH" != "$HASH_AT_OPEN" ]]; then
      echo "{\"verdict\":\"fail\",\"action\":\"merge-if-ready\",\"error\":\"content-hash-advanced\",\"openHash\":\"$HASH_AT_OPEN\",\"liveHash\":\"$LIVE_HASH\"}" >&2
      exit 14
    fi
    if [[ "$dry_run" -eq 1 ]]; then
      printf '{"verdict":"pass","action":"merge-if-ready","dry_run":true,"hash":"%s"}\n' "$LIVE_HASH"
      exit 0
    fi
    premerge_check >/dev/null || exit $?
    PR="${pr_number:-}"
    if [[ -z "$PR" ]] && command -v gh >/dev/null 2>&1; then
      PR="$(gh pr list --head "$MECH" --base "$DEFAULT" --json number --jq '.[0].number' 2>/dev/null || true)"
    fi
    GATE_EC=0
    if OUT=$(bash "$ROOT/scripts/check-gate.sh" "${PR:-}" 2>/dev/null); then GATE_EC=0; else GATE_EC=$?; fi
    VERDICT=$(echo "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('verdict','blocked'))" 2>/dev/null || echo blocked)
    if [[ "$VERDICT" != "green" ]]; then
      echo "{\"verdict\":\"blocked\",\"action\":\"merge-if-ready\",\"gate\":$OUT}" >&2
      exit 5
    fi
    if [[ -n "$PR" ]] && command -v gh >/dev/null 2>&1; then
      gh pr merge "$PR" --merge --delete-branch=false >/dev/null 2>&1 || true
    fi
    printf '{"verdict":"pass","action":"merge-if-ready","pr":"%s","hash":"%s"}\n' "${PR:-}" "$LIVE_HASH"
    ;;
  direct-trunk)
    PROBE=$(python3 "$HOST" --root "$ROOT" branch-protection-probe)
    ROUTE=$(echo "$PROBE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('route','pr'))")
    ALLOW=$(echo "$PROBE" | python3 -c "import json,sys; print('yes' if json.load(sys.stdin).get('allowDirectTrunk') else 'no')")
    if [[ "$ROUTE" != "direct" || "$ALLOW" != "yes" ]]; then
      echo "{\"verdict\":\"fail\",\"action\":\"direct-trunk\",\"error\":\"direct-trunk-refused\",\"probe\":$PROBE}" >&2
      exit 13
    fi
    if [[ "$dry_run" -eq 1 ]]; then
      printf '{"verdict":"pass","action":"direct-trunk","dry_run":true}\n'
      exit 0
    fi
    premerge_check >/dev/null || exit $?
    host_remote="$(python3 "$HOST" --root "$ROOT" remote-name 2>/dev/null || echo origin)"
    git -C "$ROOT" push "$host_remote" "$DEFAULT"
    printf '{"verdict":"pass","action":"direct-trunk","branch":"%s"}\n' "$DEFAULT"
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
