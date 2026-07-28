"""Migration release and version-floor gate for credential cutover (PRD 080 phase 26)."""

from __future__ import annotations

import importlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping

MANIFEST_REL: Final[str] = "scripts/_sw/credential-migration-release.json"
VERSION_FILE_REL: Final[str] = "version.txt"
VERSION_FLOOR_UNPUBLISHED_CODE: Final[str] = "migration-version-floor-unpublished"
TRANSPORTS_NOT_MIGRATED_CODE: Final[str] = "migration-transports-incomplete"


@dataclass(frozen=True, slots=True)
class MigrationReleaseManifest:
    version_floor: str
    published: bool
    enumerated_transports: tuple[dict[str, Any], ...]
    environment_shim: str
    removal_targets: dict[str, Any]


def repo_root(start: Path | None = None) -> Path:
    if start is not None:
        path = start.expanduser().resolve()
        if path.is_file():
            path = path.parent
        for candidate in (path, *path.parents):
            if (candidate / MANIFEST_REL).is_file():
                return candidate
    return Path(__file__).resolve().parents[2]


def manifest_path(root: Path | None = None) -> Path:
    return repo_root(root) / MANIFEST_REL


def load_manifest(root: Path | None = None) -> MigrationReleaseManifest:
    path = manifest_path(root)
    data = json.loads(path.read_text(encoding="utf-8"))
    return MigrationReleaseManifest(
        version_floor=str(data.get("versionFloor", "")).strip(),
        published=bool(data.get("published")),
        enumerated_transports=tuple(dict(item) for item in data.get("enumeratedTransports", [])),
        environment_shim=str(data.get("environmentShim", "")).strip(),
        removal_targets=dict(data.get("removalTargets") or {}),
    )


def parse_semver(text: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text.strip())
    if not match:
        raise ValueError(f"invalid semver: {text!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def published_version(root: Path | None = None) -> str:
    path = repo_root(root) / VERSION_FILE_REL
    return path.read_text(encoding="utf-8").strip()


def version_floor_satisfied(root: Path | None = None) -> bool:
    manifest = load_manifest(root)
    if not manifest.version_floor:
        return False
    current = parse_semver(published_version(root))
    floor = parse_semver(manifest.version_floor)
    return current >= floor


def is_version_floor_published(root: Path | None = None) -> bool:
    manifest = load_manifest(root)
    return manifest.published and version_floor_satisfied(root)


def _transport_migrated(spec: Mapping[str, Any]) -> bool:
    module_name = str(spec.get("module", "")).strip()
    attrs = tuple(str(item) for item in spec.get("brokerAttrs", []))
    if not module_name or not attrs:
        return False
    module = importlib.import_module(module_name)
    return any(hasattr(module, attr) for attr in attrs)


def enumerated_transports_migrated(root: Path | None = None) -> tuple[bool, tuple[str, ...]]:
    manifest = load_manifest(root)
    missing: list[str] = []
    for spec in manifest.enumerated_transports:
        module_name = str(spec.get("module", "")).strip() or "<unknown>"
        if not _transport_migrated(spec):
            missing.append(module_name)
    return (not missing, tuple(missing))


def migration_release_gate_open(root: Path | None = None) -> tuple[bool, str | None]:
    """Return (open, blocking_code) when env-read fail mode and alias removal are safe."""
    if not is_version_floor_published(root):
        return False, VERSION_FLOOR_UNPUBLISHED_CODE
    migrated, missing = enumerated_transports_migrated(root)
    if not migrated:
        return False, TRANSPORTS_NOT_MIGRATED_CODE
    return True, None


def env_read_enforcement_mode(root: Path | None = None) -> str:
    """Default env-read guard mode: fail only after the migration release gate opens."""
    open_gate, _ = migration_release_gate_open(root)
    return "fail" if open_gate else "warn"
