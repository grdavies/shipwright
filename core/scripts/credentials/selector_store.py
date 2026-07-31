"""Machine-local credential selector loader (PRD 080 phase 2 / R2)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from credentials.backends import BACKEND_NAMES
from credentials.selector_integrity import (
    IntegrityReport,
    check_selector_integrity,
    verify_selector_path,
)

SELECTOR_FILENAME = "credential-selector.json"
SELECTOR_RELATIVE = Path("shipwright") / SELECTOR_FILENAME
MANDATORY_SCOPE_FIELDS = ("allowedRepos", "allowedProjectIds", "allowedEndpoints")


class SelectorStoreError(Exception):
    """Fail-closed selector load error with a stable code and remediation hint."""

    def __init__(self, code: str, hint: str) -> None:
        self.code = code
        self.hint = hint
        super().__init__(f"{code}: {hint}")


@dataclass(frozen=True, slots=True)
class SelectorEntry:
    ref: str
    backend: str
    provider: str
    hostname: str | None
    account: str | None
    allowed_repos: tuple[str, ...]
    allowed_project_ids: tuple[str, ...]
    allowed_endpoints: tuple[str, ...]
    token_env: str | None = None


@dataclass(frozen=True, slots=True)
class SelectorDocument:
    version: int
    entries: dict[str, SelectorEntry]
    integrity: IntegrityReport
    path: Path


def trusted_user_root() -> Path:
    return Path.home().resolve()


def resolve_xdg_config_home(xdg_base: Path | None = None) -> Path:
    if xdg_base is not None:
        return validate_trusted_xdg_base(xdg_base)
    env = os.environ.get("XDG_CONFIG_HOME", "").strip()
    if env:
        return validate_trusted_xdg_base(Path(env).expanduser())
    return trusted_user_root() / ".config"


def validate_trusted_xdg_base(xdg_base: Path) -> Path:
    resolved = xdg_base.expanduser().resolve()
    home = trusted_user_root()
    if resolved != home and home not in resolved.parents:
        raise SelectorStoreError(
            "selector-untrusted-xdg-base",
            "XDG config base must resolve under the trusted user-owned home directory",
        )
    return resolved


def default_selector_path(*, xdg_base: Path | None = None) -> Path:
    return resolve_xdg_config_home(xdg_base) / SELECTOR_RELATIVE


def _normalize_scope(values: Any, *, field: str, ref: str) -> tuple[str, ...]:
    if not isinstance(values, list) or not values:
        code = {
            "allowedRepos": "selector-missing-allowed-repos",
            "allowedProjectIds": "selector-missing-allowed-project-ids",
            "allowedEndpoints": "selector-missing-allowed-endpoints",
        }[field]
        raise SelectorStoreError(
            code,
            f"selector entry {ref!r} must declare non-empty {field}",
        )
    normalized: list[str] = []
    for item in values:
        if not isinstance(item, str) or not item.strip():
            raise SelectorStoreError(
                code,
                f"selector entry {ref!r} must declare non-empty {field}",
            )
        normalized.append(item.strip())
    return tuple(normalized)


def _parse_entry(ref: str, raw: Any) -> SelectorEntry:
    if not isinstance(raw, dict):
        raise SelectorStoreError(
            "selector-invalid-entry",
            f"selector entry {ref!r} must be an object",
        )
    backend = raw.get("backend")
    if not isinstance(backend, str) or backend not in BACKEND_NAMES:
        raise SelectorStoreError(
            "selector-unknown-backend",
            f"selector entry {ref!r} uses an unknown backend; expected one of {', '.join(BACKEND_NAMES)}",
        )
    for field in MANDATORY_SCOPE_FIELDS:
        if field not in raw:
            code = {
                "allowedRepos": "selector-missing-allowed-repos",
                "allowedProjectIds": "selector-missing-allowed-project-ids",
                "allowedEndpoints": "selector-missing-allowed-endpoints",
            }[field]
            raise SelectorStoreError(
                code,
                f"selector entry {ref!r} must declare {field}",
            )
    provider = raw.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise SelectorStoreError(
            "selector-invalid-entry",
            f"selector entry {ref!r} must declare provider",
        )
    hostname = raw.get("hostname")
    account = raw.get("account")
    token_env = raw.get("tokenEnv")
    return SelectorEntry(
        ref=ref,
        backend=backend,
        provider=provider.strip(),
        hostname=hostname.strip() if isinstance(hostname, str) and hostname.strip() else None,
        account=account.strip() if isinstance(account, str) and account.strip() else None,
        allowed_repos=_normalize_scope(raw.get("allowedRepos"), field="allowedRepos", ref=ref),
        allowed_project_ids=_normalize_scope(
            raw.get("allowedProjectIds"),
            field="allowedProjectIds",
            ref=ref,
        ),
        allowed_endpoints=_normalize_scope(
            raw.get("allowedEndpoints"),
            field="allowedEndpoints",
            ref=ref,
        ),
        token_env=token_env.strip() if isinstance(token_env, str) and token_env.strip() else None,
    )


def _parse_document(
    raw: Any,
    *,
    path: Path,
    previous_digests: dict[str, str] | None,
    skip_integrity: bool,
) -> SelectorDocument:
    if not isinstance(raw, dict):
        raise SelectorStoreError(
            "selector-invalid-json",
            "selector document must be a JSON object",
        )
    version = raw.get("version")
    if version != 1:
        raise SelectorStoreError(
            "selector-invalid-version",
            "selector document version must be 1",
        )
    entries_raw = raw.get("entries")
    if not isinstance(entries_raw, dict) or not entries_raw:
        raise SelectorStoreError(
            "selector-empty",
            "selector document must contain at least one entry",
        )
    entries = {ref: _parse_entry(ref, entry) for ref, entry in entries_raw.items()}
    if skip_integrity:
        integrity = IntegrityReport(verdict="skipped")
    else:
        integrity = check_selector_integrity(path, previous_digests=previous_digests)
    return SelectorDocument(version=version, entries=entries, integrity=integrity, path=path)


def load_selector_store(
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
    previous_digests: dict[str, str] | None = None,
    skip_integrity: bool = False,
) -> SelectorDocument:
    if xdg_base is not None:
        validate_trusted_xdg_base(xdg_base)
    selector_path = (path or default_selector_path(xdg_base=xdg_base)).expanduser()
    if skip_integrity:
        if not selector_path.exists():
            raise SelectorStoreError(
                "selector-absent",
                "create the machine-local selector file under your trusted config directory",
            )
    else:
        try:
            verify_selector_path(selector_path)
        except Exception as exc:
            if hasattr(exc, "code") and hasattr(exc, "hint"):
                raise SelectorStoreError(exc.code, exc.hint) from exc
            raise
    try:
        raw = json.loads(selector_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectorStoreError(
            "selector-invalid-json",
            "selector document must be valid JSON",
        ) from exc
    return _parse_document(
        raw,
        path=selector_path,
        previous_digests=previous_digests,
        skip_integrity=skip_integrity,
    )
