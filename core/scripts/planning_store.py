#!/usr/bin/env python3
"""PRD 034 Phase 3 + PRD 043 Phase 1–2 — planning.store interface + issue-store."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from host_lib import (
    github_api_base,
    git_remote_url,
    gitlab_api_base,
    host_section,
    load_workflow_config,
    parse_owner_repo,
    remote_name,
    resolve_provider,
    token_present,
)
from memory_sot import resolve_memory_provider

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_BACKEND = "in-repo-public"
SHIPPED_BACKENDS = frozenset({"in-repo-public", "local-synced", "memory", "issue-store"})
DEFERRED_BACKENDS = frozenset({"private-repo", "encryption-at-rest"})
ALL_BACKENDS = SHIPPED_BACKENDS | DEFERRED_BACKENDS

ISSUES_PROVIDERS = frozenset({"github-issues", "gitlab-issues", "jira", "none"})
SHIPPED_ISSUES_PROVIDERS = frozenset({"github-issues", "gitlab-issues"})

DEFAULT_ISSUES_TOKEN_ENV: dict[str, str] = {
    "github-issues": "ISSUES_GITHUB_TOKEN",
    "gitlab-issues": "ISSUES_GITLAB_TOKEN",
    "jira": "ISSUES_JIRA_TOKEN",
    "none": "",
}

MIN_ISSUES_SCOPES: dict[str, list[str]] = {
    "github-issues": ["repo"],
    "gitlab-issues": ["api"],
    "jira": ["read:jira-work", "write:jira-work"],
}

ISSUE_STORE_FALLBACK_NOTICE = (
    "issue-store configured but effective backend is in-repo-public "
    "(issuesProvider none/unsupported or host.provider none)"
)

PROJECT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
PROJECT_KEY_REGISTRY = ".cursor/hooks/state/issue-store-project-keys.json"
ISSUE_UNIT_INDEX = ".cursor/hooks/state/issue-store-unit-index.json"

from issues_lib import (  # noqa: E402
    IssueCapabilityError,
    IssueNotFound,
    IssueRevisionConflict,
    IssuesClient,
)
from planning_canonical import (  # noqa: E402
    IssueSnapshot,
    canonical_hash,
    chunk_body_if_needed,
    compose_issue_body,
    infer_artifact_type,
    parse_edges_block,
    project_label,
    reconcile_edges,
    reassemble_body,
    strip_markers_and_edges,
    title_prefix,
    type_label,
    verify_project_scope,
    verify_unit_id,
)

BANNED_MEMORY_CLASSES = frozenset({"discussion", "progress"})
RAW_TRANSCRIPT_MARKERS = (
    re.compile(r"(?i)\buser:\s"),
    re.compile(r"(?i)\bassistant:\s"),
    re.compile(r"(?i)\braw transcript\b"),
    re.compile(r"(?i)\bagent transcript\b"),
)

CLOUD_SYNC_ROOTS = (
    "Dropbox",
    "Library/Mobile Documents/com~apple~CloudDocs",
    "OneDrive",
    "Google Drive",
)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def git_root(start: Path | None = None) -> Path:
    cwd = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def planning_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning")
    return planning if isinstance(planning, dict) else {}


def store_section(cfg: dict[str, Any]) -> dict[str, Any]:
    store = planning_section(cfg).get("store")
    return store if isinstance(store, dict) else {}


def issues_section(cfg: dict[str, Any]) -> dict[str, Any]:
    issues = store_section(cfg).get("issues")
    return issues if isinstance(issues, dict) else {}


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def log_operation(
    op: str,
    unit_id: str,
    body_path: str,
    content: str | None,
    backend: str,
    *,
    stream: Any = None,
    notice: str | None = None,
) -> None:
    digest = content_hash(content) if content is not None else "none"
    payload: dict[str, Any] = {
        "planningStore": True,
        "op": op,
        "unitId": unit_id,
        "path": body_path,
        "hash": digest,
        "backend": backend,
    }
    if notice:
        payload["notice"] = notice
    line = json.dumps(payload, ensure_ascii=False)
    target = stream if stream is not None else sys.stderr
    print(line, file=target)


def redact_content(content: str) -> str:
    proc = subprocess.run(
        [str(SCRIPT_DIR / "memory-redact.py")],
        input=content,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or "memory-redact failed", code="redact-failed")
    return proc.stdout


def contains_raw_transcript(content: str) -> bool:
    return any(marker.search(content) for marker in RAW_TRANSCRIPT_MARKERS)


def resolve_issues_provider(cfg: dict[str, Any]) -> dict[str, Any]:
    store = store_section(cfg)
    configured = store.get("issuesProvider")
    if not isinstance(configured, str) or not configured.strip():
        return {
            "verdict": "ok",
            "provider": "none",
            "configured": None,
            "supported": False,
            "shipped": False,
        }
    provider = configured.strip()
    supported = provider in ISSUES_PROVIDERS
    shipped = provider in SHIPPED_ISSUES_PROVIDERS
    if not supported:
        return {
            "verdict": "ok",
            "provider": provider,
            "configured": provider,
            "supported": False,
            "shipped": False,
        }
    return {
        "verdict": "ok",
        "provider": provider,
        "configured": provider,
        "supported": True,
        "shipped": shipped,
    }


def resolve_issues_token_env(cfg: dict[str, Any], issues_provider: str) -> str:
    issues = issues_section(cfg)
    token_env = issues.get("tokenEnv")
    if isinstance(token_env, str) and token_env.strip():
        return token_env.strip()
    return DEFAULT_ISSUES_TOKEN_ENV.get(issues_provider, "")


def issue_store_fallback_reason(root: Path, cfg: dict[str, Any], *, override: str | None = None) -> str | None:
    configured = resolve_backend_id(cfg, override=override)
    if configured != "issue-store":
        return None
    issues = resolve_issues_provider(cfg)
    if issues["provider"] in {"none", ""} or not issues.get("supported"):
        return "issues-provider-none-or-unsupported"
    if issues["provider"] not in SHIPPED_ISSUES_PROVIDERS:
        return "issues-provider-not-shipped"
    host = resolve_provider(root)
    if host.get("verdict") != "ok" or host.get("provider") == "none":
        return "host-provider-none"
    return None


def resolve_effective_backend(root: Path, cfg: dict[str, Any], *, override: str | None = None) -> dict[str, Any]:
    configured = resolve_backend_id(cfg, override=override)
    fallback_reason = issue_store_fallback_reason(root, cfg, override=override) if configured == "issue-store" else None
    if fallback_reason:
        return {
            "verdict": "ok",
            "configured": configured,
            "backend": DEFAULT_BACKEND,
            "effective": DEFAULT_BACKEND,
            "fallback": True,
            "fallbackReason": fallback_reason,
            "notice": ISSUE_STORE_FALLBACK_NOTICE,
            "shipped": True,
            "deferred": False,
        }
    return {
        "verdict": "ok",
        "configured": configured,
        "backend": configured,
        "effective": configured,
        "fallback": False,
        "shipped": configured in SHIPPED_BACKENDS,
        "deferred": configured in DEFERRED_BACKENDS,
    }


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


def _github_scope_probe(token: str, cfg: dict[str, Any]) -> dict[str, Any]:
    host = host_section(cfg)
    url = f"{github_api_base(host)}/user"
    req = Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "User-Agent": "shipwright-planning-store"})
    try:
        with urlopen(req, timeout=15) as resp:
            scopes_header = resp.headers.get("X-OAuth-Scopes") or resp.headers.get("x-oauth-scopes") or ""
    except HTTPError as exc:
        return {"verdict": "fail", "error": "auth-failed", "httpStatus": exc.code}
    except URLError as exc:
        return {"verdict": "fail", "error": "network-unavailable", "message": str(exc.reason)}
    scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
    required = set(MIN_ISSUES_SCOPES["github-issues"])
    if scopes & required:
        return {"verdict": "ok", "scopes": sorted(scopes), "required": sorted(required)}
    if "repo" in scopes or "public_repo" in scopes:
        return {"verdict": "ok", "scopes": sorted(scopes), "required": sorted(required)}
    return {
        "verdict": "fail",
        "error": "insufficient-scope",
        "scopes": sorted(scopes),
        "required": sorted(required),
        "message": "GitHub token lacks repo/public_repo scope for issue-store",
    }


def _gitlab_scope_probe(token: str, cfg: dict[str, Any]) -> dict[str, Any]:
    host = host_section(cfg)
    url = f"{gitlab_api_base(host)}/user"
    req = Request(url, headers={"PRIVATE-TOKEN": token, "User-Agent": "shipwright-planning-store"})
    try:
        with urlopen(req, timeout=15) as resp:
            if resp.status >= 400:
                return {"verdict": "fail", "error": "auth-failed", "httpStatus": resp.status}
    except HTTPError as exc:
        return {"verdict": "fail", "error": "auth-failed", "httpStatus": exc.code}
    except URLError as exc:
        return {"verdict": "fail", "error": "network-unavailable", "message": str(exc.reason)}
    return {"verdict": "ok", "required": MIN_ISSUES_SCOPES["gitlab-issues"]}


def probe_issues_token(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    issues = resolve_issues_provider(cfg)
    provider = issues.get("provider", "none")
    if provider in {"none", ""} or not issues.get("supported"):
        return {
            "verdict": "ok",
            "skipped": True,
            "reason": "issues-provider-none-or-unsupported",
            "provider": provider,
        }
    if provider not in SHIPPED_ISSUES_PROVIDERS:
        return {
            "verdict": "ok",
            "skipped": True,
            "reason": "issues-provider-not-shipped",
            "provider": provider,
        }
    token_env = resolve_issues_token_env(cfg, provider)
    if not token_env:
        return {"verdict": "fail", "error": "missing-token-env", "provider": provider}
    if not token_present(token_env):
        return {
            "verdict": "fail",
            "error": "missing-token",
            "provider": provider,
            "tokenEnv": token_env,
            "message": f"Set {token_env} for issue-store API access (value never logged).",
        }
    token = os.environ.get(token_env, "")
    if provider == "github-issues":
        probe = _github_scope_probe(token, cfg)
    elif provider == "gitlab-issues":
        probe = _gitlab_scope_probe(token, cfg)
    else:
        return {
            "verdict": "fail",
            "error": "probe-not-implemented",
            "provider": provider,
            "requiredScopes": MIN_ISSUES_SCOPES.get(provider, []),
        }
    out: dict[str, Any] = {
        "verdict": probe.get("verdict", "fail"),
        "provider": provider,
        "tokenEnv": token_env,
        "tokenPresent": True,
        "requiredScopes": MIN_ISSUES_SCOPES.get(provider, []),
    }
    for key in ("error", "message", "scopes", "required", "httpStatus"):
        if key in probe:
            out[key] = probe[key]
    return out


@dataclass(frozen=True)
class StoreResult:
    verdict: str
    unit_id: str
    body_path: str
    backend: str
    content: str | None = None
    hash: str | None = None
    reason: str | None = None
    inert: bool = False
    notice: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "verdict": self.verdict,
            "unitId": self.unit_id,
            "bodyPath": self.body_path,
            "backend": self.backend,
        }
        if self.content is not None:
            out["content"] = self.content
        if self.hash is not None:
            out["hash"] = self.hash
        if self.reason is not None:
            out["reason"] = self.reason
        if self.inert:
            out["inert"] = True
        if self.notice:
            out["notice"] = self.notice
        return out


class PlanningStoreBackend(ABC):
    backend_id: str

    def __init__(self, root: Path, cfg: dict[str, Any]) -> None:
        self.root = root
        self.cfg = cfg

    @abstractmethod
    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def get(self, unit_id: str, body_path: str) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        raise NotImplementedError


class InRepoPublicBackend(PlanningStoreBackend):
    backend_id = "in-repo-public"

    def _resolve_path(self, body_path: str) -> Path:
        path = (self.root / body_path).resolve()
        root_resolved = self.root.resolve()
        if root_resolved not in path.parents and path != root_resolved:
            fail("body path escapes repository root", bodyPath=body_path)
        return path

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        path = self._resolve_path(body_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._resolve_path(body_path)
        if not path.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        content = path.read_text(encoding="utf-8")
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._resolve_path(body_path)
        present = path.is_file()
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        src = self._resolve_path(body_path)
        if not src.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
        content = dest_path.read_text(encoding="utf-8")
        log_operation("materialize", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))



def load_issue_unit_index(root: Path) -> dict[str, str]:
    path = root / ISSUE_UNIT_INDEX
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    units = data.get("units") if isinstance(data, dict) else None
    if not isinstance(units, dict):
        return {}
    return {str(k): str(v) for k, v in units.items() if isinstance(k, str) and isinstance(v, str)}


def save_issue_unit_index(root: Path, index: dict[str, str]) -> None:
    path = root / ISSUE_UNIT_INDEX
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "units": index}, indent=2) + "\n", encoding="utf-8")


def issue_index_key(project_key: str, unit_id: str) -> str:
    return f"{project_key}:{unit_id}"


class IssueStoreBackend(PlanningStoreBackend):
    backend_id = "issue-store"

    def __init__(self, root: Path, cfg: dict[str, Any]) -> None:
        super().__init__(root, cfg)
        key_result = validate_project_key(root, cfg)
        if key_result.get("verdict") != "ok":
            fail(key_result.get("message") or key_result.get("error", "invalid-project-key"))
        self.project_key = str(key_result["projectKey"])
        issues = resolve_issues_provider(cfg)
        self.issues_provider = str(issues.get("provider", "none"))
        self._client = IssuesClient(root, self.issues_provider)
        self._index = load_issue_unit_index(root)

    def _artifact_type(self, body_path: str) -> str:
        return infer_artifact_type(body_path)

    def _issue_title(self, artifact_type: str, unit_id: str) -> str:
        return f"{title_prefix(self.project_key)} {artifact_type}:{unit_id}"

    def _labels_for(self, artifact_type: str) -> list[str]:
        return sorted({project_label(self.project_key), type_label(artifact_type)})

    def _record_to_snapshot(self, record: Any) -> IssueSnapshot:
        return IssueSnapshot(
            title=record.title,
            body=record.body,
            state=record.state,
            labels=list(record.labels),
            comments=list(record.comments),
            native_links=list(record.native_links),
            etag=record.etag,
            updated_at=record.updated_at,
        )

    def _extract_content(self, record: Any) -> str:
        full_body = reassemble_body(record.body, record.comments)
        if not verify_project_scope(full_body, self.project_key):
            fail(
                "project-scope-violation",
                code="project-scope-violation",
                unitId=record.unit_id,
                projectKey=self.project_key,
            )
        if not verify_unit_id(full_body, record.unit_id):
            fail("unit-id-mismatch", code="unit-id-mismatch", unitId=record.unit_id)
        body_edges = parse_edges_block(full_body)
        try:
            reconcile_edges(body_edges, record.native_links)
        except ValueError as exc:
            fail(str(exc), code="edge-divergence")
        return strip_markers_and_edges(full_body)

    def _lookup_record(self, unit_id: str, body_path: str) -> Any:
        idx_key = issue_index_key(self.project_key, unit_id)
        issue_id = self._index.get(idx_key)
        if issue_id:
            try:
                record = self._client.issue_get(issue_id)
            except IssueNotFound:
                record = None
            else:
                if verify_project_scope(record.body, self.project_key):
                    return record
        matches = self._client.issue_search(
            project_key=self.project_key,
            unit_id=unit_id,
            artifact_type=self._artifact_type(body_path),
        )
        if not matches:
            raise IssueNotFound(f"no issue for unit {unit_id}")
        record = matches[0]
        self._index[idx_key] = record.id
        save_issue_unit_index(self.root, self._index)
        return record

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        artifact_type = self._artifact_type(body_path)
        title = self._issue_title(artifact_type, unit_id)
        labels = self._labels_for(artifact_type)
        body = compose_issue_body(self.project_key, artifact_type, unit_id, content)
        body, extra_comments = chunk_body_if_needed(body, [])
        try:
            record = self._lookup_record(unit_id, body_path)
        except IssueNotFound:
            record = self._client.issue_create(
                title=title,
                body=body,
                labels=labels,
                project_key=self.project_key,
                artifact_type=artifact_type,
                unit_id=unit_id,
            )
        else:
            try:
                record = self._client.issue_update(
                    record.id,
                    title=title,
                    body=body,
                    labels=labels,
                    if_match=record.etag,
                )
            except IssueRevisionConflict as exc:
                fail(
                    "revision-conflict",
                    code="revision-conflict",
                    expected=exc.expected,
                    actual=exc.actual,
                )
        for comment in extra_comments:
            self._client.issue_comment(record.id, comment.body, markers=comment.markers)
            record = self._client.issue_get(record.id)
        idx_key = issue_index_key(self.project_key, unit_id)
        self._index[idx_key] = record.id
        save_issue_unit_index(self.root, self._index)
        digest = canonical_hash(self._record_to_snapshot(record))
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=digest)

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        try:
            record = self._lookup_record(unit_id, body_path)
        except IssueNotFound:
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        except IssueCapabilityError as exc:
            fail(str(exc), code="issues-capability")
        content = self._extract_content(record)
        digest = canonical_hash(self._record_to_snapshot(record))
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=digest)

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        try:
            self._lookup_record(unit_id, body_path)
        except IssueNotFound:
            log_operation("exists", unit_id, body_path, None, self.backend_id)
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        except IssueCapabilityError as exc:
            fail(str(exc), code="issues-capability")
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id)

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        if got.verdict != "ok" or got.content is None:
            return StoreResult(got.verdict, unit_id, body_path, self.backend_id, reason=got.reason)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(got.content, encoding="utf-8")
        log_operation("materialize", unit_id, body_path, got.content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=got.content, hash=got.hash)

    def link_brainstorm_to_prd(self, brainstorm_unit_id: str, prd_unit_id: str) -> dict[str, Any]:
        try:
            brainstorm = self._lookup_record(brainstorm_unit_id, f"docs/brainstorms/{brainstorm_unit_id}.md")
        except IssueNotFound:
            fail("brainstorm-issue-missing", code="brainstorm-missing")
        edges = [{"rel": "spawned", "target": prd_unit_id, "targetType": "prd"}]
        body = compose_issue_body(
            self.project_key,
            "brainstorm",
            brainstorm_unit_id,
            strip_markers_and_edges(reassemble_body(brainstorm.body, brainstorm.comments)),
            edges=edges,
        )
        try:
            updated = self._client.issue_update(brainstorm.id, body=body, if_match=brainstorm.etag)
        except IssueRevisionConflict as exc:
            fail("revision-conflict", code="revision-conflict", expected=exc.expected, actual=exc.actual)
        return {
            "verdict": "ok",
            "brainstormUnitId": brainstorm_unit_id,
            "prdUnitId": prd_unit_id,
            "etag": updated.etag,
        }


class LocalSyncedBackend(PlanningStoreBackend):
    backend_id = "local-synced"

    def synced_root(self) -> Path:
        store = store_section(self.cfg)
        local = store.get("localSynced")
        if not isinstance(local, dict):
            fail("planning.store.localSynced.path is required for local-synced backend")
        raw = local.get("path")
        if not isinstance(raw, str) or not raw.strip():
            fail("planning.store.localSynced.path is required for local-synced backend")
        return Path(os.path.expanduser(raw.strip())).resolve()

    def _unit_path(self, unit_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", unit_id)
        return self.synced_root() / f"{safe_id}.md"

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        path = self._unit_path(unit_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._unit_path(unit_id)
        if not path.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        content = path.read_text(encoding="utf-8")
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        present = self._unit_path(unit_id).is_file()
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        src = self._unit_path(unit_id)
        if not src.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)
        content = dest_path.read_text(encoding="utf-8")
        log_operation("materialize", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))


class MemoryBackend(PlanningStoreBackend):
    backend_id = "memory"

    def memory_project(self) -> str:
        memory = self.cfg.get("memory")
        if isinstance(memory, dict) and isinstance(memory.get("project"), str) and memory["project"].strip():
            return memory["project"].strip()
        return self.root.name

    def provider(self) -> str | None:
        return resolve_memory_provider(self.root, self.cfg)

    def _store_dir(self) -> Path:
        if self.provider() is None:
            fail("memory backend degraded: no memory provider configured", verdict="degraded")
        return self.root / ".cursor" / "sw-memory" / "planning-bodies" / self.memory_project()

    def _unit_path(self, unit_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", unit_id)
        return self._store_dir() / f"{safe_id}.md"

    def _validate_class(self, content_class: str | None) -> None:
        if content_class and content_class.lower() in BANNED_MEMORY_CLASSES:
            fail(f"memory backend bans content class: {content_class}", code="banned-class")

    def _validate_content(self, content: str) -> None:
        if contains_raw_transcript(content):
            fail("raw transcript content refused by memory backend", code="raw-transcript")

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        self._validate_class(content_class)
        self._validate_content(content)
        redacted = redact_content(content)
        store_dir = self._store_dir()
        store_dir.mkdir(parents=True, exist_ok=True)
        target = self._unit_path(unit_id)
        frontmatter = (
            "---\n"
            f"unitId: {unit_id}\n"
            f"bodyPath: {body_path}\n"
            f"project: {self.memory_project()}\n"
            f"provider: {self.provider() or 'none'}\n"
            "---\n"
        )
        target.write_text(frontmatter + redacted, encoding="utf-8")
        log_operation("put", unit_id, body_path, redacted, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted))

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._unit_path(unit_id)
        if not path.is_file():
            if self.provider() is None:
                return StoreResult("degraded", unit_id, body_path, self.backend_id, reason="no-provider")
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        raw = path.read_text(encoding="utf-8")
        body = raw.split("---", 2)[-1].lstrip("\n") if raw.startswith("---") else raw
        redacted = redact_content(body)
        log_operation("get", unit_id, body_path, redacted, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted))

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        present = self._unit_path(unit_id).is_file()
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        if not present and self.provider() is None:
            return StoreResult("degraded", unit_id, body_path, self.backend_id, reason="no-provider")
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        if got.verdict != "ok" or got.content is None:
            return StoreResult(got.verdict, unit_id, body_path, self.backend_id, reason=got.reason)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_text(got.content, encoding="utf-8")
        log_operation("materialize", unit_id, body_path, got.content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=got.content, hash=got.hash)


class DeferredBackend(PlanningStoreBackend):
    def __init__(self, root: Path, cfg: dict[str, Any], backend_id: str) -> None:
        super().__init__(root, cfg)
        self.backend_id = backend_id

    def _inert(self, unit_id: str, body_path: str) -> StoreResult:
        log_operation("inert", unit_id, body_path, None, self.backend_id)
        return StoreResult("deferred", unit_id, body_path, self.backend_id, reason="backend-deferred", inert=True)

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        return self._inert(unit_id, body_path)

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        return self._inert(unit_id, body_path)

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        return self._inert(unit_id, body_path)

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        return self._inert(unit_id, body_path)


BACKEND_CLASSES: dict[str, type[PlanningStoreBackend]] = {
    "in-repo-public": InRepoPublicBackend,
    "issue-store": IssueStoreBackend,
    "local-synced": LocalSyncedBackend,
    "memory": MemoryBackend,
    "private-repo": DeferredBackend,
    "encryption-at-rest": DeferredBackend,
}


def resolve_backend_id(cfg: dict[str, Any], *, override: str | None = None) -> str:
    if override and override in ALL_BACKENDS:
        return override
    store = store_section(cfg)
    pinned = store.get("pinnedBackend")
    if isinstance(pinned, str) and pinned in ALL_BACKENDS:
        return pinned
    backend = store.get("backend", DEFAULT_BACKEND)
    if isinstance(backend, str) and backend in ALL_BACKENDS:
        return backend
    return DEFAULT_BACKEND


def get_backend(root: Path, cfg: dict[str, Any] | None = None, *, override: str | None = None) -> PlanningStoreBackend:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    effective = resolve_effective_backend(root, cfg, override=override)
    backend_id = effective["effective"]
    cls = BACKEND_CLASSES[backend_id]
    if backend_id in DEFERRED_BACKENDS:
        return cls(root, cfg, backend_id)
    return cls(root, cfg)


def validate_local_synced_path(path: Path, *, allowlist: list[str] | None = None) -> dict[str, Any]:
    warnings: list[str] = []
    checks: list[dict[str, Any]] = []
    home = Path.home().resolve()
    try:
        resolved = path.resolve()
    except OSError as exc:
        return {"verdict": "fail", "path": str(path), "error": str(exc), "checks": [], "warnings": []}
    allow_roots = [home] + [Path(os.path.expanduser(e)).resolve() for e in (allowlist or [])]
    contained = any(resolved == root or root in resolved.parents for root in allow_roots)
    checks.append({"check": "allowlist", "status": "ok" if contained else "fail", "resolved": str(resolved)})
    if not contained:
        return {"verdict": "fail", "path": str(resolved), "checks": checks, "warnings": ["path-outside-allowlist"]}
    if path.is_symlink():
        checks.append({"check": "symlink", "status": "fail"})
        return {"verdict": "fail", "path": str(resolved), "checks": checks, "warnings": ["symlink-rejected"]}
    checks.append({"check": "symlink", "status": "ok"})
    if ".." in path.parts:
        checks.append({"check": "dotdot", "status": "fail"})
        return {"verdict": "fail", "path": str(resolved), "checks": checks, "warnings": ["dotdot-rejected"]}
    checks.append({"check": "dotdot", "status": "ok"})
    if resolved.is_dir():
        mode = resolved.stat().st_mode & 0o777
        loose = mode > 0o700
        checks.append({"check": "mode", "status": "fail" if loose else "ok", "mode": oct(mode)})
        if loose:
            return {"verdict": "fail", "path": str(resolved), "checks": checks, "warnings": ["loose-directory-mode"]}
    else:
        checks.append({"check": "mode", "status": "skipped", "reason": "not-a-directory"})
    for cloud in CLOUD_SYNC_ROOTS:
        cloud_path = home / cloud
        try:
            if cloud_path.exists() and cloud_path.resolve() in resolved.parents:
                warnings.append(f"cloud-sync-root:{cloud}")
                checks.append({"check": "cloud-sync", "status": "warn", "root": cloud})
                break
        except OSError:
            continue
    return {"verdict": "ok", "path": str(resolved), "checks": checks, "warnings": warnings}


def _require(args: list[str], flag: str) -> str:
    if flag not in args:
        fail(f"missing required flag: {flag}")
    idx = args.index(flag)
    if idx + 1 >= len(args):
        fail(f"missing value for {flag}")
    return args[idx + 1]


def _optional(args: list[str], flag: str) -> str | None:
    if flag not in args:
        return None
    idx = args.index(flag)
    return args[idx + 1] if idx + 1 < len(args) else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Planning store interface (PRD 034 + PRD 043)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "resolve-backend",
        "list-backends",
        "resolve-issues",
        "resolve-store-location",
        "probe-issues-token",
        "validate-project-key",
        "put",
        "get",
        "exists",
        "materialize",
        "validate-local-synced",
        "canonical-hash",
        "link-brainstorm-prd",
        "clear-issue-fixture",
    ):
        sub.add_parser(name)
    args, rest = parser.parse_known_args()
    root = git_root(Path(args.root).resolve())
    cfg = load_workflow_config(root)
    if args.command == "resolve-backend":
        override = _optional(rest, "--backend")
        emit(resolve_effective_backend(root, cfg, override=override))
    elif args.command == "list-backends":
        emit({
            "verdict": "ok",
            "default": DEFAULT_BACKEND,
            "shipped": sorted(SHIPPED_BACKENDS),
            "deferred": sorted(DEFERRED_BACKENDS),
            "issuesProviders": sorted(ISSUES_PROVIDERS),
            "interface": ["put", "get", "exists", "materialize"],
        })
    elif args.command == "resolve-issues":
        emit(resolve_issues_provider(cfg))
    elif args.command == "resolve-store-location":
        emit(resolve_store_location(root, cfg))
    elif args.command == "probe-issues-token":
        result = probe_issues_token(root, cfg)
        emit(result, 0 if result.get("verdict") == "ok" else 2)
    elif args.command == "validate-project-key":
        register = "--register" in rest
        result = validate_project_key(root, cfg, register=register)
        emit(result, 0 if result.get("verdict") == "ok" else 2)
    elif args.command == "put":
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"))
        result = backend.put(_require(rest, "--unit-id"), _require(rest, "--body-path"), _require(rest, "--content"), content_class=_optional(rest, "--content-class"))
        emit(result.as_dict())
    elif args.command == "get":
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"))
        result = backend.get(_require(rest, "--unit-id"), _require(rest, "--body-path"))
        emit(result.as_dict(), 0 if result.verdict in {"ok", "degraded"} else 2)
    elif args.command == "exists":
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"))
        emit(backend.exists(_require(rest, "--unit-id"), _require(rest, "--body-path")).as_dict())
    elif args.command == "materialize":
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"))
        result = backend.materialize(_require(rest, "--unit-id"), _require(rest, "--body-path"), Path(_require(rest, "--dest")))
        emit(result.as_dict(), 0 if result.verdict == "ok" else 2)

    elif args.command == "canonical-hash":
        from planning_canonical import CommentRecord, IssueSnapshot, canonical_form, canonical_hash as ch
        fixture_path = Path(_require(rest, "--fixture"))
        data = json.loads(fixture_path.read_text(encoding="utf-8"))
        comments = [CommentRecord(**c) for c in data.get("comments", [])]
        snap = IssueSnapshot(
            title=data["title"],
            body=data["body"],
            state=data.get("state", "open"),
            labels=list(data.get("labels", [])),
            comments=comments,
        )
        emit({"verdict": "ok", "canonical": canonical_form(snap), "hash": ch(snap)})
    elif args.command == "link-brainstorm-prd":
        backend = get_backend(root, cfg, override="issue-store")
        if not isinstance(backend, IssueStoreBackend):
            fail("issue-store backend required")
        emit(backend.link_brainstorm_to_prd(_require(rest, "--brainstorm-unit"), _require(rest, "--prd-unit")))
    elif args.command == "clear-issue-fixture":
        from issues_lib import get_fixture_store
        get_fixture_store(root).clear()
        emit({"verdict": "ok"})
    elif args.command == "validate-local-synced":
        raw = _require(rest, "--path")
        allowlist_raw = _optional(rest, "--allowlist")
        allowlist = [p.strip() for p in allowlist_raw.split(",") if p.strip()] if allowlist_raw else None
        store = store_section(cfg)
        local = store.get("localSynced")
        if isinstance(local, dict) and not allowlist:
            cfg_allow = local.get("allowlist")
            if isinstance(cfg_allow, list):
                allowlist = [str(x) for x in cfg_allow]
        result = validate_local_synced_path(Path(os.path.expanduser(raw)), allowlist=allowlist)
        emit(result, 0 if result["verdict"] == "ok" else 2)


if __name__ == "__main__":
    main()
