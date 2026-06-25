#!/usr/bin/env bash
# Deterministic native panel roster selection from a diff (R7, R33, R47, R51, R61).
#
# Usage: code-review-select.sh --diff PATH|JSON [--diff-json INLINE]
# Exit: 0; JSON stdout with core, specialists, signals
set -euo pipefail

DIFF_INPUT=""
DIFF_INLINE=""

usage() {
  echo "Usage: code-review-select.sh --diff PATH|JSON [--diff-json INLINE]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --diff) DIFF_INPUT="${2:-}"; shift 2 ;;
    --diff-json) DIFF_INLINE="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$DIFF_INPUT" || -n "$DIFF_INLINE" ]] || usage

if [[ -n "$DIFF_INLINE" ]]; then
  DIFF_JSON="$DIFF_INLINE"
elif [[ -f "$DIFF_INPUT" ]]; then
  DIFF_JSON="$(cat "$DIFF_INPUT")"
else
  DIFF_JSON="$DIFF_INPUT"
fi

export DIFF_JSON
python3 <<'PY'
import fnmatch, json, os, re, sys

CORE = [
    "correctness",
    "maintainability",
    "scope-fidelity",
    "testing",
    "security",
]
ADVERSARIAL_THRESHOLD = 50

raw = os.environ.get("DIFF_JSON", "")
try:
    diff = json.loads(raw)
except json.JSONDecodeError:
    print(json.dumps({"error": "malformed diff JSON"}))
    sys.exit(1)

files = diff.get("files") or []
added_all = []
for f in files:
    path = f.get("path", "")
    for line in f.get("added_lines") or []:
        added_all.append((path, line))

def is_executable_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if s in {"{", "}", "(", ")", "[", "]"}:
        return False
    if re.match(r"^[{}\[\]()]+$", s):
        return False
    if re.match(r"^(import\s|from\s+\S+\s+import|#include|using\s|require\(|use\s)", s):
        return False
    if re.match(r"^(//|#(?!!)|/\*|\*|--|<!--)", s):
        return False
    return True

def exec_line_count() -> int:
    return sum(1 for _, line in added_all if is_executable_line(line))

def path_match(path: str, pattern: str) -> bool:
    p = path.replace("\\", "/").lower()
    pat = pattern.lower()
    return fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(os.path.basename(p), pat)

def any_path(patterns):
    return any(path_match(f.get("path", ""), p) for f in files for p in patterns)

def any_added(regex, flags=re.I):
    rx = re.compile(regex, flags)
    return any(rx.search(line) for _, line in added_all)

def any_file(regex, flags=re.I):
    rx = re.compile(regex, flags)
    return any(rx.search(f.get("path", "")) for f in files)

signals = {}
specialists = []

# performance
perf_signals = []
if any_added(r"\b(loop|hot[- ]?path|query|index|perf)\b"):
    perf_signals.append("keyword:performance")
if any_path(["**/*.sql"]):
    perf_signals.append("glob:**/*.sql")
if perf_signals:
    specialists.append("performance")
    signals["performance"] = perf_signals

# api-contract
api_signals = []
api_patterns = [
    r"openapi", r"swagger", r"\.proto$", r"graphql", r"/routes?/", r"handler",
    r"/api/", r"\.openapi\.",
]
for p in api_patterns:
    if any_file(p) or any_added(p):
        api_signals.append(f"match:{p}")
if api_signals:
    specialists.append("api-contract")
    signals["api-contract"] = api_signals

# data-migration
dm_signals = []
dm_globs = ["**/migrations/**", "**/migrate/**", "**/schema.sql", "*backfill*"]
for g in dm_globs:
    if any_path([g]):
        dm_signals.append(f"glob:{g}")
if dm_signals:
    specialists.append("data-migration")
    signals["data-migration"] = dm_signals

# reliability
rel_signals = []
if any_added(r"\b(retry|timeout|concurrency|error.handling|catch|rescue|panic)\b"):
    rel_signals.append("keyword:reliability")
if rel_signals:
    specialists.append("reliability")
    signals["reliability"] = rel_signals

# adversarial
adv_signals = []
exe = exec_line_count()
if exe >= ADVERSARIAL_THRESHOLD:
    adv_signals.append(f"executable_lines:{exe}>={ADVERSARIAL_THRESHOLD}")
if any_added(r"\b(auth|payment|stripe|mutation|external.api|webhook)\b"):
    adv_signals.append("keyword:high-stakes")
if adv_signals:
    specialists.append("adversarial")
    signals["adversarial"] = adv_signals

# ui-ux (R73)
ui_signals = []
ui_globs = [
    "*.tsx", "*.jsx", "*.vue", "*.svelte", "*.css", "*.scss", "*.less",
    "*.styles.ts", "*.css.ts", "*.swift", "*.kt", "*.dart", "*.storyboard", "*.xib",
    "**/components/**", "**/ui/**", "**/styles/**", "**/theme/**",
    "**/res/layout/*.xml",
]
for g in ui_globs:
    if any_path([g]):
        ui_signals.append(f"glob:{g}")
if any_added(r"\b(styled|makeStyles|createGlobalStyle)\b") or any_added(r"css`"):
    ui_signals.append("marker:css-in-js")
if ui_signals:
    specialists.append("ui-ux")
    signals["ui-ux"] = ui_signals

# type-design
td_signals = []
if any_path(["*.d.ts"]):
    td_signals.append("glob:*.d.ts")
if any_added(r"\b(interface|type|class|struct|enum)\b"):
    td_signals.append("marker:type-decl")
if td_signals:
    specialists.append("type-design")
    signals["type-design"] = td_signals

# comment-accuracy
ca_signals = []
if any_path(["*.md", "*.mdx"]):
    ca_signals.append("glob:docs")
if any_added(r"^\s*(//|#|/\*|\*|\"\"\"|''')"):
    ca_signals.append("marker:comment-change")
if ca_signals:
    specialists.append("comment-accuracy")
    signals["comment-accuracy"] = ca_signals

# ai-native (R53)
ai_signals = []
ai_globs = [
    "commands/**", "core/commands/**", "skills/**", "core/skills/**",
    "rules/**", "providers/**",
]
for g in ai_globs:
    if any_path([g]):
        ai_signals.append(f"glob:{g}")
if any_path(["*.md"]) and any_added(r"\b(prompt|agent|subagent|skill)\b"):
    ai_signals.append("glob:prompt-md")
if any_added(r"\b(openai|anthropic|llm|chat\.completions|untrusted)\b"):
    ai_signals.append("marker:untrusted-llm")
if ai_signals:
    specialists.append("ai-native")
    signals["ai-native"] = ai_signals

out = {
    "core": CORE,
    "specialists": specialists,
    "signals": signals,
    "executable_line_count": exe,
    "adversarial_threshold": ADVERSARIAL_THRESHOLD,
    "excluded": ["previous-comments"],
}
print(json.dumps(out, separators=(",", ":")))
PY
