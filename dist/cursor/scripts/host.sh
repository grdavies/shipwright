#!/usr/bin/env bash
# Host verb dispatcher — routes to provider adapter scripts (PRD 026).
#
# Usage:
#   host.sh [--root PATH] <verb> [--key value ...]
#
# Emits JSON on stdout; exit 0 on ok/degraded, non-zero on hard failure.
set -euo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$SCRIPT_ROOT"
VERB=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,6p' "$0"
      exit 0
      ;;
    *)
      VERB="$1"
      shift
      break
      ;;
  esac
done

if [[ -z "$VERB" ]]; then
  echo '{"verdict":"fail","reason":"usage","message":"verb required"}' >&2
  exit 2
fi

RESOLVED="$(python3 "$SCRIPT_ROOT/scripts/host_lib.py" --root "$ROOT" resolve)"
PROVIDER="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('provider','none'))" "$RESOLVED")"

if [[ "$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('verdict','fail'))" "$RESOLVED")" != "ok" ]]; then
  python3 -c "import json,sys; print(json.dumps({'verdict':'fail','verb':sys.argv[2],'reason':'unknown_provider','detail':json.loads(sys.argv[1])}))" "$RESOLVED" "$VERB"
  exit 30
fi

ADAPTER_ID="$PROVIDER"
if [[ "$PROVIDER" == "none" ]]; then
  ADAPTER_ID="local"
fi
ADAPTER="$SCRIPT_ROOT/scripts/host_${ADAPTER_ID}.sh"
if [[ ! -x "$ADAPTER" ]]; then
  python3 -c "import json,sys; print(json.dumps({'verdict':'degraded','verb':sys.argv[1],'provider':sys.argv[2],'reason':'capability-missing','retryable':False}))" "$VERB" "$PROVIDER"
  exit 0
fi

exec "$ADAPTER" --root "$ROOT" "$VERB" "$@"
