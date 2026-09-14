"""Idempotent cross-host HandoffBundle import with CAS lock and context checks (PRD 349 R34–R37, R51)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

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


class ImportValidationError(ImportError_):
    """Import record is absent, incomplete, or invalid (PRD 352 R2)."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        remediation: str,
        **details: Any,
    ) -> None:
        super().__init__(code, message, remediation=remediation, **details)
        self.remediation = remediation

    def as_dict(self) -> dict[str, Any]:
        payload = super().as_dict()
        payload["remediation"] = self.remediation
        return payload


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


def _evidence_recovery_action(code: str, rel: str) -> str:
    if code == "evidence_missing":
        return (
            f"Restore evidence file {rel!r} from checkpoint export or re-run the "
            "verification step that produced it; then retry resume."
        )
    if code == "evidence_digest_mismatch":
        return (
            f"Evidence at {rel!r} changed since checkpoint; re-run verification for "
            "that artifact or refresh the handoff bundle export."
        )
    if code == "evidence_path_escape":
        return f"Evidence path {rel!r} escapes the repository; fix bundle paths (R15)."
    return f"Fix evidence reference {rel!r} and retry resume."


def validate_evidence_digests(
    root: Path,
    evidence_refs: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate evidence digests on resume; explain issues; rerun only failed checks (R26)."""
    root_r = Path(root).resolve()
    issues: list[dict[str, Any]] = []
    rerun_checks: list[str] = []
    checked = 0
    for entry in evidence_refs:
        if not isinstance(entry, Mapping):
            issues.append(
                {
                    "path": "",
                    "code": "evidence_entry_invalid",
                    "message": "evidence reference must be an object",
                    "recovery": "Fix evidenceReferences entries in the import record.",
                }
            )
            continue
        rel = str(entry.get("path") or "").strip()
        expected = str(entry.get("digest") or "").strip()
        if not rel:
            issues.append(
                {
                    "path": "",
                    "code": "evidence_path_missing",
                    "message": "evidence reference missing path",
                    "recovery": "Add repo-relative path and digest to evidenceReferences.",
                }
            )
            continue
        checked += 1
        path = (root_r / rel).resolve()
        if not str(path).startswith(str(root_r)):
            issues.append(
                {
                    "path": rel,
                    "code": "evidence_path_escape",
                    "message": f"evidence path escapes repository: {rel}",
                    "recovery": _evidence_recovery_action("evidence_path_escape", rel),
                }
            )
            rerun_checks.append(rel)
            continue
        if not path.is_file():
            issues.append(
                {
                    "path": rel,
                    "code": "evidence_missing",
                    "message": f"evidence file missing: {rel}",
                    "recovery": _evidence_recovery_action("evidence_missing", rel),
                }
            )
            rerun_checks.append(rel)
            continue
        if expected:
            actual = _file_digest(path)
            if actual != expected:
                issues.append(
                    {
                        "path": rel,
                        "code": "evidence_digest_mismatch",
                        "message": f"evidence digest stale for {rel}",
                        "expectedDigest": expected,
                        "actualDigest": actual,
                        "recovery": _evidence_recovery_action("evidence_digest_mismatch", rel),
                    }
                )
                rerun_checks.append(rel)
    verdict = "pass" if not issues else "fail"
    return {
        "verdict": verdict,
        "checked": checked,
        "issueCount": len(issues),
        "issues": issues,
        "rerunChecks": rerun_checks,
        "explanation": (
            "All evidence digests match."
            if verdict == "pass"
            else f"{len(issues)} evidence issue(s); rerun checks only for: {', '.join(rerun_checks) or 'none'}"
        ),
    }


def validate_evidence_on_resume(
    root: Path,
    import_record: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate import-record evidence references before resume dispatch (PRD 352 R26)."""
    refs: list[Any] = []
    if isinstance(import_record.get("evidence"), list):
        refs.extend(import_record["evidence"])
    continuation = import_record.get("continuation_payload") or {}
    if isinstance(continuation, Mapping):
        refs.extend(list(continuation.get("evidenceReferences") or []))
    deduped: list[Mapping[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in refs:
        if not isinstance(entry, Mapping):
            continue
        key = (str(entry.get("path") or ""), str(entry.get("digest") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return validate_evidence_digests(root, deduped)


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


_IMPORT_RECORD_REQUIRED = ("transition_id", "bundleDigest", "taskRows")
_SAFE_HANDOFF_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
_BUNDLE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REIMPORT_REMEDIATION = (
    "Re-import the handoff bundle with `python3 scripts/handoff_bundle.py import "
    "<bundle> --run-id <id>` then retry `resume`."
)


def _require_safe_handoff_id(value: str, *, field: str) -> str:
    text = str(value or "").strip()
    if not text or not _SAFE_HANDOFF_ID_RE.match(text):
        raise ImportValidationError(
            "import_record_invalid",
            f"{field} is not a safe identifier",
            remediation=_REIMPORT_REMEDIATION,
            field=field,
        )
    return text


def validate_import_record(
    root: Path,
    run_id: str,
    transition_id: str | None = None,
) -> dict[str, Any]:
    """Load and validate a materialized import record (PRD 352 R2)."""
    rid = _require_safe_handoff_id(run_id, field="run_id")
    try:
        imports_dir = run_dir(root, rid) / "imports"
    except ValueError as exc:
        raise ImportValidationError(
            "import_record_absent",
            str(exc),
            remediation=_REIMPORT_REMEDIATION,
        ) from exc
    imports_root = imports_dir.resolve()
    tid = str(transition_id or "").strip()
    if tid:
        tid = _require_safe_handoff_id(tid, field="transition_id")
        path = (imports_dir / f"{tid}.json").resolve()
        try:
            path.relative_to(imports_root)
        except ValueError as exc:
            raise ImportValidationError(
                "import_record_invalid",
                "import record path escapes the imports directory",
                remediation=_REIMPORT_REMEDIATION,
                path=str(path),
            ) from exc
        if not path.is_file():
            raise ImportValidationError(
                "import_record_absent",
                f"no import record for transition {tid!r}",
                remediation=_REIMPORT_REMEDIATION,
                path=str(path),
            )
    else:
        files = sorted(imports_dir.glob("*.json")) if imports_dir.is_dir() else []
        if not files:
            raise ImportValidationError(
                "import_record_absent",
                "no import record on disk",
                remediation=_REIMPORT_REMEDIATION,
                path=str(imports_dir),
            )
        if len(files) > 1:
            raise ImportValidationError(
                "import_record_incomplete",
                "multiple import records; pass --transition-id",
                remediation="Retry resume with --transition-id <id>.",
                candidates=[p.stem for p in files],
            )
        path = files[0].resolve()
        try:
            path.relative_to(imports_root)
        except ValueError as exc:
            raise ImportValidationError(
                "import_record_invalid",
                "import record path escapes the imports directory",
                remediation=_REIMPORT_REMEDIATION,
                path=str(path),
            ) from exc
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportValidationError(
            "import_record_invalid",
            "import record is not valid JSON",
            remediation=_REIMPORT_REMEDIATION,
            path=str(path),
        ) from exc
    if not isinstance(record, dict):
        raise ImportValidationError(
            "import_record_invalid",
            "import record must be a JSON object",
            remediation=_REIMPORT_REMEDIATION,
            path=str(path),
        )
    missing = [
        key
        for key in _IMPORT_RECORD_REQUIRED
        if key not in record or record.get(key) in (None, "")
    ]
    if missing:
        raise ImportValidationError(
            "import_record_incomplete",
            "import record is missing required fields",
            remediation=_REIMPORT_REMEDIATION,
            missing=missing,
            path=str(path),
        )
    record_tid = str(record.get("transition_id") or "").strip()
    if record_tid != path.stem:
        raise ImportValidationError(
            "import_record_invalid",
            "import record transition_id does not match file stem",
            remediation=_REIMPORT_REMEDIATION,
            path=str(path),
        )
    digest = str(record.get("bundleDigest") or "")
    if not _BUNDLE_DIGEST_RE.match(digest):
        raise ImportValidationError(
            "import_record_invalid",
            "import record bundleDigest is not a sha256 digest",
            remediation=_REIMPORT_REMEDIATION,
            path=str(path),
        )
    task_rows = record.get("taskRows")
    if not isinstance(task_rows, dict):
        raise ImportValidationError(
            "import_record_invalid",
            "import record taskRows must be an object",
            remediation=_REIMPORT_REMEDIATION,
            path=str(path),
        )
    record_run = str(record.get("run_id") or "").strip()
    if record_run and record_run != rid:
        raise ImportValidationError(
            "import_record_invalid",
            "import record run_id does not match --run-id",
            remediation=_REIMPORT_REMEDIATION,
            path=str(path),
        )
    return record


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
        "run_id": run_id,
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


def write_import_record_from_bundle(
    root: Path, run_id: str, bundle: Mapping[str, Any]
) -> dict[str, Any]:
    """Materialize a resume ticket from a validated bundle (informational or cross-host)."""
    rid = _require_safe_handoff_id(run_id, field="run_id")
    raw_tid = str(bundle.get("transition_id") or "").strip()
    if raw_tid and bundle.get("continuation_payload"):
        _require_safe_handoff_id(raw_tid, field="transition_id")
        return _materialize_run_state(root, rid, bundle)
    tid = raw_tid if _SAFE_HANDOFF_ID_RE.match(raw_tid) else "imported"
    digest = str(bundle.get("bundleDigest") or digest_payload(bundle))
    task_rows = bundle.get("taskRows")
    if not isinstance(task_rows, dict):
        task_rows = {"completed": [], "remaining": []}
    state = {
        "transition_id": tid,
        "run_id": rid,
        "bundleDigest": digest,
        "taskRows": task_rows,
        "continuation_payload": dict(bundle.get("continuation_payload") or {}),
    }
    atomic_write_json(_state_path(root, rid, tid), state)
    return state


class ImportLock:
    """Single-node filesystem CAS lock via O_CREAT|O_EXCL (R36/R7).

    Covers validation through ownership-transfer — not just filesystem import.
    """

    def __init__(self, root: Path, run_id: str, *, agent_identity: str) -> None:
        self.root = root
        self.run_id = run_id
        self.agent_identity = agent_identity
        self.path = bundle_import_lock_path(root, run_id)
        self._phase = "idle"
        self._held = False

    def _write_meta(self, phase: str) -> None:
        meta = {
            "agentIdentity": self.agent_identity,
            "pid": os.getpid(),
            "phase": phase,
            "runId": self.run_id,
        }
        self.path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    def acquire(self, *, phase: str = "validation") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._held:
            self._phase = phase
            self._write_meta(phase)
            return
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        payload = (
            json.dumps(
                {
                    "agentIdentity": self.agent_identity,
                    "pid": os.getpid(),
                    "phase": phase,
                    "runId": self.run_id,
                }
            )
            + "\n"
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
                lockPhase=(holder.get("phase") if isinstance(holder, dict) else None),
            ) from exc
        try:
            os.write(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        self._held = True
        self._phase = phase

    def enter_ownership_transfer(self) -> None:
        if not self._held:
            self.acquire(phase="ownership_transfer")
            return
        self._phase = "ownership_transfer"
        self._write_meta("ownership_transfer")

    def release(self) -> None:
        try:
            self.path.unlink(missing_ok=True)
        except OSError:
            pass
        self._held = False
        self._phase = "idle"


def write_resume_evidence(
    root: Path,
    *,
    run_id: str,
    transition_id: str,
    next_eligible_action: str,
    host_adapter_id: str,
) -> dict[str, Any]:
    """Prove destination began the next eligible action — distinct from import-ack (R21)."""
    from datetime import datetime, timezone

    from .bundle import atomic_write_json

    try:
        from shipwright_paths import resume_evidence_path
    except ImportError:  # pragma: no cover
        import sys

        _SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
        if str(_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS))
        from shipwright_paths import resume_evidence_path

    record = {
        "transitionId": str(transition_id),
        "runId": str(run_id),
        "recordedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "nextEligibleAction": str(next_eligible_action),
        "hostAdapterId": str(host_adapter_id),
    }
    path = resume_evidence_path(root, run_id, transition_id)
    atomic_write_json(path, record)
    import_path = _state_path(root, run_id, transition_id)
    if import_path.is_file():
        try:
            import_record = json.loads(import_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            import_record = {}
        if isinstance(import_record, dict):
            import_record["resumeEvidence"] = record
            atomic_write_json(import_path, import_record)
    return record


def read_resume_evidence(root: Path, *, run_id: str, transition_id: str) -> dict[str, Any] | None:
    try:
        from shipwright_paths import resume_evidence_path
    except ImportError:  # pragma: no cover
        import sys

        _SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
        if str(_SCRIPTS) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS))
        from shipwright_paths import resume_evidence_path

    path = resume_evidence_path(root, run_id, transition_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


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
    lock.acquire(phase="validation")
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
        lock.enter_ownership_transfer()
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
                "lockPhase": "ownership_transfer",
            },
        )
    finally:
        lock.release()
