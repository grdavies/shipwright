#!/usr/bin/env bash
# Executable Recallium rule-fetcher for hooks. Emits JSON to stdout; never prints credentials.
set -euo pipefail

ROOT="${SW_WORKSPACE_ROOT:-$(pwd)}"
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG=""
for p in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
  [ -f "$p" ] && CONFIG="$p" && break
done

provider="recallium"
project=""
base="http://localhost:8001"
if [ -n "$CONFIG" ]; then
  provider="$(jq -r '.memory.provider // "recallium"' "$CONFIG")"
  project="$(jq -r '.memory.project // ""' "$CONFIG")"
  base="$(jq -r '.memory.connection.restBaseUrl // "http://localhost:8001"' "$CONFIG")"
fi
[ -z "$project" ] && project="$(basename "$ROOT")"

if [ "$provider" != "recallium" ]; then
  jq -n --arg p "$provider" '{ok:false, error:"unsupported provider for executable fetch", provider:$p, rules:[]}'
  exit 1
fi

if ! PYTHONPATH="$PLUGIN_ROOT" python3 -c "from hooks.sw_recallium_url import is_allowed_recallium_base; import sys; sys.exit(0 if is_allowed_recallium_base(sys.argv[1]) else 1)" "$base"; then
  jq -n --arg u "$base" '{ok:false, error:"restBaseUrl must be localhost-only", rules:[]}'
  exit 1
fi

url="${base%/}/api/projects/$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=''))" "$project")/memories?memory_type=rule&limit=25"
if ! body="$(curl -fsS --max-time 3 "$url" 2>/dev/null)"; then
  jq -n '{ok:false, error:"provider unreachable", rules:[]}'
  exit 1
fi

echo "$body" | jq '{
  ok: true,
  rules: [.data[]? | {id: (.id // .memory_id // .summary), summary: (.summary // .content // "")}]
}'
