"""Cross-host HandoffBundle continuation fields and atomic export (PRD 349 R31–R33)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from .validate_bundle import digest_payload, validate_bundle  # noqa: F401 — digest_payload used below

TRANSITION_SCHEMA_VERSION = "cross-host-handoff@v1"
_CREDENTIAL_KEY_RE = re.compile(
    r"(password|secret|token|credential|api[_-]?key|authorization|private[_-]?key)",
    re.IGNORECASE,
)


class BundleBuildError(ValueError):
    """Raised when a continuation bundle cannot be constructed safely."""


def _reject_credential_material(value: Any, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_s = str(key)
            if _CREDENTIAL_KEY_RE.search(key_s):
                raise BundleBuildError(
                    f"credential material forbidden in continuation bundle at {path}.{key_s} (SC2)"
                )
            _reject_credential_material(child, path=f"{path}.{key_s}")
        return
    if isinstance(value, list):
        for idx, child in enumerate(value):
            _reject_credential_material(child, path=f"{path}[{idx}]")
        return
    if isinstance(value, str) and value.lower().startswith(
        ("ghp_", "gho_", "github_pat_", "sk-", "xoxb-", "xoxp-")
    ):
        raise BundleBuildError(f"credential-like value forbidden at {path} (SC2)")


def build_continuation_payload(
    *,
    task_baseline: Mapping[str, str],
    prd_baseline: Mapping[str, str],
    repo: Mapping[str, str],
    current_workflow_node_id: str,
    completed_task_rows: Sequence[Mapping[str, Any]],
    remaining_task_rows: Sequence[Mapping[str, Any]],
    unresolved_decisions: Sequence[Mapping[str, Any]],
    evidence_references: Sequence[Mapping[str, str]],
    model_attempt_lineage: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    """Assemble the R32 continuation payload (no credentials)."""
    payload: dict[str, Any] = {
        "taskBaseline": {
            "unitId": str(task_baseline["unitId"]),
            "canonicalVersion": str(task_baseline["canonicalVersion"]),
        },
        "prdBaseline": {
            "frozenCanonicalVersion": str(prd_baseline["frozenCanonicalVersion"]),
        },
        "repo": {
            "worktree": str(repo["worktree"]),
            "head": str(repo["head"]),
        },
        "currentWorkflowNodeId": str(current_workflow_node_id),
        "completedTaskRows": [dict(row) for row in completed_task_rows],
        "remainingTaskRows": [dict(row) for row in remaining_task_rows],
        "unresolvedDecisions": [dict(row) for row in unresolved_decisions],
        "evidenceReferences": [dict(row) for row in evidence_references],
        "modelAttemptLineage": [dict(row) for row in model_attempt_lineage],
    }
    if repo.get("remoteUrl"):
        payload["repo"]["remoteUrl"] = str(repo["remoteUrl"])
    _reject_credential_material(payload)
    return payload


def attach_cross_host_transition(
    bundle: MutableMapping[str, Any],
    *,
    source_host: str,
    destination_host: str,
    continuation_payload: Mapping[str, Any],
    pending_captures: Sequence[Mapping[str, Any]] | None = None,
    source_repo_id: str | None = None,
    source_head: str | None = None,
    transition_id: str | None = None,
    transition_schema_version: str = TRANSITION_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Add optional cross-host fields; same-host bundles may omit this entirely."""
    updated = deepcopy(dict(bundle))
    tid = transition_id or str(uuid.uuid4())
    payload = dict(continuation_payload)
    captures = [dict(item) for item in (pending_captures or ())]
    _reject_credential_material(payload)
    _reject_credential_material(captures)

    updated["source_host"] = str(source_host)
    updated["destination_host"] = str(destination_host)
    updated["transition_id"] = tid
    updated["transition_schema_version"] = str(transition_schema_version)
    updated["continuation_payload"] = payload
    updated["pending_captures"] = captures
    if source_repo_id:
        updated["source_repo_id"] = str(source_repo_id)
    head = source_head or payload.get("repo", {}).get("head")
    if head:
        updated["source_head"] = str(head)
    updated.pop("destination_ack", None)
    updated["bundleDigest"] = digest_payload(updated)
    return updated


def canonical_remote_url(url: str) -> str:
    """Normalize a git remote URL for stable identity hashing (R51)."""
    value = (url or "").strip()
    if value.endswith(".git"):
        value = value[:-4]
    if value.startswith("git@"):
        # git@host:owner/repo -> https://host/owner/repo
        host_path = value[4:]
        if ":" in host_path:
            host, path = host_path.split(":", 1)
            value = f"https://{host}/{path}"
    value = value.rstrip("/")
    return value.lower()


def source_repo_id_for_remote(remote_url: str) -> str:
    digest = hashlib.sha256(canonical_remote_url(remote_url).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def atomic_write_json(path: Path, document: Mapping[str, Any], *, mode: int = 0o600) -> None:
    """Crash-safe JSON write via temp + os.replace (TR5)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def export_cross_host_bundle(
    bundle: Mapping[str, Any],
    destination: Path,
    *,
    source_host: str,
    destination_host: str,
    continuation_payload: Mapping[str, Any],
    pending_captures: Sequence[Mapping[str, Any]] | None = None,
    source_repo_id: str | None = None,
    source_head: str | None = None,
    transition_id: str | None = None,
) -> dict[str, Any]:
    """Validate and atomically write a cross-host continuation bundle."""
    enriched = attach_cross_host_transition(
        dict(bundle),
        source_host=source_host,
        destination_host=destination_host,
        continuation_payload=continuation_payload,
        pending_captures=pending_captures,
        source_repo_id=source_repo_id,
        source_head=source_head,
        transition_id=transition_id,
    )
    verdict = validate_bundle(enriched)
    if verdict.get("verdict") != "pass":
        raise BundleBuildError(f"cross-host bundle failed validation: {verdict}")
    atomic_write_json(Path(destination), enriched)
    return enriched
