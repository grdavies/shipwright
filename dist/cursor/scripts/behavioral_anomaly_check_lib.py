"""Trust-anchored behavioral-anomaly guardrails (PRD 041 R28)."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import evidence_read as er
import failure_signature_record_lib as fsr

TDD_SKIP_PREFIXES = ("tdd:", "refactor:", "prd-a:")
FILE_LINE_RE = re.compile(r"^\*\*File:\*\*\s+`([^`]+)`", re.M)
RELEVANT_FILES_RE = re.compile(r"^## Relevant Files\s*$", re.M)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_declared_scope(tasks_path: Path) -> set[str]:
    if not tasks_path.is_file():
        return set()
    text = tasks_path.read_text(encoding="utf-8")
    scope: set[str] = set()
    for m in FILE_LINE_RE.finditer(text):
        path = m.group(1).strip()
        if path:
            scope.add(path)
    if RELEVANT_FILES_RE.search(text):
        section = text.split("## Relevant Files", 1)[-1].split("## ", 1)[0]
        for line in section.splitlines():
            for path in re.findall(r"`([^`]+)`", line):
                path = path.strip()
                if path and not path.startswith("{"):
                    scope.add(path)
    return scope


def git_name_status(root: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-status"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split("	", 1)
            if len(parts) != 2:
                continue
            status, path = parts[0].strip(), parts[1].strip()
            rows.append((status, path))
    status_proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if status_proc.returncode == 0:
        seen = {path for _, path in rows}
        for line in status_proc.stdout.splitlines():
            if len(line) < 4:
                continue
            code, path = line[:2].strip(), line[3:].strip()
            if not path or path in seen:
                continue
            if code in ("??", "A", "D", "AD", "AM"):
                rows.append((code if code != "??" else "A", path))
                seen.add(path)
    return rows

def git_dirty(root: Path) -> bool:
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    return bool(proc.stdout.strip())


def path_in_scope(path: str, scope: set[str]) -> bool:
    if not scope:
        return True
    norm = path.replace("\\", "/")
    for declared in scope:
        dec = declared.replace("\\", "/")
        if norm == dec or norm.startswith(dec.rstrip("/") + "/"):
            return True
        if dec.endswith("*") and norm.startswith(dec[:-1]):
            return True
    return False


def detect_unauthorized_changes(
    diff_rows: list[tuple[str, str]],
    baseline_paths: set[str],
    scope: set[str],
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    for status, path in diff_rows:
        code = status[:1]
        if code not in ("A", "D", "??"):
            continue
        if path_in_scope(path, scope):
            continue
        if path in baseline_paths:
            continue
        kind = "unauthorized-create" if code in ("A", "??") else "unauthorized-delete"
        anomalies.append(
            {
                "class": kind,
                "path": path,
                "gitStatus": status,
                "severity": "high",
                "advisory": True,
            }
        )
    return anomalies


def detect_false_success(verify_path: Path, root: Path) -> tuple[list[dict[str, Any]], bool]:
    anomalies: list[dict[str, Any]] = []
    integrity_mismatch = False
    if not verify_path.is_file():
        return anomalies, integrity_mismatch
    try:
        doc = er.safe_json_load(verify_path)
    except (PermissionError, json.JSONDecodeError, OSError):
        integrity_mismatch = True
        anomalies.append(
            {
                "class": "false-success",
                "reason": "verify status unreadable or fails evidence integrity check",
                "severity": "blocking",
                "advisory": False,
            }
        )
        return anomalies, integrity_mismatch
    exit_code = int(doc.get("exitCode", 1))
    status = str(doc.get("status") or "")
    claims_pass = exit_code == 0 and status == "pass"
    if not claims_pass:
        return anomalies, integrity_mismatch
    for cmd in doc.get("commands") or []:
        if not isinstance(cmd, dict):
            continue
        if cmd.get("status") == "fail" or int(cmd.get("exitCode", 0)) != 0:
            anomalies.append(
                {
                    "class": "false-success",
                    "reason": "aggregate pass but sub-command failed",
                    "command": cmd.get("name"),
                    "severity": "high",
                    "advisory": True,
                }
            )
    evidence_hash = doc.get("evidenceHash")
    if isinstance(evidence_hash, str) and evidence_hash:
        recomputed = hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()
        if evidence_hash != recomputed and len(evidence_hash) == 64:
            integrity_mismatch = True
            anomalies.append(
                {
                    "class": "false-success",
                    "reason": "evidence hash mismatch — possible fabricated status",
                    "severity": "blocking",
                    "advisory": False,
                }
            )
    return anomalies, integrity_mismatch


def detect_failed_rollback(root: Path, marker_path: Path | None) -> list[dict[str, Any]]:
    if marker_path and marker_path.is_file():
        if git_dirty(root):
            return [
                {
                    "class": "failed-rollback",
                    "reason": "revert attempted but working tree remains dirty",
                    "severity": "high",
                    "advisory": True,
                }
            ]
    return []


def detect_silent_skips(ship_steps_path: Path) -> list[dict[str, Any]]:
    doc = load_json(ship_steps_path)
    if not doc:
        return []
    anomalies: list[dict[str, Any]] = []
    for step in doc.get("steps") or []:
        if not isinstance(step, dict):
            continue
        status = str(step.get("status") or "")
        if status != "skipped":
            continue
        reason = step.get("skipReason") or step.get("reason")
        if reason:
            reason_s = str(reason).strip().lower()
            if any(reason_s.startswith(p) for p in TDD_SKIP_PREFIXES):
                continue
        anomalies.append(
            {
                "class": "silent-skip",
                "step": step.get("id") or step.get("step"),
                "severity": "high",
                "advisory": True,
            }
        )
    return anomalies


def record_anomalies(root: Path, anomalies: list[dict[str, Any]], *, run_id: str = "") -> None:
    for anom in anomalies:
        cls = str(anom.get("class") or "behavioral-anomaly")
        fsr.maybe_record(
            root,
            "behavioral-anomaly-check",
            check_id=f"behavioral/{cls}",
            exit_code=10 if anom.get("severity") == "blocking" else 1,
            job_id="local",
            message=json.dumps(anom, sort_keys=True),
            run_id=run_id,
        )


def apply_verification_overlay(verdict: dict[str, Any], check_result: dict[str, Any]) -> dict[str, Any]:
    if check_result.get("evidenceIntegrityMismatch"):
        return {
            **verdict,
            "verdict": "inconclusive",
            "reason": "behavioral-anomaly: evidence integrity mismatch",
            "inconclusiveClass": "missing-required",
            "behavioralAnomalies": check_result.get("anomalies") or [],
        }
    if check_result.get("anomalies"):
        verdict = dict(verdict)
        verdict["behavioralAnomalies"] = check_result["anomalies"]
    return verdict


def check(
    root: Path,
    *,
    tasks_path: Path | None = None,
    verify_status_path: Path | None = None,
    ship_steps_path: Path | None = None,
    baseline_path: Path | None = None,
    rollback_marker_path: Path | None = None,
    run_id: str = "",
    record_signatures: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    baseline_doc = load_json(baseline_path) if baseline_path else None
    baseline_paths = set((baseline_doc or {}).get("paths") or [])
    scope = parse_declared_scope(tasks_path) if tasks_path else set()
    diff_rows = git_name_status(root)
    anomalies: list[dict[str, Any]] = []
    anomalies.extend(detect_unauthorized_changes(diff_rows, baseline_paths, scope))
    integrity = False
    if verify_status_path:
        false_items, integrity = detect_false_success(verify_status_path, root)
        anomalies.extend(false_items)
    anomalies.extend(detect_failed_rollback(root, rollback_marker_path))
    if ship_steps_path:
        anomalies.extend(detect_silent_skips(ship_steps_path))
    evidence_integrity_mismatch = integrity
    if record_signatures and anomalies:
        record_anomalies(root, anomalies, run_id=run_id)
    blocking = evidence_integrity_mismatch or any(a.get("severity") == "blocking" for a in anomalies)
    return {
        "verdict": "blocking" if blocking else ("advisory" if anomalies else "clean"),
        "checkedAt": utc_now(),
        "anomalies": anomalies,
        "evidenceIntegrityMismatch": evidence_integrity_mismatch,
        "declaredScopeCount": len(scope),
    }
