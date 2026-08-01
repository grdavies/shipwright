#!/usr/bin/env python3
"""Freeze receipt helpers (PRD 081 R10/R12)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Iterator

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_artifact_handle import issue_store_separate_project_effective
from wave_transition_receipt import hash_json

FREEZE_RECORDS_DIR = ".cursor/sw-freeze-records"


def is_driver_invoked(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    if os.environ.get("SW_DOC_DRIVER", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.environ.get("SW_DOC_ORCHESTRATOR", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return False


@contextmanager
def scoped_doc_driver_env() -> Iterator[None]:
    """Temporarily set SW_DOC_DRIVER; restore prior value (including unset) on exit."""
    key = "SW_DOC_DRIVER"
    had_key = key in os.environ
    prior = os.environ.get(key)
    os.environ[key] = "1"
    try:
        yield
    finally:
        if had_key:
            os.environ[key] = prior  # type: ignore[assignment]
        else:
            os.environ.pop(key, None)


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


def freeze_record_path(root: Path, artifact: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "__", artifact.strip("/"))
    return (root / FREEZE_RECORDS_DIR / f"{safe}.json").resolve()


def load_freeze_record(root: Path, artifact: str) -> dict[str, Any] | None:
    path = freeze_record_path(root, artifact)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return doc if isinstance(doc, dict) else None


def save_freeze_record(root: Path, artifact: str, record: dict[str, Any]) -> Path:
    path = freeze_record_path(root, artifact)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def canonical_freeze_record(
    *,
    artifact: str,
    owner: str,
    revision: str,
    commit_sha: str | None = None,
    store_revision: str | None = None,
    frozen_at: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "artifact": artifact,
        "owner": owner,
        "revision": revision,
        "frozenAt": frozen_at or date.today().isoformat(),
    }
    if commit_sha:
        record["commitSha"] = commit_sha
    if store_revision:
        record["storeRevision"] = store_revision
    return record


def freeze_records_match(
    record: dict[str, Any],
    *,
    owner: str,
    revision: str,
    commit_sha: str | None = None,
    store_revision: str | None = None,
) -> tuple[bool, str | None]:
    if str(record.get("owner") or "") != owner:
        return False, "freeze-owner-conflict"
    if str(record.get("revision") or "") != revision:
        return False, "freeze-revision-conflict"
    if commit_sha is not None and str(record.get("commitSha") or "") != commit_sha:
        return False, "freeze-commit-conflict"
    if store_revision is not None and str(record.get("storeRevision") or "") != store_revision:
        return False, "freeze-store-revision-conflict"
    return True, None


def _git_run(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def commit_frozen_artifact(root: Path, artifact: str, revision: str) -> dict[str, Any]:
    """Low-level git commit for a frozen artifact onto <type>/<slug> (no re-entrant freeze_artifact)."""
    from primary_checkout_guard import enforce_guard
    from wave_spec_seed import git_toplevel, load_trunk_base, resolve_target_from_artifact

    top = git_toplevel(root)
    default = load_trunk_base(top)
    branch, slug, _docs_dir = resolve_target_from_artifact(top, artifact)

    if branch == default:
        return {"verdict": "warn", "error": "refused-default-branch", "branch": branch}

    enforce_guard(top, branch)

    artifact_path = (top / artifact).resolve()
    if not artifact_path.is_file():
        return {"verdict": "fail", "error": "artifact-missing", "artifact": artifact}

    existing = verify_commit_contains_revision(top, artifact, revision, branch=branch)
    if existing.get("verdict") == "pass":
        return {
            "verdict": "pass",
            "commit": existing.get("commitSha"),
            "branch": branch,
            "note": "already committed with matching revision",
        }

    current = _git_run(["branch", "--show-current"], top, check=False).stdout.strip()
    prev = current or default
    base_ref = default
    if _git_run(["show-ref", "--verify", f"refs/heads/{branch}"], top, check=False).returncode == 0:
        base_ref = branch

    _git_run(["checkout", "-B", branch, base_ref], top)
    _git_run(["add", "--", artifact], top)
    diff_cached = _git_run(["diff", "--cached", "--quiet"], top, check=False)
    if diff_cached.returncode == 0:
        head = _git_run(["rev-parse", "HEAD"], top).stdout.strip()
        if prev and prev != branch:
            _git_run(["checkout", prev], top, check=False)
        verified = verify_commit_contains_revision(top, artifact, revision, commit_sha=head)
        if verified.get("verdict") != "pass":
            return {
                "verdict": "fail",
                "error": "commit-revision-mismatch",
                "commit": head,
                "detail": verified,
            }
        return {"verdict": "pass", "commit": head, "branch": branch, "note": "docs already match branch HEAD"}

    _git_run(["commit", "-m", f"docs: freeze artifact for {slug}"], top)
    head = _git_run(["rev-parse", "HEAD"], top).stdout.strip()
    if prev and prev != branch:
        _git_run(["checkout", prev], top, check=False)

    verified = verify_commit_contains_revision(top, artifact, revision, commit_sha=head)
    if verified.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "error": "commit-revision-mismatch",
            "commit": head,
            "detail": verified,
        }
    return {"verdict": "pass", "commit": head, "branch": branch}


def verify_commit_contains_revision(
    root: Path,
    artifact: str,
    revision: str,
    *,
    commit_sha: str | None = None,
    branch: str | None = None,
) -> dict[str, Any]:
    """Confirm committed content hash matches the stamped revision."""
    top = root.resolve()
    if commit_sha:
        show = _git_run(["show", f"{commit_sha}:{artifact}"], top, check=False)
        if show.returncode != 0:
            return {"verdict": "fail", "error": "artifact-not-in-commit", "commitSha": commit_sha}
        actual = hashlib.sha256(show.stdout.encode("utf-8")).hexdigest()
        if actual != revision:
            return {
                "verdict": "fail",
                "error": "revision-mismatch",
                "commitSha": commit_sha,
                "expected": revision,
                "actual": actual,
            }
        return {"verdict": "pass", "commitSha": commit_sha, "revision": revision}

    if not branch:
        return {"verdict": "fail", "error": "commit-or-branch-required"}

    log = _git_run(["log", "-1", "--format=%H", branch, "--", artifact], top, check=False)
    if log.returncode != 0 or not log.stdout.strip():
        return {"verdict": "fail", "error": "no-commit-for-artifact", "branch": branch}
    return verify_commit_contains_revision(top, artifact, revision, commit_sha=log.stdout.strip())


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


def verify_file_store_durability(root: Path, artifact: str, revision: str) -> dict[str, Any]:
    commit_payload = commit_frozen_artifact(root, artifact, revision)
    verdict = str(commit_payload.get("verdict") or "")
    commit_sha = commit_payload.get("commit")
    if verdict in {"pass", "ok"} and commit_sha:
        verified = verify_commit_contains_revision(root, artifact, revision, commit_sha=str(commit_sha))
        if verified.get("verdict") == "pass":
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
    already_frozen = artifact_is_frozen(path)
    if already_frozen:
        lifecycle = "frozen"
        existing = load_freeze_record(root, artifact)
        if existing:
            matches, conflict = freeze_records_match(existing, owner=owner, revision=revision)
            if not matches:
                return build_freeze_receipt(
                    artifact=artifact,
                    owner=owner,
                    lifecycle_state=lifecycle,
                    durability_state="failed",
                    revision=revision,
                    commit_sha=existing.get("commitSha"),
                    store_revision=existing.get("storeRevision"),
                    freeze_record_digest=existing.get("revision"),
                    driver_invoked=driver,
                    verdict="fail",
                    error=conflict,
                )
            return build_freeze_receipt(
                artifact=artifact,
                owner=owner,
                lifecycle_state=lifecycle,
                durability_state="verified",
                revision=revision,
                commit_sha=existing.get("commitSha"),
                store_revision=existing.get("storeRevision"),
                freeze_record_digest=str(existing.get("revision") or revision),
                driver_invoked=driver,
                verdict="pass",
                note="idempotent-freeze-record",
            )
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
        finalized = finalize_durability_verdict(receipt, driver_invoked=driver)
        if finalized.get("verdict") == "pass":
            save_freeze_record(
                root,
                artifact,
                canonical_freeze_record(
                    artifact=artifact,
                    owner=owner,
                    revision=revision,
                    store_revision=durability.get("storeRevision"),
                    frozen_at=parse_frontmatter(path.read_text(encoding="utf-8")).get("frozen_at"),
                ),
            )
        return finalized

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
    finalized = finalize_durability_verdict(receipt, driver_invoked=driver)
    if finalized.get("verdict") == "pass":
        save_freeze_record(
            root,
            artifact,
            canonical_freeze_record(
                artifact=artifact,
                owner=owner,
                revision=revision,
                commit_sha=durability.get("commitSha"),
                frozen_at=parse_frontmatter(path.read_text(encoding="utf-8")).get("frozen_at"),
            ),
        )
    return finalized


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
