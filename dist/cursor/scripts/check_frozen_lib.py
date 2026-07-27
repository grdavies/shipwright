#!/usr/bin/env python3
"""Freeze receipt helpers (PRD 081 R10/R12)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_artifact_handle import issue_store_separate_project_effective
from wave_transition_receipt import hash_json


def is_driver_invoked(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    if os.environ.get("SW_DOC_DRIVER", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.environ.get("SW_DOC_ORCHESTRATOR", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def parse_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            out[key.strip()] = val.strip()
    return out


def artifact_is_frozen(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    if fm.get("frozen", "").lower() == "true":
        return True
    return bool(re.search(r"^frozen:\s*true\s*$", text[:1200], re.MULTILINE))


def content_revision(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp_frozen(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if artifact_is_frozen(path):
        return content_revision(path)
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            block = text[4:end]
            lines = block.splitlines()
            if not any(line.strip().startswith("frozen:") for line in lines):
                lines.append("frozen: true")
            if not any(line.strip().startswith("frozen_at:") for line in lines):
                lines.append(f"frozen_at: {date.today().isoformat()}")
            text = "---" + "\n".join(lines) + "\n---" + text[end + 4 :]
        else:
            text = f"---\nfrozen: true\nfrozen_at: {date.today().isoformat()}\n---\n" + text
    else:
        text = f"---\nfrozen: true\nfrozen_at: {date.today().isoformat()}\n---\n" + text
    path.write_text(text, encoding="utf-8")
    return content_revision(path)


def build_freeze_receipt(
    *,
    artifact: str,
    owner: str,
    lifecycle_state: str,
    durability_state: str,
    revision: str,
    commit_sha: str | None = None,
    store_revision: str | None = None,
    freeze_record_digest: str | None = None,
    driver_invoked: bool,
    verdict: str,
    **extra: Any,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "verdict": verdict,
        "action": "freeze",
        "artifact": artifact,
        "owner": owner,
        "lifecycleState": lifecycle_state,
        "durabilityState": durability_state,
        "revision": revision,
        "freezeRecordDigest": freeze_record_digest,
        "driverInvoked": driver_invoked,
    }
    if commit_sha:
        receipt["commitSha"] = commit_sha
    if store_revision:
        receipt["storeRevision"] = store_revision
    receipt.update(extra)
    return receipt


def run_freeze_commit(root: Path, artifact: str) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "check-frozen.py"), "freeze-commit", "--artifact", artifact],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    detail = (proc.stdout or proc.stderr or "").strip()
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        payload = {"verdict": "fail", "detail": detail}
    payload.setdefault("exitCode", proc.returncode)
    return payload


def verify_file_store_durability(root: Path, artifact: str, revision: str) -> dict[str, Any]:
    commit_payload = run_freeze_commit(root, artifact)
    verdict = str(commit_payload.get("verdict") or "")
    commit_sha = commit_payload.get("commit")
    if verdict in {"pass", "ok"} and commit_sha:
        return {
            "durabilityState": "verified",
            "commitSha": commit_sha,
            "freezeRecordDigest": revision,
            "detail": commit_payload,
        }
    if verdict == "warn":
        return {
            "durabilityState": "failed",
            "detail": commit_payload,
        }
    return {
        "durabilityState": "failed",
        "detail": commit_payload,
    }


def verify_issue_store_durability(root: Path, unit_id: str, body_path: str, revision: str) -> dict[str, Any]:
    from planning_store import get_backend

    backend = get_backend(root)
    freeze_out = backend.freeze(unit_id, body_path, distill=False)
    store_revision = str(freeze_out.get("hash") or "")
    verify = backend.verify_frozen_hash(unit_id, body_path)
    recorded = str(verify.get("hash") or verify.get("recordedHash") or "")
    freeze_record_digest = recorded or store_revision
    if verify.get("verdict") == "ok" and freeze_record_digest:
        return {
            "durabilityState": "verified",
            "storeRevision": store_revision,
            "freezeRecordDigest": freeze_record_digest,
            "detail": {"freeze": freeze_out, "verify": verify},
        }
    return {
        "durabilityState": "failed",
        "storeRevision": store_revision,
        "freezeRecordDigest": freeze_record_digest or None,
        "detail": {"freeze": freeze_out, "verify": verify},
    }


def finalize_durability_verdict(receipt: dict[str, Any], *, driver_invoked: bool) -> dict[str, Any]:
    durability = str(receipt.get("durabilityState") or "")
    if durability == "verified":
        receipt["verdict"] = "pass"
        return receipt
    if driver_invoked:
        receipt["verdict"] = "fail"
        receipt["error"] = "durability-not-verified"
        return receipt
    receipt["verdict"] = "warn"
    return receipt


def freeze_artifact(
    root: Path,
    artifact: str,
    *,
    owner: str,
    driver_invoked: bool | None = None,
    unit_id: str | None = None,
    freeze_commit_fn=None,
    issue_store_fn=None,
) -> dict[str, Any]:
    """Freeze one artifact exactly once; idempotent when already frozen by same owner."""
    driver = is_driver_invoked(driver_invoked)
    path = (root / artifact).resolve()
    if not path.is_file():
        return build_freeze_receipt(
            artifact=artifact,
            owner=owner,
            lifecycle_state="missing",
            durability_state="failed",
            revision="",
            driver_invoked=driver,
            verdict="fail",
            error="artifact-missing",
        )

    revision = content_revision(path)
    if artifact_is_frozen(path):
        lifecycle = "frozen"
    else:
        revision = stamp_frozen(path)
        lifecycle = "frozen"

    if issue_store_separate_project_effective(root):
        uid = unit_id or path.stem
        durability = issue_store_fn(uid, artifact, revision) if issue_store_fn else verify_issue_store_durability(
            root, uid, artifact, revision
        )
        receipt = build_freeze_receipt(
            artifact=artifact,
            owner=owner,
            lifecycle_state=lifecycle,
            durability_state=str(durability.get("durabilityState") or "failed"),
            revision=revision,
            store_revision=durability.get("storeRevision"),
            freeze_record_digest=durability.get("freezeRecordDigest"),
            driver_invoked=driver,
            verdict="pass",
            detail=durability.get("detail"),
        )
        return finalize_durability_verdict(receipt, driver_invoked=driver)

    durability = (
        freeze_commit_fn(root, artifact, revision)
        if freeze_commit_fn
        else verify_file_store_durability(root, artifact, revision)
    )
    receipt = build_freeze_receipt(
        artifact=artifact,
        owner=owner,
        lifecycle_state=lifecycle,
        durability_state=str(durability.get("durabilityState") or "failed"),
        revision=revision,
        commit_sha=durability.get("commitSha"),
        freeze_record_digest=durability.get("freezeRecordDigest") or revision,
        driver_invoked=driver,
        verdict="pass",
        detail=durability.get("detail"),
    )
    return finalize_durability_verdict(receipt, driver_invoked=driver)


def receipt_digest(receipt: dict[str, Any]) -> str:
    return hash_json(
        {
            "artifact": receipt.get("artifact"),
            "owner": receipt.get("owner"),
            "revision": receipt.get("revision"),
            "durabilityState": receipt.get("durabilityState"),
            "commitSha": receipt.get("commitSha"),
            "storeRevision": receipt.get("storeRevision"),
            "freezeRecordDigest": receipt.get("freezeRecordDigest"),
        }
    )
