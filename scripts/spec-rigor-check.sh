#!/usr/bin/env bash
# Pre-freeze spec-rigor gate: clarify + checklist (PRD) or analyze (tasks).
# Usage:
#   spec-rigor-check.sh --artifact prd --path FILE [--tier full|standard]
#   spec-rigor-check.sh --artifact tasks --path FILE --prd PRD_PATH
# Exit: 0 pass, 10 warn, 20 fail
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARTIFACT=""
PATH_FILE=""
TIER="standard"
PRD_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact) ARTIFACT="${2:-}"; shift 2 ;;
    --path) PATH_FILE="${2:-}"; shift 2 ;;
    --tier) TIER="${2:-}"; shift 2 ;;
    --prd) PRD_PATH="${2:-}"; shift 2 ;;
    -h|--help)
      echo "usage: spec-rigor-check.sh --artifact prd|tasks --path FILE [--tier full|standard] [--prd PRD]"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$ARTIFACT" || -z "$PATH_FILE" ]]; then
  echo '{"verdict":"fail","error":"usage: --artifact and --path required"}' >&2
  exit 2
fi

if [[ ! -f "$PATH_FILE" ]]; then
  echo "{\"verdict\":\"fail\",\"error\":\"not found: $PATH_FILE\"}" >&2
  exit 2
fi

exec python3 - "$ROOT" "$ARTIFACT" "$PATH_FILE" "$TIER" "$PRD_PATH" <<'PY'
import json, re, subprocess, sys
from pathlib import Path

root, artifact, path_file, tier, prd_path = sys.argv[1:6]
text = Path(path_file).read_text()
findings = []

AMBIGUITY = re.compile(r"\b(TBD|TODO|FIXME|\?\?\?|to be determined)\b", re.I)
RID_LINE = re.compile(r"^- \*\*(R\d+)\*\*\s*(.*)$", re.M)
RID_INLINE = re.compile(r"\bR\d+\b")

def add(gate, severity, message, rid=None):
    f = {"gate": gate, "severity": severity, "message": message}
    if rid:
        f["rid"] = rid
    findings.append(f)

def section_body(name):
    m = re.search(rf"^##\s+{re.escape(name)}\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.M | re.I)
    return m.group(1) if m else ""

if artifact == "prd":
    rids = []
    for m in RID_LINE.finditer(text):
        rid, body = m.group(1), m.group(2).strip()
        rids.append(rid)
        if AMBIGUITY.search(body):
            add("checklist", "error", f"ambiguity marker in {rid}", rid)
        if len(body) < 12:
            add("checklist", "warn", f"requirement text very short in {rid}", rid)

    if not rids:
        add("checklist", "error", "no R-IDs found in Requirements bullets")

    dupes = {r for r in rids if rids.count(r) > 1}
    for d in sorted(dupes):
        add("checklist", "error", f"duplicate R-ID {d}", d)

    for sec in ("Overview", "Goals", "Non-Goals", "Requirements", "Testing Strategy"):
        if not re.search(rf"^##\s+{re.escape(sec)}\s*$", text, re.M | re.I):
            add("checklist", "error", f"missing section: {sec}")

    oq = section_body("Open Questions")
    if tier == "full":
        if oq.strip():
            for line in oq.splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                if s.lower() in ("none", "(none)", "n/a", "- none"):
                    continue
                if re.match(r"^- \[[ xX]\]", s) or AMBIGUITY.search(s) or s.startswith("- "):
                    add("clarify", "error", f"unresolved open question: {s[:80]}")

    worst = "pass"
    if any(f["severity"] == "error" for f in findings):
        worst = "fail"
    elif any(f["severity"] == "warn" for f in findings):
        worst = "warn"

    out = {"verdict": worst, "artifact": "prd", "tier": tier, "findings": findings}
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if worst == "pass" else 10 if worst == "warn" else 20)

elif artifact == "tasks":
  if not prd_path or not Path(prd_path).is_file():
    add("analyze", "error", "--prd required and must exist for tasks analyze")
    print(json.dumps({"verdict": "fail", "artifact": "tasks", "findings": findings}))
    sys.exit(20)

  union = json.loads(
    subprocess.check_output(["bash", str(Path(root) / "scripts/spec-union.sh"), prd_path], text=True)
  )
  union_ids = [r["id"] for r in union.get("requirements", [])]

  if not re.search(r"^##\s+Traceability\s*$", text, re.M | re.I):
    add("analyze", "error", "missing ## Traceability section")

  task_text = text
  for rid in union_ids:
    if rid not in task_text:
      add("analyze", "error", f"R-ID {rid} from union not referenced in task list", rid)

  worst = "fail" if any(f["severity"] == "error" for f in findings) else "pass"
  out = {"verdict": worst, "artifact": "tasks", "findings": findings, "unionRids": union_ids}
  print(json.dumps(out, ensure_ascii=False))
  sys.exit(0 if worst == "pass" else 20)

else:
  print(json.dumps({"verdict": "fail", "error": f"unknown artifact: {artifact}"}))
  sys.exit(2)
PY
