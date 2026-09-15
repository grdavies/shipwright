"""PRD 356 D3 — packaged provider-conformance host-bundle search roots."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CONFORMANCE_FIXTURES_REL = Path("scripts/test/fixtures/planning-provider-conformance")
PACKAGED_CONFORMANCE_REL = Path("core/sw-reference/provider-conformance")
PACKAGED_DIST_IDS: tuple[str, ...] = ("cursor", "claude-code", "codex", "opencode")
_HOST_ENV_KEYS: dict[str, str] = {
    "cursor": "CURSOR_PLUGIN_ROOT",
    "claude-code": "CLAUDE_PLUGIN_ROOT",
    "codex": "CODEX_PLUGIN_ROOT",
    "opencode": "OPENCODE_PLUGIN_ROOT",
}
_HOST_PLUGIN_MARKERS: dict[str, tuple[str, ...]] = {
    "cursor": (".cursor-plugin/plugin.json",),
    "claude-code": (".claude-plugin/plugin.json",),
    "codex": (".codex-plugin/plugin.json",),
    "opencode": ("opencode.plugin.json",),
}


def normalize_host_id(host: str | None) -> str | None:
    if not host:
        return None
    norm = host.strip().lower().replace("_", "-")
    return norm if norm in PACKAGED_DIST_IDS else None


def host_id_from_bundle(bundle: Path) -> str | None:
    resolved = bundle.resolve()
    for host_id, markers in _HOST_PLUGIN_MARKERS.items():
        if any((resolved / marker).is_file() for marker in markers):
            return host_id
    if resolved.parent.name == "dist" and resolved.name in PACKAGED_DIST_IDS:
        return resolved.name
    return None


def is_host_bundle(path: Path) -> bool:
    resolved = path.resolve()
    if (resolved / PACKAGED_CONFORMANCE_REL).is_dir():
        return True
    return host_id_from_bundle(resolved) is not None


def resolve_package_root(start: Path | None = None) -> Path:
    """Resolve the Shipwright package root (wheel ``sw/`` tree or source checkout)."""
    candidate = (start or Path(__file__).resolve().parent.parent).resolve()
    if candidate.parent.name == "dist" and candidate.name in PACKAGED_DIST_IDS:
        return candidate.parent.parent
    dist = candidate / "dist"
    if dist.is_dir() and any((dist / host_id).is_dir() for host_id in PACKAGED_DIST_IDS):
        return candidate
    for env_key in _HOST_ENV_KEYS.values():
        val = os.environ.get(env_key, "").strip()
        if not val:
            continue
        env_path = Path(val).expanduser().resolve()
        if env_path.parent.name == "dist" and env_path.name in PACKAGED_DIST_IDS:
            return env_path.parent.parent
        if is_host_bundle(env_path):
            return env_path
    return candidate


def resolve_active_host_id(
    package_root: Path,
    *,
    active_host: str | None = None,
) -> str | None:
    """Resolve the active integration host for D3 packaged conformance search."""
    explicit = normalize_host_id(active_host)
    if explicit:
        return explicit
    pkg = package_root.resolve()
    script_parent = Path(__file__).resolve().parent.parent
    if script_parent.parent.name == "dist" and script_parent.name in PACKAGED_DIST_IDS:
        if script_parent.parent.parent.resolve() == pkg or pkg == script_parent.resolve():
            return script_parent.name
    for host_id, env_key in _HOST_ENV_KEYS.items():
        val = os.environ.get(env_key, "").strip()
        if not val:
            continue
        env_path = Path(val).expanduser().resolve()
        expected = (pkg / "dist" / host_id).resolve()
        if env_path == expected:
            return host_id
        if host_id_from_bundle(env_path) == host_id:
            return host_id
    return host_id_from_bundle(pkg)


def _conformance_record_in_bundle(bundle: Path, filename: str) -> Path | None:
    candidate = (bundle / PACKAGED_CONFORMANCE_REL / filename).resolve()
    return candidate if candidate.is_file() else None


def _active_host_bundle(package_root: Path, host_id: str) -> Path | None:
    pkg = package_root.resolve()
    active = pkg / "dist" / host_id
    if active.is_dir():
        return active
    if host_id_from_bundle(pkg) == host_id:
        return pkg
    return None


def resolve_conformance_fixture_path(
    root: Path,
    filename: str,
    *,
    package_root: Path | None = None,
    active_host: str | None = None,
) -> Path | None:
    """Locate recorded evidence — source checkout paths then D3 packaged host bundles."""
    for rel in (CONFORMANCE_FIXTURES_REL, PACKAGED_CONFORMANCE_REL):
        candidate = (root / rel / filename).resolve()
        if candidate.is_file():
            return candidate
    return _resolve_packaged_conformance_fixture_path(
        root,
        filename,
        package_root=package_root,
        active_host=active_host,
    )


def _resolve_packaged_conformance_fixture_path(
    root: Path,
    filename: str,
    *,
    package_root: Path | None = None,
    active_host: str | None = None,
) -> Path | None:
    pkg = (package_root or resolve_package_root(root)).resolve()
    host = resolve_active_host_id(pkg, active_host=active_host)
    if host is None:
        return _conformance_record_in_bundle(pkg, filename) if is_host_bundle(pkg) else None

    active_bundle = _active_host_bundle(pkg, host)
    if active_bundle is None:
        return None

    active_hit = _conformance_record_in_bundle(active_bundle, filename)
    if active_hit is not None:
        return active_hit

    for host_id in PACKAGED_DIST_IDS:
        if host_id == host:
            continue
        sibling = pkg / "dist" / host_id
        if not sibling.is_dir():
            continue
        sibling_hit = _conformance_record_in_bundle(sibling, filename)
        if sibling_hit is not None:
            return sibling_hit
    return None


def provider_fixture_slug(provider: str) -> str:
    return provider.replace("-issues", "")


def conformance_fixture_path(root: Path, provider: str) -> Path:
    slug = provider_fixture_slug(provider)
    return (root / CONFORMANCE_FIXTURES_REL / f"{slug}.ok.json").resolve()


def load_conformance_record(
    root: Path,
    provider: str,
    *,
    package_root: Path | None = None,
    active_host: str | None = None,
) -> dict[str, Any]:
    slug = provider_fixture_slug(provider)
    path = resolve_conformance_fixture_path(
        root,
        f"{slug}.ok.json",
        package_root=package_root,
        active_host=active_host,
    )
    if path is None:
        path = conformance_fixture_path(root, provider)
    if not path.is_file():
        return {
            "verdict": "fail",
            "provider": provider,
            "error": "missing-conformance-record",
            "fixturePath": str(path),
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "verdict": "fail",
            "provider": provider,
            "error": "invalid-conformance-record",
            "fixturePath": str(path),
            "message": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "verdict": "fail",
            "provider": provider,
            "error": "invalid-conformance-record",
            "fixturePath": str(path),
        }
    payload.setdefault("provider", provider)
    payload.setdefault("fixturePath", str(path))
    return payload


def _provider_docs_gate_green(root: Path, provider: str) -> bool:
    if provider != "notion":
        return True
    try:
        from planning_notion_client import docs_gate

        return docs_gate(root).get("verdict") == "ok"
    except Exception:  # noqa: BLE001 — fail closed; never break import-time shipped resolution
        return False


def providers_with_green_conformance(
    root: Path,
    *,
    package_root: Path | None = None,
    active_host: str | None = None,
) -> frozenset[str]:
    from planning.provider_conformance import (
        CONFORMANCE_GATED_PROVIDERS,
        DOCS_GATED_PROVIDERS,
        conformance_dimensions_green,
    )

    pkg = package_root or resolve_package_root(root)
    shipped: set[str] = set()
    for provider in sorted(CONFORMANCE_GATED_PROVIDERS):
        record = load_conformance_record(
            root,
            provider,
            package_root=pkg,
            active_host=active_host,
        )
        if conformance_dimensions_green(record):
            if provider in DOCS_GATED_PROVIDERS and not _provider_docs_gate_green(root, provider):
                continue
            shipped.add(provider)
    return frozenset(shipped)
