"""Ownership, permission, symlink, and digest integrity for the selector file (PRD 080 R2)."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SELECTOR_FILE_MODE = 0o600
SELECTOR_DIR_MODE = 0o700
WINDOWS_REDUCED_REASON = (
    "POSIX ownership and permission checks are unavailable on this platform; "
    "presence and symlink checks still apply"
)


class SelectorIntegrityError(Exception):
    """Hard integrity failure for the machine-local selector file."""

    def __init__(self, code: str, hint: str) -> None:
        self.code = code
        self.hint = hint
        super().__init__(f"{code}: {hint}")


@dataclass(frozen=True, slots=True)
class PathVerificationResult:
    verdict: str
    posture: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    verdict: str
    warnings: tuple[str, ...] = ()
    posture: str | None = None
    reason: str | None = None


def _supports_posix_ownership_checks() -> bool:
    """True when POSIX uid/mode checks are meaningful on this platform."""
    return os.name == "posix"


def verify_selector_path(path: Path, *, uid: int | None = None) -> PathVerificationResult:
    """Fail closed on mode, ownership, or symlink violations."""
    if not path.exists():
        raise SelectorIntegrityError(
            "selector-absent",
            "create the machine-local selector file under your trusted config directory",
        )
    targets = [path]
    if path.parent != path:
        targets.append(path.parent)
    for current in targets:
        if current.is_symlink():
            raise SelectorIntegrityError(
                "selector-integrity-symlink",
                "selector file and parent directories must not be symlinks",
            )
    if not _supports_posix_ownership_checks():
        return PathVerificationResult(
            verdict="ok",
            posture="windows-reduced",
            reason=WINDOWS_REDUCED_REASON,
        )
    owner = os.getuid() if uid is None else uid
    for current in targets:
        stat = current.stat()
        if stat.st_uid != owner:
            raise SelectorIntegrityError(
                "selector-integrity-owner",
                "selector file and directories must be owned by the current user",
            )
        mode = stat.st_mode & 0o777
        if current == path:
            if mode != SELECTOR_FILE_MODE:
                raise SelectorIntegrityError(
                    "selector-integrity-file-mode",
                    f"selector file must be mode {oct(SELECTOR_FILE_MODE)}",
                )
        elif current.is_dir() and mode != SELECTOR_DIR_MODE:
            raise SelectorIntegrityError(
                "selector-integrity-dir-mode",
                f"selector parent directory must be mode {oct(SELECTOR_DIR_MODE)}",
            )
    return PathVerificationResult(verdict="ok")


def entry_content_digest(entry: dict[str, Any]) -> str:
    payload = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def entry_digests(document: dict[str, Any]) -> dict[str, str]:
    entries = document.get("entries")
    if not isinstance(entries, dict):
        return {}
    digests: dict[str, str] = {}
    for ref, entry in entries.items():
        if isinstance(ref, str) and isinstance(entry, dict):
            digests[ref] = entry_content_digest(entry)
    return digests


def digest_change_warnings(
    current: dict[str, str],
    previous: dict[str, str] | None,
) -> list[str]:
    if not previous:
        return []
    warnings: list[str] = []
    for ref, digest in current.items():
        prior = previous.get(ref)
        if prior is not None and prior != digest:
            warnings.append(f"selector-digest-changed:{ref}")
    return warnings


def check_selector_integrity(
    path: Path,
    *,
    previous_digests: dict[str, str] | None = None,
    uid: int | None = None,
) -> IntegrityReport:
    path_result = verify_selector_path(path, uid=uid)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise SelectorIntegrityError(
            "selector-invalid-json",
            "selector document must be a JSON object",
        )
    warnings = tuple(digest_change_warnings(entry_digests(raw), previous_digests))
    return IntegrityReport(
        verdict="ok",
        warnings=warnings,
        posture=path_result.posture,
        reason=path_result.reason,
    )
