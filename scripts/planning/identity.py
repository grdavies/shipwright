"""Unit identity and project-key resolution (PRD 082 phase 11 / R27)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from host_lib import load_workflow_config, parse_owner_repo, remote_name, resolve_provider

PROJECT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
PROJECT_KEY_REGISTRY = ".cursor/hooks/state/issue-store-project-keys.json"
LEGACY_UNIT_MAP_PATH = ".cursor/hooks/state/issue-store-legacy-unit-map.json"
NATIVE_UNIT_ID_PREFIX: dict[str, str] = {
    "github-issues": "gh:",
    "jira": "jira:",
    "gitlab-issues": "gl:",
}
NATIVE_UNIT_ID_PATTERN = re.compile(r"^(gh|jira|gl):(\d+)$")
BARE_INTEGER_UNIT_ID = re.compile(r"^\d{3}$")
DECISION_ISSUE_TYPE_LABEL = "sw:decision"
DECISION_ARTIFACT_TYPE = "decision"
DECISION_GRAPH_FILENAME = "decision-graph.json"
DECISION_GRAPH_UNIT_SUFFIX = "-decision-graph"


def store_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning")
    if not isinstance(planning, dict):
        return {}
    store = planning.get("store")
    return store if isinstance(store, dict) else {}


def resolve_store_location(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    store = store_section(cfg)
    loc = store.get("storeLocation")
    mode = "same-repo"
    if isinstance(loc, dict):
        raw_mode = loc.get("mode")
        if isinstance(raw_mode, str) and raw_mode in {"same-repo", "separate-project"}:
            mode = raw_mode

    if mode == "same-repo":
        host = resolve_provider(root)
        remote = host.get("remote") if isinstance(host.get("remote"), str) else remote_name(cfg)
        owner_repo = parse_owner_repo(host.get("remoteUrl") if isinstance(host.get("remoteUrl"), str) else None)
        owner, repo = (owner_repo if owner_repo else (None, None))
        return {
            "verdict": "ok",
            "mode": "same-repo",
            "remote": remote,
            "owner": owner,
            "repo": repo,
            "hostProvider": host.get("provider"),
        }

    if not isinstance(loc, dict):
        return {"verdict": "fail", "error": "storeLocation required for separate-project mode"}
    owner = loc.get("owner")
    repo = loc.get("repo")
    if not isinstance(owner, str) or not owner.strip() or not isinstance(repo, str) or not repo.strip():
        return {"verdict": "fail", "error": "storeLocation.owner and storeLocation.repo required for separate-project"}
    remote = loc.get("remote")
    remote_name_out = remote.strip() if isinstance(remote, str) and remote.strip() else "origin"
    return {
        "verdict": "ok",
        "mode": "separate-project",
        "remote": remote_name_out,
        "owner": owner.strip(),
        "repo": repo.strip(),
    }


def store_location_fingerprint(location: dict[str, Any]) -> str:
    mode = location.get("mode", "same-repo")
    owner = location.get("owner") or ""
    repo = location.get("repo") or ""
    return f"{mode}:{owner}/{repo}"


def load_project_key_registry(root: Path) -> dict[str, Any]:
    path = root / PROJECT_KEY_REGISTRY
    if not path.is_file():
        return {"version": 1, "keys": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "keys": {}}
    if not isinstance(data, dict):
        return {"version": 1, "keys": {}}
    keys = data.get("keys")
    if not isinstance(keys, dict):
        data["keys"] = {}
    return data


def validate_project_key(root: Path, cfg: dict[str, Any], *, register: bool = False) -> dict[str, Any]:
    store = store_section(cfg)
    raw_key = store.get("projectKey")
    if not isinstance(raw_key, str) or not raw_key.strip():
        return {"verdict": "fail", "error": "missing-project-key", "message": "planning.store.projectKey is required for issue-store"}
    project_key = raw_key.strip()
    if not PROJECT_KEY_PATTERN.fullmatch(project_key):
        return {
            "verdict": "fail",
            "error": "invalid-project-key",
            "projectKey": project_key,
            "message": "projectKey must match ^[a-z][a-z0-9-]*$",
        }

    location = resolve_store_location(root, cfg)
    if location.get("verdict") != "ok":
        return location
    fingerprint = store_location_fingerprint(location)
    registry = load_project_key_registry(root)
    keys: dict[str, Any] = registry.setdefault("keys", {})
    existing = keys.get(project_key)
    if isinstance(existing, dict):
        existing_fp = existing.get("storeFingerprint")
        if isinstance(existing_fp, str) and existing_fp != fingerprint:
            return {
                "verdict": "fail",
                "error": "project-key-collision",
                "projectKey": project_key,
                "existingFingerprint": existing_fp,
                "requestedFingerprint": fingerprint,
                "message": "project key already registered for a different store location; choose a namespaced key",
            }

    if register and not existing:
        keys[project_key] = {
            "storeFingerprint": fingerprint,
            "mode": location.get("mode"),
            "owner": location.get("owner"),
            "repo": location.get("repo"),
        }
        reg_path = root / PROJECT_KEY_REGISTRY
        reg_path.parent.mkdir(parents=True, exist_ok=True)
        reg_path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "verdict": "ok",
        "projectKey": project_key,
        "storeFingerprint": fingerprint,
        "registered": bool(existing) or register,
    }


def native_unit_id_prefix(provider: str) -> str:
    return NATIVE_UNIT_ID_PREFIX.get(provider, f"{provider}:")


def format_native_unit_id(provider: str, issue_number: int) -> str:
    """R19 — namespaced provider-native unit id (e.g. gh:352)."""
    return f"{native_unit_id_prefix(provider)}{issue_number}"


def is_namespaced_native_unit_id(unit_id: str) -> bool:
    return bool(NATIVE_UNIT_ID_PATTERN.match((unit_id or "").strip()))


def is_bare_integer_unit_id(unit_id: str) -> bool:
    """Detect bare PRD numbers like 061 that collide with sequential ids (R19)."""
    return bool(BARE_INTEGER_UNIT_ID.match((unit_id or "").strip()))


def reject_bare_integer_unit_id(unit_id: str) -> None:
    if is_bare_integer_unit_id(unit_id):
        from planning_store import fail

        fail(
            "bare-integer-unit-id-collision",
            code="bare-integer-unit-id",
            unitId=unit_id,
        )


def load_legacy_unit_map(root: Path) -> dict[str, str]:
    path = root / LEGACY_UNIT_MAP_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    mapping = data.get("legacyToNative") if isinstance(data, dict) else None
    if not isinstance(mapping, dict):
        return {}
    return {str(k): str(v) for k, v in mapping.items() if isinstance(k, str) and isinstance(v, str)}


def save_legacy_unit_map(root: Path, mapping: dict[str, str]) -> None:
    path = root / LEGACY_UNIT_MAP_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "legacyToNative": dict(sorted(mapping.items())),
        "nativeToLegacy": {v: k for k, v in sorted(mapping.items())},
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def register_legacy_unit_mapping(root: Path, legacy_id: str, native_id: str) -> None:
    if not legacy_id or not native_id or legacy_id == native_id:
        return
    mapping = load_legacy_unit_map(root)
    mapping[legacy_id] = native_id
    save_legacy_unit_map(root, mapping)


def resolve_legacy_unit_id(root: Path, unit_id: str) -> str | None:
    return load_legacy_unit_map(root).get(unit_id)


def reverse_resolve_legacy_unit_id(root: Path, native_id: str) -> str | None:
    for legacy, native in load_legacy_unit_map(root).items():
        if native == native_id:
            return legacy
    return None


def decision_graph_unit_id(prd_unit_id: str) -> str:
    """Derive the DecisionGraph issue-store unit id for a PRD unit (PRD 280 R16)."""
    unit_id = (prd_unit_id or "").strip()
    if not unit_id:
        return ""
    if unit_id.endswith(DECISION_GRAPH_UNIT_SUFFIX):
        return unit_id
    return f"{unit_id}{DECISION_GRAPH_UNIT_SUFFIX}"


def decision_graph_virtual_body_path(unit_id: str) -> str:
    """Virtual body path for DecisionGraph JSON in separate-project issue-store (R17)."""
    uid = (unit_id or "").strip()
    if not uid:
        raise ValueError("decision-graph unit id required")
    return f"docs/planning/decision/{uid}/{DECISION_GRAPH_FILENAME}"


def decision_record_virtual_body_path(unit_id: str) -> str:
    """Virtual body path for markdown decision records."""
    uid = (unit_id or "").strip()
    if not uid:
        raise ValueError("decision unit id required")
    return f"docs/decisions/{uid}.md"


def is_decision_graph_body_path(body_path: str) -> bool:
    norm = body_path.replace("\\", "/").lower()
    return norm.endswith(f"/{DECISION_GRAPH_FILENAME}") or "/planning/decision/" in norm


def resolve_decision_put_path(unit_id: str, body_path: str) -> tuple[str, str]:
    """Normalize unit id + virtual path for decision artifact puts (fail-closed)."""
    uid = (unit_id or "").strip()
    rel = body_path.replace("\\", "/").lstrip("/") if body_path else ""
    if is_decision_graph_body_path(rel):
        if not uid:
            parts = rel.split("/")
            if len(parts) >= 3 and parts[-1] == DECISION_GRAPH_FILENAME:
                uid = parts[-2]
        if not uid:
            raise ValueError("decision-graph put requires unit id")
        return uid, decision_graph_virtual_body_path(uid)
    if rel.startswith("docs/decisions/"):
        if not uid:
            uid = Path(rel).stem
        return uid, decision_record_virtual_body_path(uid)
    if uid:
        return uid, decision_graph_virtual_body_path(uid)
    raise ValueError("decision put requires unit id or recognized virtual body path")


def unit_id_lookup_candidates(root: Path, unit_id: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in (
        unit_id,
        resolve_legacy_unit_id(root, unit_id),
        reverse_resolve_legacy_unit_id(root, unit_id),
    ):
        if candidate and candidate not in seen:
            seen.add(candidate)
            ordered.append(candidate)
    return ordered or [unit_id]
