#!/usr/bin/env bash
# Pre-freeze spec-rigor gate: clarify + checklist (PRD) or analyze (tasks).
# Usage:
#   spec-rigor-check.sh --artifact prd --path FILE [--tier full|standard]
#   spec-rigor-check.sh --artifact decision --path FILE [--tier full|standard]
#   spec-rigor-check.sh --artifact tasks --path FILE --prd PRD_PATH
# Exit: 0 pass, 10 warn, 20 fail
# R16 no-regression (PRD 035): frozen immutability, traceability, and spec-rigor gates feed the delivery loop — preserve pre-freeze structural checks and union/traceability completeness.
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
      echo "usage: spec-rigor-check.sh --artifact prd|decision|tasks --path FILE [--tier full|standard] [--prd PRD]"
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

# Pre-freeze structural check (R13) — fail closed before spec-rigor gates.
if ! STRUCT_OUT=$(bash "$ROOT/scripts/doc-format-normalize.sh" --check "$PATH_FILE" 2>&1); then
  echo "$STRUCT_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps({'verdict':'fail','gate':'structural','findings':d.get('findings',[])}))" 2>/dev/null || echo "$STRUCT_OUT"
  exit 20
fi

exec python3 - "$ROOT" "$ARTIFACT" "$PATH_FILE" "$TIER" "$PRD_PATH" <<'PY'
import json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import doc_format

root, artifact, path_file, tier, prd_path = sys.argv[1:6]
text = Path(path_file).read_text()
findings = []

AMBIGUITY = re.compile(r"\b(TBD|TODO|FIXME|\?\?\?|to be determined)\b", re.I)
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
    for rid, body in doc_format.extract_rd_bullets(text):
        if not rid.startswith("R"):
            continue
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

elif artifact == "decision":
    dids = []
    for did, body in doc_format.extract_rd_bullets(text):
        if not did.startswith("D"):
            continue
        dids.append(did)
        if AMBIGUITY.search(body):
            add("checklist", "error", f"ambiguity marker in {did}", did)
        if len(body) < 12:
            add("checklist", "warn", f"requirement text very short in {did}", did)

    if not dids:
        add("checklist", "error", "no D-IDs found in Decision bullets")

    dupes = {d for d in dids if dids.count(d) > 1}
    for d in sorted(dupes):
        add("checklist", "error", f"duplicate D-ID {d}", d)

    for sec in ("Context", "Decision", "Rationale", "Alternatives", "Consequences"):
        if not re.search(rf"^##\s+{re.escape(sec)}\s*$", text, re.M | re.I):
            add("checklist", "error", f"missing section: {sec}")

    worst = "pass"
    if any(f["severity"] == "error" for f in findings):
        worst = "fail"
    elif any(f["severity"] == "warn" for f in findings):
        worst = "warn"

    out = {"verdict": worst, "artifact": "decision", "tier": tier, "findings": findings}
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

  phase_ids = sorted({p["id"] for p in doc_format.extract_phases(text)}, key=int)
  dep_rows_list = doc_format.extract_phase_dependencies(text)
  if dep_rows_list is None:
    add("analyze", "error", "missing ## Phase Dependencies section")
  else:
    dep_rows: dict[str, str] = {}
    for row in dep_rows_list:
      phase, depends = row["phase"], row["depends_on"]
      if phase in dep_rows:
        add("analyze", "error", f"duplicate Phase Dependencies row for phase {phase}")
      dep_rows[phase] = depends

    phase_set = set(phase_ids)
    for pid in phase_ids:
      if pid not in dep_rows:
        add("analyze", "error", f"Phase Dependencies missing row for phase {pid}")

    for phase, depends in dep_rows.items():
      if phase not in phase_set:
        add("analyze", "error", f"Phase Dependencies row for unknown phase {phase}")
      raw = depends.strip().lower()
      if raw in ("none", "—", "-", ""):
        continue
      for dep in re.findall(r"\d+", raw):
        if dep not in phase_set:
          add("analyze", "error", f"phase {phase} depends on unknown phase {dep}")
        if dep == phase:
          add("analyze", "error", f"phase {phase} cannot depend on itself")

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
