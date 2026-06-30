#!/usr/bin/env bash
# Untrusted-output validation before auto-applying local review fixes.
#
# Usage: code-review-apply-check.py --finding JSON --repo-root PATH \
#   [--max-fix-chars N] [--max-fix-lines N] [--max-fix-hunks N] \
#   [--validated] [--apply-policy auto|surface|off] [--phase-mode] \
#   [--diff-context JSON] [--patch-target PATH]
# Exit: 0 eligible, 20 reject (surface only)
set -euo pipefail

FINDING=""
REPO_ROOT="${PWD}"
MAX_FIX_CHARS=2000
MAX_FIX_LINES=15
MAX_FIX_HUNKS=3
VALIDATED=false
APPLY_POLICY="auto"
PHASE_MODE=false
DIFF_CONTEXT="{}"
PATCH_TARGET=""

usage() {
  echo "Usage: code-review-apply-check.py --finding JSON --repo-root PATH [options]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --finding) FINDING="${2:-}"; shift 2 ;;
    --repo-root) REPO_ROOT="${2:-}"; shift 2 ;;
    --max-fix-chars) MAX_FIX_CHARS="${2:-}"; shift 2 ;;
    --max-fix-lines) MAX_FIX_LINES="${2:-}"; shift 2 ;;
    --max-fix-hunks) MAX_FIX_HUNKS="${2:-}"; shift 2 ;;
    --validated) VALIDATED=true; shift ;;
    --apply-policy) APPLY_POLICY="${2:-}"; shift 2 ;;
    --phase-mode) PHASE_MODE=true; shift ;;
    --diff-context) DIFF_CONTEXT="${2:-}"; shift 2 ;;
    --patch-target) PATCH_TARGET="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$FINDING" ]] || usage

export FINDING REPO_ROOT MAX_FIX_CHARS MAX_FIX_LINES MAX_FIX_HUNKS VALIDATED APPLY_POLICY PHASE_MODE DIFF_CONTEXT PATCH_TARGET

python3 <<'PY'
import fnmatch, json, os, re, sys

finding_raw = os.environ.get("FINDING", "")
repo_root = os.environ.get("REPO_ROOT", ".")
max_chars = int(os.environ.get("MAX_FIX_CHARS", "2000"))
max_lines = int(os.environ.get("MAX_FIX_LINES", "15"))
max_hunks = int(os.environ.get("MAX_FIX_HUNKS", "3"))
validated = os.environ.get("VALIDATED", "false").lower() == "true"
apply_policy = os.environ.get("APPLY_POLICY", "auto").lower()
phase_mode = os.environ.get("PHASE_MODE", "false").lower() == "true"
try:
    diff_ctx = json.loads(os.environ.get("DIFF_CONTEXT", "{}"))
except json.JSONDecodeError:
    diff_ctx = {}
patch_target = os.environ.get("PATCH_TARGET", "")

def reject(reason, **extra):
    out = {"eligible": False, "reason": reason}
    out.update(extra)
    print(json.dumps(out, separators=(",", ":")))
    sys.exit(20)

def accept(**extra):
    out = {"eligible": True}
    out.update(extra)
    print(json.dumps(out, separators=(",", ":")))
    sys.exit(0)

try:
    finding = json.loads(finding_raw)
except json.JSONDecodeError:
    reject("malformed finding JSON")

sev = finding.get("severity", "P3")

if apply_policy not in ("auto",):
    reject("apply policy disables auto-apply", apply_policy=apply_policy)

if phase_mode and sev == "P1":
    reject("phase-mode P1 blocked", severity=sev)

if sev == "P0":
    reject("P0 never auto-applied", severity=sev)

if finding.get("behavior_altering"):
    reject("behavior-altering fix surfaced only", severity=sev)

if sev == "P1":
    if not validated:
        reject("unvalidated P1 never auto-applied", severity=sev)
elif sev not in ("P2", "P3"):
    reject("severity not P1/P2/P3", severity=sev)

fix = finding.get("suggested_fix") or ""
if not fix or fix == "null":
    reject("no concrete suggested_fix")

reqv = finding.get("requires_verification")
if reqv is None:
    reqv = True
if reqv:
    reject("requires_verification is true")

if len(fix) > max_chars:
    reject("fix exceeds character bound", max_chars=max_chars)

fix_lines = [ln for ln in fix.splitlines() if ln.strip()]
if len(fix_lines) > max_lines:
    reject("fix exceeds line bound", max_lines=max_lines)

hunk_count = len(re.findall(r"^@@", fix, re.M))
if hunk_count == 0:
    hunk_count = 1
if hunk_count > max_hunks:
    reject("fix exceeds hunk bound", max_hunks=max_hunks)

file_path = finding.get("file") or ""
if not file_path or file_path == "null":
    reject("missing file path")

if file_path.startswith("/"):
    reject("absolute file path rejected")

if ".." in file_path or file_path.startswith("/"):
    reject("path traversal rejected")

repo_real = os.path.realpath(repo_root)
target = os.path.realpath(os.path.join(repo_real, file_path))

if not (target == repo_real or target.startswith(repo_real + os.sep)):
    reject("file outside repo root", file=file_path)

# Symlink component check
check_path = repo_real
for part in file_path.replace("\\", "/").split("/"):
    if not part:
        continue
    check_path = os.path.join(check_path, part)
    if os.path.islink(check_path):
        reject("symlink path component rejected", file=file_path)

norm = file_path.replace("\\", "/").lower()
if norm == ".git" or norm.startswith(".git/"):
    reject(".git path rejected", file=file_path)

if patch_target and patch_target.replace("\\", "/") != file_path.replace("\\", "/"):
    reject("patch target mismatch", file=file_path, patch_target=patch_target)

# Deny-list path globs (R48/R55)
DENY_GLOBS = [
    "**/auth/**", "**/authz/**", "**/*secret*", "**/*credential*", "**/.env*",
    "**/.github/workflows/**", "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx",
    "**/*.jks", "**/*.keystore", "**/.ssh/**", "**/id_rsa*", "**/id_ed25519*",
    "**/*.asc", "**/*.gpg", "**/.npmrc", "**/.netrc", "**/.pypirc",
    "**/.dockercfg", "**/.docker/config.json", "**/*.tf", "**/*.tfvars",
    "**/dockerfile*", "**/.gitlab-ci.yml", "**/.circleci/**", "**/jenkinsfile",
    "**/azure-pipelines.yml", "**/.drone.yml", "**/bitbucket-pipelines.yml",
]

def path_deny_match(path: str):
    p = path.replace("\\", "/").lower()
    base = os.path.basename(p)
    for g in DENY_GLOBS:
        gl = g.lower()
        if fnmatch.fnmatch(p, gl) or fnmatch.fnmatch(base, gl):
            return g
        # fnmatch ** is weak — explicit fallbacks for pinned globs
        if gl == "**/.github/workflows/**" and (
            p.startswith(".github/workflows/") or "/.github/workflows/" in p
        ):
            return g
        if gl == "**/dockerfile*" and base.startswith("dockerfile"):
            return g
        if gl.endswith("/**"):
            prefix = gl[3:-3] if gl.startswith("**/") else gl[:-3]
            if p.startswith(prefix + "/") or f"/{prefix}/" in p:
                return g
        if "*" in gl:
            core = gl.replace("**/", "").replace("**", "")
            if core in p or core in base:
                return g
    return None

matched_glob = path_deny_match(file_path)
if matched_glob:
    reject("security-sensitive target (path glob)", file=file_path, matched_glob=matched_glob)

CONTENT_MARKERS = [
    "password", "secret", "token", "apikey", "api_key", "private_key",
    "authorization", "set-cookie", "-----begin", "client_secret", "_authtoken",
]
CONTROL_MARKERS = [
    "authorize", "permission", "role", "isadmin", "verifytoken", "verifysignature",
    "verifypassword", "hmac", "jwt", "session", "cookie", "csrf", "cors",
    "bcrypt", "crypto",
]

def content_hits(text: str, markers):
    low = text.lower()
    for m in markers:
        if m in low:
            return m
    return None

text_blobs = [fix]
for line in diff_ctx.get("changed_lines") or []:
    text_blobs.append(line)

for blob in text_blobs:
    hit = content_hits(blob, CONTENT_MARKERS)
    if hit:
        reject("security-sensitive content marker", marker=hit)
    hit = content_hits(blob, CONTROL_MARKERS)
    if hit:
        reject("security-control marker", marker=hit)

if finding.get("security_reviewer_touched"):
    reject("security-reviewer-touched finding")

accept(file=file_path, severity=sev)
PY
