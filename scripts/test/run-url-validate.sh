#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHONPATH="$ROOT" python3 <<'PY'
from hooks.sw_recallium_url import is_allowed_recallium_base

assert is_allowed_recallium_base("http://localhost:8001")
assert is_allowed_recallium_base("http://127.0.0.1:8001")
assert not is_allowed_recallium_base("http://169.254.169.254/")
assert not is_allowed_recallium_base("file:///etc/passwd")
print("OK  recallium URL validation")
PY
