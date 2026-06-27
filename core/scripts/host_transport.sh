#!/usr/bin/env bash
# Shared host HTTP transport with rate-limit retry wrapper (PRD 026 R35–R42).
#
# Usage:
#   host_transport.sh --provider NAME --method METHOD --url URL \
#     [--root PATH] [--token-env VAR] [--header-file PATH] [--body-file PATH]
#
# Token is read from the named env var and passed to curl via a header file — never argv.
# Emits JSON transport outcome on stdout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROVIDER=""
METHOD="GET"
URL=""
TOKEN_ENV=""
HEADER_FILE=""
BODY_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --provider) PROVIDER="$2"; shift 2 ;;
    --method) METHOD="$2"; shift 2 ;;
    --url) URL="$2"; shift 2 ;;
    --token-env) TOKEN_ENV="$2"; shift 2 ;;
    --header-file) HEADER_FILE="$2"; shift 2 ;;
    --body-file) BODY_FILE="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,8p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$PROVIDER" || -z "$URL" ]]; then
  echo '{"verdict":"fail","reason":"usage","message":"--provider and --url required"}' >&2
  exit 2
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

HDR_FILE="$TMP_DIR/headers.txt"
BODY_OUT="$TMP_DIR/body.txt"
META_OUT="$TMP_DIR/meta.json"
CURL_HDR="$TMP_DIR/curl-headers.txt"
LOCK_FILE="$TMP_DIR/serial.lock"

if [[ -n "$TOKEN_ENV" ]]; then
  if [[ -z "${!TOKEN_ENV:-}" ]]; then
    python3 -c 'import json; print(json.dumps({"verdict":"degraded","reason":"missing-token","retryable":false}))'
    exit 0
  fi
  printf 'Authorization: Bearer %s\n' "${!TOKEN_ENV}" > "$CURL_HDR"
  chmod 600 "$CURL_HDR"
elif [[ -n "$HEADER_FILE" && -f "$HEADER_FILE" ]]; then
  cp "$HEADER_FILE" "$CURL_HDR"
  chmod 600 "$CURL_HDR"
fi

python3 - "$ROOT" "$PROVIDER" "$METHOD" "$URL" "$HDR_FILE" "$BODY_OUT" "$META_OUT" "$CURL_HDR" "$BODY_FILE" "$LOCK_FILE" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from host_lib import host_section, load_workflow_config, resolve_rate_limit
from host_ratelimit import SerialGate, RequestResult, execute_with_retry

root = Path(sys.argv[1])
provider = sys.argv[2]
method = sys.argv[3].upper()
url = sys.argv[4]
hdr_file = Path(sys.argv[5])
body_out = Path(sys.argv[6])
meta_out = Path(sys.argv[7])
curl_hdr = Path(sys.argv[8]) if sys.argv[8] else None
body_file = Path(sys.argv[9]) if sys.argv[9] else None
lock_file = Path(sys.argv[10])

cfg = resolve_rate_limit(host_section(load_workflow_config(root)))

def request_fn():
    cmd = [
        "curl", "-sS", "-X", method,
        "-D", str(hdr_file),
        "-o", str(body_out),
        "-w", "%{http_code}",
    ]
    if curl_hdr and curl_hdr.is_file():
        cmd.extend(["-H", f"@{curl_hdr}"])
    if body_file and body_file.is_file():
        cmd.extend(["--data-binary", f"@{body_file}"])
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    status = int(proc.stdout.strip() or "0")
    headers = {}
    if hdr_file.is_file():
        for line in hdr_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" not in line or line.startswith("HTTP/"):
                continue
            key, val = line.split(":", 1)
            headers[key.strip()] = val.strip()
    return RequestResult(status_code=status, headers=headers, body=body_out.read_text(encoding="utf-8", errors="replace") if body_out.is_file() else "")

outcome = execute_with_retry(
    provider=provider,
    config=cfg,
    method=method,
    request_fn=request_fn,
    serial_gate=SerialGate(lock_file),
)
payload = outcome.to_json()
if outcome.result is not None:
    payload["bodyBytes"] = len(outcome.result.body or "")
meta_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2))
sys.exit(0 if outcome.verdict == "ok" else 37 if outcome.verdict == "rate-limited" else 1)
PY
