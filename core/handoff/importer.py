"""Idempotent cross-host HandoffBundle import with CAS lock and context checks (PRD 349 R34–R37, R51)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .acknowledgement import read_destination_ack, write_destination_ack
from .bundle import atomic_write_json, canonical_remote_url, source_repo_id_for_remote
from .validate_bundle import digest_payload, validate_bundle

try:
    from shipwright_paths import (
        AllowlistMissingError,
        allowlist_path,
        bundle_import_lock_path,
        require_allowlist_path,
        run_dir,
    )
except ImportError:  # pragma: no cover
    import sys

    _SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    from shipwright_paths import (  # type: ignore
        AllowlistMissingError,
        allowlist_path,
        bundle_import_lock_path,
        require_allowlist_path,
        run_dir,
    )


# R36: cross-clone / cross-machine concurrency is out of scope — requires external coordination.
# The O_CREAT|O_EXCL lock lives only under the destination repo's neutral runs directory (SC5).
CROSS_CLONE_CONCURRENCY_NOTE = (
    "Cross-clone and cross-machine concurrent import coordination is out of scope; "
    "use an external coordination mechanism. The bundle-import.lock CAS guard is "
    "stored only under the destination repo's neutral .shipwright/runs/<run_id>/ tree (SC5)."
)


class ImportError_(RuntimeError):
    """Structured import failure."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.details}


@dataclass
class ImportResult:
    status: str
    transition_id: str
    run_id: str
    state_path: str
    ack: dict[str, Any] | None = None
    already_imported: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "transitionId": self.transition_id,
            "runId": self.run_id,
            "statePath": self.state_path,
            "alreadyImported": self.already_imported,
            **self.details,
        }
        if self.ack is not None:
            payload["destination_ack"] = self.ack
        return payload


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def resolve_canonical_remote(root: Path) -> str:
    proc = _git(root, "remote", "get-url", "origin")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ImportError_("remote_unavailable", "git remote origin URL unavailable")
    return canonical_remote_url(proc.stdout.strip())


def verify_repo_identity(root: Path, bundle: Mapping[str, Any]) -> None:
    """R51 — SHA-256(canonical remote) vs source_repo_id before any execution-permission check."""
    expected = str(bundle.get("source_repo_id") or "").strip()
    if not expected:
        raise ImportError_("source_repo_id_missing", "bundle missing source_repo_id")
    actual = source_repo_id_for_remote(resolve_canonical_remote(root))
    if actual != expected:
        raise ImportError_(
            "repo_identity_mismatch",
            "destination repository identity does not match bundle source_repo_id",
            expected=expected,
            actual=actual,
        )


def _ls_remote_head(root: Path) -> str:
    proc = _git(root, "ls-remote", "origin", "HEAD")
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ImportError_(
            "ls_remote_failed",
            "git ls-remote origin HEAD failed",
            stderr=proc.stderr,
        )
    sha = proc.stdout.split()[0].strip().lower()
    if len(sha) != 40:
        raise ImportError_("ls_remote_invalid", f"unexpected ls-remote sha: {sha!r}")
    return sha


def _worktree_clean(root: Path) -> bool:
    proc = _git(root, "status", "--porcelain")
    if proc.returncode != 0:
        raise ImportError_("worktree_status_failed", "git status failed", stderr=proc.stderr)
    return proc.stdout.strip() == ""


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def verify_bundle_context(
    root: Path,
    bundle: Mapping[str, Any],
    *,
    interactive: bool = False,
    confirm: bool = False,
    headless: bool = False,
) -> list[str]:
    """R37 context checks. Headless/CI fails closed — confirm cannot bypass."""
    failures: list[str] = []
    expected_head = str(bundle.get("source_head") or "").strip().lower()
    if expected_head:
        try:
            remote_head = _ls_remote_head(root)
            if remote_head != expected_head:
                failures.append(
                    f"head_mismatch: expected {expected_head}, ls-remote={remote_head}"
                )
        except ImportError_ as exc:
            failures.append(f"{exc.code}: {exc.message}")

    continuation = bundle.get("continuation_payload") or {}
    evidence_refs: list[Any] = []
    if isinstance(continuation, Mapping):
        evidence_refs = list(continuation.get("evidenceReferences") or [])
    for entry in evidence_refs:
        if not isinstance(entry, Mapping):
            failures.append("evidence_entry_invalid")
            continue
        rel = str(entry.get("path") or "")
        expected = str(entry.get("digest") or "")
        path = (root / rel).resolve()
        if not str(path).startswith(str(root.resolve())):
            failures.append(f"evidence_path_escape:{rel}")
            continue
        if not path.is_file():
            failures.append(f"evidence_missing:{rel}")
            continue
        actual = _file_digest(path)
        if expected and actual != expected:
            failures.append(f"evidence_digest_mismatch:{rel}")

    if not _worktree_clean(root):
        failures.append("worktree_dirty")

    if not failures:
        return []

    if headless or not interactive:
        raise ImportError_(
            "context_validation_failed",
            "bundle context checks failed (headless fail-closed)",
            failures=failures,
        )
    if not confirm:
        raise ImportError_(
            "context_validation_failed",
            "bundle context checks failed; re-run interactively with explicit confirmation",
            failures=failures,
        )
    return failures


def _load_allowlist(root: Path) -> list[Any]:
    """SC3/SC4 — on-disk allowlist only; missing or [] rejects. Bundle snapshot never substitutes."""
    _ = allowlist_path  # API stability; require_* is authoritative for presence
    try:
        path = require_allowlist_path(root)
    except AllowlistMissingError as exc:
        raise ImportError_("allowlist_missing", str(exc)) from exc
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = raw.get("rules") or raw.get("allowlist") or raw.get("entries") or []
    else:
        entries = []
    if not entries:
        raise ImportError_(
            "allowlist_empty",
            f"allowlist at {path} is empty — import rejected (SC4)",
        )
    return list(entries)


def _state_path(root: Path, run_id: str, transition_id: str) -> Path:
    return run_dir(root, run_id) / "imports" / f"{transition_id}.json"


def _dedupe(rows: list[Any], key_fields: tuple[str, ...]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = "|".join(str(row.get(k, "")) for k in key_fields) or json.dumps(
            row, sort_keys=True, default=str
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(dict(row))
    return out


def _materialize_run_state(
    root: Path, run_id: str, bundle: Mapping[str, Any]
) -> dict[str, Any]:
    continuation = dict(bundle.get("continuation_payload") or {})
    state = {
        "transition_id": bundle.get("transition_id"),
        "source_host": bundle.get("source_host"),
        "destination_host": bundle.get("destination_host"),
        "continuation_payload": continuation,
        "taskRows": {
            "completed": _dedupe(
                list(continuation.get("completedTaskRows") or []),
                ("id", "ref", "title"),
            ),
            "remaining": _dedupe(
                list(continuation.get("remainingTaskRows") or []),
                ("id", "ref", "title"),
            ),
        },
        "evidence": _dedupe(
            list(continuation.get("evidenceReferences") or []),
            ("path", "digest"),
        ),
        "gapItems": _dedupe(
            list(bundle.get("pending_captures") or []),
            ("kind", "title", "path"),
        ),
        "unresolvedDecisions": list(continuation.get("unresolvedDecisions") or []),
        "bundleDigest": digest_payload(bundle),
    }
    path = _state_path(root, run_id, str(bundle["transition_id"]))
    atomic_write_json(path, state)
    return state


class ImportLock:
    """Single-node filesystem CAS lock via O_CREAT|O_EXCL (R36). Not fcntl.flock."""

    def __init__(self, root: Path, run_id: str, *, agent_identity: str) -> None:
        self.root = root
        self.run_id = run_id
        self.agent_identity = agent_identity
        self.path = bundle_import_lock_path(root, run_id)

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        payload = (
            json.dumps({"agentIdentity": self.agent_identity, "pid": os.getpid()}) + "\n"
        ).encode()
        try:
            fd = os.open(str(self.path), flags, 0o600)
        except FileExistsError as exc:
            holder: Any = {}
            try:
                holder = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
            raise ImportError_(
                "already_acquired",
                "bundle import lock held by another agent",
                holder=(holder.get("agentIdentity") if isinstance(holder, dict) else holder),
                lockPath=str(self.path),
            ) from exc
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)

    def release(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass


def import_bundle(
    root: Path,
    bundle: Mapping[str, Any],
    *,
    run_id: str,
    destination_adapter_id: str,
    agent_identity: str = "agent",
    interactive: bool = False,
    confirm: bool = False,
    headless: bool | None = None,
) -> ImportResult:
    """Import a cross-host bundle: R51 → allowlist → R37 → CAS lock → idempotent materialize → ack."""
    root = Path(root).resolve()
    if headless is None:
        headless = not interactive

    verdict = validate_bundle(dict(bundle))
    if verdict.get("verdict") != "pass":
        raise ImportError_("bundle_invalid", "bundle failed validation", verdict=verdict)

    transition_id = str(bundle.get("transition_id") or "").strip()
    if not transition_id:
        raise ImportError_("transition_id_missing", "cross-host import requires transition_id")

    # R51 first — before execution-permission evaluation
    verify_repo_identity(root, bundle)

    # Destination allowlist from on-disk path only (SC3/SC4)
    _load_allowlist(root)

    # R37 context validation
    verify_bundle_context(
        root,
        bundle,
        interactive=interactive,
        confirm=confirm,
        headless=bool(headless),
    )

    existing_ack = read_destination_ack(root, run_id=run_id, transition_id=transition_id)
    state_file = _state_path(root, run_id, transition_id)
    if existing_ack and state_file.is_file():
        return ImportResult(
            status="ok",
            transition_id=transition_id,
            run_id=run_id,
            state_path=str(state_file),
            ack=existing_ack,
            already_imported=True,
        )

    lock = ImportLock(root, run_id, agent_identity=agent_identity)
    lock.acquire()
    try:
        existing_ack = read_destination_ack(root, run_id=run_id, transition_id=transition_id)
        if existing_ack and state_file.is_file():
            return ImportResult(
                status="ok",
                transition_id=transition_id,
                run_id=run_id,
                state_path=str(state_file),
                ack=existing_ack,
                already_imported=True,
            )

        state = _materialize_run_state(root, run_id, bundle)
        import_digest = str(state.get("bundleDigest") or digest_payload(bundle))
        ack = write_destination_ack(
            root,
            run_id=run_id,
            transition_id=transition_id,
            host_adapter_id=destination_adapter_id,
            import_digest=import_digest,
            agent_identity=agent_identity,
        )
        return ImportResult(
            status="ok",
            transition_id=transition_id,
            run_id=run_id,
            state_path=str(state_file),
            ack=ack,
            already_imported=False,
            details={
                "taskRowCounts": {
                    "completed": len(state["taskRows"]["completed"]),
                    "remaining": len(state["taskRows"]["remaining"]),
                },
                "evidenceCount": len(state["evidence"]),
                "gapCount": len(state["gapItems"]),
            },
        )
    finally:
        lock.release()
