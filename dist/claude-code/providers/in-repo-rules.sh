#!/usr/bin/env bash
# Executable in-repo rule-fetcher for hooks. Emits JSON to stdout.
set -euo pipefail

ROOT="${PF_WORKSPACE_ROOT:-$(pwd)}"
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAX_RULE_CHARS=2000

CONFIG=""
for p in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
  [ -f "$p" ] && CONFIG="$p" && break
done

provider="in-repo"
store_dir=".cursor/pf-memory"
if [ -n "$CONFIG" ] && jq -e . "$CONFIG" >/dev/null 2>&1; then
  provider="$(jq -r '.memory.provider // "in-repo"' "$CONFIG")"
  store_dir="$(jq -r '.memory.inRepo.storeDir // ".cursor/pf-memory"' "$CONFIG")"
fi

if [ "$provider" != "in-repo" ]; then
  jq -n --arg p "$provider" '{ok:false, error:"unsupported provider for in-repo rules adapter", provider:$p, rules:[]}'
  exit 1
fi

RULES_DIR="$ROOT/$store_dir/rules"
RULES_DIR="$(cd "$ROOT" && realpath -m "$RULES_DIR" 2>/dev/null || echo "$RULES_DIR")"
case "$RULES_DIR" in
  "$ROOT"/*) ;;
  *)
    jq -n '{ok:false, error:"storeDir escapes workspace", rules:[]}'
    exit 1
    ;;
esac
if [ ! -d "$RULES_DIR" ]; then
  jq -n '{ok:true, rules:[]}'
  exit 0
fi

emit_rules() {
  local rules_json="[]"
  for f in "$RULES_DIR"/*.md; do
    [ -f "$f" ] || continue
    id=$(basename "$f" .md)
    category=$(awk 'BEGIN{c=0} /^---$/{c++; next} c==1 && /^category:/{sub(/^category:[[:space:]]*/,""); print; exit}' "$f")
    if [ "$category" != "rule" ]; then
      continue
    fi
    body=$(awk 'BEGIN{c=0} /^---$/{c++; next} c>=2{print}' "$f")
    summary=$(printf '%s' "$body" | head -c "$MAX_RULE_CHARS")
    len=${#body}
    if [ "$len" -gt "$MAX_RULE_CHARS" ]; then
      continue
    fi
    # Basic injection hardening: strip control chars
    summary=$(printf '%s' "$summary" | tr -d '\000-\010\013\014\016-\037')
    [ -n "$summary" ] || continue
    rules_json=$(echo "$rules_json" | jq --arg id "$id" --arg summary "$summary" '. + [{id:$id, summary:$summary}]')
  done
  jq -n --argjson rules "$rules_json" '{ok:true, rules:$rules}'
}

emit_rules
