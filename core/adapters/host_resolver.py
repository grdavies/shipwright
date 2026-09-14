"""Host adapter resolution with explicit unknown_host path (PRD 349 R18)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CAPABILITIES_DIR = _REPO_ROOT / "core" / "schemas" / "capabilities"


@dataclass(frozen=True)
class HostResolution:
    """Successful host → adapter binding."""

    host_id: str
    adapter_id: str
    descriptor: Mapping[str, Any]
    descriptor_path: Path


@dataclass(frozen=True)
class UnknownHostDiagnostic:
    """Structured diagnostic when no descriptor matches the runtime host."""

    host_id: str
    available_adapter_ids: tuple[str, ...]
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": "unknown_host",
            "host_id": self.host_id,
            "available_adapter_ids": list(self.available_adapter_ids),
            "message": self.message,
        }


class UnknownHostError(RuntimeError):
    """Raised when the runtime host has no matching capability descriptor."""

    def __init__(self, diagnostic: UnknownHostDiagnostic) -> None:
        super().__init__(diagnostic.message)
        self.diagnostic = diagnostic


def _load_descriptor(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _load_descriptor_entries(path: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Load one or more capability descriptors from a JSON object or array (R24)."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        return [(path, data)]
    if isinstance(data, list):
        return [(path, row) for row in data if isinstance(row, dict)]
    return []


def available_descriptors(
    capabilities_dir: Path | None = None,
) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Map adapter/host id → (path, descriptor) for JSON capability files.

    Multi-surface files may be a JSON array (PRD 349 R24). Plain adapter/host
    keys prefer the ``cli`` surface when present; every surface is also keyed as
    ``{adapter_id}:{surface}``.
    """
    root = capabilities_dir or _CAPABILITIES_DIR
    found: dict[str, tuple[Path, dict[str, Any]]] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.json")):
        if path.name.endswith(".schema.json") or path.name == "capability.schema.json":
            continue
        entries = _load_descriptor_entries(path)
        # Prefer cli when assigning the bare adapter/host key.
        ordered = sorted(
            entries,
            key=lambda item: 0 if str(item[1].get("surface") or "") == "cli" else 1,
        )
        for file_path, data in ordered:
            adapter_id = str(data.get("adapter_id") or data.get("host") or path.stem).strip()
            host_id = str(data.get("host") or adapter_id).strip()
            surface = str(data.get("surface") or "").strip()
            if adapter_id and adapter_id not in found:
                found[adapter_id] = (file_path, data)
            if host_id and host_id not in found:
                found[host_id] = (file_path, data)
            if adapter_id and surface:
                found[f"{adapter_id}:{surface}"] = (file_path, data)
            if host_id and surface and f"{host_id}:{surface}" not in found:
                found[f"{host_id}:{surface}"] = (file_path, data)
    return found


def resolve_host(
    host_id: str,
    *,
    capabilities_dir: Path | None = None,
) -> HostResolution:
    """Resolve *host_id* to a capability descriptor or raise UnknownHostError.

    Exhaustive match over known hosts; unknown ids never fall through to Cursor.
    """
    host = str(host_id or "").strip()
    catalog = available_descriptors(capabilities_dir)
    available = tuple(sorted(catalog))

    match host:
        case "":
            diagnostic = UnknownHostDiagnostic(
                host_id=host,
                available_adapter_ids=available,
                message="unknown_host: empty host id; available adapters: "
                + (", ".join(available) if available else "(none)"),
            )
            print(json.dumps(diagnostic.as_dict()), file=sys.stderr)
            raise UnknownHostError(diagnostic)
        case known if known in catalog:
            path, descriptor = catalog[known]
            adapter_id = str(descriptor.get("adapter_id") or known)
            return HostResolution(
                host_id=known,
                adapter_id=adapter_id,
                descriptor=descriptor,
                descriptor_path=path,
            )
        case _:
            diagnostic = UnknownHostDiagnostic(
                host_id=host,
                available_adapter_ids=available,
                message=(
                    f"unknown_host: no capability descriptor for host {host!r}; "
                    "available adapters: "
                    + (", ".join(available) if available else "(none)")
                ),
            )
            print(json.dumps(diagnostic.as_dict()), file=sys.stderr)
            raise UnknownHostError(diagnostic)


def dispatch_host_adapter(host_id: str) -> str:
    """Return adapter_id for *host_id* using exhaustive match (TR4).

    Raises NotImplementedError for hosts that are not in the built-in dispatch
    table (distinct from UnknownHostError when the descriptor catalog misses).
    """
    host = str(host_id or "").strip()
    match host:
        case "cursor":
            return "cursor"
        case "claude-code":
            return "claude-code"
        case "codex":
            return "codex"
        case "opencode":
            return "opencode"
        case _:
            raise NotImplementedError(host)


AUTH_VALID = "valid"
AUTH_REVOKED = "revoked"
AUTH_UNKNOWN = "unknown"
AUTH_STATUSES = frozenset({AUTH_VALID, AUTH_REVOKED, AUTH_UNKNOWN})

MISSING_CAPABILITY_ERROR = "destination:missing-capability"
AUTH_REVOKED_ERROR = "destination:auth-revoked"


@dataclass(frozen=True)
class QualifiedHost:
    """Live destination qualification (PRD 352 R10 / TR3)."""

    host_id: str
    surface_adapter: str
    installed_version: str
    capabilities: Mapping[str, Any]
    auth_status: str


class DestinationValidationError(RuntimeError):
    """Fail-closed destination qualification (PRD 352 R12)."""

    def __init__(
        self,
        code: str,
        *,
        remediation: str,
        host_id: str = "",
        detail: str = "",
    ) -> None:
        super().__init__(code)
        self.code = code
        self.remediation = remediation
        self.host_id = host_id
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "verdict": "fail",
            "error": self.code,
            "remediation": self.remediation,
        }
        if self.host_id:
            payload["host_id"] = self.host_id
        if self.detail:
            payload["detail"] = self.detail
        return payload


def detect_runtime_host_id(environ: Mapping[str, str] | None = None) -> str:
    """Detect the current host id from process environment (legacy detect-platform)."""
    env = environ if environ is not None else os.environ
    platform = str(env.get("SW_SETUP_PLATFORM") or "").strip()
    if not platform:
        if env.get("CURSOR_AGENT") or env.get("CURSOR_PLUGIN_ROOT"):
            platform = "cursor"
        elif (
            env.get("CLAUDE_CODE")
            or env.get("CLAUDE_CODE_SSE_PORT")
            or env.get("CLAUDE_PLUGIN_ROOT")
        ):
            platform = "claude-code"
        else:
            platform = "cursor"
    return platform


def _read_installed_version(repo_root: Path | None = None) -> str:
    root = repo_root or _REPO_ROOT
    for rel in (
        Path("dist/cursor/.cursor-plugin/plugin.json"),
        Path("dist/claude-code/.claude-plugin/plugin.json"),
        Path(".cursor-plugin/plugin.json"),
    ):
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("version"):
            return str(data["version"]).strip()
    return "unknown"


def _capability_supported(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    mode = str(entry.get("implementation_mode") or "").strip()
    return mode not in {"", "unsupported"}


def _read_auth_status(environ: Mapping[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    raw = str(env.get("SW_HOST_AUTH_STATUS") or AUTH_VALID).strip().lower()
    if raw in AUTH_STATUSES:
        return raw
    return AUTH_UNKNOWN


def resolve(
    host_id: str | None = None,
    *,
    required_capabilities: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
    capabilities_dir: Path | None = None,
    installed_version: str | None = None,
    repo_root: Path | None = None,
) -> QualifiedHost:
    """Qualify the destination host from live inputs — never a cached session snapshot (R10/R13)."""
    env = environ if environ is not None else os.environ
    detected = str(host_id or "").strip() or detect_runtime_host_id(env)
    try:
        binding = resolve_host(detected, capabilities_dir=capabilities_dir)
    except UnknownHostError as exc:
        raise DestinationValidationError(
            "destination:unknown-host",
            host_id=detected,
            detail=exc.diagnostic.message,
            remediation="Install a capability descriptor for the destination host or pass a known host id.",
        ) from exc

    caps = dict(binding.descriptor.get("capabilities") or {})
    required = [str(item).strip() for item in (required_capabilities or ()) if str(item).strip()]
    missing = [
        name
        for name in required
        if name not in caps or not _capability_supported(caps.get(name))
    ]
    if missing:
        raise DestinationValidationError(
            MISSING_CAPABILITY_ERROR,
            host_id=binding.host_id,
            detail=",".join(missing),
            remediation=(
                f"Enable capability {missing[0]!r} on host {binding.host_id!r} "
                "or pick a destination whose descriptor declares it."
            ),
        )

    auth = _read_auth_status(env)
    if auth == AUTH_REVOKED:
        raise DestinationValidationError(
            AUTH_REVOKED_ERROR,
            host_id=binding.host_id,
            remediation=(
                "Re-authenticate the destination host adapter, then re-run host qualification "
                "(auth is never reused from a prior session)."
            ),
        )

    version = str(
        installed_version
        if installed_version is not None
        else env.get("SW_HOST_INSTALLED_VERSION") or _read_installed_version(repo_root)
    ).strip() or "unknown"
    surface = str(
        binding.descriptor.get("adapter_id")
        or binding.adapter_id
        or binding.host_id
    )
    return QualifiedHost(
        host_id=binding.host_id,
        surface_adapter=surface,
        installed_version=version,
        capabilities=MappingProxyType(caps),
        auth_status=auth,
    )


def requalify(
    host_id: str | None = None,
    **kwargs: Any,
) -> QualifiedHost:
    """Re-evaluate destination qualification at switch time (PRD 352 R13)."""
    return resolve(host_id, **kwargs)
