"""Cross-host HandoffBundle continuation fields and atomic export (PRD 349 R31–R33)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from .validate_bundle import digest_payload, validate_bundle  # noqa: F401 — digest_payload used below

TRANSITION_SCHEMA_VERSION = "cross-host-handoff@v1"
CHECKPOINT_SCHEMA_VERSION = "handoff-checkpoint@v1"
CHECKPOINT_DIR_NAME = "sw-handoff-checkpoints"
UNCOMMITTED_CHECKPOINT_DIR = "sw-handoff-uncommitted"
UNCOMMITTED_POLICY_PRESERVE = "preserve"
UNCOMMITTED_POLICY_REQUIRE_DISCARD = "require_discard_confirm"
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
    root: Path | None = None,
) -> dict[str, Any]:
    """Add optional cross-host fields; same-host bundles may omit this entirely."""
    updated = deepcopy(dict(bundle))
    tid = transition_id or str(uuid.uuid4())
    payload = dict(continuation_payload)
    if root is not None:
        payload = neutralize_checkpoint_paths(payload, root=Path(root))
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


def _is_host_absolute(value: str) -> bool:
    """True for POSIX, Windows drive, or UNC paths regardless of this host's OS."""
    text = str(value or "")
    if not text:
        return False
    if Path(text).is_absolute() or text.startswith(("/", "\\")):
        return True
    return len(text) >= 3 and text[1] == ":" and text[0].isalpha() and text[2] in "/\\"


def repo_relative_checkpoint_path(root: Path, raw: str) -> str:
    """Return a repo-relative POSIX path; refuse paths that escape root (R15)."""
    value = str(raw or "").strip()
    if not value:
        raise BundleBuildError("checkpoint path is empty (R15)")
    if value in {".", "./"}:
        return "."
    root_r = Path(root).resolve()
    path = Path(value)
    if ".." in path.parts:
        raise BundleBuildError(
            f"checkpoint path {value!r} is not inside repo {root_r} (R15)"
        )
    candidate = path if _is_host_absolute(value) else (root_r / path)
    try:
        rel = candidate.resolve().relative_to(root_r)
    except ValueError as exc:
        raise BundleBuildError(
            f"checkpoint path {value!r} is not inside repo {root_r} (R15)"
        ) from exc
    posix = rel.as_posix()
    return "." if posix in {"", "."} else posix


def neutralize_checkpoint_paths(
    payload: Mapping[str, Any], *, root: Path
) -> dict[str, Any]:
    """Rewrite continuation checkpoint paths to repo-relative form (PRD 352 R15)."""
    out = deepcopy(dict(payload))
    if "repo" in out:
        repo_raw = out.get("repo")
        if not isinstance(repo_raw, Mapping):
            raise BundleBuildError("continuation repo must be an object (R15)")
        repo = dict(repo_raw)
        worktree = str(repo.get("worktree") or "").strip()
        if not worktree:
            raise BundleBuildError("repo.worktree is required (R15)")
        repo["worktree"] = repo_relative_checkpoint_path(root, worktree)
        out["repo"] = repo
    evidence: list[dict[str, Any]] = []
    if "evidenceReferences" in out:
        for entry in out.get("evidenceReferences") or []:
            if not isinstance(entry, Mapping):
                raise BundleBuildError("evidenceReferences entries must be objects (R15)")
            item = dict(entry)
            path = str(item.get("path") or "").strip()
            if not path:
                raise BundleBuildError("evidenceReferences.path is required (R15)")
            item["path"] = repo_relative_checkpoint_path(root, path)
            evidence.append(item)
        out["evidenceReferences"] = evidence
    return out


def durable_checkpoint_path(root: Path, transition_id: str) -> Path:
    """Return durable checkpoint location under operator-local state (PRD 352 R16)."""
    safe = str(transition_id or "").strip()
    if not safe or "/" in safe or "\\" in safe or ".." in safe:
        raise BundleBuildError(f"invalid transition_id for checkpoint: {transition_id!r}")
    return Path(root).resolve() / ".cursor" / CHECKPOINT_DIR_NAME / f"{safe}.json"


def write_durable_checkpoint(
    root: Path,
    *,
    transition_id: str,
    continuation_payload: Mapping[str, Any],
    bundle_digest: str = "",
    source_host: str = "",
    destination_host: str = "",
) -> dict[str, Any]:
    """Persist continuation checkpoint before source completion signal (PRD 352 R16)."""
    normalized = neutralize_checkpoint_paths(dict(continuation_payload), root=Path(root))
    record: dict[str, Any] = {
        "schemaVersion": CHECKPOINT_SCHEMA_VERSION,
        "transitionId": str(transition_id),
        "status": "checkpointed",
        "continuationPayload": normalized,
    }
    if bundle_digest:
        record["bundleDigest"] = str(bundle_digest)
    if source_host:
        record["sourceHost"] = str(source_host)
    if destination_host:
        record["destinationHost"] = str(destination_host)
    _reject_credential_material(record)
    path = durable_checkpoint_path(root, transition_id)
    atomic_write_json(path, record)
    return {"verdict": "pass", "path": str(path), "transitionId": str(transition_id)}


def read_durable_checkpoint(root: Path, transition_id: str) -> dict[str, Any]:
    """Load a durable checkpoint written before source completion (PRD 352 R16)."""
    path = durable_checkpoint_path(root, transition_id)
    if not path.is_file():
        raise BundleBuildError(f"durable checkpoint missing at {path} (R16)")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleBuildError(f"durable checkpoint invalid at {path} (R16)") from exc
    if not isinstance(payload, dict):
        raise BundleBuildError(f"durable checkpoint must be an object at {path} (R16)")
    return payload


def uncommitted_checkpoint_path(root: Path, transition_id: str) -> Path:
    """Return durable uncommitted-changes checkpoint location (PRD 352 R27)."""
    safe = str(transition_id or "").strip()
    if not safe or "/" in safe or "\\" in safe or ".." in safe:
        raise BundleBuildError(f"invalid transition_id for uncommitted checkpoint: {transition_id!r}")
    return Path(root).resolve() / ".cursor" / UNCOMMITTED_CHECKPOINT_DIR / f"{safe}.json"


def _git_porcelain(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise BundleBuildError(f"git status failed: {proc.stderr.strip()}")
    return proc.stdout


def _git_diff_patch(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise BundleBuildError(f"git diff failed: {proc.stderr.strip()}")
    patch = proc.stdout
    untracked_proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
        capture_output=True,
        text=True,
        check=False,
    )
    if untracked_proc.returncode == 0:
        for rel in untracked_proc.stdout.splitlines():
            rel = rel.strip()
            if not rel:
                continue
            path = root / rel
            if path.is_file():
                patch += f"\n# untracked:{rel}\n"
                patch += path.read_text(encoding="utf-8", errors="replace")
    return patch


def worktree_has_uncommitted_changes(root: Path) -> bool:
    """True when the worktree has staged or unstaged changes."""
    return bool(_git_porcelain(root).strip())


def capture_uncommitted_changes_checkpoint(
    root: Path,
    transition_id: str,
    *,
    policy: str = UNCOMMITTED_POLICY_PRESERVE,
) -> dict[str, Any]:
    """Persist uncommitted worktree state before handoff; never silent discard (R27)."""
    if policy not in {UNCOMMITTED_POLICY_PRESERVE, UNCOMMITTED_POLICY_REQUIRE_DISCARD}:
        raise BundleBuildError(f"unknown uncommitted policy: {policy!r}")
    porcelain = _git_porcelain(root)
    if not porcelain.strip():
        return {
            "verdict": "pass",
            "action": "uncommitted-checkpoint",
            "skipped": True,
            "reason": "worktree-clean",
            "policy": policy,
        }
    record: dict[str, Any] = {
        "schemaVersion": "handoff-uncommitted@v1",
        "transitionId": str(transition_id),
        "policy": policy,
        "status": "preserved",
        "porcelain": porcelain,
        "patch": _git_diff_patch(root),
    }
    path = uncommitted_checkpoint_path(root, transition_id)
    atomic_write_json(path, record)
    return {
        "verdict": "pass",
        "action": "uncommitted-checkpoint",
        "path": str(path),
        "transitionId": str(transition_id),
        "policy": policy,
        "patchBytes": len(record["patch"].encode("utf-8")),
    }


def read_uncommitted_changes_checkpoint(root: Path, transition_id: str) -> dict[str, Any] | None:
    path = uncommitted_checkpoint_path(root, transition_id)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def resolve_uncommitted_changes_policy(
    root: Path,
    transition_id: str,
    *,
    policy: str = UNCOMMITTED_POLICY_PRESERVE,
    confirm_discard: bool = False,
) -> dict[str, Any]:
    """Apply explicit uncommitted-changes policy at switch/resume (PRD 352 R27)."""
    if not worktree_has_uncommitted_changes(root):
        return {"verdict": "pass", "action": "uncommitted-policy", "worktreeClean": True}
    existing = read_uncommitted_changes_checkpoint(root, transition_id)
    if existing and existing.get("status") == "preserved":
        return {
            "verdict": "pass",
            "action": "uncommitted-policy",
            "worktreeClean": False,
            "checkpointPath": str(uncommitted_checkpoint_path(root, transition_id)),
            "policy": existing.get("policy") or policy,
            "note": "checkpoint-already-preserved",
        }
    if policy == UNCOMMITTED_POLICY_REQUIRE_DISCARD:
        if not confirm_discard:
            return {
                "verdict": "halt",
                "action": "uncommitted-policy",
                "error": "handoff:uncommitted-changes-require-discard",
                "policy": policy,
                "recovery": (
                    "Re-run with explicit discard confirmation or apply preserved patch "
                    f"from {uncommitted_checkpoint_path(root, transition_id)}"
                ),
            }
        return {
            "verdict": "pass",
            "action": "uncommitted-policy",
            "policy": policy,
            "discarded": True,
            "note": "explicit-discard-confirmed",
        }
    return capture_uncommitted_changes_checkpoint(root, transition_id, policy=policy)


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
    root: Path | None = None,
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
        root=root,
    )
    verdict = validate_bundle(enriched)
    if verdict.get("verdict") != "pass":
        raise BundleBuildError(f"cross-host bundle failed validation: {verdict}")
    tid = str(enriched.get("transition_id") or transition_id or "").strip()
    if root is not None and tid:
        write_durable_checkpoint(
            Path(root),
            transition_id=tid,
            continuation_payload=continuation_payload,
            bundle_digest=str(enriched.get("bundleDigest") or ""),
            source_host=str(source_host),
            destination_host=str(destination_host),
        )
    atomic_write_json(Path(destination), enriched)
    return enriched
