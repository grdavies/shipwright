"""Trust-on-first-use pairing record store (PRD 080 phase 4 / R3)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from credentials.selector_integrity import (
    SELECTOR_DIR_MODE,
    SELECTOR_FILE_MODE,
    SelectorIntegrityError,
    verify_selector_path,
)
from credentials.selector_store import resolve_xdg_config_home, validate_trusted_xdg_base

PAIRING_FILENAME = "credential-pairings.json"
PAIRING_RELATIVE = Path("shipwright") / PAIRING_FILENAME


class PairingStoreError(Exception):
    """Fail-closed pairing store error with a stable code and remediation hint."""

    def __init__(self, code: str, hint: str) -> None:
        self.code = code
        self.hint = hint
        super().__init__(f"{code}: {hint}")


class PairingVerdict(str, Enum):
    ALLOWED = "allowed"
    ABSENT = "absent"
    UNAPPROVED = "unapproved"
    MISMATCH = "mismatch"


@dataclass(frozen=True, slots=True)
class PairingRecord:
    credential_ref: str
    project_id: str
    remote: str
    status: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class PairingCheck:
    verdict: PairingVerdict
    record: PairingRecord | None = None
    code: str | None = None
    hint: str | None = None


def default_pairing_path(*, xdg_base: Path | None = None) -> Path:
    return resolve_xdg_config_home(xdg_base) / PAIRING_RELATIVE


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_triple(
    credential_ref: str,
    project_id: str,
    remote: str,
) -> tuple[str, str, str]:
    ref = str(credential_ref).strip()
    project = str(project_id).strip()
    repo_remote = str(remote).strip()
    if not ref or not project or not repo_remote:
        raise PairingStoreError(
            "pairing-invalid-triple",
            "pairing requires non-empty credential reference, project id, and remote",
        )
    return ref, project, repo_remote


def _record_from_raw(ref: str, raw: Any) -> PairingRecord:
    if not isinstance(raw, dict):
        raise PairingStoreError(
            "pairing-invalid-record",
            f"pairing record for {ref!r} must be an object",
        )
    project_id = raw.get("projectId")
    remote = raw.get("remote")
    status = raw.get("status")
    recorded_at = raw.get("recordedAt")
    if not isinstance(project_id, str) or not project_id.strip():
        raise PairingStoreError(
            "pairing-invalid-record",
            f"pairing record for {ref!r} must declare projectId",
        )
    if not isinstance(remote, str) or not remote.strip():
        raise PairingStoreError(
            "pairing-invalid-record",
            f"pairing record for {ref!r} must declare remote",
        )
    if status not in {"pending", "approved"}:
        raise PairingStoreError(
            "pairing-invalid-record",
            f"pairing record for {ref!r} must use status pending or approved",
        )
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise PairingStoreError(
            "pairing-invalid-record",
            f"pairing record for {ref!r} must declare recordedAt",
        )
    return PairingRecord(
        credential_ref=ref,
        project_id=project_id.strip(),
        remote=remote.strip(),
        status=status,
        recorded_at=recorded_at.strip(),
    )


def _load_document(path: Path, *, skip_integrity: bool) -> dict[str, Any]:
    if not skip_integrity:
        try:
            verify_selector_path(path)
        except SelectorIntegrityError as exc:
            raise PairingStoreError(exc.code, exc.hint) from exc
    elif not path.exists():
        return {"version": 1, "pairings": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PairingStoreError(
            "pairing-invalid-json",
            "pairing document must be valid JSON",
        ) from exc
    if not isinstance(raw, dict):
        raise PairingStoreError(
            "pairing-invalid-json",
            "pairing document must be a JSON object",
        )
    if raw.get("version") != 1:
        raise PairingStoreError(
            "pairing-invalid-version",
            "pairing document version must be 1",
        )
    pairings = raw.get("pairings")
    if pairings is None:
        raw["pairings"] = {}
    elif not isinstance(pairings, dict):
        raise PairingStoreError(
            "pairing-invalid-json",
            "pairing document pairings must be an object",
        )
    return raw


def _write_document(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, SELECTOR_DIR_MODE)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temp, SELECTOR_FILE_MODE)
    temp.replace(path)


def load_pairing_store(
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
) -> dict[str, PairingRecord]:
    if xdg_base is not None:
        validate_trusted_xdg_base(xdg_base)
    pairing_path = (path or default_pairing_path(xdg_base=xdg_base)).expanduser()
    document = _load_document(pairing_path, skip_integrity=skip_integrity)
    pairings = document.get("pairings", {})
    return {
        ref: _record_from_raw(ref, entry)
        for ref, entry in pairings.items()
        if isinstance(ref, str)
    }


def record_first_use(
    credential_ref: str,
    project_id: str,
    remote: str,
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
) -> PairingRecord:
    ref, project, repo_remote = _normalize_triple(credential_ref, project_id, remote)
    if xdg_base is not None:
        validate_trusted_xdg_base(xdg_base)
    pairing_path = (path or default_pairing_path(xdg_base=xdg_base)).expanduser()
    document = _load_document(pairing_path, skip_integrity=skip_integrity)
    pairings = document.setdefault("pairings", {})
    if ref in pairings:
        existing = _record_from_raw(ref, pairings[ref])
        if (
            existing.project_id == project
            and existing.remote == repo_remote
            and existing.status == "pending"
        ):
            return existing
        raise PairingStoreError(
            "pairing-already-recorded",
            f"pairing for {ref!r} is already recorded; mismatches refuse without re-prompt",
        )
    record = {
        "projectId": project,
        "remote": repo_remote,
        "status": "pending",
        "recordedAt": _utc_now(),
    }
    pairings[ref] = record
    _write_document(pairing_path, document)
    return _record_from_raw(ref, record)


def approve_pairing(
    credential_ref: str,
    project_id: str,
    remote: str,
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
) -> PairingRecord:
    ref, project, repo_remote = _normalize_triple(credential_ref, project_id, remote)
    if xdg_base is not None:
        validate_trusted_xdg_base(xdg_base)
    pairing_path = (path or default_pairing_path(xdg_base=xdg_base)).expanduser()
    document = _load_document(pairing_path, skip_integrity=skip_integrity)
    pairings = document.get("pairings", {})
    if ref not in pairings:
        raise PairingStoreError(
            "pairing-absent",
            f"no pairing record exists for {ref!r}",
        )
    existing = _record_from_raw(ref, pairings[ref])
    if existing.project_id != project or existing.remote != repo_remote:
        raise PairingStoreError(
            "pairing-mismatch",
            f"pairing for {ref!r} does not match the recorded project id and remote",
        )
    if existing.status == "approved":
        return existing
    record = {
        "projectId": project,
        "remote": repo_remote,
        "status": "approved",
        "recordedAt": existing.recorded_at,
        "approvedAt": _utc_now(),
    }
    pairings[ref] = record
    _write_document(pairing_path, document)
    return _record_from_raw(ref, record)


def check_pairing(
    credential_ref: str,
    project_id: str,
    remote: str,
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
) -> PairingCheck:
    ref, project, repo_remote = _normalize_triple(credential_ref, project_id, remote)
    records = load_pairing_store(path=path, xdg_base=xdg_base, skip_integrity=skip_integrity)
    record = records.get(ref)
    if record is None:
        return PairingCheck(
            verdict=PairingVerdict.ABSENT,
            code="pairing-absent",
            hint="record the first-use pairing and approve it before resolution",
        )
    if record.project_id != project or record.remote != repo_remote:
        return PairingCheck(
            verdict=PairingVerdict.MISMATCH,
            record=record,
            code="pairing-mismatch",
            hint="recorded pairing does not match; refusal is permanent without re-prompt",
        )
    if record.status != "approved":
        return PairingCheck(
            verdict=PairingVerdict.UNAPPROVED,
            record=record,
            code="pairing-unapproved",
            hint="approve the recorded pairing before credential resolution",
        )
    return PairingCheck(verdict=PairingVerdict.ALLOWED, record=record)


def require_approved_pairing(
    credential_ref: str,
    project_id: str,
    remote: str,
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
) -> PairingRecord:
    result = check_pairing(
        credential_ref,
        project_id,
        remote,
        path=path,
        xdg_base=xdg_base,
        skip_integrity=skip_integrity,
    )
    if result.verdict is PairingVerdict.ALLOWED and result.record is not None:
        return result.record
    raise PairingStoreError(
        result.code or "pairing-refused",
        result.hint or "pairing refused",
    )
