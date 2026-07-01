"""Cross-run failure signature capture via sw_state_write_lib (PRD 041 R22)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sw_state_write_lib as writer

WRITER_NAME = "failure_signature_record_lib"

PATH_RE = re.compile(
    r"(/tmp/[^\s]+|/var/folders/[^\s]+|\.sw-worktrees/[^\s]+)"
)
UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.I,
)
LINE_COLON_RE = re.compile(r":line:\d+")
LINE_WORD_RE = re.compile(r"\bline \d+\b")
ISO_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
EPOCH_RE = re.compile(r"\b\d{10}\b")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_message(message: str) -> str:
    text = message.lower()
    text = PATH_RE.sub("<path>", text)
    text = UUID_RE.sub("<uuid>", text)
    text = LINE_COLON_RE.sub(":line:<n>", text)
    text = LINE_WORD_RE.sub(":line:<n>", text)
    text = ISO_TS_RE.sub("<ts>", text)
    text = EPOCH_RE.sub("<ts>", text)
    return " ".join(text.split())


def signature_key(
    check_id: str,
    exit_code: int,
    job_id: str,
    message_class: str,
) -> dict[str, Any]:
    return {
        "checkId": check_id,
        "exitCode": int(exit_code),
        "jobId": job_id,
        "messageClass": message_class,
    }


def raw_hash(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def empty_store() -> dict[str, Any]:
    return {"version": 1, "records": []}


def load_failure_store(root: Path) -> dict[str, Any]:
    path = writer.resolve_store_path(root, "failure-signatures")
    doc = writer.load_store(path)
    if not doc:
        return empty_store()
    writer.validate_failure_signatures(doc)
    return doc


def upsert_record(
    root: Path,
    *,
    check_id: str,
    exit_code: int,
    job_id: str,
    message: str,
    source: str,
    run_id: str,
) -> dict[str, Any]:
    message_class = normalize_message(message)
    key = signature_key(check_id, exit_code, job_id, message_class)
    now = utc_now()
    doc = load_failure_store(root)
    records: list[dict[str, Any]] = list(doc.get("records") or [])
    by_token = {writer.key_token(r["key"]): r for r in records if isinstance(r.get("key"), dict)}
    existing = by_token.get(writer.key_token(key))
    if existing:
        existing["count"] = int(existing.get("count") or 0) + 1
        runs = list(existing.get("runs") or [])
        if run_id and run_id not in runs:
            runs.append(run_id)
        existing["runs"] = runs
        existing["lastSeen"] = now
        existing["rawHash"] = raw_hash(message)
        result = existing
    else:
        result = {
            "key": key,
            "rawHash": raw_hash(message),
            "count": 1,
            "runs": [run_id] if run_id else [],
            "firstSeen": now,
            "lastSeen": now,
            "source": source,
            "writer": WRITER_NAME,
        }
        records.append(result)
    doc["records"] = sorted(records, key=lambda r: writer.key_token(r["key"]))
    writer.cmd_write(root, store="failure-signatures", data=doc)
    return result


def record_from_surface(
    root: Path,
    source: str,
    *,
    check_id: str,
    exit_code: int,
    job_id: str,
    message: str,
    run_id: str = "",
) -> dict[str, Any]:
    return upsert_record(
        root,
        check_id=check_id,
        exit_code=exit_code,
        job_id=job_id,
        message=message,
        source=source,
        run_id=run_id or "unknown",
    )


def maybe_record(
    root: Path,
    source: str,
    *,
    check_id: str,
    exit_code: int,
    job_id: str,
    message: str,
    run_id: str = "",
) -> None:
    try:
        record_from_surface(
            root,
            source,
            check_id=check_id,
            exit_code=exit_code,
            job_id=job_id,
            message=message,
            run_id=run_id,
        )
    except Exception:
        return


def maybe_record_gate(root: Path, payload: dict[str, Any], *, reason: str = "") -> None:
    verdict = str(payload.get("verdict") or "")
    if verdict != "red":
        return
    failing = payload.get("failingChecks") or payload.get("requiredFailingChecks") or []
    check_id = str(failing[0]) if failing else "check-gate"
    job_id = str(payload.get("branch") or payload.get("head") or "local")[:128]
    message = reason or str(payload.get("reason") or verdict)
    run_id = str(payload.get("pr") or payload.get("head") or "")
    maybe_record(
        root,
        "check-gate",
        check_id=check_id,
        exit_code=20,
        job_id=job_id,
        message=message,
        run_id=run_id,
    )


def maybe_record_verify_blocked(
    root: Path,
    outcome: dict[str, Any],
    *,
    target: str = "",
    run_id: str = "",
) -> None:
    message = str(outcome.get("note") or outcome.get("stderr") or outcome.get("stdout") or "verify failed")
    maybe_record(
        root,
        "wave-verify",
        check_id="verify",
        exit_code=int(outcome.get("exitCode") or 20),
        job_id=target or "local",
        message=message,
        run_id=run_id,
    )


def maybe_record_no_progress(root: Path, state: dict[str, Any]) -> None:
    streak = int(state.get("noProgressStreak") or 0)
    run_id = str(state.get("runId") or state.get("scopedRunId") or "")
    message = f"conductor:no-progress streak={streak}"
    maybe_record(
        root,
        "wave-deliver",
        check_id="conductor:no-progress",
        exit_code=20,
        job_id=str((state.get("target") or {}).get("branch") or "local"),
        message=message,
        run_id=run_id,
    )


def maybe_record_not_verified(root: Path, verdict: dict[str, Any]) -> None:
    if verdict.get("verdict") != "not-verified":
        return
    evidence = verdict.get("evidence") or {}
    gate = evidence.get("gate") or {}
    check_id = "verify-evidence"
    job_id = "local"
    if gate.get("status") == "fail":
        check_id = "gate"
        job_id = str(gate.get("path") or "local")
    message = str(verdict.get("reason") or "not-verified")
    maybe_record(
        root,
        "verify-evidence",
        check_id=check_id,
        exit_code=20,
        job_id=job_id,
        message=message,
        run_id="",
    )


def index_merge(root: Path, worktrees: list[str] | None = None) -> dict[str, Any]:
    return writer.index_merge(root, store="failure-signatures", worktrees=worktrees)
