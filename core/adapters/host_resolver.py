"""Host adapter resolution with explicit unknown_host path (PRD 349 R18)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

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


def available_descriptors(
    capabilities_dir: Path | None = None,
) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Map adapter/host id → (path, descriptor) for JSON capability files."""
    root = capabilities_dir or _CAPABILITIES_DIR
    found: dict[str, tuple[Path, dict[str, Any]]] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.glob("*.json")):
        if path.name.endswith(".schema.json") or path.name == "capability.schema.json":
            continue
        data = _load_descriptor(path)
        if not data:
            continue
        adapter_id = str(data.get("adapter_id") or data.get("host") or path.stem).strip()
        host_id = str(data.get("host") or adapter_id).strip()
        if adapter_id:
            found[adapter_id] = (path, data)
        if host_id and host_id not in found:
            found[host_id] = (path, data)
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
