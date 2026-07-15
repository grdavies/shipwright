#!/usr/bin/env python3
"""PRD 034 Phase 3 + PRD 043 Phase 1–2 — planning.store interface + issue-store."""

from __future__ import annotations

import argparse
import ast
import hashlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import issues_http

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
import planning_visibility
from planning_projection_ledger import (
    assert_portable_graph_authority,
    check_projection_drift,
    clear_projection_dirty,
    load_projection_ledger,
    projection_is_dirty,
    projection_ledger_checkpoint,
    projection_ledger_discover_by_marker,
    projection_ledger_lookup,
    projection_ledger_reconcile_duplicates,
    projection_ledger_upsert,
    rebuild_projection_from_graph,
    resume_projection_from_checkpoint,
    set_projection_dirty,
)
from planning_linear_projection import (
    apply_initiative_capability,
    assert_cycle_orthogonal_to_milestone,
    assert_projection_mirrors_not_freeze_authority,
    assign_issue_to_cycle,
    check_canonical_projection_split_brain,
    cycle_sharing_notice,
    dual_write_body_policy,
    dual_write_projection_mirror,
    encode_planning_edge,
    freeze_from_canonical_body,
    infer_canonical_body_source,
    linear_entity_mapping,
    linear_projection_schema_contract,
    map_artifact_to_linear_entity,
    probe_initiative_availability,
    project_graph_to_linear_layout,
    r1_4_substitute_views,
    resolve_canonical_freeze_body,
)

SCRIPT_DIR = Path(__file__).resolve().parent

DEFAULT_BACKEND = "in-repo-public"
SHIPPED_BACKENDS = frozenset({"in-repo-public", "local-synced", "memory", "issue-store"})
DEFERRED_BACKENDS = frozenset({"private-repo", "encryption-at-rest"})
ALL_BACKENDS = SHIPPED_BACKENDS | DEFERRED_BACKENDS

def _linear_live_client_wired() -> bool:
    """PRD 066 R9 — recognize Linear in ISSUES_PROVIDERS only when live client exists."""
    try:
        import planning_linear_client as _plc  # noqa: WPS433 — optional provider probe
    except ImportError:
        return False
    return bool(getattr(_plc, "LIVE_CLIENT", False)) and callable(getattr(_plc, "graphql", None))


_BASE_ISSUES_PROVIDERS = frozenset({"github-issues", "gitlab-issues", "jira", "none"})
ISSUES_PROVIDERS = _BASE_ISSUES_PROVIDERS | (
    frozenset({"linear"}) if _linear_live_client_wired() else frozenset()
)
# PRD 057 R7 / D1: gitlab-issues is a known-but-deferred provider — supported for
# config validation yet absent from the shipped set until a live adapter ships in a
# follow-up unit (originating gap-039). Selection therefore fails closed with the
# issues-provider-not-shipped fallback reason instead of an advertised round-trip.
# PRD 066 R9/R20: linear is recognized when the live client is wired, but not shipped
# until conformance + OAuth docs gate pass.
DEFERRED_ISSUES_PROVIDERS = frozenset({"gitlab-issues"})
SHIPPED_ISSUES_PROVIDERS = frozenset({"github-issues", "jira"})

DEFAULT_ISSUES_TOKEN_ENV: dict[str, str] = {
    "github-issues": "ISSUES_GITHUB_TOKEN",
    "gitlab-issues": "ISSUES_GITLAB_TOKEN",
    "jira": "ISSUES_JIRA_TOKEN",
    "linear": "ISSUES_LINEAR_TOKEN",
    "none": "",
}

MIN_ISSUES_SCOPES: dict[str, list[str]] = {
    "github-issues": ["repo"],
    "gitlab-issues": ["api"],
    "jira": ["read:jira-work", "write:jira-work"],
    "linear": ["read", "write"],
}

ISSUE_STORE_FALLBACK_NOTICE = (
    "issue-store configured but effective backend is in-repo-public "
    "(issuesProvider none/unsupported or host.provider none)"
)

# PRD 057 R31: operator-facing effective-backend kill-switch. Setting this env var
# forces effective-backend resolution back to the file-store default regardless of
# `planning.store.backend`, so a regressed issue-store wave can be rolled back
# without editing committed config. Never mutates or deletes store data — pair
# with `materialize_from_store` to re-sync local projections on demand.
KILL_SWITCH_ENV = "SW_PLANNING_KILL_SWITCH"
KILL_SWITCH_NOTICE = (
    f"{KILL_SWITCH_ENV} set — effective backend forced to file-store default "
    "for wave rollback; no store data was modified"
)
BITBUCKET_ISSUE_STORE_GUIDANCE = {
    "defaultPath": "separate-project",
    "summary": (
        "Bitbucket Cloud has no native issues adapter in core. Default planning store is a separate "
        "GitHub/GitLab project; Jira is opt-in (Cloud first). Never route to native Bitbucket issues."
    ),
    "options": [
        {
            "path": "separate-project",
            "issuesProvider": "github-issues",
            "storeLocation": {"mode": "separate-project"},
            "doc": "core/providers/host/bitbucket.md",
        },
        {
            "path": "jira",
            "issuesProvider": "jira",
            "storeLocation": {"mode": "separate-project"},
            "doc": "core/providers/issues/jira.md",
        },
    ],
    "never": "native-bitbucket-issues",
}

PROJECT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
PROJECT_KEY_REGISTRY = ".cursor/hooks/state/issue-store-project-keys.json"
ISSUE_UNIT_INDEX = ".cursor/hooks/state/issue-store-unit-index.json"

# PRD 057 R26 -- partial-write journal for chunked `IssueStoreBackend.put`
# calls. A chunked put cannot commit the head body, the overflow comments,
# and the real-id manifest rewrite as one atomic provider transaction, so a
# crash/exception between those steps must still (a) resolve a retry back to
# the SAME issue -- never mint a duplicate -- and (b) stay visibly flagged
# until the manifest rewrite completes. The journal entry (keyed the same as
# ISSUE_UNIT_INDEX) records the issue id + step + posted comment ids so a
# retry (or the doctor) can see exactly how far a put got; PUT_INCOMPLETE_LABEL
# is the durable, provider-side twin of that same signal.
PUT_JOURNAL_PATH = ".cursor/hooks/state/issue-store-put-journal.json"
PUT_INCOMPLETE_LABEL = "sw:put-incomplete"
LEGACY_UNIT_MAP_PATH = ".cursor/hooks/state/issue-store-legacy-unit-map.json"
NATIVE_UNIT_ID_PREFIX: dict[str, str] = {
    "github-issues": "gh:",
    "jira": "jira:",
    "gitlab-issues": "gl:",
}
NATIVE_UNIT_ID_PATTERN = re.compile(r"^(gh|jira|gl):(\d+)$")
BARE_INTEGER_UNIT_ID = re.compile(r"^\d{3}$")


from issues_lib import (  # noqa: E402
    IssueBudgetExhausted,
    IssueLifecycleDrift,
    IssueArchivedProject,
    IssueTypeConverted,
    IssueCapabilityError,
    IssueNotFound,
    IssueRevisionConflict,
    IssueTombstone,
    IssueTransferred,
    IssuesClient,
)
from planning_canonical import (  # noqa: E402
    ARTIFACT_TYPE_UNRESOLVED,
    FREEZE_INCOMPLETE_LABEL,
    FROZEN_LABEL,
    GAP_LABEL_RESOLVED,
    IssueSnapshot,
    ArtifactTypeUnresolved,
    artifact_type_from_content,
    artifact_type_from_labels,
    build_freeze_record_body,
    canonical_hash,
    chunk_body_if_needed,
    compose_issue_body,
    human_readable_title,
    infer_artifact_type,
    is_resolved_artifact_type,
    MARKER_ARTIFACT_TYPE,
    parse_body_marker,
    parse_edges_block,
    parse_freeze_record_hash,
    project_label,
    reconcile_edges,
    reassemble_body,
    require_artifact_type,
    rewrite_chunk_manifest_ids,
    strip_markers_and_edges,
    canonical_content_from_operator,
    has_raw_yaml_frontmatter,
    is_hybrid_operator_body,
    operator_body_from_canonical,
    strip_hybrid_operator_body,
    structural_labels_from_content,
    type_label,
    unit_id_from_labels,
    unit_id_label,
    verify_project_scope,
    gap_status_from_labels,
    status_from_labels,
    status_label,
    verify_unit_id,
    inbound_authoring_comments,
    CommentRecord,
    RelationRecord,
    FLAT_COMMENT_PROVIDERS,
    build_comment_threads,
    comment_thread_status,
    normalize_flat_provider_comments,
    serialize_comment_facade,
    serialize_relation_facade,
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


# PRD 057 R21 / 21b -- memory backend provider round-trip (planning bodies only).
#
# `_urlopen` is a module-level indirection (mirrors `issues_http._urlopen`) so unit
# tests can monkeypatch the transport without a live Recallium server.
_urlopen = urlopen
PLANNING_BODY_PROVIDER_TIMEOUT_SECONDS = 5
_RECALLIUM_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _is_allowed_recallium_base(url: str) -> bool:
    """Localhost-only SSRF guard for `memory.connection.restBaseUrl`.

    Deliberately reimplemented rather than imported from
    `core/hooks/sw_recallium_url.is_allowed_recallium_base`: `scripts/` and
    `core/hooks/` are independent sync trees (`scripts/build-chain-sync.py` /
    `scripts/copy-to-core.py` do not model a cross-tree import here), so this
    keeps the guard's semantics local to the tree that ships it. Same rules:
    http(s) only, no embedded credentials, loopback host only.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname
    if not host:
        return False
    if host in _RECALLIUM_ALLOWED_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _recallium_rest_base(cfg: dict[str, Any]) -> str | None:
    memory = cfg.get("memory")
    if not isinstance(memory, dict):
        return None
    connection = memory.get("connection")
    if not isinstance(connection, dict):
        return None
    base = str(connection.get("restBaseUrl") or "").strip().rstrip("/")
    if not base or not _is_allowed_recallium_base(base):
        return None
    return base


def _planning_body_provider_url(base: str, project: str, unit_id: str) -> str:
    # Dedicated document-style resource, deliberately separate from the
    # semantically-indexed memory-note REST collection (see
    # `core/providers/recallium.md` operation mapping): a full planning body
    # is not a distilled memory note, and mixing the two would pollute
    # semantic search (see that doc's "Notes / gotchas"). Keyed by `unitId`
    # for a deterministic get, since note search has no exact-key guarantee.
    quoted_project = urllib.parse.quote(project, safe="")
    quoted_unit = urllib.parse.quote(unit_id, safe="")
    return f"{base}/api/projects/{quoted_project}/planning-bodies/{quoted_unit}"


def _provider_round_trip_put(base: str, project: str, unit_id: str, body_path: str, content: str) -> tuple[bool, str]:
    """Best-effort PUT of a redacted planning body through the Recallium REST adapter.

    Never raises -- any failure (unreachable, timeout, non-2xx) degrades to a
    `(False, reason)` tuple so the caller always has the R21a local cache to
    fall back to.
    """
    url = _planning_body_provider_url(base, project, unit_id)
    payload = json.dumps({"content": content, "bodyPath": body_path}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="PUT")
    try:
        with _urlopen(req, timeout=PLANNING_BODY_PROVIDER_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if not (200 <= status < 300):
                return False, f"provider-http-{status}"
    except HTTPError as exc:
        exc.close()
        return False, f"provider-http-{exc.code}"
    except (URLError, OSError, ValueError) as exc:
        return False, f"provider-unreachable:{type(exc).__name__}"
    return True, "ok"


def _provider_round_trip_get(base: str, project: str, unit_id: str) -> tuple[bool, str, str | None]:
    """Best-effort GET of a planning body through the Recallium REST adapter.

    Returns `(ok, reason, content)`; `content` is only set when `ok` is True.
    Never raises.
    """
    url = _planning_body_provider_url(base, project, unit_id)
    req = Request(url, method="GET")
    try:
        with _urlopen(req, timeout=PLANNING_BODY_PROVIDER_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if not (200 <= status < 300):
                return False, f"provider-http-{status}", None
            raw = resp.read()
            raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    except HTTPError as exc:
        code = exc.code
        exc.close()
        if code == 404:
            return False, "provider-not-found", None
        return False, f"provider-http-{code}", None
    except (URLError, OSError, ValueError) as exc:
        return False, f"provider-unreachable:{type(exc).__name__}", None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, "provider-invalid-response", None
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, str):
        return False, "provider-invalid-response", None
    return True, "ok", content


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


ISSUES_CAPABILITY_INDEX_IDS: dict[str, str] = {
    "github-issues": "provider.providers.issues.github-issues",
    "gitlab-issues": "provider.providers.issues.gitlab-issues",
    "jira": "provider.providers.issues.jira",
    "linear": "provider.providers.issues.linear",
    "none": "provider.providers.issues.none",
}

ISSUES_MIGRATION_HOOKS: tuple[str, ...] = (
    "scripts/planning_migrate_issue_store.py",
    "scripts/planning_migrate.py",
)


def issues_provider_registration_footprint() -> dict[str, Any]:
    """PRD 066 R16/R20 — registration touchpoints for issue-backed adapters."""
    linear_wired = _linear_live_client_wired()
    return {
        "verdict": "ok",
        "action": "issues-provider-registration",
        "issuesProviders": sorted(ISSUES_PROVIDERS),
        "shippedIssuesProviders": sorted(SHIPPED_ISSUES_PROVIDERS),
        "deferredIssuesProviders": sorted(DEFERRED_ISSUES_PROVIDERS),
        "rateLimitMap": dict(issues_http.ISSUES_PROVIDER_TO_RATELIMIT),
        "capabilityIndexIds": dict(ISSUES_CAPABILITY_INDEX_IDS),
        "migrationHooks": list(ISSUES_MIGRATION_HOOKS),
        "linear": {
            "recognized": "linear" in ISSUES_PROVIDERS,
            "shipped": "linear" in SHIPPED_ISSUES_PROVIDERS,
            "liveClientWired": linear_wired,
            "promotionGatedBy": ["conformance", "oauth-docs-gate"],
            "adapterModule": "scripts/planning_linear_client.py",
            "doctorHooks": ["doctor-issues-provider-stub", "planning_linear_client.doctor-oauth"],
        },
        "recognitionVsShipped": {
            provider: {
                "recognized": provider in ISSUES_PROVIDERS,
                "shipped": provider in SHIPPED_ISSUES_PROVIDERS,
                "deferred": provider in DEFERRED_ISSUES_PROVIDERS,
            }
            for provider in sorted(_BASE_ISSUES_PROVIDERS | {"linear"})
        },
    }


def doctor_issues_provider_stub(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """PRD 066 R16/R20 — refuse enum-only / stub providers; note recognized-but-unshipped."""
    issues = resolve_issues_provider(cfg)
    provider = str(issues.get("provider") or "none")
    if provider in {"none", ""} or not issues.get("configured"):
        return {"verdict": "pass", "action": "doctor-issues-provider-stub", "skipped": True, "reason": "no-issues-provider"}
    if provider in DEFERRED_ISSUES_PROVIDERS:
        return {
            "verdict": "fail",
            "action": "doctor-issues-provider-stub",
            "error": "deferred-provider-stub-refused",
            "provider": provider,
            "message": (
                f"issue provider {provider!r} is deferred — select a shipped provider "
                "(github-issues or jira) or use file-store fallback"
            ),
        }
    if provider == "linear" and provider not in ISSUES_PROVIDERS:
        return {
            "verdict": "fail",
            "action": "doctor-issues-provider-stub",
            "error": "linear-stub-refused",
            "provider": provider,
            "message": (
                "linear is configured but no live client is wired — enum-only stub refused; "
                "install planning_linear_client.py with LIVE_CLIENT before recognition"
            ),
        }
    if provider == "linear" and provider not in SHIPPED_ISSUES_PROVIDERS:
        oauth = {}
        try:
            from planning_linear_client import doctor_oauth_ci_secret_check

            oauth = doctor_oauth_ci_secret_check(root)
        except ImportError:
            oauth = {"verdict": "fail", "error": "linear-client-missing"}
        if oauth.get("verdict") == "fail" and oauth.get("error") == "oauth-shared-ci-secret-refused":
            return {
                "verdict": "fail",
                "action": "doctor-issues-provider-stub",
                "error": "linear-oauth-stub-refused",
                "provider": provider,
                "oauth": oauth,
            }
        return {
            "verdict": "pass",
            "action": "doctor-issues-provider-stub",
            "provider": provider,
            "notice": "linear-recognized-not-shipped",
            "message": (
                "linear is recognized (live client wired) but not yet in SHIPPED_ISSUES_PROVIDERS; "
                "issue-store falls back to file-store until conformance + OAuth docs gate pass"
            ),
            "oauth": oauth,
        }
    return {"verdict": "pass", "action": "doctor-issues-provider-stub", "provider": provider}


def resolve_issues_token_env(cfg: dict[str, Any], issues_provider: str) -> str:
    issues = issues_section(cfg)
    token_env = issues.get("tokenEnv")
    if isinstance(token_env, str) and token_env.strip():
        return token_env.strip()
    return DEFAULT_ISSUES_TOKEN_ENV.get(issues_provider, "")


def bitbucket_host_active(root: Path, cfg: dict[str, Any]) -> bool:
    host = host_section(cfg)
    configured = host.get("provider")
    if isinstance(configured, str) and configured.strip() == "bitbucket":
        return True
    resolved = resolve_provider(root)
    return resolved.get("verdict") == "ok" and resolved.get("provider") == "bitbucket"


def bitbucket_issue_store_guidance(root: Path, cfg: dict[str, Any]) -> dict[str, Any] | None:
    if resolve_backend_id(cfg) != "issue-store":
        return None
    if not bitbucket_host_active(root, cfg):
        return None
    issues = resolve_issues_provider(cfg)
    if issues["provider"] not in {"none", ""} and issues.get("supported"):
        return None
    return {
        "verdict": "ok",
        "hostProvider": "bitbucket",
        "fallbackReason": "bitbucket-issues-unavailable",
        **BITBUCKET_ISSUE_STORE_GUIDANCE,
    }


def issue_store_fallback_reason(root: Path, cfg: dict[str, Any], *, override: str | None = None) -> str | None:
    configured = resolve_backend_id(cfg, override=override)
    if configured != "issue-store":
        return None
    issues = resolve_issues_provider(cfg)
    if issues["provider"] in {"none", ""} or not issues.get("supported"):
        if bitbucket_host_active(root, cfg):
            return "bitbucket-issues-unavailable"
        return "issues-provider-none-or-unsupported"
    if issues["provider"] not in SHIPPED_ISSUES_PROVIDERS:
        return "issues-provider-not-shipped"
    host = resolve_provider(root)
    if host.get("verdict") != "ok" or host.get("provider") == "none":
        return "host-provider-none"
    return None


def _effective_backend_kill_switch() -> bool:
    return os.environ.get(KILL_SWITCH_ENV, "").strip().lower() in {"1", "true", "yes"}


def resolve_effective_backend(root: Path, cfg: dict[str, Any], *, override: str | None = None) -> dict[str, Any]:
    configured = resolve_backend_id(cfg, override=override)
    # PRD 057 R31: an explicit per-call --backend override is a deliberate operator
    # choice for that one invocation and takes precedence over the blanket kill-switch
    # (e.g. `materialize_from_store` reads the real issue store while the kill-switch
    # is globally active).
    if override is None and configured != DEFAULT_BACKEND and _effective_backend_kill_switch():
        return {
            "verdict": "ok",
            "configured": configured,
            "backend": DEFAULT_BACKEND,
            "effective": DEFAULT_BACKEND,
            "fallback": True,
            "fallbackReason": "kill-switch",
            "killSwitch": True,
            "notice": KILL_SWITCH_NOTICE,
            "shipped": True,
            "deferred": False,
        }
    fallback_reason = issue_store_fallback_reason(root, cfg, override=override) if configured == "issue-store" else None
    if fallback_reason:
        out: dict[str, Any] = {
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
        guidance = bitbucket_issue_store_guidance(root, cfg)
        if guidance:
            out["guidance"] = guidance
        return out
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




def _probe_rate_limited_result(exc: Exception) -> dict[str, Any] | None:
    from issues_lib import IssueRateLimited

    if not isinstance(exc, IssueRateLimited):
        return None
    return {
        "verdict": "fail",
        "error": "rate-limited",
        "retryable": bool(exc.retryable),
        "reason": exc.reason,
        "cumulativeWaitMs": exc.cumulative_wait_ms,
        "message": str(exc),
    }

def _github_probe_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "shipwright-planning-store",
    }


def _github_fine_grained_probe(
    token: str,
    cfg: dict[str, Any],
    root: Path,
    *,
    required: set[str],
) -> dict[str, Any]:
    """Fine-grained PATs omit X-OAuth-Scopes — verify issue-store repo access functionally."""
    location = resolve_store_location(root, cfg)
    if location.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "error": "store-location-unresolved",
            "message": str(location.get("error") or "unable to resolve store location for probe"),
        }
    owner = location.get("owner")
    repo = location.get("repo")
    if not isinstance(owner, str) or not owner.strip() or not isinstance(repo, str) or not repo.strip():
        return {
            "verdict": "fail",
            "error": "store-location-unresolved",
            "message": "store location missing owner/repo for fine-grained probe",
        }
    owner = owner.strip()
    repo = repo.strip()
    api_base = github_api_base(host_section(cfg))
    headers = _github_probe_headers(token)
    probes = (
        (f"{api_base}/repos/{owner}/{repo}", "metadata"),
        (f"{api_base}/repos/{owner}/{repo}/issues?state=all&per_page=1", "issues"),
    )
    for probe_url, probe_kind in probes:
        try:
            status, _, _body = issues_http.http_request(
                "GET",
                probe_url,
                headers,
                root=root,
                issues_provider="github-issues",
                timeout=15,
            )
        except ConnectionError as exc:
            return {"verdict": "fail", "error": "network-unavailable", "message": str(exc)}
        except Exception as exc:
            limited = _probe_rate_limited_result(exc)
            if limited is not None:
                limited["probe"] = probe_kind
                return limited
            raise
        else:
            if status >= 400:
                if status in {401, 403}:
                    return {
                        "verdict": "fail",
                        "error": "insufficient-scope",
                        "probe": probe_kind,
                        "httpStatus": status,
                        "scopes": [],
                        "required": sorted(required),
                        "message": f"GitHub fine-grained token lacks {probe_kind} access to {owner}/{repo}",
                    }
                if status == 404:
                    return {
                        "verdict": "fail",
                        "error": "repo-not-found",
                        "httpStatus": 404,
                        "owner": owner,
                        "repo": repo,
                        "message": f"Repository {owner}/{repo} not found or not accessible with this token",
                    }
                return {"verdict": "fail", "error": "auth-failed", "httpStatus": status}
    return {
        "verdict": "ok",
        "scopes": [],
        "required": sorted(required),
        "tokenKind": "fine-grained",
        "probeRepo": f"{owner}/{repo}",
        "owner": owner,
        "repo": repo,
    }




def _github_native_links_capable_probe(
    token: str,
    cfg: dict[str, Any],
    root: Path,
    *,
    owner: str,
    repo: str,
) -> bool:
    api_base = github_api_base(host_section(cfg))
    headers = _github_probe_headers(token)
    headers["X-GitHub-Api-Version"] = "2026-03-10"
    url = f"{api_base}/repos/{owner}/{repo}/issues/1/sub_issues"
    try:
        status, _, _body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider="github-issues",
            timeout=15,
        )
    except Exception:
        return False
    if status == 403:
        return False
    return status < 400 or status == 404


def _attach_github_native_links_capable(
    probe: dict[str, Any],
    token: str,
    cfg: dict[str, Any],
    root: Path,
) -> None:
    if probe.get("verdict") != "ok":
        probe["nativeLinksCapable"] = False
        return
    owner = probe.get("owner")
    repo = probe.get("repo")
    probe_repo = probe.get("probeRepo")
    if (not owner or not repo) and isinstance(probe_repo, str) and "/" in probe_repo:
        owner, repo = probe_repo.split("/", 1)
    if not isinstance(owner, str) or not isinstance(repo, str) or not owner or not repo:
        location = resolve_store_location(root, cfg)
        owner = location.get("owner") if isinstance(location.get("owner"), str) else ""
        repo = location.get("repo") if isinstance(location.get("repo"), str) else ""
    if owner and repo:
        probe["nativeLinksCapable"] = _github_native_links_capable_probe(
            token,
            cfg,
            root,
            owner=owner.strip(),
            repo=repo.strip(),
        )
    else:
        probe["nativeLinksCapable"] = False



def _gitlab_native_links_capable_probe(
    token: str,
    cfg: dict[str, Any],
    root: Path,
    *,
    owner: str,
    project: str,
) -> bool:
    from urllib.parse import quote

    api_base = gitlab_api_base(host_section(cfg))
    encoded = quote(f"{owner}/{project}", safe="")
    url = f"{api_base}/projects/{encoded}/issues/1/links"
    headers = {"PRIVATE-TOKEN": token, "User-Agent": "shipwright-planning-store"}
    try:
        status, _, _body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider="gitlab-issues",
            timeout=15,
        )
    except Exception:
        return False
    if status == 403:
        return False
    return status < 400 or status == 404


def _jira_native_links_capable_probe(token: str, cfg: dict[str, Any], root: Path) -> bool:
    from planning_jira_probe import _api_base, _auth_header, _http_get

    base = _api_base(cfg)
    headers = _auth_header(cfg, token)
    if not base or not headers:
        return False
    try:
        status, _payload = _http_get(f"{base}/issueLinkType", headers, root=root)
    except Exception:
        return False
    return status < 400


def _attach_gitlab_native_links_capable(
    probe: dict[str, Any],
    token: str,
    cfg: dict[str, Any],
    root: Path,
) -> None:
    if probe.get("verdict") != "ok":
        probe["nativeLinksCapable"] = False
        return
    owner = probe.get("owner")
    repo = probe.get("repo")
    probe_repo = probe.get("probeRepo")
    if (not owner or not repo) and isinstance(probe_repo, str) and "/" in probe_repo:
        owner, repo = probe_repo.split("/", 1)
    if not isinstance(owner, str) or not isinstance(repo, str) or not owner or not repo:
        location = resolve_store_location(root, cfg)
        owner = location.get("owner") if isinstance(location.get("owner"), str) else ""
        repo = location.get("repo") if isinstance(location.get("repo"), str) else ""
    if owner and repo:
        probe["nativeLinksCapable"] = _gitlab_native_links_capable_probe(
            token,
            cfg,
            root,
            owner=owner.strip(),
            project=repo.strip(),
        )
    else:
        probe["nativeLinksCapable"] = False


def _attach_jira_native_links_capable(
    probe: dict[str, Any],
    token: str,
    cfg: dict[str, Any],
    root: Path,
) -> None:
    if probe.get("verdict") != "ok":
        probe["nativeLinksCapable"] = False
        return
    probe["nativeLinksCapable"] = _jira_native_links_capable_probe(token, cfg, root)

def _github_scope_probe(token: str, cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    host = host_section(cfg)
    url = f"{github_api_base(host)}/user"
    headers = _github_probe_headers(token)
    try:
        status, resp_headers, _body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider="github-issues",
            timeout=15,
        )
    except ConnectionError as exc:
        return {"verdict": "fail", "error": "network-unavailable", "message": str(exc)}
    except Exception as exc:
        limited = _probe_rate_limited_result(exc)
        if limited is not None:
            return limited
        raise
    else:
        if status >= 400:
            return {"verdict": "fail", "error": "auth-failed", "httpStatus": status}
        scopes_header = resp_headers.get("x-oauth-scopes") or resp_headers.get("X-OAuth-Scopes") or ""
    scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
    required = set(MIN_ISSUES_SCOPES["github-issues"])
    if scopes & required:
        return {
            "verdict": "ok",
            "scopes": sorted(scopes),
            "required": sorted(required),
            "tokenKind": "classic",
        }
    if "repo" in scopes or "public_repo" in scopes:
        return {
            "verdict": "ok",
            "scopes": sorted(scopes),
            "required": sorted(required),
            "tokenKind": "classic",
        }
    if not scopes:
        return _github_fine_grained_probe(token, cfg, root, required=required)
    return {
        "verdict": "fail",
        "error": "insufficient-scope",
        "scopes": sorted(scopes),
        "required": sorted(required),
        "message": "GitHub token lacks repo/public_repo scope for issue-store",
    }


def _gitlab_scope_probe(token: str, cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    host = host_section(cfg)
    url = f"{gitlab_api_base(host)}/user"
    headers = {"PRIVATE-TOKEN": token, "User-Agent": "shipwright-planning-store"}
    try:
        status, _, _body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider="gitlab-issues",
            timeout=15,
        )
    except ConnectionError as exc:
        return {"verdict": "fail", "error": "network-unavailable", "message": str(exc)}
    except Exception as exc:
        limited = _probe_rate_limited_result(exc)
        if limited is not None:
            return limited
        raise
    else:
        if status >= 400:
            return {"verdict": "fail", "error": "auth-failed", "httpStatus": status}
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
        probe = _github_scope_probe(token, cfg, root)
    elif provider == "gitlab-issues":
        probe = _gitlab_scope_probe(token, cfg, root)
    elif provider == "jira":
        probe = _jira_scope_probe(root, cfg, token)
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
    for key in ("error", "message", "scopes", "required", "httpStatus", "tokenKind", "probeRepo", "probe", "owner", "repo"):
        if key in probe:
            out[key] = probe[key]
    if provider == "github-issues":
        _attach_github_native_links_capable(out, token, cfg, root)
    elif provider == "gitlab-issues":
        _attach_gitlab_native_links_capable(out, token, cfg, root)
    elif provider == "jira":
        _attach_jira_native_links_capable(out, token, cfg, root)
    else:
        out["nativeLinksCapable"] = False
    return out



def _jira_scope_probe(root: Path, cfg: dict[str, Any], token: str) -> dict[str, Any]:
    from planning_jira_probe import probe_jira_init

    return probe_jira_init(cfg, token, root)


def jira_privacy_create_gate(root: Path, cfg: dict[str, Any], unit_id: str, body_path: str, content: str) -> None:
    """R105 — fail-closed on create when shared Jira project + private/memory unit."""
    issues = resolve_issues_provider(cfg)
    if issues.get("provider") != "jira":
        return
    from planning_jira_probe import probe_jira_privacy

    artifact_type = require_artifact_type(body_path, content=content)
    unit: dict[str, Any] = {"id": unit_id, "type": artifact_type, "bodyPath": body_path}
    explicit = parse_visibility_from_content(content)
    if explicit:
        unit["visibility"] = explicit
    resolved = planning_visibility.resolve_unit_visibility(unit, cfg)
    if not planning_visibility.body_is_redacted(resolved["visibility"]):
        return
    probe = probe_jira_privacy(cfg, root)
    if probe.get("verdict") != "ok":
        fail(
            probe.get("error", "per-issue-privacy-unsupported"),
            code="visibility-refused",
            visibility=resolved["visibility"],
            unitId=unit_id,
            remediation=probe.get("remediation"),
        )
    fail(
        "per-issue-privacy-unsupported-on-jira",
        code="visibility-refused",
        visibility=resolved["visibility"],
        unitId=unit_id,
        remediation="use separate Jira project per visibility tier or reroute per PRD 043 R28/R43",
    )


def parse_visibility_from_content(content: str) -> str | None:
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end == -1:
        return None
    block = content[4:end]
    for line in block.splitlines():
        if line.strip().lower().startswith("visibility:"):
            return line.split(":", 1)[1].strip()
    return None


def secret_scan_text(text: str, *, path_hint: str | None = None) -> None:
    from secret_scan import load_allowlist, scan_text

    allowlist = load_allowlist(git_root())
    findings = scan_text(text, allowlist=allowlist, path=path_hint)
    if findings:
        fail(
            "secret-scan-deny",
            code="secret-scan",
            pattern=findings[0].pattern,
            line=findings[0].line_no,
        )


def _store_host_privacy_ci_context() -> bool:
    """R14 — explicit CI-context probe. Mirrors `planning_materialize.is_ci_or_host`'s
    env-var signals; kept local (not imported) so this override gate has no dependency
    on `planning_materialize`'s materialize-skip semantics, only on CI detection."""
    if os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def _store_host_privacy_override() -> str | None:
    """R14 — SW_STORE_HOST_PRIVACY is an override intended for CI fixtures/hermetic
    runs only; it MUST NOT be honored in an operator's local/interactive run, where a
    stale or mistaken override could silently misclassify a shared/public store host
    as private and admit private-tier bodies to it."""
    if not _store_host_privacy_ci_context():
        return None
    raw = os.environ.get("SW_STORE_HOST_PRIVACY", "").strip().lower()
    if raw in {"private", "public"}:
        return raw
    return None


def _jira_store_project_browse_private(root: Path, cfg: dict[str, Any], project_key: str) -> bool | None:
    """R14 — real host-privacy probe for the Jira shipped provider (was previously a
    placeholder that always fell through to ``unknown`` when ``jiraProjectVisibility``
    was not declared). Inspects the project's permission scheme BROWSE_PROJECTS grants:
    a grant to an unrestricted holder (``anyone`` / any authenticated Jira user) means
    the project is effectively public within the Jira instance; grants scoped only to
    specific groups, roles, or users mean the project is private. Returns ``None``
    (probe-inconclusive) when unauthenticated, unreachable, or the scheme carries no
    BROWSE_PROJECTS entries."""
    from planning_jira_probe import _api_base, _auth_header, resolve_jira_flavor

    token_env = resolve_issues_token_env(cfg, "jira")
    api_token = os.environ.get(token_env, "") if token_env else ""
    if not api_token:
        return None
    if resolve_jira_flavor(cfg) == "dc":
        headers = {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}
    else:
        headers = _auth_header(cfg, api_token)
    base = _api_base(cfg)
    if not base or not headers:
        return None
    url = f"{base}/project/{project_key}/permissionscheme"
    request_headers = {**headers, "User-Agent": "shipwright-planning-store"}
    try:
        status, _resp_headers, body = issues_http.http_request(
            "GET",
            url,
            request_headers,
            root=root,
            issues_provider="jira",
            timeout=15,
        )
        if status >= 400:
            return None
        data = json.loads(body)
    except (ConnectionError, json.JSONDecodeError, TimeoutError):
        return None
    if not isinstance(data, dict):
        return None
    browse_holders = [
        entry.get("holder")
        for entry in data.get("permissions") or []
        if isinstance(entry, dict) and entry.get("permission") == "BROWSE_PROJECTS"
    ]
    browse_holders = [h for h in browse_holders if isinstance(h, dict)]
    if not browse_holders:
        return None
    unrestricted_holder_types = {"anyone", "loggedin", "authenticated"}
    if any(str(h.get("type", "")).strip().lower() in unrestricted_holder_types for h in browse_holders):
        return False
    return True


def _github_store_repo_private(root: Path, cfg: dict[str, Any], owner: str, repo: str) -> bool | None:
    from issues_lib import IssueRateLimited

    provider = "github-issues"
    token_env = resolve_issues_token_env(cfg, provider)
    api_token = os.environ.get(token_env, "") if token_env else ""
    host = host_section(cfg)
    url = f"{github_api_base(host)}/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "shipwright-planning-store",
    }
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    try:
        status, _, body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider=provider,
            timeout=15,
        )
        if status >= 400:
            return None
        data = json.loads(body)
    except (IssueRateLimited, ConnectionError, json.JSONDecodeError, TimeoutError):
        return None
    if isinstance(data, dict) and "private" in data:
        return bool(data["private"])
    return None


def _gitlab_store_project_private(root: Path, cfg: dict[str, Any], owner: str, project: str) -> bool | None:
    from issues_lib import IssueRateLimited
    from urllib.parse import quote

    provider = "gitlab-issues"
    token_env = resolve_issues_token_env(cfg, provider)
    api_token = os.environ.get(token_env, "") if token_env else ""
    host = host_section(cfg)
    encoded = quote(f"{owner}/{project}", safe="")
    url = f"{gitlab_api_base(host)}/projects/{encoded}"
    headers = {"PRIVATE-TOKEN": api_token, "User-Agent": "shipwright-planning-store"}
    if not api_token:
        return None
    try:
        status, _, body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider=provider,
            timeout=15,
        )
        if status >= 400:
            return None
        data = json.loads(body)
    except (IssueRateLimited, ConnectionError, json.JSONDecodeError, TimeoutError):
        return None
    if isinstance(data, dict):
        visibility = str(data.get("visibility", "")).strip().lower()
        if visibility == "private":
            return True
        if visibility in {"public", "internal"}:
            return False
    return None


def probe_store_host_privacy(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Resolve whether the configured issue store host can hold private-tier units."""
    override = _store_host_privacy_override()
    if override:
        return {"verdict": "ok", "storeHostPrivacy": override, "source": "SW_STORE_HOST_PRIVACY"}

    store = store_section(cfg)
    declared = store.get("storeHostPrivacy")
    if isinstance(declared, str) and declared.strip().lower() in {"private", "public"}:
        return {
            "verdict": "ok",
            "storeHostPrivacy": declared.strip().lower(),
            "source": "config-declared",
        }

    provider = str(store.get("issuesProvider", "none")).strip().lower()
    if provider not in SHIPPED_ISSUES_PROVIDERS:
        return {
            "verdict": "ok",
            "storeHostPrivacy": "public",
            "source": "issues-provider-none",
            "provider": provider,
        }

    if provider == "jira":
        jpv = store.get("jiraProjectVisibility")
        if isinstance(jpv, str):
            vis = jpv.strip().lower()
            if vis == "private":
                return {"verdict": "ok", "storeHostPrivacy": "private", "source": "jiraProjectVisibility"}
            if vis in {"public", "shared"}:
                return {"verdict": "ok", "storeHostPrivacy": "public", "source": "jiraProjectVisibility"}
        # R14 — no placeholder always-unknown fallback: probe the live permission
        # scheme before giving up, so Jira gets the same host-API evaluation as the
        # other shipped providers rather than a config-declared-only check.
        from planning_jira_probe import resolve_jira_api_project_key

        project_key = resolve_jira_api_project_key(cfg, root=root)
        if project_key:
            is_private = _jira_store_project_browse_private(root, cfg, project_key)
            if is_private is True:
                return {
                    "verdict": "ok",
                    "storeHostPrivacy": "private",
                    "source": "host-api",
                    "provider": provider,
                    "projectKey": project_key,
                }
            if is_private is False:
                return {
                    "verdict": "ok",
                    "storeHostPrivacy": "public",
                    "source": "host-api",
                    "provider": provider,
                    "projectKey": project_key,
                }
        return {
            "verdict": "ok",
            "storeHostPrivacy": "unknown",
            "source": "probe-inconclusive",
            "provider": provider,
        }

    location = resolve_store_location(root, cfg)
    if location.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "error": location.get("error", "store-location-unresolved"),
            "storeHostPrivacy": "unknown",
        }

    owner = str(location.get("owner") or "").strip()
    repo = str(location.get("repo") or "").strip()
    if not owner or not repo:
        return {"verdict": "ok", "storeHostPrivacy": "unknown", "source": "store-location-incomplete"}

    if provider == "github-issues":
        is_private = _github_store_repo_private(root, cfg, owner, repo)
        if is_private is True:
            return {
                "verdict": "ok",
                "storeHostPrivacy": "private",
                "source": "host-api",
                "owner": owner,
                "repo": repo,
                "provider": provider,
            }
        if is_private is False:
            return {
                "verdict": "ok",
                "storeHostPrivacy": "public",
                "source": "host-api",
                "owner": owner,
                "repo": repo,
                "provider": provider,
            }
        return {
            "verdict": "ok",
            "storeHostPrivacy": "unknown",
            "source": "probe-inconclusive",
            "owner": owner,
            "repo": repo,
            "provider": provider,
        }

    # R14 — no other shipped provider reaches this point: jira returns early above,
    # and gitlab-issues is deferred/fail-closed (R7) and excluded from
    # SHIPPED_ISSUES_PROVIDERS, so it never reaches probe_store_host_privacy at all.
    # This is a defensive guard for a future shipped provider, not a placeholder
    # always-false branch for a provider that is (misleadingly) advertised as shipped.
    return {"verdict": "ok", "storeHostPrivacy": "unknown", "source": "unsupported-provider", "provider": provider}


def issue_store_private_enough(cfg: dict[str, Any], root: Path | None = None) -> bool:
    """True when private/memory artifacts may be written to the configured issue store."""
    worktree = root if root is not None else git_root()
    probe = probe_store_host_privacy(worktree, cfg)
    return probe.get("storeHostPrivacy") == "private"


def issue_store_visibility_allowed(
    root: Path,
    cfg: dict[str, Any],
    unit_id: str,
    body_path: str,
    content: str,
) -> bool:
    artifact_type = require_artifact_type(body_path, content=content)
    unit: dict[str, Any] = {
        "id": unit_id,
        "type": artifact_type,
        "bodyPath": body_path,
    }
    explicit = parse_visibility_from_content(content)
    if explicit:
        unit["visibility"] = explicit
    resolved = planning_visibility.resolve_unit_visibility(unit, cfg)
    if planning_visibility.body_is_redacted(resolved["visibility"]):
        return issue_store_private_enough(cfg, root)
    return True


def issue_store_visibility_gate(
    root: Path,
    cfg: dict[str, Any],
    unit_id: str,
    body_path: str,
    content: str,
) -> None:
    if issue_store_visibility_allowed(root, cfg, unit_id, body_path, content):
        return
    artifact_type = require_artifact_type(body_path, content=content)
    unit: dict[str, Any] = {
        "id": unit_id,
        "type": artifact_type,
        "bodyPath": body_path,
    }
    explicit = parse_visibility_from_content(content)
    if explicit:
        unit["visibility"] = explicit
    resolved = planning_visibility.resolve_unit_visibility(unit, cfg)
    fail(
        "private-visibility-refused-for-public-issue-store",
        code="visibility-refused",
        visibility=resolved["visibility"],
        unitId=unit_id,
    )


def handle_issue_client_error(exc: Exception) -> None:
    if isinstance(exc, IssueBudgetExhausted):
        fail(str(exc), code="deliver-aborted-inconsistent")
    if isinstance(exc, IssueTombstone):
        fail(str(exc), code="lifecycle-tombstone")
    if isinstance(exc, IssueTransferred):
        fail(str(exc), code="issue-transferred")
    if isinstance(exc, IssueLifecycleDrift):
        fail(str(exc), code="lifecycle-drift")
    if isinstance(exc, IssueArchivedProject):
        fail(str(exc), code="archived-project")
    if isinstance(exc, IssueTypeConverted):
        fail(str(exc), code="issue-type-converted")
    if isinstance(exc, IssueCapabilityError):
        fail(str(exc), code="issues-capability")


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


MATERIALIZE_MISSING_FROZEN_BODY = "materialize:missing-frozen-body"


def materialize_missing_result(unit_id: str, body_path: str, backend_id: str) -> StoreResult:
    """Typed fail-closed cause when a frozen body cannot be materialized (PRD 069 R5)."""
    return StoreResult("missing", unit_id, body_path, backend_id, reason=MATERIALIZE_MISSING_FROZEN_BODY)


def finalize_materialize_from_get(
    got: StoreResult,
    unit_id: str,
    body_path: str,
    backend_id: str,
    dest_path: Path,
) -> StoreResult:
    """Write materialized body to dest or return typed missing-frozen-body (PRD 069 R5)."""
    content = got.content
    if got.verdict != "ok" or content is None or (isinstance(content, str) and not content.strip()):
        return materialize_missing_result(unit_id, body_path, backend_id)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(content, encoding="utf-8")
    log_operation("materialize", unit_id, body_path, content, backend_id)
    return StoreResult("ok", unit_id, body_path, backend_id, content=content, hash=got.hash or content_hash(content))




def _native_status_from_content(content: str, *, artifact_type: str, state: str = "open", labels: list[str] | None = None) -> str:
    import planning_discover as pd

    class _Record:
        def __init__(self, body: str, lbls: list[str], st: str, unit_id: str, atype: str) -> None:
            self.body = body
            self.labels = lbls
            self.state = st
            self.unit_id = unit_id
            self.artifact_type = atype

    return pd._status_from_record(
        _Record(content, list(labels or []), state, "", artifact_type),
        content,
    )


def _unified_status_from_native(native_status: str, artifact_type: str) -> str:
    import planning_unit_status as pus

    return pus.map_native_status_to_unified(native_status, artifact_type)


class PlanningStoreBackend(ABC):
    backend_id: str

    def __init__(self, root: Path, cfg: dict[str, Any]) -> None:
        self.root = root
        self.cfg = cfg

    def _guard_duplicate_open_tasks_mint(self, unit_id: str) -> None:
        """Refuse minting a second open tasks issue for the same PRD slug (PRD 068 R8)."""
        if not unit_id.startswith("tasks"):
            return
        my_tail = _tasks_tail_from_unit_id(unit_id)
        search = getattr(self._client, "issue_search", None)
        if not callable(search):
            return
        for record in search(project_key=self.project_key, artifact_type="tasks"):
            other_id = str(getattr(record, "unit_id", "") or "").strip()
            if not other_id or other_id == unit_id:
                continue
            if not _tasks_slug_family_compatible(my_tail, _tasks_tail_from_unit_id(other_id)):
                continue
            labels = list(getattr(record, "labels", []) or [])
            if (
                str(getattr(record, "state", "")) == "open"
                and FROZEN_LABEL not in labels
                and status_from_labels(labels) != "complete"
            ):
                fail(
                    "duplicate-open-tasks-refused",
                    code="duplicate-open-tasks",
                    unitId=unit_id,
                    existingUnitId=other_id,
                )

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

    def derive_unit_status(self, unit_id: str, body_path: str) -> str:
        """Map backend-native state to the unified four-state surface (+ unknown)."""
        result = self.get(unit_id, body_path)
        if result.verdict != "ok" or not result.content:
            return "unknown"
        artifact_type = infer_artifact_type(body_path)
        native = _native_status_from_content(result.content, artifact_type=artifact_type)
        return _unified_status_from_native(native, artifact_type)



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
        got = self.get(unit_id, body_path)
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)



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


def load_put_journal(root: Path) -> dict[str, Any]:
    """R26 -- load the partial-write journal (keyed by ``issue_index_key``)."""
    path = root / PUT_JOURNAL_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entries = data.get("units") if isinstance(data, dict) else None
    return entries if isinstance(entries, dict) else {}


def save_put_journal(root: Path, journal: dict[str, Any]) -> None:
    path = root / PUT_JOURNAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "units": journal}, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


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
        self._journal = load_put_journal(root)


    def derive_unit_status(self, unit_id: str, body_path: str) -> str:
        import planning_discover as pd
        try:
            record = self._lookup_record(unit_id, body_path)
        except IssueNotFound:
            return "unknown"
        if record is None:
            return "unknown"
        content = strip_markers_and_edges(reassemble_body(record.body, record.comments))
        native = pd._status_from_record(record, content)
        artifact_type = self._resolve_artifact_type(
            body_path, record=record, content=content, unit_id=unit_id
        )
        return _unified_status_from_native(native, artifact_type)

    def _resolve_artifact_type(
        self,
        body_path: str,
        *,
        record: Any | None = None,
        content: str | None = None,
        caller_type: str | None = None,
        unit_id: str | None = None,
    ) -> str:
        record_type = record.artifact_type if record is not None and record.artifact_type else None
        record_labels = list(record.labels) if record is not None and record.labels else None
        record_content = content
        if record is not None and not artifact_type_from_content(content or ""):
            record_content = strip_markers_and_edges(reassemble_body(record.body, record.comments))
        try:
            return require_artifact_type(
                body_path,
                record_type=record_type,
                content=record_content,
                caller_type=caller_type,
                labels=record_labels,
            )
        except ArtifactTypeUnresolved:
            fail(
                "artifact-type-unresolved",
                code="artifact-type-unresolved",
                bodyPath=body_path,
                unitId=unit_id,
            )

    def _issue_title(self, artifact_type: str, unit_id: str, content: str) -> str:
        # R11: human-readable title (doc H1 / frontmatter `title:`) instead of
        # the legacy `[project] type:unit-id` prefix -- see
        # `planning_canonical.human_readable_title` for the fallback chain.
        return human_readable_title(content, artifact_type, unit_id)

    def _labels_for(self, artifact_type: str, unit_id: str, content: str) -> list[str]:
        # R11: `unit_id_label` plus the doc's structural frontmatter keys
        # (status/topic/depends/absorbs/amends/visibility) are additive
        # provider-native label projections -- never a substitute for the
        # frontmatter itself, which stays embedded in `content` (dual-read
        # window, D5). Recomputed on every put() so an old (pre-R11) issue's
        # labels are backfilled the next time it is written through this
        # path, in addition to the read-time backfill in `_lookup_record`.
        labels = {project_label(self.project_key), type_label(artifact_type), unit_id_label(unit_id)}
        labels.update(structural_labels_from_content(content))
        return sorted(labels)

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

    def _canonical_content_from_record(self, record: Any, unit_id: str) -> str:
        operator_content = self._extract_content(record)
        if has_raw_yaml_frontmatter(operator_content):
            return operator_content
        if is_hybrid_operator_body(operator_content):
            return canonical_content_from_operator(
                list(record.labels),
                operator_content,
                unit_id=unit_id,
            )
        return operator_content

    def _resolve_canonical_body_for_op(
        self,
        unit_id: str,
        body_path: str,
        record: Any,
        *,
        projection_mirrors: list[dict[str, Any]] | None = None,
        prefer: str | None = None,
    ) -> dict[str, Any]:
        """R26 — get/freeze resolve LCD Issue or Document-backed body; never projection SoT."""
        content = self._canonical_content_from_record(record, unit_id)
        labels = list(getattr(record, "labels", []) or [])
        resolved = resolve_canonical_freeze_body(
            unit_id=unit_id,
            body_path=body_path,
            body=content,
            labels=labels,
            projection_mirrors=projection_mirrors,
            prefer=prefer,
        )
        if resolved.get("verdict") != "pass":
            fail(
                str(resolved.get("error") or "canonical-body-unresolved"),
                code=str(resolved.get("error") or "canonical-body-unresolved"),
                unitId=unit_id,
                bodyPath=body_path,
                bodySource=resolved.get("bodySource"),
                typedDrift=resolved.get("typedDrift"),
            )
        return resolved

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


    def _verify_frozen_integrity(self, record: Any) -> None:
        if FREEZE_INCOMPLETE_LABEL in record.labels:
            fail("freeze-incomplete", code="freeze-incomplete", unitId=record.unit_id)
        if FROZEN_LABEL not in record.labels:
            return
        recorded = parse_freeze_record_hash(record.comments)
        if not recorded:
            fail("missing-freeze-record", code="lifecycle-tombstone", unitId=record.unit_id)
        current = canonical_hash(self._record_to_snapshot(record))
        if current != recorded:
            fail(
                "tamper-detected",
                code="tamper-detected",
                unitId=record.unit_id,
                recordedHash=recorded,
                currentHash=current,
            )

    def _guard_write_visibility(self, unit_id: str, body_path: str, content: str) -> None:
        issue_store_visibility_gate(self.root, self.cfg, unit_id, body_path, content)

    def _guard_write_secrets(self, *texts: str, path_hint: str | None = None) -> None:
        for chunk in texts:
            if chunk:
                secret_scan_text(chunk, path_hint=path_hint)

    def _find_linked_brainstorm(self, prd_unit_id: str) -> Any | None:
        matches = self._client.issue_search(project_key=self.project_key, artifact_type="brainstorm")
        for record in matches:
            full_body = reassemble_body(record.body, record.comments)
            edges = parse_edges_block(full_body)
            if not edges:
                continue
            for edge in edges.get("edges") or []:
                if isinstance(edge, dict) and edge.get("target") == prd_unit_id:
                    return record
        return None

    def _distill_brainstorm_rationale(self, brainstorm: Any, prd_unit_id: str) -> dict[str, Any]:
        if os.environ.get("SW_FREEZE_DISTILL_FAIL", "").strip() in {"1", "true", "yes"}:
            raise RuntimeError("distillation-forced-fail")
        content = self._extract_content(brainstorm)
        if contains_raw_transcript(content):
            raise RuntimeError("raw-transcript-in-brainstorm")
        excerpt = content[:4000]
        redacted = redact_content(excerpt)
        mem = MemoryLocalCacheBackend(self.root, self.cfg)
        mem_result = mem.put(
            f"brainstorm-{brainstorm.unit_id}",
            f"docs/brainstorms/{brainstorm.unit_id}.md",
            redacted,
            content_class="research",
        )
        pointer = (
            f"<!-- sw-memory-pointer -->\n"
            f"memoryUnit: {mem_result.unit_id}\n"
            f"prdUnit: {prd_unit_id}\n"
            f"brainstormUnit: {brainstorm.unit_id}\n"
        )
        self._guard_write_secrets(pointer, path_hint="freeze-memory-pointer")
        self._client.issue_comment(brainstorm.id, pointer, markers=["sw-memory-pointer"])
        closed = self._client.issue_update(brainstorm.id, state="closed", if_match=brainstorm.etag)
        return {"memoryUnitId": mem_result.unit_id, "brainstormUnitId": brainstorm.unit_id, "etag": closed.etag}

    def _maybe_backfill_labels(self, record: Any, unit_id: str) -> Any:
        """R11 dual-read backfill: an issue resolved via the pre-R11 body-
        marker/frontmatter fallback (no `sw:unit:*` / `sw:<type>` label yet)
        gets those structural labels written back immediately, so the next
        read/discover pass no longer needs the body fallback for it. Best
        effort only -- a frozen/put-incomplete issue, a stale etag, or a
        provider error here must never block the read or put already in
        progress; the label projection simply catches up on the next write.
        """
        if FROZEN_LABEL in record.labels or PUT_INCOMPLETE_LABEL in record.labels:
            return record
        content = strip_markers_and_edges(reassemble_body(record.body, record.comments))
        artifact_type = (
            record.artifact_type
            or artifact_type_from_labels(record.labels)
            or artifact_type_from_content(content)
        )
        if not is_resolved_artifact_type(artifact_type):
            return record
        missing: set[str] = set()
        if not unit_id_from_labels(record.labels):
            missing.add(unit_id_label(unit_id))
        if artifact_type and not artifact_type_from_labels(record.labels):
            missing.add(type_label(artifact_type))
        if not missing:
            return record
        try:
            updated = self._client.issue_label(
                record.id,
                sorted(set(record.labels) | missing),
                if_match=record.etag,
            )
        except (
            IssueRevisionConflict,
            IssueCapabilityError,
            IssueBudgetExhausted,
            IssueTombstone,
            IssueTransferred,
        ):
            return record
        except RuntimeError:
            # Provider-level HTTP error (e.g. GitHub 422 invalid-label-name on an
            # oversized `sw:unit:<id>` -- gap-085): the label projection is a
            # purely additive optimization over the frontmatter/body-marker dual
            # -read source of truth, never the read/put's source of truth itself,
            # so degrade to a no-op exactly as this method's own docstring
            # promises rather than propagating an uncaught traceback.
            return record
        return updated

    def _lookup_record(self, unit_id: str, body_path: str, *, content: str | None = None) -> Any:
        for candidate in unit_id_lookup_candidates(self.root, unit_id):
            record = self._lookup_record_candidate(candidate, body_path, content=content)
            if record is not None:
                return record
        raise IssueNotFound(f"no issue for unit {unit_id}")

    def _lookup_record_candidate(self, unit_id: str, body_path: str, *, content: str | None = None) -> Any | None:
        idx_key = issue_index_key(self.project_key, unit_id)
        issue_id = self._index.get(idx_key)
        if issue_id:
            try:
                record = self._client.issue_get(issue_id)
            except IssueNotFound:
                record = None
            except (IssueTombstone, IssueTransferred, IssueBudgetExhausted) as exc:
                handle_issue_client_error(exc)
            else:
                if verify_project_scope(record.body, self.project_key):
                    return self._maybe_backfill_labels(record, unit_id)
        search_kwargs: dict[str, Any] = {
            "project_key": self.project_key,
            "unit_id": unit_id,
        }
        path_inferred = infer_artifact_type(body_path)
        if path_inferred != ARTIFACT_TYPE_UNRESOLVED:
            search_kwargs["artifact_type"] = path_inferred
        elif content:
            content_type = artifact_type_from_content(content)
            if content_type:
                search_kwargs["artifact_type"] = content_type
        matches = self._client.issue_search(**search_kwargs)
        if not matches:
            return None
        record = matches[0]
        self._index[idx_key] = record.id
        save_issue_unit_index(self.root, self._index)
        self._register_native_unit_alias(unit_id, record)
        return self._maybe_backfill_labels(record, unit_id)


    def _register_native_unit_alias(self, caller_unit_id: str, record: Any) -> None:
        """R19 — index namespaced native ids and legacy compatibility aliases."""
        native_id = format_native_unit_id(self.issues_provider, int(record.number))
        if is_namespaced_native_unit_id(caller_unit_id):
            canonical = caller_unit_id
        else:
            canonical = native_id
            register_legacy_unit_mapping(self.root, caller_unit_id, native_id)
        self._index[issue_index_key(self.project_key, canonical)] = record.id
        if caller_unit_id != canonical:
            self._index[issue_index_key(self.project_key, caller_unit_id)] = record.id
        save_issue_unit_index(self.root, self._index)

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        reject_bare_integer_unit_id(unit_id)
        self._guard_write_visibility(unit_id, body_path, content)
        self._guard_write_secrets(content, path_hint=body_path)
        existing: Any | None
        try:
            existing = self._lookup_record(unit_id, body_path, content=content)
        except IssueNotFound:
            existing = None
        artifact_type = self._resolve_artifact_type(
            body_path, record=existing, content=content, unit_id=unit_id
        )
        if existing is None and artifact_type == "tasks":
            self._guard_duplicate_open_tasks_mint(unit_id)
        title = self._issue_title(artifact_type, unit_id, content)
        labels = self._labels_for(artifact_type, unit_id, content)
        store_content = operator_body_from_canonical(content) if has_raw_yaml_frontmatter(content) else content
        body = compose_issue_body(self.project_key, artifact_type, unit_id, store_content)
        body, extra_comments = chunk_body_if_needed(body, [], provider=self.issues_provider)
        idx_key = issue_index_key(self.project_key, unit_id)
        chunked = bool(extra_comments)
        # R26: a chunked put cannot commit its head body, its overflow
        # comments, and its real-id manifest rewrite in one atomic provider
        # call. Mark the issue `sw:put-incomplete` for the duration of that
        # multi-step write so a crash mid-flight leaves a durable, doctor-
        # visible signal instead of a manifest silently pointing at synthetic
        # ids that were never a real comment. Cleared only once the manifest
        # rewrite below actually succeeds.
        head_labels = sorted(set(labels) | {PUT_INCOMPLETE_LABEL}) if chunked else labels
        if existing is None:
            record = self._client.issue_create(
                title=title,
                body=body,
                labels=head_labels,
                project_key=self.project_key,
                artifact_type=artifact_type,
                unit_id=unit_id,
            )
        else:
            record = existing
            try:
                record = self._client.issue_update(
                    record.id,
                    title=title,
                    body=body,
                    labels=head_labels,
                    if_match=record.etag,
                )
            except IssueRevisionConflict as exc:
                fail(
                    "revision-conflict",
                    code="revision-conflict",
                    expected=exc.expected,
                    actual=exc.actual,
                )
        # R26: persist the unit->issue index (and, for a chunked body, a
        # journal entry) immediately after the head write succeeds -- before
        # posting a single overflow comment -- so a crash anywhere past this
        # point still resolves a retry of this same unit id back to THIS
        # issue instead of minting a duplicate (idempotent resume).
        self._index[idx_key] = record.id
        save_issue_unit_index(self.root, self._index)
        self._register_native_unit_alias(unit_id, record)
        if chunked:
            self._journal[idx_key] = {
                "unitId": unit_id,
                "issueId": record.id,
                "step": "body-written",
                "expectedChunks": len(extra_comments),
                "postedCommentIds": [],
            }
            save_put_journal(self.root, self._journal)
        chunk_comment_ids: list[str] = []
        for comment in extra_comments:
            self._guard_write_secrets(comment.body, path_hint=body_path)
            posted = self._client.issue_comment(record.id, comment.body, markers=comment.markers)
            chunk_comment_ids.append(posted.id)
            record = self._client.issue_get(record.id)
            self._journal[idx_key]["step"] = "comments-pending"
            self._journal[idx_key]["postedCommentIds"] = list(chunk_comment_ids)
            save_put_journal(self.root, self._journal)
        if chunk_comment_ids:
            # R8: `body` still carries the synthetic placeholder chunk ids
            # assigned before the provider issued real comment ids above;
            # rewrite the manifest with the real ids before persisting so
            # `reassemble_body` matches comments directly instead of falling
            # back to positional matching, which can select a stale overflow
            # comment left over from an earlier put.
            rewritten_body = rewrite_chunk_manifest_ids(body, chunk_comment_ids)
            final_labels = sorted(set(record.labels) - {PUT_INCOMPLETE_LABEL})
            if rewritten_body != record.body or final_labels != sorted(record.labels):
                try:
                    record = self._client.issue_update(
                        record.id,
                        body=rewritten_body,
                        labels=final_labels,
                        if_match=record.etag,
                    )
                except IssueRevisionConflict as exc:
                    # R26: fail closed -- the issue is left at its prior
                    # (pre-this-update) etag, still carrying
                    # PUT_INCOMPLETE_LABEL and its journal entry, both
                    # visible to `planning-doctor.py` (`put-partial`,
                    # `chunk-cardinality-mismatch`) until a retry converges.
                    fail(
                        "revision-conflict",
                        code="revision-conflict",
                        expected=exc.expected,
                        actual=exc.actual,
                    )
                record = self._client.issue_get(record.id)
        if chunked:
            self._journal.pop(idx_key, None)
            save_put_journal(self.root, self._journal)
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
        except (IssueTombstone, IssueTransferred, IssueBudgetExhausted) as exc:
            handle_issue_client_error(exc)
        self._verify_frozen_integrity(record)
        # R26 — facade get resolves canonical LCD/Document-backed body; never prefers projection.
        resolved = self._resolve_canonical_body_for_op(unit_id, body_path, record)
        content = str(resolved["body"])
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
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)

    def freeze(self, unit_id: str, body_path: str, *, distill: bool = True) -> dict[str, Any]:
        try:
            record = self._lookup_record(unit_id, body_path)
        except IssueNotFound:
            fail("issue-not-found", code="not-found", unitId=unit_id)
        except (IssueTombstone, IssueTransferred, IssueBudgetExhausted) as exc:
            handle_issue_client_error(exc)
        # R26 — freeze/hash SoT is LCD Issue or Document-backed body via facade resolution.
        resolved = self._resolve_canonical_body_for_op(unit_id, body_path, record)
        self._guard_write_visibility(unit_id, body_path, str(resolved["body"]))
        if FROZEN_LABEL in record.labels:
            fail("already-frozen", code="already-frozen", unitId=unit_id)
        try:
            record = self._client.issue_lock(record.id, if_match=record.etag)
            labels = sorted(set(record.labels) | {FROZEN_LABEL})
            record = self._client.issue_label(record.id, labels, if_match=record.etag)
            digest = canonical_hash(self._record_to_snapshot(record))
            freeze_body = build_freeze_record_body(digest)
            self._guard_write_secrets(freeze_body, path_hint="sw-freeze-record")
            self._client.issue_comment(record.id, freeze_body, markers=["sw-freeze-record"])
            record = self._client.issue_get(record.id)
        except IssueRevisionConflict as exc:
            fail("revision-conflict", code="revision-conflict", expected=exc.expected, actual=exc.actual)
        except (IssueBudgetExhausted, IssueTombstone, IssueTransferred) as exc:
            handle_issue_client_error(exc)

        distillation: dict[str, Any] | None = None
        freeze_content = self._extract_content(record)
        artifact_type = self._resolve_artifact_type(
            body_path, record=record, content=freeze_content, unit_id=unit_id
        )
        if distill and artifact_type == "prd":
            brainstorm = self._find_linked_brainstorm(unit_id)
            if brainstorm is not None:
                try:
                    distillation = self._distill_brainstorm_rationale(brainstorm, unit_id)
                except Exception as exc:  # noqa: BLE001 — fail-closed R48
                    labels = sorted(set(record.labels) | {FREEZE_INCOMPLETE_LABEL})
                    try:
                        record = self._client.issue_label(record.id, labels, if_match=record.etag)
                    except Exception:
                        pass
                    fail("freeze-incomplete", code="freeze-incomplete", reason=str(exc))

        absorb_linkage: dict[str, Any] | None = None
        if artifact_type == "prd":
            absorb_linkage = self._ensure_absorb_linkage_at_freeze(unit_id, freeze_content)
            if absorb_linkage.get("verdict") == "fail":
                labels = sorted(set(record.labels) | {FREEZE_INCOMPLETE_LABEL})
                try:
                    record = self._client.issue_label(record.id, labels, if_match=record.etag)
                except Exception:
                    pass
                fail(
                    "freeze-incomplete",
                    code="freeze-incomplete",
                    unitId=unit_id,
                    reason="absorb-linkage-failed",
                    absorbLinkage=absorb_linkage,
                )

        log_operation("freeze", unit_id, body_path, None, self.backend_id)
        return {
            "verdict": "ok",
            "unitId": unit_id,
            "bodyPath": body_path,
            "hash": digest,
            "locked": True,
            "labels": list(record.labels),
            "distillation": distillation,
            "bodySource": resolved.get("bodySource"),
            "freezeAuthority": resolved.get("freezeAuthority"),
            "absorbLinkage": absorb_linkage,
        }

    def _ensure_absorb_linkage_at_freeze(self, unit_id: str, content: str) -> dict[str, Any]:
        from planning_gap_capture import record_absorb_linkage

        fm = _migrate_issue_store().parse_frontmatter_fields(content)
        prd_num = _prd_number_from_unit_id(unit_id)
        absorbs = _parse_absorbs_targets(fm.get("absorbs", ""))
        gap_targets = [g for g in absorbs if "gap" in g or g.startswith("gap-")]
        planning_issues = parse_planning_issues_refs(fm.get("planningIssues", ""))
        if not gap_targets and not planning_issues:
            return {"verdict": "skipped", "reason": "no-absorb-targets"}
        return record_absorb_linkage(
            self.root,
            prd_unit_id=unit_id,
            prd_number=prd_num,
            gap_unit_ids=gap_targets or None,
            planning_issues=planning_issues or None,
            dry_run=False,
        )

    def verify_frozen_hash(self, unit_id: str, body_path: str) -> dict[str, Any]:
        try:
            record = self._lookup_record(unit_id, body_path)
        except IssueNotFound:
            fail("issue-not-found", code="not-found", unitId=unit_id)
        except (IssueTombstone, IssueTransferred, IssueBudgetExhausted) as exc:
            handle_issue_client_error(exc)
        if FREEZE_INCOMPLETE_LABEL in record.labels:
            fail("freeze-incomplete", code="freeze-incomplete", unitId=unit_id)
        if FROZEN_LABEL not in record.labels:
            fail("not-frozen", code="not-frozen", unitId=unit_id)
        recorded = parse_freeze_record_hash(record.comments)
        if not recorded:
            fail("missing-freeze-record", code="lifecycle-tombstone", unitId=unit_id)
        current = canonical_hash(self._record_to_snapshot(record))
        if current != recorded:
            fail(
                "tamper-detected",
                code="tamper-detected",
                unitId=unit_id,
                recordedHash=recorded,
                currentHash=current,
            )
        return {
            "verdict": "ok",
            "unitId": unit_id,
            "bodyPath": body_path,
            "hash": current,
            "recordedHash": recorded,
        }

    def link_brainstorm_to_prd(self, brainstorm_unit_id: str, prd_unit_id: str) -> dict[str, Any]:
        try:
            brainstorm = self._lookup_record(brainstorm_unit_id, f"docs/brainstorms/{brainstorm_unit_id}.md")
        except IssueNotFound:
            fail("brainstorm-issue-missing", code="brainstorm-missing")
        edges = [{"rel": "spawned", "target": prd_unit_id, "targetType": "prd"}]
        raw_content = self._canonical_content_from_record(brainstorm, brainstorm_unit_id)
        self._guard_write_visibility(brainstorm_unit_id, f"docs/brainstorms/{brainstorm_unit_id}.md", raw_content)
        self._guard_write_secrets(raw_content, path_hint=f"docs/brainstorms/{brainstorm_unit_id}.md")
        body = compose_issue_body(
            self.project_key,
            "brainstorm",
            brainstorm_unit_id,
            raw_content,
            edges=edges,
        )
        self._guard_write_secrets(body, path_hint=f"docs/brainstorms/{brainstorm_unit_id}.md")
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
        got = self.get(unit_id, body_path)
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)


class MemoryLocalCacheBackend(PlanningStoreBackend):
    """PRD 057 R21 — the `memory` backend's planning-body store.

    21a made the local cache (`.cursor/sw-memory/planning-bodies/`, gitignored per
    `.gitignore`) available unconditionally, independent of whether a memory provider
    is configured — see the R21a history below. 21b (this revision) adds a *real*
    round-trip through the configured provider's REST adapter on top of that cache:

    - `put()` always writes the local cache first (the R21a guarantee never
      regresses), then best-effort round-trips the redacted body through the
      Recallium REST adapter (`memory.provider: recallium` + a loopback-only
      `memory.connection.restBaseUrl`) via `_provider_round_trip_put`.
    - `get()` reads the local cache when present (fast path, unchanged from 21a).
      When the cache is missing — e.g. a fresh checkout on another machine, since
      the cache dir is gitignored — it attempts recovery through the same provider
      adapter (`_provider_round_trip_get`) and repopulates the local cache on
      success, before falling back to `missing`.
    - Any provider outage, timeout, non-2xx response, disallowed/unconfigured REST
      base, or non-`recallium` provider degrades to the R21a local-cache-only
      behavior — never a hard failure. See `_provider_round_trip_put`/`_get` and
      `_is_allowed_recallium_base`.
    - Round-trip bodies use a dedicated `/planning-bodies/<unitId>` REST resource,
      not the semantically-indexed memory-note REST collection: a full planning
      body is not a distilled memory note, and indexing raw bodies alongside them
      would pollute semantic search (see `core/providers/recallium.md`).

    `configured_provider()` still names whichever provider is configured for the
    skill's other memory operations (rules/decisions/etc. — see
    `core/skills/memory/SKILL.md`); frontmatter also records whether *this* body
    actually round-tripped (`providerRoundTrip`) and why not when it didn't
    (`providerRoundTripReason`).

    **R21a history:** prior to 21a, `_store_dir()` unconditionally called
    `fail(..., verdict="degraded")` (which `emit()` turns into `sys.exit(2)`)
    whenever no memory provider was configured — a hard CI failure for a purely
    local disk write. Removing that gate fixed the CI false-failure and the
    misleading-durability framing described in R21.
    """

    backend_id = "memory"

    def memory_project(self) -> str:
        memory = self.cfg.get("memory")
        if isinstance(memory, dict) and isinstance(memory.get("project"), str) and memory["project"].strip():
            return memory["project"].strip()
        return self.root.name

    def configured_provider(self) -> str | None:
        return resolve_memory_provider(self.root, self.cfg)

    def _provider_rest_base(self) -> str | None:
        if self.configured_provider() != "recallium":
            return None
        return _recallium_rest_base(self.cfg)

    def _round_trip_unavailable_reason(self) -> str:
        provider = self.configured_provider()
        if not provider:
            return "provider-not-configured"
        if provider != "recallium":
            return f"provider-not-round-trippable:{provider}"
        return "provider-rest-base-unavailable"

    def _local_cache_dir(self) -> Path:
        return self.root / ".cursor" / "sw-memory" / "planning-bodies" / self.memory_project()

    def _unit_path(self, unit_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", unit_id)
        return self._local_cache_dir() / f"{safe_id}.md"

    def _validate_class(self, content_class: str | None) -> None:
        if content_class and content_class.lower() in BANNED_MEMORY_CLASSES:
            fail(f"memory backend bans content class: {content_class}", code="banned-class")

    def _validate_content(self, content: str) -> None:
        if contains_raw_transcript(content):
            fail("raw transcript content refused by memory backend", code="raw-transcript")

    def _write_cache_file(
        self,
        unit_id: str,
        body_path: str,
        redacted: str,
        *,
        provider_round_trip: bool,
        round_trip_reason: str,
    ) -> Path:
        store_dir = self._local_cache_dir()
        store_dir.mkdir(parents=True, exist_ok=True)
        target = self._unit_path(unit_id)
        frontmatter = (
            "---\n"
            f"unitId: {unit_id}\n"
            f"bodyPath: {body_path}\n"
            f"project: {self.memory_project()}\n"
            f"configuredProvider: {self.configured_provider() or 'none'}\n"
            f"providerRoundTrip: {'true' if provider_round_trip else 'false'}\n"
            f"providerRoundTripReason: {round_trip_reason}\n"
            "localCacheFallback: true\n"
            "---\n"
        )
        target.write_text(frontmatter + redacted, encoding="utf-8")
        return target

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        self._validate_class(content_class)
        self._validate_content(content)
        redacted = redact_content(content)

        base = self._provider_rest_base()
        if base is not None:
            round_trip_ok, round_trip_reason = _provider_round_trip_put(
                base, self.memory_project(), unit_id, body_path, redacted
            )
        else:
            round_trip_ok = False
            round_trip_reason = self._round_trip_unavailable_reason()

        self._write_cache_file(
            unit_id, body_path, redacted, provider_round_trip=round_trip_ok, round_trip_reason=round_trip_reason
        )
        notice = (
            "provider round-trip ok (recallium); local cache also updated"
            if round_trip_ok
            else f"provider round-trip unavailable ({round_trip_reason}) -- served from R21a local cache"
        )
        log_operation("put", unit_id, body_path, redacted, self.backend_id, notice=notice)
        return StoreResult(
            "ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted), notice=notice
        )

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._unit_path(unit_id)
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            body = raw.split("---", 2)[-1].lstrip("\n") if raw.startswith("---") else raw
            redacted = redact_content(body)
            log_operation("get", unit_id, body_path, redacted, self.backend_id)
            return StoreResult("ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted))

        # 21b: the local cache is gitignored, so a fresh checkout on another
        # machine (or a wiped `.cursor/sw-memory/`) never had it. Attempt genuine
        # recovery through the provider adapter before declaring the unit missing.
        base = self._provider_rest_base()
        if base is not None:
            ok, reason, recovered = _provider_round_trip_get(base, self.memory_project(), unit_id)
            if ok and recovered is not None:
                redacted = redact_content(recovered)
                self._write_cache_file(
                    unit_id, body_path, redacted, provider_round_trip=True, round_trip_reason="ok"
                )
                notice = "recovered via provider round-trip (recallium); local cache repopulated"
                log_operation("get", unit_id, body_path, redacted, self.backend_id, notice=notice)
                return StoreResult(
                    "ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted), notice=notice
                )

        return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        present = self._unit_path(unit_id).is_file()
        if not present:
            base = self._provider_rest_base()
            if base is not None:
                ok, _reason, _content = _provider_round_trip_get(base, self.memory_project(), unit_id)
                present = ok
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)


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
    "memory": MemoryLocalCacheBackend,
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


def _resync_backup_path(dest_path: Path) -> Path:
    return dest_path.parent / f"{dest_path.name}.pre-resync.bak"


def _apply_ledger_checks(body: str, ledger_tasks: dict[str, Any]) -> tuple[str, int, int]:
    """Re-apply ledger-recorded checks onto a freshly materialized body (PRD 059 R9)."""
    from checkbox_diff import parse_task_checkboxes, toggle_checkbox

    applied = 0
    already_matching = 0
    checkboxes = parse_task_checkboxes(body)
    updated = body
    for ref, entry in sorted(ledger_tasks.items()):
        if not isinstance(entry, dict) or not entry.get("done"):
            continue
        if checkboxes.get(ref, False):
            already_matching += 1
            continue
        try:
            updated = toggle_checkbox(updated, ref, done=True)
            applied += 1
            checkboxes[ref] = True
        except ValueError:
            continue
    return updated, applied, already_matching


def _local_checked_ledger_unchecked(
    pre_resync_checkboxes: dict[str, bool],
    ledger_tasks: dict[str, Any],
) -> list[str]:
    """Subtasks checked locally before resync but absent or open in the ledger (PRD 059 R10)."""
    findings: list[str] = []
    for ref, checked in sorted(pre_resync_checkboxes.items()):
        if not checked:
            continue
        entry = ledger_tasks.get(ref) if isinstance(ledger_tasks, dict) else None
        if not isinstance(entry, dict) or not entry.get("done"):
            findings.append(ref)
    return findings


def _ledger_check_divergences(body: str, ledger_tasks: dict[str, Any]) -> list[dict[str, Any]]:
    from checkbox_diff import parse_task_checkboxes

    checkboxes = parse_task_checkboxes(body)
    divergences: list[dict[str, Any]] = []
    for ref, checked in checkboxes.items():
        entry = ledger_tasks.get(ref) if isinstance(ledger_tasks, dict) else None
        if not entry:
            if checked:
                divergences.append(
                    {"ref": ref, "kind": "stale", "reason": "checkbox-checked-missing-ledger"}
                )
            continue
        ledger_done = bool(entry.get("done"))
        if ledger_done != checked:
            divergences.append(
                {
                    "ref": ref,
                    "kind": "divergence",
                    "reason": "checkbox-ledger-mismatch",
                    "checkbox": checked,
                    "ledger": ledger_done,
                }
            )
    if isinstance(ledger_tasks, dict):
        for ref, entry in ledger_tasks.items():
            if not isinstance(entry, dict) or not entry.get("done"):
                continue
            if not checkboxes.get(ref, False):
                if not any(d.get("ref") == ref for d in divergences):
                    divergences.append(
                        {"ref": ref, "kind": "stale", "reason": "ledger-done-checkbox-open"}
                    )
    return divergences


def materialize_with_resync(
    root: Path,
    unit_id: str,
    body_path: str,
    dest_path: Path,
    *,
    state: dict[str, Any] | None = None,
    target: str | None = None,
    task_list: str | None = None,
) -> dict[str, Any]:
    """Rematerialize from store and re-apply deliver run-state ledger checks (PRD 059 R9-R12)."""
    from checkbox_diff import parse_task_checkboxes
    from planning_materialize import store_revision
    from wave_state import load_task_ledger

    cfg = load_workflow_config(root)
    backend = get_backend(root, cfg)
    dest_path = dest_path.resolve()
    pre_resync_text = dest_path.read_text(encoding="utf-8") if dest_path.is_file() else ""
    pre_resync_checkboxes = parse_task_checkboxes(pre_resync_text) if pre_resync_text else {}

    backup_path: Path | None = None
    if pre_resync_text:
        backup_path = _resync_backup_path(dest_path)
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(pre_resync_text, encoding="utf-8")

    materialized = backend.materialize(unit_id, body_path, dest_path)
    if materialized.verdict != "ok" or materialized.content is None:
        return {
            "verdict": "fail",
            "action": "materialize-resync",
            "error": materialized.reason or "materialize-failed",
            "unitId": unit_id,
            "bodyPath": body_path,
            "dest": str(dest_path),
        }

    ledger = load_task_ledger(root, target=target, task_list=task_list, state=state)
    ledger_tasks = ledger.get("tasks") or {}
    if not isinstance(ledger_tasks, dict):
        ledger_tasks = {}

    local_only = _local_checked_ledger_unchecked(pre_resync_checkboxes, ledger_tasks)
    body, checks_applied, checks_already_matching = _apply_ledger_checks(
        materialized.content, ledger_tasks
    )
    dest_path.write_text(body, encoding="utf-8")

    divergences = _ledger_check_divergences(body, ledger_tasks)
    divergence_refs = sorted(
        {
            *(local_only or []),
            *(
                d["ref"]
                for d in divergences
                if d.get("reason") == "checkbox-checked-missing-ledger"
            ),
        }
    )

    rel_dest = str(dest_path)
    try:
        rel_dest = str(dest_path.relative_to(git_root(root))).replace("\\", "/")
    except ValueError:
        pass

    follow_up = f"python3 scripts/wave_state.py {root} ledger check --tasks-file {body_path}"
    if divergence_refs:
        sample = divergence_refs[0]
        follow_up = (
            f"python3 scripts/wave_state.py {root} ledger record --task {sample} "
            f"--done true  # repeat for: {', '.join(divergence_refs)}"
        )

    result: dict[str, Any] = {
        "verdict": "ok" if not divergence_refs else "fail",
        "action": "materialize-resync",
        "dest": rel_dest,
        "unitId": unit_id,
        "bodyPath": body_path,
        "ledgerSource": {
            "unitId": unit_id,
            "revision": store_revision(cfg),
        },
        "checksApplied": checks_applied,
        "checksAlreadyMatching": checks_already_matching,
        "divergences": divergence_refs,
        "divergenceDetails": divergences,
        "localOnlyChecked": local_only,
        "backupPath": str(backup_path).replace("\\", "/") if backup_path else None,
        "followUpCommand": follow_up,
    }
    if divergence_refs:
        result["error"] = "local-checked-but-ledger-unchecked"
    return result


def materialize_from_store(
    root: Path,
    cfg: dict[str, Any],
    units: list[dict[str, str]],
) -> dict[str, Any]:
    """Re-materialize local file-store projections from the authoritative issue store.

    PRD 057 R31 wave-rollback recovery: after flipping the ``effective-backend``
    kill-switch back to the file-store default, an operator re-syncs local
    projections from the still-intact issue store so no authored content is lost.
    Reads the issue store explicitly (bypasses the kill-switch via
    ``override="issue-store"``); writes are local-only, idempotent, and never
    mutate or delete store data.
    """
    issue_backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(issue_backend, IssueStoreBackend):
        return {"verdict": "fail", "action": "materialize-from-store", "error": "issue-store-backend-required"}
    local_backend = InRepoPublicBackend(root, cfg)
    results: list[dict[str, Any]] = []
    ok = True
    for unit in units:
        unit_id = str(unit.get("unitId", "") or "")
        body_path = str(unit.get("bodyPath", "") or "")
        if not unit_id or not body_path:
            results.append({"unitId": unit_id, "bodyPath": body_path, "verdict": "fail", "error": "missing-unit-or-path"})
            ok = False
            continue
        fetched = issue_backend.get(unit_id, body_path)
        if fetched.verdict != "ok" or fetched.content is None or (
            isinstance(fetched.content, str) and not fetched.content.strip()
        ):
            results.append(
                {
                    "unitId": unit_id,
                    "bodyPath": body_path,
                    "verdict": "missing",
                    "reason": MATERIALIZE_MISSING_FROZEN_BODY,
                }
            )
            ok = False
            continue
        written = local_backend.put(unit_id, body_path, fetched.content)
        results.append({"unitId": unit_id, "bodyPath": body_path, "verdict": "ok", "hash": written.hash})
    return {
        "verdict": "ok" if ok else "partial",
        "action": "materialize-from-store",
        "count": len(units),
        "results": results,
        "dataLoss": False,
    }


def wave_regression_finding(
    root: Path,
    cfg: dict[str, Any],
    *,
    tracked_units: list[dict[str, str]] | None = None,
) -> dict[str, Any] | None:
    """Detect drift between local file-store projections and the issue store.

    PRD 057 R31: only meaningful while the ``effective-backend`` kill-switch is
    active (the code path that would normally keep them in sync is the thing
    being rolled back). Returns ``None`` (inert) when the kill-switch is off, the
    configured backend is not issue-store, or no units are under rollback
    supervision — never a false positive on ordinary file-store repos.
    """
    if not _effective_backend_kill_switch():
        return None
    if resolve_backend_id(cfg) != "issue-store":
        return None
    if tracked_units is None:
        rollback = store_section(cfg).get("waveRollback")
        tracked_units = rollback.get("trackedUnits") if isinstance(rollback, dict) else None
        if not isinstance(tracked_units, list):
            tracked_units = []
    if not tracked_units:
        return {"check": "wave-regression", "status": "ok", "reason": "no-tracked-units", "killSwitch": True}
    try:
        issue_backend = get_backend(root, cfg, override="issue-store")
    except SystemExit:
        return {"check": "wave-regression", "status": "unknown", "reason": "store-unreachable", "killSwitch": True}
    if not isinstance(issue_backend, IssueStoreBackend):
        return None
    local_backend = InRepoPublicBackend(root, cfg)
    drift: list[dict[str, Any]] = []
    checked = 0
    for unit in tracked_units:
        unit_id = str(unit.get("unitId", "") or "")
        body_path = str(unit.get("bodyPath", "") or "")
        if not unit_id or not body_path:
            continue
        try:
            store_result = issue_backend.get(unit_id, body_path)
        except SystemExit:
            continue
        if store_result.verdict != "ok":
            continue  # not this check's concern — reachability is covered separately
        checked += 1
        local_result = local_backend.get(unit_id, body_path)
        # Compare canonical *content*, not the raw `.hash` field: each backend
        # hashes with a different scheme (issue-store hashes the full record
        # snapshot via `canonical_hash`; in-repo-public truncates a sha256 of
        # the body only) so the hashes are never comparable across backends.
        if local_result.verdict != "ok" or local_result.content != store_result.content:
            drift.append({
                "unitId": unit_id,
                "bodyPath": body_path,
                "storeContentHash": content_hash(store_result.content or ""),
                "localContentHash": content_hash(local_result.content or "") if local_result.verdict == "ok" else None,
                "localVerdict": local_result.verdict,
            })
    if drift:
        return {
            "check": "wave-regression",
            "status": "drift",
            "killSwitch": True,
            "checkedUnits": checked,
            "driftedUnits": drift,
            "remediation": (
                "run `planning_store.py materialize-from-store --units-json ...` "
                "to re-sync local projections from the store"
            ),
        }
    return {"check": "wave-regression", "status": "ok", "killSwitch": True, "checkedUnits": checked}





def _migrate_issue_store():
    import planning_migrate_issue_store as pmis
    return pmis


def _invalidate_query_cache(root: Path) -> None:
    from planning_query_cache import invalidate_all
    invalidate_all(root)


CLOSURE_NON_GAP_ORDER = ("prd", "tasks", "brainstorm", "amendment", "decision")
CLOSURE_ARTIFACT_ORDER = {artifact: idx for idx, artifact in enumerate((*CLOSURE_NON_GAP_ORDER, "gap"))}


def _normalize_prd_unit_id(prd_unit_id: str) -> str:
    unit = prd_unit_id.strip()
    if unit.startswith("prd-"):
        return unit
    return unit


def _prd_unit_id_alias_candidates(prd_unit_id: str) -> list[str]:
    """PRD 060 R4 — canonical ``<n>-prd-<slug>`` plus legacy alias forms for closure lookup."""
    unit = prd_unit_id.strip()
    out: list[str] = []

    def _add(candidate: str) -> None:
        if candidate and candidate not in out:
            out.append(candidate)

    _add(unit)
    _add(_normalize_prd_unit_id(unit))
    m = re.match(r"^(\d{3})-prd-(.+)$", unit)
    if m:
        prd_num, slug = m.group(1), m.group(2)
        _add(f"prd-{prd_num}-{slug}")
        _add(f"{prd_num}-{slug}")
    m = re.match(r"^prd-(\d{3})-(.+)$", unit)
    if m:
        prd_num, slug = m.group(1), m.group(2)
        _add(f"{prd_num}-prd-{slug}")
        _add(f"{prd_num}-{slug}")
    m = re.match(r"^(\d{3})-(.+)$", unit)
    if m and "-prd-" not in unit:
        prd_num, slug = m.group(1), m.group(2)
        _add(f"{prd_num}-prd-{slug}")
        _add(f"prd-{prd_num}-{slug}")
    return out


def _gap_closure_evidence(
    fm: dict[str, str],
    edges: dict[str, Any] | None,
    prd_num: str | None,
    root: Path,
    cfg: dict[str, Any],
) -> tuple[set[str], list[dict[str, str]]]:
    """Classify gap units for closure: delivery-grade vs related-only skip (PRD 060 R6)."""
    delivery_grade: set[str] = set()
    skipped: list[dict[str, str]] = []

    for target in _parse_absorbs_targets(fm.get("absorbs", "")):
        if "gap" in target or target.startswith("gap-"):
            delivery_grade.add(target)

    related_only: set[str] = set()
    for edge in (edges or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        target = str(edge.get("target", "")).strip()
        if not target or ("gap" not in target and not target.startswith("gap-")):
            continue
        rel = str(edge.get("rel") or edge.get("relationship") or "depends").strip().lower()
        if rel == "absorbs":
            delivery_grade.add(target)
        else:
            related_only.add(target)

    if prd_num:
        for gap_id in _migrate_issue_store().gap_unit_ids_scheduled_for_prd(root, prd_num, cfg):
            if gap_id:
                delivery_grade.add(gap_id)

    for gap_id in sorted(related_only - delivery_grade):
        skipped.append({"unitId": gap_id, "reason": "related-only-not-delivery-grade"})

    return delivery_grade, skipped


def _discover_planning_issues_gaps(
    root: Path,
    cfg: dict[str, Any],
    *,
    prd_unit_id: str,
    fm: dict[str, str],
    edges: dict[str, Any] | None,
    prd_num: str | None,
    delivery_grade: set[str],
    skipped: list[dict[str, str]],
) -> tuple[set[str], list[dict[str, str]]]:
    """Augment expected gap set from provenance-bound planningIssues refs (R7)."""
    out = set(delivery_grade)
    skip = list(skipped)
    for ref in parse_planning_issues_refs(fm.get("planningIssues", "")):
        gap_id = resolve_planning_issue_ref_to_gap(root, cfg, ref)
        if not gap_id:
            skip.append({"ref": ref, "reason": "planning-issue-unresolved"})
            continue
        if gap_has_absorb_provenance(root, cfg, gap_id, prd_unit_id, fm, prd_num=prd_num, edges=edges):
            out.add(gap_id)
        else:
            skip.append({"ref": ref, "unitId": gap_id, "reason": "planning-issue-no-provenance"})
    return out, skip


def _prd_number_from_unit_id(unit_id: str) -> str | None:
    m = re.match(r"^prd-(\d{3})-", unit_id)
    if m:
        return m.group(1)
    m = re.match(r"^(\d{3})-", unit_id)
    if m:
        return m.group(1)
    return None


def _slug_from_prd_unit(unit_id: str, prd_num: str) -> str:
    canonical = f"{prd_num}-prd-"
    if unit_id.startswith(canonical):
        return unit_id[len(canonical) :]
    for prefix in (f"prd-{prd_num}-", f"{prd_num}-", "prd-"):
        if unit_id.startswith(prefix):
            return unit_id[len(prefix) :]
    return unit_id


def _tasks_unit_id_candidates(prd_unit: str, prd_num: str | None) -> list[str]:
    """Ordered tasks unit-id aliases for retrospective closure (PRD 060 R4 / PRD 067 R9).

    Includes first-class ``tasks-debug-<slug>`` forms used by thin debug→deliver packs.
    Ambiguous matches must fail closed at the caller (resolve_delivery_linked_units).
    """
    if not prd_num:
        return [f"tasks-{prd_unit}", f"tasks-debug-{prd_unit}"]
    slug = _slug_from_prd_unit(prd_unit, prd_num)
    candidates = [
        f"tasks-{prd_num}-{slug}",
        f"tasks-{prd_unit}",
        f"tasks-debug-{slug}",
        f"tasks-debug-{prd_num}-{slug}",
    ]
    legacy = f"{prd_num}-{slug}"
    if legacy != prd_unit:
        candidates.append(legacy)
    out: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in out:
            out.append(candidate)
    return out


def _tasks_tail_from_unit_id(unit_id: str) -> str:
    if unit_id.startswith("tasks-debug-"):
        return unit_id[len("tasks-debug-") :]
    if unit_id.startswith("tasks-"):
        return unit_id[len("tasks-") :]
    return unit_id


def _normalize_tasks_slug(tail: str) -> str:
    tail = tail.strip()
    m = re.match(r"^(\d{3})-prd-(.+)$", tail)
    if m:
        return m.group(2)
    m = re.match(r"^(\d{3})-(.+)$", tail)
    if m:
        return m.group(2)
    if tail.startswith("prd-"):
        return tail[4:]
    return tail


def _tasks_slug_family_compatible(left: str, right: str) -> bool:
    return _normalize_tasks_slug(left) == _normalize_tasks_slug(right)


def _record_artifact_type(record: Any) -> str:
    labels = list(getattr(record, "labels", []) or [])
    from_labels = artifact_type_from_labels(labels)
    if from_labels:
        return from_labels
    record_type = str(getattr(record, "artifact_type", "") or "").strip()
    if record_type:
        return record_type
    body = str(getattr(record, "body", "") or "")
    return parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""


def _parse_absorbs_targets(raw: str) -> list[str]:
    value = raw.strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            parsed = json.loads(value.replace("'", '"'))
        except json.JSONDecodeError:
            parsed = [part.strip().strip(chr(39) + chr(34)) for part in value.strip('[]').split(',') if part.strip()]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in value.split(",") if part.strip()]


def parse_planning_issues_refs(raw: str) -> list[str]:
    """Parse hybrid ``planningIssues`` frontmatter refs (PRD 068 R7)."""
    value = (raw or "").strip()
    if not value:
        return []
    if value.startswith("["):
        try:
            parsed = json.loads(value.replace("'", '"'))
        except json.JSONDecodeError:
            parsed = [part.strip().strip("'\"") for part in value.strip("[]").split(",") if part.strip()]
        if isinstance(parsed, list):
            return [_normalize_planning_issue_ref(str(item)) for item in parsed if str(item).strip()]
    return [_normalize_planning_issue_ref(part) for part in re.split(r"[\s,]+", value) if part.strip()]


def _normalize_planning_issue_ref(ref: str) -> str:
    ref = ref.strip().strip(chr(39) + chr(34))
    if ref.startswith("#"):
        ref = ref[1:]
    return ref


def resolve_planning_issue_ref_to_gap(
    root: Path,
    cfg: dict[str, Any],
    ref: str,
    *,
    backend: "IssueStoreBackend | None" = None,
) -> str | None:
    """Map a planning issue ref to a gap unit id via issue-store search (R7)."""
    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return None
    if backend is None:
        backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return None
    key_result = pmis.validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return None
    project_key = str(key_result["projectKey"])
    normalized = _normalize_planning_issue_ref(ref)
    issue_num = None
    m = re.search(r"(?:planning#|#)?(\d+)$", normalized, re.I)
    if m:
        issue_num = int(m.group(1))
    client = backend._client
    search = getattr(client, "issue_search", None)
    if not callable(search):
        return None
    for record in search(project_key=project_key, artifact_type="gap"):
        unit_id = str(getattr(record, "unit_id", "") or "").strip()
        if not unit_id:
            continue
        if issue_num is not None and int(getattr(record, "number", 0) or 0) == issue_num:
            return unit_id
        body = reassemble_body(record.body, record.comments)
        gap_fm = pmis.parse_frontmatter_fields(strip_markers_and_edges(body))
        related = str(gap_fm.get("related") or "")
        needles = {normalized, f"planning#{issue_num}" if issue_num else "", f"#{issue_num}" if issue_num else ""}
        if any(n and n in related for n in needles):
            return unit_id
    return None


def gap_has_absorb_provenance(
    root: Path,
    cfg: dict[str, Any],
    gap_unit_id: str,
    prd_unit_id: str,
    prd_fm: dict[str, str],
    *,
    prd_num: str | None = None,
    edges: dict[str, Any] | None = None,
) -> bool:
    """True when ``gap_unit_id`` is provenance-bound to ``prd_unit_id`` for closure (R7)."""
    from planning_gap_capture import gap_absorb_target_match

    absorbs = _parse_absorbs_targets(prd_fm.get("absorbs", ""))
    if any(gap_absorb_target_match(item, gap_unit_id) for item in absorbs):
        return True
    prd_num = prd_num or _prd_number_from_unit_id(prd_unit_id)
    if prd_num:
        scheduled = _migrate_issue_store().gap_unit_ids_scheduled_for_prd(root, prd_num, cfg)
        if gap_unit_id in scheduled:
            return True
    for edge in (edges or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        target = str(edge.get("target", "")).strip()
        rel = str(edge.get("rel") or edge.get("relationship") or "").strip().lower()
        if rel == "absorbs" and gap_absorb_target_match(target, gap_unit_id):
            return True
    backend = get_backend(root, cfg, override="issue-store")
    if isinstance(backend, IssueStoreBackend):
        gap_path = _default_body_path(gap_unit_id, "gap")
        gap_fetch = backend.get(gap_unit_id, gap_path)
        if gap_fetch.verdict == "ok" and gap_fetch.content:
            gap_fm = _migrate_issue_store().parse_frontmatter_fields(gap_fetch.content)
            absorbed_by = str(gap_fm.get("absorbed-by") or gap_fm.get("absorbed_by") or "").strip()
            if absorbed_by == prd_unit_id:
                return True
    return False


def _tasks_unit_selection_rank(record: Any) -> tuple[int, int, int, int]:
    labels = list(getattr(record, "labels", []) or [])
    frozen = FROZEN_LABEL in labels
    complete = status_from_labels(labels) == "complete" or str(getattr(record, "state", "")) == "closed"
    open_state = str(getattr(record, "state", "")) == "open" and not complete
    return (
        1 if frozen and complete else 0,
        1 if frozen else 0,
        1 if complete else 0,
        -1 if open_state else 0,
    )


def _select_tasks_unit_candidate(
    matched_tasks: list[tuple[str, Any]],
) -> dict[str, Any]:
    """Rank tasks aliases: prefer frozen+complete; open-dup → not-ready (PRD 068 R8)."""
    if not matched_tasks:
        return {"verdict": "missing"}
    if len(matched_tasks) == 1:
        uid, rec = matched_tasks[0]
        return {"verdict": "ok", "unitId": uid, "record": rec}
    ranked = sorted(matched_tasks, key=lambda item: _tasks_unit_selection_rank(item[1]), reverse=True)
    best_rank = _tasks_unit_selection_rank(ranked[0][1])
    top = [item for item in ranked if _tasks_unit_selection_rank(item[1]) == best_rank]
    frozen_complete = [item for item in matched_tasks if _tasks_unit_selection_rank(item[1])[0]]
    if len(frozen_complete) == 1:
        uid, rec = frozen_complete[0]
        return {"verdict": "ok", "unitId": uid, "record": rec, "resolution": "frozen-complete"}
    if len(top) == 1:
        uid, rec = top[0]
        return {"verdict": "ok", "unitId": uid, "record": rec, "resolution": "ranked"}
    open_dups = [
        uid
        for uid, rec in matched_tasks
        if str(getattr(rec, "state", "")) == "open" and FROZEN_LABEL not in list(getattr(rec, "labels", []) or [])
    ]
    if open_dups:
        return {
            "verdict": "not-ready",
            "error": "open-duplicate-tasks",
            "candidates": [uid for uid, _ in matched_tasks],
            "openDuplicates": open_dups,
            "failSoftGaps": True,
        }
    return {
        "verdict": "not-ready",
        "error": "ambiguous-tasks-unit",
        "candidates": [uid for uid, _ in matched_tasks],
        "failSoftGaps": True,
    }


def _record_prior_state(record: Any, artifact_type: str) -> str:
    if artifact_type == "gap":
        return gap_status_from_labels(list(record.labels)) or record.state
    return status_from_labels(list(record.labels)) or record.state


def _record_is_closed(record: Any, artifact_type: str) -> bool:
    if artifact_type == "gap":
        return record.state == "closed" and GAP_LABEL_RESOLVED in list(record.labels)
    return record.state == "closed" and status_from_labels(list(record.labels)) == "complete"


def _closure_labels_for(record: Any, artifact_type: str) -> list[str]:
    labels = list(record.labels)
    if artifact_type == "gap":
        pmis = _migrate_issue_store()
        return pmis._apply_gap_labels(labels, pmis.ArtifactLifecycle(issue_state="closed", gap_status="resolved"), "gap")
    out = [label for label in labels if not label.startswith("sw:status:")]
    out.append(status_label("complete"))
    return sorted(set(out))


def _lookup_issue_record(backend: "IssueStoreBackend", unit_id: str, body_path: str) -> Any:
    try:
        return backend._lookup_record(unit_id, body_path)
    except IssueNotFound:
        return None
    except (IssueTombstone, IssueTransferred, IssueBudgetExhausted) as exc:
        handle_issue_client_error(exc)
        return None


def _default_body_path(unit_id: str, artifact_type: str) -> str:
    if artifact_type == "brainstorm":
        return f"docs/brainstorms/{unit_id}.md"
    if artifact_type == "tasks":
        tasks_unit = unit_id
        if unit_id.startswith("tasks-"):
            tasks_unit = unit_id[len("tasks-") :]
        prd_num = _prd_number_from_unit_id(tasks_unit)
        if prd_num and tasks_unit.startswith(f"{prd_num}-"):
            slug = _slug_from_prd_unit(tasks_unit, prd_num)
            return f"docs/prds/{prd_num}-{slug}/tasks-{unit_id}.md"
        return f"docs/prds/tasks-{unit_id}.md"
    if artifact_type == "gap":
        return f"docs/planning/gap/{unit_id}/{unit_id}.md"
    if artifact_type == "prd":
        prd_num = _prd_number_from_unit_id(unit_id)
        if prd_num:
            slug = _slug_from_prd_unit(unit_id, prd_num)
            name = unit_id if unit_id.startswith("prd-") else f"prd-{unit_id}"
            return f"docs/prds/{prd_num}-{slug}/{name}.md"
    return f"docs/prds/{unit_id}/{unit_id}.md"


def resolve_delivery_linked_units(
    root: Path,
    cfg: dict[str, Any],
    prd_unit_id: str,
) -> dict[str, Any]:
    """Snapshot the complete linked-unit set for retrospective closure (PRD 059 R17)."""
    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return {"verdict": "fail", "error": "issue-store-required", "prdUnitId": prd_unit_id}
    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "fail", "error": "issue-store-backend-required", "prdUnitId": prd_unit_id}

    normalized = _normalize_prd_unit_id(prd_unit_id)
    candidates = _prd_unit_id_alias_candidates(prd_unit_id)
    prd_num = _prd_number_from_unit_id(normalized)
    seen: set[str] = set()
    prd_record = None
    prd_unit = ""
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        body_path = _default_body_path(candidate, "prd")
        prd_record = _lookup_issue_record(backend, candidate, body_path)
        if prd_record is None:
            continue
        if _record_artifact_type(prd_record) != "prd":
            continue
        prd_unit = candidate
        break
    if prd_record is None:
        return {"verdict": "fail", "error": "prd-unit-not-found", "prdUnitId": prd_unit_id}

    full_body = reassemble_body(prd_record.body, prd_record.comments)
    raw_content = strip_markers_and_edges(full_body)
    fm = _migrate_issue_store().parse_frontmatter_fields(raw_content)
    edges = parse_edges_block(full_body) or {}

    units: dict[str, dict[str, str]] = {}
    tasks_resolution: dict[str, Any] | None = None
    units[prd_unit] = {
        "unitId": prd_unit,
        "artifactType": "prd",
        "bodyPath": _default_body_path(prd_unit, "prd"),
    }

    if prd_num:
        # R9: collect all matching tasks unit ids; ambiguity fails closed
        matched_tasks: list[tuple[str, Any]] = []
        for tasks_id in _tasks_unit_id_candidates(prd_unit, prd_num):
            body_path = _default_body_path(tasks_id, "tasks")
            record = _lookup_issue_record(backend, tasks_id, body_path)
            if record is None:
                continue
            if _record_artifact_type(record) != "tasks":
                continue
            resolved_id = str(getattr(record, "unit_id", "") or tasks_id).strip() or tasks_id
            if not any(existing == resolved_id for existing, _ in matched_tasks):
                matched_tasks.append((resolved_id, record))
        if matched_tasks:
            tasks_resolution = _select_tasks_unit_candidate(matched_tasks)
            if tasks_resolution.get("verdict") == "ok":
                resolved_id = str(tasks_resolution["unitId"])
                units[resolved_id] = {
                    "unitId": resolved_id,
                    "artifactType": "tasks",
                    "bodyPath": _default_body_path(resolved_id, "tasks"),
                }
            elif not tasks_resolution.get("failSoftGaps"):
                return {
                    "verdict": "fail",
                    "error": tasks_resolution.get("error", "ambiguous-tasks-unit"),
                    "candidates": tasks_resolution.get("candidates", []),
                    "prdUnitId": prd_unit,
                }

    brainstorm_ref = (fm.get("brainstorm") or "").strip()
    brainstorm_unit = ""
    if brainstorm_ref:
        brainstorm_unit = Path(brainstorm_ref).stem
        if not brainstorm_unit.startswith("brainstorm"):
            brainstorm_unit = f"brainstorm-{brainstorm_unit}"
    linked = backend._find_linked_brainstorm(prd_unit)
    if linked is not None:
        brainstorm_unit = str(getattr(linked, "unit_id", "") or brainstorm_unit)
    if brainstorm_unit and brainstorm_unit not in units:
        units[brainstorm_unit] = {
            "unitId": brainstorm_unit,
            "artifactType": "brainstorm",
            "bodyPath": _default_body_path(brainstorm_unit, "brainstorm"),
        }

    gap_ids, gap_skipped = _gap_closure_evidence(fm, edges, prd_num, root, cfg)
    gap_ids, gap_skipped = _discover_planning_issues_gaps(
        root,
        cfg,
        prd_unit_id=prd_unit,
        fm=fm,
        edges=edges,
        prd_num=prd_num,
        delivery_grade=gap_ids,
        skipped=gap_skipped,
    )
    for gap_id in sorted(gap_ids):
        if gap_id in units:
            continue
        body_path = _default_body_path(gap_id, "gap")
        if _lookup_issue_record(backend, gap_id, body_path) is not None:
            units[gap_id] = {"unitId": gap_id, "artifactType": "gap", "bodyPath": body_path}

    ordered = sorted(
        units.values(),
        key=lambda item: (
            CLOSURE_ARTIFACT_ORDER.get(item["artifactType"], 99),
            item["unitId"],
        ),
    )
    payload: dict[str, Any] = {
        "verdict": "ok",
        "prdUnitId": prd_unit,
        "snapshot": ordered,
        "count": len(ordered),
        "skipped": gap_skipped,
        "planningIssues": parse_planning_issues_refs(fm.get("planningIssues", "")),
    }
    if tasks_resolution is not None and tasks_resolution.get("verdict") == "not-ready":
        payload["tasksResolution"] = tasks_resolution
        if not tasks_resolution.get("failSoftGaps"):
            payload["verdict"] = "not-ready"
            payload["error"] = tasks_resolution.get("error")
            payload["candidates"] = tasks_resolution.get("candidates", [])
    return payload


def _phase_done_from_state(state: dict[str, Any] | None, phase_id: str) -> bool:
    if not state:
        return False
    phases = state.get("phases") or {}
    meta = phases.get(str(phase_id)) if isinstance(phases, dict) else None
    if isinstance(meta, dict):
        status = str(meta.get("status") or "")
        if status in {"green-merged", "merge-ready-green", "complete"}:
            return True
    ledger = (state.get("taskLedger") or {}).get("phases") or {}
    phase_ledger = ledger.get(str(phase_id)) if isinstance(ledger, dict) else None
    if isinstance(phase_ledger, dict) and phase_ledger.get("declaredPartial"):
        return bool(phase_ledger.get("skippedRefs"))
    return False


def _collect_phase_sub_issue_candidates(
    root: Path,
    cfg: dict[str, Any],
    *,
    state: dict[str, Any] | None,
    tasks_unit_id: str | None,
) -> list[dict[str, str]]:
    """Resolve phase sub-issues from deliver ledger hierarchyMap with live store fallback (PRD 060 R5)."""
    from planning_progress import phase_done_label
    from wave_state import load_hierarchy_map

    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(phase_id: str, issue_id: str, unit_id: str) -> None:
        key = issue_id or unit_id
        if not phase_id or key in seen:
            return
        seen.add(key)
        candidates.append({"phaseId": phase_id, "issueId": issue_id, "unitId": unit_id})

    hmap = load_hierarchy_map(state) if state else {}
    for phase_id, entry in sorted((hmap.get("phases") or {}).items()):
        if not isinstance(entry, dict):
            continue
        issue_id = str(entry.get("issueId") or "")
        unit_id = str(entry.get("unitId") or "")
        if not unit_id and tasks_unit_id:
            unit_id = f"{tasks_unit_id}-phase-{phase_id}"
        _add(str(phase_id), issue_id, unit_id)

    if candidates or not tasks_unit_id:
        return candidates

    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return candidates
    key_result = pmis.validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return candidates
    project_key = str(key_result["projectKey"])
    client = pmis.cfg_issues_client(root)
    prefix = f"{tasks_unit_id}-phase-"
    search = getattr(client, "issue_search", None)
    if not callable(search):
        return candidates
    for record in search(project_key=project_key, artifact_type="tasks"):
        unit_id = str(getattr(record, "unit_id", "") or "")
        if not unit_id.startswith(prefix):
            continue
        phase_id = unit_id[len(prefix) :]
        if not phase_id.isdigit():
            continue
        done_label = phase_done_label(phase_id)
        if done_label not in list(getattr(record, "labels", [])):
            continue
        _add(phase_id, str(record.id), unit_id)
    return candidates


def close_done_phase_sub_issues(
    root: Path,
    cfg: dict[str, Any],
    prd_unit_id: str,
    *,
    state: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Close phase sub-issues marked done in deliver ledger or via ``sw:phase:N:done`` (PRD 060 R5)."""
    from planning_progress import phase_done_label

    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return {"verdict": "ok", "skipped": True, "reason": "issue-store-required", "prdUnitId": prd_unit_id}

    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "fail", "error": "issue-store-backend-required", "prdUnitId": prd_unit_id}

    snapshot = resolve_delivery_linked_units(root, cfg, prd_unit_id)
    if snapshot.get("verdict") != "ok":
        return snapshot
    tasks_unit_id = next(
        (item["unitId"] for item in snapshot.get("snapshot") or [] if item.get("artifactType") == "tasks"),
        None,
    )

    if state is None:
        try:
            from wave_state import load_deliver_state

            state = load_deliver_state(root)
        except Exception:  # noqa: BLE001
            state = None

    considered: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    failures: list[dict[str, Any]] = []

    for entry in _collect_phase_sub_issue_candidates(root, cfg, state=state, tasks_unit_id=tasks_unit_id):
        phase_id = entry["phaseId"]
        issue_id = entry.get("issueId") or ""
        unit_id = entry.get("unitId") or f"{tasks_unit_id}-phase-{phase_id}"
        body_path = _default_body_path(unit_id, "tasks")
        record = None
        if issue_id:
            try:
                record = backend._client.issue_get(str(issue_id))
            except IssueNotFound:
                record = None
        if record is None:
            record = _lookup_issue_record(backend, unit_id, body_path)
        if record is None:
            skipped.append({"unitId": unit_id, "reason": "phase-sub-issue-not-found"})
            continue

        done_label = phase_done_label(phase_id)
        labels = list(record.labels)
        is_done = done_label in labels or _phase_done_from_state(state, phase_id)
        considered.append({"unitId": unit_id, "phaseId": phase_id, "issueId": record.id, "done": is_done})
        if not is_done:
            skipped.append({"unitId": unit_id, "reason": "phase-not-done"})
            continue

        unit = {"unitId": unit_id, "artifactType": "tasks", "bodyPath": body_path}
        outcome = _close_issue_store_unit(backend, unit, dry_run=dry_run)
        if outcome.get("verdict") == "fail":
            failures.append(outcome)
        elif outcome.get("action") in {"close", "would-close", "noop"}:
            closed.append(outcome)
        else:
            failures.append(outcome)

    open_remaining = [item["unitId"] for item in failures if item.get("unitId")]
    resume = (
        f"python3 scripts/planning_store.py close-delivery-units --prd-unit {snapshot['prdUnitId']}"
        if open_remaining
        else None
    )
    verdict = "ready" if not failures else "not-ready"
    if dry_run:
        verdict = "dry-run"
    return {
        "verdict": verdict,
        "action": "close-done-phase-sub-issues",
        "prdUnitId": snapshot["prdUnitId"],
        "dryRun": dry_run,
        "considered": considered,
        "closed": closed,
        "skipped": skipped,
        "openRemaining": open_remaining,
        "resumeCommand": resume,
    }


def _close_issue_store_unit(
    backend: "IssueStoreBackend",
    unit: dict[str, str],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    unit_id = unit["unitId"]
    artifact_type = unit["artifactType"]
    body_path = unit["bodyPath"]
    if artifact_type == "gap":
        if dry_run:
            record = _lookup_issue_record(backend, unit_id, body_path)
            prior = _record_prior_state(record, artifact_type) if record else "unknown"
            return {
                "unitId": unit_id,
                "artifactType": artifact_type,
                "priorState": prior,
                "resultingState": "resolved",
                "action": "would-close-gap",
                "verdict": "pass",
            }
        outcome = _migrate_issue_store().close_gap_issue(backend.root, unit_id, backend.cfg)
        return {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "priorState": "open",
            "resultingState": "resolved" if outcome.get("verdict") == "pass" else "open",
            "action": "noop" if outcome.get("alreadyClosed") else "close-gap",
            "verdict": outcome.get("verdict", "fail"),
            "detail": outcome,
        }

    record = _lookup_issue_record(backend, unit_id, body_path)
    if record is None:
        return {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "verdict": "fail",
            "error": "unit-not-found",
        }
    prior_state = _record_prior_state(record, artifact_type)
    target_labels = _closure_labels_for(record, artifact_type)
    if _record_is_closed(record, artifact_type):
        return {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "priorState": prior_state,
            "resultingState": "complete",
            "action": "noop",
            "verdict": "pass",
            "alreadyClosed": True,
        }
    if dry_run:
        return {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "priorState": prior_state,
            "resultingState": "complete",
            "action": "would-close",
            "verdict": "pass",
            "locked": FROZEN_LABEL in list(record.labels) or bool(record.locked),
        }
    before_hash = None
    before_body = None
    if FROZEN_LABEL in list(record.labels) or bool(record.locked):
        before_hash = parse_freeze_record_hash(record.comments)
        before_body = reassemble_body(record.body, record.comments)
    try:
        updated = backend._client.issue_update(
            record.id,
            labels=target_labels,
            state="closed",
            if_match=record.etag,
            allow_locked=True,
        )
    except IssueRevisionConflict as exc:
        return {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "priorState": prior_state,
            "verdict": "fail",
            "error": "revision-conflict",
            "detail": {"expected": exc.expected, "actual": exc.actual},
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "priorState": prior_state,
            "verdict": "fail",
            "error": str(exc),
        }
    if before_body is not None:
        after = backend._client.issue_get(updated.id)
        after_hash = parse_freeze_record_hash(after.comments)
        after_body = reassemble_body(after.body, after.comments)
        if before_body != after_body or before_hash != after_hash:
            return {
                "unitId": unit_id,
                "artifactType": artifact_type,
                "priorState": prior_state,
                "verdict": "fail",
                "error": "locked-body-mutated",
            }
    return {
        "unitId": unit_id,
        "artifactType": artifact_type,
        "priorState": prior_state,
        "resultingState": "complete",
        "action": "close",
        "verdict": "pass",
    }


def audit_closure_completeness(
    root: Path,
    cfg: dict[str, Any],
    prd_unit_id: str,
    *,
    closure_result: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Expected-set closure audit for finalize/retrospective (PRD 068 R9)."""
    snap = resolve_delivery_linked_units(root, cfg, prd_unit_id)
    tasks_note = snap.get("tasksResolution") if isinstance(snap.get("tasksResolution"), dict) else None
    if snap.get("verdict") == "fail" and not (tasks_note and tasks_note.get("failSoftGaps")):
        return {
            "verdict": "not-ready",
            "action": "audit-closure-completeness",
            "error": snap.get("error"),
            "prdUnitId": prd_unit_id,
            "resumeCommand": f"python3 scripts/planning_store.py audit-closure-completeness --prd-unit {prd_unit_id}",
        }

    expected_gaps = {
        item["unitId"]
        for item in (snap.get("snapshot") or [])
        if item.get("artifactType") == "gap"
    }
    considered = list(snap.get("snapshot") or [])
    closed_ids: set[str] = set()
    skipped = list(snap.get("skipped") or [])
    if closure_result:
        for item in closure_result.get("closed") or []:
            uid = str(item.get("unitId") or "")
            if uid:
                closed_ids.add(uid)
        skipped.extend(list(closure_result.get("skipped") or []))

    pmis = _migrate_issue_store()
    if pmis.issue_store_effective(root, cfg):
        backend = get_backend(root, cfg, override="issue-store")
        if isinstance(backend, IssueStoreBackend):
            for gap_id in sorted(expected_gaps):
                body_path = _default_body_path(gap_id, "gap")
                record = _lookup_issue_record(backend, gap_id, body_path)
                if record is None:
                    continue
                if _record_is_closed(record, "gap"):
                    closed_ids.add(gap_id)

    open_remaining = sorted(g for g in expected_gaps if g not in closed_ids)
    if tasks_note and tasks_note.get("verdict") == "not-ready":
        open_remaining = sorted(set(open_remaining) | set(tasks_note.get("openDuplicates") or []))

    verdict = "ready" if not open_remaining else "not-ready"
    resume = (
        f"python3 scripts/planning_store.py audit-closure-completeness --prd-unit {snap.get('prdUnitId', prd_unit_id)}"
        if open_remaining
        else None
    )
    return {
        "verdict": verdict,
        "action": "audit-closure-completeness",
        "prdUnitId": snap.get("prdUnitId", prd_unit_id),
        "considered": considered,
        "closed": sorted(closed_ids),
        "skipped": skipped,
        "openRemaining": open_remaining,
        "planningIssues": snap.get("planningIssues") or [],
        "tasksResolution": tasks_note,
        "resumeCommand": resume,
    }


def _doctor_absorb_pollution_check_prd(
    root: Path,
    cfg: dict[str, Any],
    record: Any,
    unit_id: str,
    pollution: list[dict[str, str]],
) -> None:
    labels = list(getattr(record, "labels", []) or [])
    if status_from_labels(labels) != "complete" and str(getattr(record, "state", "")) != "closed":
        return
    audit = audit_closure_completeness(root, cfg, unit_id)
    if audit.get("openRemaining"):
        pollution.append({"prdUnitId": unit_id, "openRemaining": ",".join(audit["openRemaining"])})


def _doctor_absorb_pollution_scoped_record(
    backend: IssueStoreBackend,
    project_key: str,
    prd_unit_id: str,
) -> Any | None:
    """Resolve one PRD issue via unit index + issue_get; unit-scoped search on index miss (PRD 069 R2)."""
    body_path = _default_body_path(prd_unit_id, "prd")
    record = _lookup_issue_record(backend, prd_unit_id, body_path)
    if record is not None:
        return record
    client = backend._client
    search = getattr(client, "issue_search", None)
    if not callable(search):
        return None
    matches = client.issue_search(
        project_key=project_key,
        unit_id=prd_unit_id,
        artifact_type="prd",
    )
    return matches[0] if matches else None


def doctor_absorb_pollution(
    root: Path,
    cfg: dict[str, Any],
    *,
    prd_unit_id: str | None = None,
) -> dict[str, Any]:
    """Flag complete PRDs with open absorbed gaps (PRD 068 R9 doctor)."""
    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return {"verdict": "pass", "action": "doctor-absorb-pollution", "skipped": True}
    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "pass", "action": "doctor-absorb-pollution", "skipped": True}
    key_result = pmis.validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return {"verdict": "fail", "action": "doctor-absorb-pollution", "error": key_result.get("error")}
    project_key = str(key_result["projectKey"])
    pollution: list[dict[str, str]] = []
    client = backend._client
    search = getattr(client, "issue_search", None)
    if not callable(search):
        return {"verdict": "pass", "action": "doctor-absorb-pollution", "skipped": True, "reason": "no-search"}

    if prd_unit_id:
        record = _doctor_absorb_pollution_scoped_record(backend, project_key, prd_unit_id)
        if record is None:
            return {
                "verdict": "pass",
                "action": "doctor-absorb-pollution",
                "checks": ["no-prd-record"],
                "prdUnitId": prd_unit_id,
            }
        unit_id = str(getattr(record, "unit_id", "") or prd_unit_id)
        _doctor_absorb_pollution_check_prd(root, cfg, record, unit_id, pollution)
    else:
        for record in search(project_key=project_key, artifact_type="prd"):
            unit_id = str(getattr(record, "unit_id", "") or "")
            if not unit_id:
                continue
            _doctor_absorb_pollution_check_prd(root, cfg, record, unit_id, pollution)

    if pollution:
        resume = (
            f"python3 scripts/planning_store.py audit-closure-completeness --prd-unit {pollution[0]['prdUnitId']}"
            if pollution
            else None
        )
        return {
            "verdict": "fail",
            "action": "doctor-absorb-pollution",
            "error": "absorb-pollution",
            "pollution": pollution,
            "resumeCommand": resume,
        }
    payload: dict[str, Any] = {"verdict": "pass", "action": "doctor-absorb-pollution", "checks": ["no-pollution"]}
    if prd_unit_id:
        payload["prdUnitId"] = prd_unit_id
    return payload


def close_parent_epic_if_complete(
    root: Path,
    cfg: dict[str, Any],
    state: dict[str, Any] | None,
    *,
    dry_run: bool = False,
    merged_to_main: bool = False,
) -> dict[str, Any]:
    """Close parent-checkbox epic after main merge when all phases terminal (PRD 063 R13)."""
    from planning_progress import _parent_progress_mode
    from wave_state import load_hierarchy_map

    if not merged_to_main:
        return {"verdict": "skipped", "reason": "pre-main-merge"}
    if not state:
        return {"verdict": "skipped", "reason": "missing-state"}
    hmap = load_hierarchy_map(state)
    if not hmap.get("applied") or not _parent_progress_mode(hmap):
        return {"verdict": "skipped", "reason": "not-parent-checkbox-mode"}
    epic_id = hmap.get("epicIssueId")
    if not epic_id:
        return {"verdict": "skipped", "reason": "missing-epic-issue-id"}

    ledger_phases = ((state.get("taskLedger") or {}).get("phases") or {})
    phases = state.get("phases") or {}
    terminal = frozenset({"green-merged", "teardown-pending", "teardown-complete", "merge-ready-green"})
    for pid, meta in (phases.items() if isinstance(phases, dict) else []):
        phase_ledger = ledger_phases.get(str(pid)) if isinstance(ledger_phases, dict) else None
        if isinstance(phase_ledger, dict) and phase_ledger.get("declaredPartial"):
            return {
                "verdict": "blocked",
                "reason": "declared-partial-phase",
                "phaseId": str(pid),
            }
        status = str((meta or {}).get("status") or "") if isinstance(meta, dict) else ""
        if status and status not in terminal:
            return {
                "verdict": "not-ready",
                "reason": "phase-not-terminal",
                "phaseId": str(pid),
                "status": status,
            }

    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return {"verdict": "skipped", "reason": "issue-store-required"}
    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "fail", "error": "issue-store-backend-required"}
    try:
        record = backend._client.issue_get(str(epic_id))
    except IssueNotFound:
        return {"verdict": "fail", "error": "epic-issue-not-found", "issueId": str(epic_id)}
    if record.state == "closed":
        return {
            "verdict": "ok",
            "action": "noop",
            "idempotent": True,
            "issueId": str(epic_id),
            "alreadyClosed": True,
        }
    if dry_run:
        return {
            "verdict": "dry-run",
            "action": "would-close-epic",
            "issueId": str(epic_id),
        }
    try:
        updated = backend._client.issue_update(
            record.id,
            labels=list(record.labels),
            state="closed",
            if_match=record.etag,
            allow_locked=True,
        )
    except IssueRevisionConflict as exc:
        return {"verdict": "fail", "error": "epic-close-conflict", "detail": str(exc)}
    return {
        "verdict": "ok",
        "action": "close-epic",
        "issueId": str(updated.id),
        "number": updated.number,
    }



def close_delivery_units(
    root: Path,
    cfg: dict[str, Any],
    prd_unit_id: str,
    *,
    dry_run: bool = False,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Close linked PRD/tasks/brainstorm/gap units after retrospective merge (PRD 059 R16-R24)."""
    snapshot = resolve_delivery_linked_units(root, cfg, prd_unit_id)
    if snapshot.get("verdict") != "ok":
        return snapshot
    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "fail", "error": "issue-store-backend-required", "prdUnitId": prd_unit_id}

    phase_closure = close_done_phase_sub_issues(
        root, cfg, prd_unit_id, state=state, dry_run=dry_run
    )

    units = list(snapshot.get("snapshot") or [])
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    considered: list[dict[str, str]] = [
        {"unitId": item["unitId"], "artifactType": item["artifactType"]} for item in units
    ]
    closed: list[dict[str, Any]] = list(phase_closure.get("closed") or [])
    skipped: list[dict[str, str]] = list(snapshot.get("skipped") or []) + list(phase_closure.get("skipped") or [])

    for unit in units:
        outcome = _close_issue_store_unit(backend, unit, dry_run=dry_run)
        results.append(outcome)
        if outcome.get("verdict") == "fail" or outcome.get("detail", {}).get("verdict") == "resolution-partial":
            failures.append(outcome)
        elif outcome.get("action") in {"close", "would-close", "noop", "would-close-gap", "close-gap"}:
            closed.append(outcome)

    cache_status = "skipped-dry-run" if dry_run else "invalidated"
    if not dry_run:
        _invalidate_query_cache(root)

    open_remaining = [
        item["unitId"]
        for item in results
        if item.get("verdict") == "fail" or item.get("detail", {}).get("verdict") == "resolution-partial"
    ]
    open_remaining.extend(phase_closure.get("openRemaining") or [])
    open_remaining = sorted(set(open_remaining))
    resume = (
        f"python3 scripts/planning_store.py close-delivery-units --prd-unit {snapshot['prdUnitId']}"
        if open_remaining
        else None
    )
    merged_main = False
    try:
        from wave_living_docs import target_merge_detected

        merged_main = bool(target_merge_detected(root, state))
    except Exception:  # noqa: BLE001
        merged_main = False
    parent_epic = close_parent_epic_if_complete(
        root, cfg, state, dry_run=dry_run, merged_to_main=merged_main
    )
    if parent_epic.get("verdict") == "blocked":
        failures.append(parent_epic)
    elif parent_epic.get("verdict") == "not-ready":
        failures.append(parent_epic)
    elif parent_epic.get("action") in {"close-epic", "would-close-epic", "noop"}:
        closed.append(parent_epic)

    phase_ok = phase_closure.get("verdict") in {"ready", "dry-run", "ok"}
    verdict = "ready" if not failures and phase_ok else "not-ready"
    if dry_run:
        verdict = "dry-run"
    closure_payload = {
        "verdict": verdict,
        "action": "close-delivery-units",
        "prdUnitId": snapshot["prdUnitId"],
        "dryRun": dry_run,
        "snapshotCount": len(units),
        "considered": considered + list(phase_closure.get("considered") or []),
        "closed": closed,
        "skipped": skipped,
        "units": results,
        "phaseClosure": phase_closure,
        "parentEpicClosure": parent_epic,
        "openRemaining": open_remaining,
        "cacheInvalidation": cache_status,
        "resumeCommand": resume,
    }
    audit = audit_closure_completeness(
        root,
        cfg,
        snapshot["prdUnitId"],
        closure_result=closure_payload,
        state=state,
    )
    closure_payload["closureAudit"] = audit
    if audit.get("verdict") == "not-ready" and not dry_run:
        closure_payload["verdict"] = "not-ready"
        audit_open = list(audit.get("openRemaining") or [])
        closure_payload["openRemaining"] = sorted(set(open_remaining) | set(audit_open))
        closure_payload["resumeCommand"] = audit.get("resumeCommand") or resume
    return closure_payload


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


PLANNING_BODY_SCAN_PREFIXES = ("docs/brainstorms/", "docs/prds/")


def tracked_planning_body_paths(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", *PLANNING_BODY_SCAN_PREFIXES],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return sorted(line.strip() for line in proc.stdout.splitlines() if line.strip())


def _porcelain_path(line: str) -> str | None:
    line = line.rstrip("\n")
    if len(line) < 4:
        return None
    return line[3:].strip() or None


def _is_planning_body_mutation_line(line: str) -> bool:
    """True for staged/committed/worktree mutations — not untracked-only (??)."""
    if len(line) < 4:
        return False
    if line.startswith("??"):
        return False
    index_status, worktree_status = line[0], line[1]
    return index_status != " " or worktree_status != " "


def planning_body_porcelain_paths(root: Path) -> list[str]:
    """Return banned-prefix paths with dirty/staged mutations (PRD 061 R3a)."""
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", *PLANNING_BODY_SCAN_PREFIXES],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if not _is_planning_body_mutation_line(line):
            continue
        path = _porcelain_path(line)
        if path and not path.endswith("/"):
            paths.append(path)
    return sorted(set(paths))


def classify_banned_repo_paths(root: Path) -> dict[str, list[str]]:
    """Classify code-repo banned paths: legacy-tracked vs newly-written (PRD 061 R3a)."""
    tracked = tracked_planning_body_paths(root)
    porcelain = planning_body_porcelain_paths(root)
    newly_written = sorted(set(porcelain))
    legacy = sorted(path for path in tracked if path not in newly_written)
    return {
        "legacy-tracked-pending-cleanup": legacy,
        "newly-written": newly_written,
    }


def doctor_separate_project_local_writes(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    from planning_artifact_handle import issue_store_separate_project_effective

    if not issue_store_separate_project_effective(root, cfg):
        return {
            "verdict": "pass",
            "action": "doctor",
            "skipped": True,
            "reason": "not-separate-project-issue-store",
        }
    classified = classify_banned_repo_paths(root)
    newly_written = classified["newly-written"]
    legacy = classified["legacy-tracked-pending-cleanup"]
    if newly_written:
        return {
            "verdict": "fail",
            "action": "doctor",
            "halt": "local-planning-body-drift",
            "error": "newly-written planning-body paths present in code repo under separate-project issue-store",
            "paths": newly_written,
            "classification": "newly-written",
            "remediation": (
                "revert or remove newly-written docs/brainstorms and docs/prds mutations; "
                "run planning_store cleanup for legacy tracked bodies"
            ),
        }
    checks = ["no-newly-written-planning-bodies"]
    result: dict[str, Any] = {"verdict": "pass", "action": "doctor", "checks": checks}
    if legacy:
        result["legacyPendingCleanup"] = legacy
        result["counts"] = {"legacy-tracked-pending-cleanup": len(legacy)}
    else:
        checks.append("no-tracked-planning-bodies")
    return result


def cleanup_separate_project_local_writes(root: Path, cfg: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
    """PRD 061 R3a — untrack legacy banned planning bodies in the code repo (idempotent)."""
    from planning_artifact_handle import issue_store_separate_project_effective

    if not issue_store_separate_project_effective(root, cfg):
        return {
            "verdict": "ok",
            "action": "cleanup",
            "skipped": True,
            "reason": "not-separate-project-issue-store",
        }
    classified = classify_banned_repo_paths(root)
    legacy = classified["legacy-tracked-pending-cleanup"]
    newly_written = classified["newly-written"]
    applied: list[str] = []
    if apply and legacy:
        proc = subprocess.run(
            ["git", "-C", str(root), "rm", "--cached", "-f", "--", *legacy],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "verdict": "fail",
                "action": "cleanup",
                "error": "git-rm-cached-failed",
                "stderr": proc.stderr.strip(),
                "legacy": legacy,
            }
        applied = list(legacy)
    return {
        "verdict": "ok",
        "action": "cleanup",
        "dryRun": not apply,
        "counts": {
            "legacy-tracked-pending-cleanup": len(legacy),
            "newly-written": len(newly_written),
        },
        "legacy": legacy,
        "newlyWritten": newly_written,
        "applied": applied,
    }


def refuse_banned_living_doc_write(root: Path, *, action: str) -> dict[str, Any] | None:
    """PRD 061 R3 — fail closed when living-doc file writes are banned under issue-store."""
    from wave_living_docs import living_doc_write_banned

    if not living_doc_write_banned(root):
        return None
    return {
        "verdict": "fail",
        "action": action,
        "halt": "banned-living-doc-write",
        "error": "living-doc file writes banned under issue-store",
        "remediation": "route through wave_living_docs facade helpers or planning_store facade",
    }



def backfill_frontmatter_hybrid(root: Path, cfg: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
    """PRD 061 R21 -- idempotent lazy migrate/backfill for YAML-embedded issues."""
    backend = get_backend(root, cfg)
    if backend.backend_id != "issue-store":
        return {
            "verdict": "ok",
            "action": "backfill-frontmatter",
            "skipped": True,
            "reason": "issue-store-only",
            "counts": {"migrated": 0, "skipped": 0, "failed": 0},
        }
    migrated = 0
    skipped = 0
    failed = 0
    details: list[dict[str, Any]] = []
    index = load_issue_unit_index(root)
    for idx_key, issue_id in sorted(index.items()):
        unit_id = idx_key.split(":", 1)[-1]
        body_path = f"docs/planning/gap/{unit_id}/{unit_id}.md"
        try:
            record = backend._lookup_record(unit_id, body_path)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            failed += 1
            details.append({"unitId": unit_id, "verdict": "failed", "error": str(exc)})
            continue
        raw = strip_markers_and_edges(reassemble_body(record.body, record.comments))
        if not has_raw_yaml_frontmatter(raw):
            skipped += 1
            details.append({"unitId": unit_id, "verdict": "skipped"})
            continue
        if apply:
            try:
                backend.put(unit_id, body_path, raw)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                details.append({"unitId": unit_id, "verdict": "failed", "error": str(exc)})
                continue
        migrated += 1
        details.append({"unitId": unit_id, "verdict": "migrated" if apply else "would-migrate"})
    return {
        "verdict": "ok",
        "action": "backfill-frontmatter",
        "dryRun": not apply,
        "counts": {"migrated": migrated, "skipped": skipped, "failed": failed},
        "details": details,
    }


def doctor(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Aggregate issue-store hygiene checks (PRD 061 R3)."""
    checks: list[str] = []
    skipped_reasons: list[str] = []

    stub = doctor_issues_provider_stub(root, cfg)
    if stub.get("verdict") == "fail":
        return stub
    if stub.get("skipped"):
        skipped_reasons.append(str(stub.get("reason") or "issues-provider-stub-skipped"))
    else:
        checks.append(f"issues-provider-stub:{stub.get('provider', 'unknown')}")
        if stub.get("notice"):
            checks.append(str(stub["notice"]))

    sep = doctor_separate_project_local_writes(root, cfg)
    if sep.get("verdict") == "fail":
        return sep
    if sep.get("skipped"):
        skipped_reasons.append(str(sep.get("reason") or "separate-project-skipped"))
    else:
        checks.extend(sep.get("checks", []))

    from wave_living_docs import doctor_banned_living_path_drift

    banned = doctor_banned_living_path_drift(root)
    if banned.get("verdict") == "fail":
        return banned
    if banned.get("skipped"):
        skipped_reasons.append("not-issue-store")
    else:
        checks.extend(banned.get("checks", []))

    from planning_github_projects_v2 import projection_health

    projection = projection_health(root, cfg)
    if not projection.get("skipped"):
        checks.append(f"projection-state:{projection.get('state', 'unknown')}")
        if projection.get("state") == "projection-unavailable":
            checks.append("projection-unavailable")

    pollution = doctor_absorb_pollution(root, cfg)
    if pollution.get("verdict") == "fail":
        return pollution
    if pollution.get("checks"):
        checks.extend(pollution.get("checks", []))

    if not checks and skipped_reasons:
        return {
            "verdict": "pass",
            "action": "doctor",
            "skipped": True,
            "reason": "; ".join(skipped_reasons),
        }
    return {"verdict": "pass", "action": "doctor", "checks": checks, "projection": projection}



def projection_refresh(
    root: Path,
    cfg: dict[str, Any],
    *,
    dry_run: bool = False,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Facade entry for GitHub Projects v2 operator projection (PRD 061 R11)."""
    from planning_github_projects_v2 import refresh_projection, sample_projection_items

    payload = items if items is not None else sample_projection_items(root, cfg)
    return refresh_projection(root, cfg, dry_run=dry_run, items=payload)


_PROGRESS_FACADE_NOTICE_EMITTED = False
ORPHAN_MIGRATED_LABEL = "sw:phase-orphan-migrated"


def _emit_progress_update_notice(notice: str, message: str) -> None:
    global _PROGRESS_FACADE_NOTICE_EMITTED
    if _PROGRESS_FACADE_NOTICE_EMITTED:
        return
    _PROGRESS_FACADE_NOTICE_EMITTED = True
    print(json.dumps({"verdict": "notice", "notice": notice, "message": message}), file=sys.stderr)


def _replace_checkbox_block(body: str, checkbox_block: str) -> str:
    marker = "## Phase checklist (body-encoded fallback)"
    if marker in body:
        start = body.index(marker)
        end = body.find("\n```sw-edges", start)
        if end == -1:
            end = len(body)
        else:
            end = body.find("\n```", end + 1)
            end = end + 4 if end != -1 else len(body)
        return body[:start] + checkbox_block + body[end:]
    return body + "\n\n" + checkbox_block


def progress_update(
    root: Path,
    *,
    parent_issue_id: str,
    phase_id: str,
    action: str = "phase-done",
    provider: str | None = None,
    project_key: str | None = None,
    task_list: str | Path | None = None,
    checked_phase_ids: list[str] | None = None,
    task_ref: str | None = None,
) -> dict[str, Any]:
    """Facade progress_update — parent labels/checkboxes without phase peer mint (PRD 061 R6–R8)."""
    from planning_hierarchy import build_checkbox_phase_block, parse_task_list_phases
    from planning_progress import phase_done_label

    cfg = load_workflow_config(root)
    backend = resolve_effective_backend(root, cfg)
    if backend.get("effective") != "issue-store":
        return {"verdict": "ok", "skipped": True, "reason": "file-store"}

    resolved_provider = provider
    if not resolved_provider:
        resolved_provider = str(resolve_issues_provider(cfg).get("provider") or "none")
    resolved_project_key = project_key
    if not resolved_project_key:
        pk = validate_project_key(root, cfg)
        if pk.get("verdict") != "ok":
            return pk
        resolved_project_key = str(pk["projectKey"])

    client = IssuesClient(root, resolved_provider)
    done_label = phase_done_label(str(phase_id))
    try:
        current = client.issue_get(str(parent_issue_id))
    except Exception as exc:  # noqa: BLE001
        # R3: fail closed — never silently degrade on store read
        _emit_progress_update_notice("progress-update-failed", str(exc))
        return {
            "verdict": "fail",
            "degraded": False,
            "notice": "progress-update-failed",
            "error": str(exc),
            "phaseId": phase_id,
            "issueId": parent_issue_id,
        }

    # R3: prefer materialized task-list path under issue-store
    resolved_task_list = task_list
    if task_list:
        try:
            from planning_progress import _resolve_task_list_path

            rel = str(task_list)
            if Path(rel).is_absolute():
                try:
                    rel = str(Path(rel).resolve().relative_to(root.resolve()))
                except ValueError:
                    rel = str(task_list)
            resolved_task_list = _resolve_task_list_path(root, rel)
        except Exception:
            resolved_task_list = task_list

    labels = list(current.labels)
    new_labels = labels
    body = current.body
    if action == "phase-done":
        if done_label in labels:
            return {
                "verdict": "ok",
                "idempotent": True,
                "phaseId": phase_id,
                "issueId": parent_issue_id,
                "label": done_label,
            }
        new_labels = sorted(set(labels) | {done_label})
        if resolved_task_list:
            task_path = Path(resolved_task_list)
            if not task_path.is_absolute():
                task_path = (root / resolved_task_list).resolve()
            if task_path.is_file():
                phases = parse_task_list_phases(task_path)
                checked = list(checked_phase_ids or [])
                checkbox_block = build_checkbox_phase_block(phases, checked)
                body = _replace_checkbox_block(body, checkbox_block)
    elif action == "task-checkbox" and resolved_task_list:
        task_path = Path(resolved_task_list)
        if not task_path.is_absolute():
            task_path = (root / resolved_task_list).resolve()
        if task_path.is_file():
            import doc_format

            section = doc_format.phase_section_text(task_path.read_text(encoding="utf-8"), str(phase_id)).strip()
            if section:
                from planning_canonical import compose_issue_body

                record_unit = str(getattr(current, "unit_id", "") or "")
                if record_unit.endswith(f"-phase-{phase_id}"):
                    body = compose_issue_body(resolved_project_key, "tasks", record_unit, section)
                else:
                    marker = f"### {phase_id}."
                    if marker in body:
                        start = body.index(marker)
                        nxt = body.find("\n### ", start + 1)
                        end = nxt if nxt != -1 else len(body)
                        body = body[:start] + section + "\n" + body[end:]
                    else:
                        body = body.rstrip() + "\n\n" + section + "\n"

    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            if new_labels != labels:
                client.issue_label(str(parent_issue_id), new_labels, if_match=current.etag)
                current = client.issue_get(str(parent_issue_id))
            if body != current.body:
                client.issue_update(str(parent_issue_id), body=body, if_match=current.etag)
            out: dict[str, Any] = {
                "verdict": "ok",
                "synced": True,
                "storePath": True,
                "phaseId": phase_id,
                "issueId": parent_issue_id,
                "action": action,
            }
            if action == "phase-done":
                out["label"] = done_label
            if task_ref:
                out["taskRef"] = task_ref
            return out
        except IssueRevisionConflict as exc:
            last_exc = exc
            if attempt >= 2:
                break
            # R3: re-read and rebuild against fresh etag (revision-safe store path)
            current = client.issue_get(str(parent_issue_id))
            labels = list(current.labels)
            new_labels = labels
            body = current.body
            if action == "phase-done":
                new_labels = sorted(set(labels) | {done_label})
                if resolved_task_list:
                    task_path = Path(resolved_task_list)
                    if not task_path.is_absolute():
                        task_path = (root / resolved_task_list).resolve()
                    if task_path.is_file():
                        phases = parse_task_list_phases(task_path)
                        checked = list(checked_phase_ids or [])
                        checkbox_block = build_checkbox_phase_block(phases, checked)
                        body = _replace_checkbox_block(body, checkbox_block)
            elif action == "task-checkbox" and resolved_task_list:
                task_path = Path(resolved_task_list)
                if not task_path.is_absolute():
                    task_path = (root / resolved_task_list).resolve()
                if task_path.is_file():
                    import doc_format

                    section = doc_format.phase_section_text(
                        task_path.read_text(encoding="utf-8"), str(phase_id)
                    ).strip()
                    if section:
                        from planning_canonical import compose_issue_body

                        record_unit = str(getattr(current, "unit_id", "") or "")
                        if record_unit.endswith(f"-phase-{phase_id}"):
                            body = compose_issue_body(
                                resolved_project_key, "tasks", record_unit, section
                            )
                        else:
                            marker = f"### {phase_id}."
                            if marker in body:
                                start_i = body.index(marker)
                                nxt = body.find("\n### ", start_i + 1)
                                end_i = nxt if nxt != -1 else len(body)
                                body = body[:start_i] + section + "\n" + body[end_i:]
                            else:
                                body = body.rstrip() + "\n\n" + section + "\n"
            continue
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            break
    _emit_progress_update_notice("progress-update-failed", str(last_exc))
    out = {
        "verdict": "fail",
        "degraded": False,
        "notice": "progress-update-failed",
        "phaseId": phase_id,
        "issueId": parent_issue_id,
        "error": str(last_exc),
    }
    if task_ref:
        out["taskRef"] = task_ref
    return out


def migrate_orphan_phase_issues(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    tasks_unit_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Close/relabel pre-061 minted phase peer issues; idempotent (PRD 061 R8a)."""
    cfg = cfg or load_workflow_config(root)
    if resolve_effective_backend(root, cfg).get("effective") != "issue-store":
        return {"verdict": "ok", "skipped": True, "reason": "file-store"}
    pk = validate_project_key(root, cfg)
    if pk.get("verdict") != "ok":
        return pk
    project_key = str(pk["projectKey"])
    provider = str(resolve_issues_provider(cfg).get("provider") or "none")
    client = IssuesClient(root, provider)
    search = getattr(client, "issue_search", None)
    if not callable(search):
        return {"verdict": "ok", "skipped": True, "reason": "issue-search-unavailable"}

    migrated: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    prefix = f"{tasks_unit_id}-phase-" if tasks_unit_id else None
    for record in search(project_key=project_key, artifact_type="tasks"):
        unit_id = str(getattr(record, "unit_id", "") or "")
        if prefix and not unit_id.startswith(prefix):
            continue
        if not prefix and "-phase-" not in unit_id:
            continue
        labels = list(getattr(record, "labels", []))
        if ORPHAN_MIGRATED_LABEL in labels:
            skipped.append({"unitId": unit_id, "reason": "already-migrated"})
            continue
        issue_id = str(getattr(record, "id", "") or "")
        if dry_run:
            migrated.append({"unitId": unit_id, "issueId": issue_id, "dryRun": True})
            continue
        new_labels = sorted(set(labels) | {ORPHAN_MIGRATED_LABEL})
        try:
            client.issue_label(issue_id, new_labels, if_match=getattr(record, "etag", None))
            if getattr(record, "state", "open") == "open":
                client.issue_update(issue_id, state="closed")
            migrated.append({"unitId": unit_id, "issueId": issue_id})
        except Exception as exc:  # noqa: BLE001
            skipped.append({"unitId": unit_id, "reason": str(exc)})
    return {
        "verdict": "ok",
        "action": "migrate-orphan-phase-issues",
        "dryRun": dry_run,
        "migrated": migrated,
        "skipped": skipped,
        "count": len(migrated),
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


def comment_sync(
    root: Path,
    *,
    unit_id: str,
    body_path: str,
    consumer: str = "authoring",
) -> dict[str, Any]:
    """R18 — inbound provider comments for authoring/deliver consumers via facade."""
    cfg = load_workflow_config(root)
    backend = resolve_effective_backend(root, cfg)
    if backend.get("effective") != "issue-store":
        return {
            "verdict": "ok",
            "skipped": True,
            "reason": "file-store",
            "consumer": consumer,
            "unitId": unit_id,
        }
    store = get_backend(root, cfg)
    if store.backend_id != "issue-store":
        return {
            "verdict": "ok",
            "skipped": True,
            "reason": "not-issue-store",
            "consumer": consumer,
            "unitId": unit_id,
        }
    reject_bare_integer_unit_id(unit_id)
    try:
        record = store._lookup_record(unit_id, body_path)  # type: ignore[attr-defined]
    except IssueNotFound:
        return {
            "verdict": "fail",
            "error": "unit-not-found",
            "consumer": consumer,
            "unitId": unit_id,
            "bodyPath": body_path,
        }
    inbound = inbound_authoring_comments(list(record.comments))
    payload = [
        {
            "id": comment.id,
            "body": comment.body,
            "createdAt": comment.created_at,
            "markers": list(comment.markers),
            "parentId": comment.parent_id or None,
            "resolvedAt": comment.resolved_at or None,
            "resolvingCommentId": comment.resolving_comment_id or None,
            "threadStatus": comment_thread_status(comment),
        }
        for comment in inbound
    ]
    return {
        "verdict": "ok",
        "action": "comment-sync",
        "consumer": consumer,
        "unitId": unit_id,
        "issueId": record.id,
        "comments": payload,
        "count": len(payload),
    }


# PRD 061 R1/R2/R2a — planning-store facade contract + IssuesClient import allowlist.
# Workflow scripts MUST route planning mutations through this module; only allowlisted
# store/provider modules may import IssuesClient directly.
FACADE_OPERATIONS: tuple[dict[str, str], ...] = (
    {"name": "put", "status": "shipped", "description": "Authoritative unit body write"},
    {"name": "get", "status": "shipped", "description": "Canonical unit body read"},
    {"name": "exists", "status": "shipped", "description": "Unit presence probe"},
    {"name": "materialize", "status": "shipped", "description": "Project store body to local path"},
    {"name": "materialize_from_store", "status": "shipped", "description": "Batch materialize for deliver"},
    {"name": "freeze", "status": "shipped", "description": "Lock unit + freeze record"},
    {"name": "verify_frozen_hash", "status": "shipped", "description": "Tamper check for frozen units"},
    {"name": "link_brainstorm_prd", "status": "shipped", "description": "Durability edge between brainstorm and PRD"},
    {"name": "close_delivery_units", "status": "shipped", "description": "Deliver closure hooks for planning units"},
    {"name": "doctor", "status": "shipped", "description": "Fail-closed hygiene for separate-project drift"},
    {"name": "cleanup", "status": "shipped", "description": "Idempotent legacy planning-body untrack under separate-project"},
    {"name": "derive_unit_status", "status": "shipped", "description": "Unified status from store evidence"},
    {"name": "progress_update", "status": "shipped", "description": "Semantic phase/task progress without ad hoc issue_create"},
    {"name": "comment_sync", "status": "shipped", "description": "Inbound/outbound provider comment sync"},
    {"name": "projection_refresh", "status": "shipped", "description": "Rebuild operator projection (Projects v2, hierarchy)"},
    {"name": "probe_projection", "status": "shipped", "description": "Probe operator-projection health / capability notices"},
    {
        "name": "operator_projection_contract",
        "status": "shipped",
        "description": "Provider-agnostic operator-projection API + R1 browse capability matrix (PRD 066)",
    },
    {
        "name": "linear_projection_schema",
        "status": "shipped",
        "description": "Linear operator schema: entity map, Initiative/Cycles, typed edges (PRD 066 R6–R8/R29)",
    },
    {
        "name": "comments_relations_schema",
        "status": "shipped",
        "description": "Facade thread parentage, resolved metadata, typed relation edges (PRD 066 R17/R24)",
    },
)

ISSUES_CLIENT_ALLOWLIST = frozenset({
    "scripts/planning_store.py",
    "scripts/issues_lib.py",
    "scripts/planning_github_client.py",
    "scripts/planning_gitlab_client.py",
    "scripts/planning_jira_client.py",
    "scripts/planning_github_projects_v2.py",
    "scripts/planning_linear_client.py",
    "scripts/planning_migrate_issue_store.py",
})

# PRD 066 R4 — workflow scripts must not import Linear/Projects mutation helpers directly.
PROJECTION_MUTATION_MODULES = frozenset({
    "planning_linear_client",
    "planning_github_projects_v2",
})
PROJECTION_MUTATION_NAMES = frozenset({
    "refresh_projection",
    "create_issue_batch",
    "create_project",
    "update_project",
    "create_milestone",
    "update_milestone",
    "create_document",
    "update_document",
    "assign_cycle",
    "mutate",
})
PROJECTION_MUTATION_ALLOWLIST = frozenset({
    "scripts/planning_store.py",
    "scripts/planning_github_projects_v2.py",
    "scripts/planning_linear_client.py",
})

# PRD 066 R32 — exclusive semantic status taxonomy + provider alias allowlists.
SEMANTIC_STATUSES = frozenset({"backlog", "in_flight", "done"})
SEMANTIC_STATUS_ALIASES: dict[str, dict[str, frozenset[str]]] = {
    "linear": {
        "backlog": frozenset({"backlog", "todo", "triage", "unstarted", "planned"}),
        "in_flight": frozenset({"in progress", "started", "in_progress", "active", "blocked"}),
        "done": frozenset({"done", "completed", "canceled", "cancelled", "duplicate"}),
    },
    "github-projects": {
        "backlog": frozenset({"backlog", "todo", "new", "ready"}),
        "in_flight": frozenset({"in progress", "in review", "in_progress", "active"}),
        "done": frozenset({"done", "complete", "completed", "closed"}),
    },
}

# PRD 066 R31 — normative R1 browse contract (card/list-visible fields; body open = failure).
R1_BROWSE_CONTRACT: dict[str, Any] = {
    "bodyOpenIsFailure": True,
    "questions": {
        "1": {
            "id": 1,
            "prompt": "which gaps a PRD absorbs",
            "cardVisibleFields": [
                "projectMembership",
                "gapLabelOrField",
                "gapIssueIdentity",
            ],
        },
        "2": {
            "id": 2,
            "prompt": "which brainstorm(s) feed a PRD",
            "cardVisibleFields": [
                "documentAttachmentOrMembership",
                "brainstormIdentity",
                "prdProjectLink",
            ],
        },
        "3": {
            "id": 3,
            "prompt": "task/phase completion for an in-flight PRD",
            "cardVisibleFields": [
                "issueSemanticStatus",
                "milestonePhaseMembership",
                "milestoneProgress",
            ],
        },
        "4": {
            "id": 4,
            "prompt": "backlog vs in_flight vs done at program level",
            "cardVisibleFields": [
                "initiativeOrProgramDiscriminator",
                "programSemanticStatus",
                "substituteViewsOrFilters",
            ],
            "notes": "Cycle is wave enrichment only — not phase source of truth",
        },
    },
}

OPERATOR_PROJECTION_MATRIX_ROWS: tuple[dict[str, Any], ...] = (
    {"row": "prd", "linear": "project", "github-projects": "project-item", "r1": [1, 2, 3, 4]},
    {"row": "brainstorm", "linear": "document", "github-projects": "draft-or-issue-field", "r1": [2]},
    {"row": "gap", "linear": "issue+gap-label", "github-projects": "issue+gap-field", "r1": [1]},
    {"row": "phase", "linear": "milestone", "github-projects": "phase-field", "r1": [3]},
    {"row": "task", "linear": "issue/sub-issue", "github-projects": "issue-item", "r1": [3]},
    {"row": "progress", "linear": "native-status", "github-projects": "status-field", "r1": [3, 4]},
    {
        "row": "program",
        "linear": "initiative-or-substitute-views",
        "github-projects": "program-discriminator",
        "r1": [4],
    },
    {"row": "cycle-wave", "linear": "cycle", "github-projects": "degraded-optional", "r1": []},
)

FACADE_WORKFLOW_SCAN_GLOB = "scripts/*.py"

FACADE_BYPASS_BASELINE = frozenset({
    "scripts/planning_discover.py",
    "scripts/planning_scheduler.py",
})

_ISSUES_CLIENT_IMPORT_ROOTS = frozenset({"issues_lib"})


def facade_surface() -> dict[str, Any]:
    shipped = [op["name"] for op in FACADE_OPERATIONS if op["status"] == "shipped"]
    planned = [op["name"] for op in FACADE_OPERATIONS if op["status"] == "planned"]
    return {
        "verdict": "ok",
        "action": "list-facade",
        "operations": list(FACADE_OPERATIONS),
        "shipped": shipped,
        "planned": planned,
        "allowlist": sorted(ISSUES_CLIENT_ALLOWLIST),
        "workflowScan": FACADE_WORKFLOW_SCAN_GLOB,
        "bypassBaseline": sorted(FACADE_BYPASS_BASELINE),
    }


def _rel_script_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _imports_issues_client(path: Path) -> list[int]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".")[0]
                if root_name in _ISSUES_CLIENT_IMPORT_ROOTS or alias.name == "IssuesClient":
                    lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom) and node.module:
            root_name = node.module.split(".")[0]
            imported = {alias.name for alias in node.names}
            if root_name in _ISSUES_CLIENT_IMPORT_ROOTS or "IssuesClient" in imported:
                lines.append(node.lineno)
    return sorted(set(lines))


def issue_get_facade(root: Path, cfg: dict[str, Any], issue_ref: str) -> dict[str, Any]:
    """Facade wrapper for issue lookup used by non-allowlisted workflow scripts."""
    effective = resolve_effective_backend(root, cfg)
    if effective.get("effective") != "issue-store":
        return {
            "verdict": "fail",
            "error": "--issue requires issue-store effective backend",
            "effectiveBackend": effective.get("effective"),
        }
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return {"verdict": "fail", "error": key_result.get("message") or "invalid project key"}
    provider = str(resolve_issues_provider(cfg).get("provider", "none"))
    client = IssuesClient(root, provider)
    try:
        record = client.issue_get(issue_ref)
    except IssueNotFound:
        return {
            "verdict": "fail",
            "error": "issue-not-found-or-outside-scope",
            "issue": issue_ref,
        }
    except IssueCapabilityError:
        return {"verdict": "fail", "error": "issue-capability-error", "issue": issue_ref}
    except IssueBudgetExhausted:
        return {"verdict": "fail", "error": "issue-budget-exhausted", "issue": issue_ref}
    return {"verdict": "ok", "record": record}


def issue_search_by_unit_facade(root: Path, cfg: dict[str, Any], *, unit_id: str) -> dict[str, Any]:
    """Facade wrapper for issue search by unit id."""
    effective = resolve_effective_backend(root, cfg)
    if effective.get("effective") != "issue-store":
        return {"verdict": "ok", "records": []}
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return {"verdict": "ok", "records": []}
    provider = str(resolve_issues_provider(cfg).get("provider", "none"))
    client = IssuesClient(root, provider)
    try:
        records = list(
            client.issue_search(
                project_key=str(key_result["projectKey"]),
                unit_id=unit_id,
            )
        )
    except (IssueCapabilityError, IssueBudgetExhausted, RuntimeError):
        return {"verdict": "fail", "error": "issue-search-failed", "records": []}
    return {"verdict": "ok", "records": records}


def scan_facade_import_violations(root: Path, *, extra_paths: list[Path] | None = None) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    candidates: list[Path] = []
    if extra_paths:
        candidates.extend(extra_paths)
    else:
        candidates.extend(sorted(root.glob(FACADE_WORKFLOW_SCAN_GLOB)))
    for script in candidates:
        if not script.is_file() or script.suffix != ".py":
            continue
        rel = _rel_script_path(root, script)
        if rel in ISSUES_CLIENT_ALLOWLIST:
            continue
        hit_lines = _imports_issues_client(script)
        if hit_lines:
            violations.append({"path": rel, "lines": hit_lines})
    return sorted(violations, key=lambda row: row["path"])


def lint_facade_imports(root: Path, *, scope: str | None = None) -> dict[str, Any]:
    if scope:
        target = Path(scope)
        if not target.is_absolute():
            target = root / target
        violations = scan_facade_import_violations(root, extra_paths=[target])
        rel = _rel_script_path(root, target)
        allowed = rel in ISSUES_CLIENT_ALLOWLIST
        if allowed and not violations:
            return {
                "verdict": "pass",
                "action": "lint-facade-imports",
                "path": rel,
                "allowed": True,
                "violations": [],
            }
        if violations:
            return {
                "verdict": "fail",
                "action": "lint-facade-imports",
                "path": rel,
                "allowed": allowed,
                "error": "issues-client-import-outside-allowlist",
                "violations": violations,
            }
        return {
            "verdict": "pass",
            "action": "lint-facade-imports",
            "path": rel,
            "allowed": allowed,
            "violations": [],
        }

    violations = scan_facade_import_violations(root)
    result: dict[str, Any] = {
        "verdict": "pass" if not violations else "fail",
        "action": "lint-facade-imports",
        "allowlist": sorted(ISSUES_CLIENT_ALLOWLIST),
        "violations": violations,
        "bypassBaseline": sorted(FACADE_BYPASS_BASELINE),
    }
    if violations:
        found = {row["path"] for row in violations}
        result["error"] = "issues-client-import-outside-allowlist"
        result["baselineMissing"] = sorted(FACADE_BYPASS_BASELINE - found)
        result["unexpected"] = sorted(found - FACADE_BYPASS_BASELINE - ISSUES_CLIENT_ALLOWLIST)
    return result


class SemanticStatusError(ValueError):
    """PRD 066 R32 — unknown native status outside the alias allowlist."""

    def __init__(self, message: str, *, code: str = "unknown-native-status", **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra


def normalize_semantic_status(provider: str, native_status: str) -> str:
    """Map provider-native status onto backlog/in_flight/done; fail closed on unknown."""
    aliases = SEMANTIC_STATUS_ALIASES.get(provider)
    if aliases is None:
        raise SemanticStatusError(
            f"unsupported projection provider: {provider}",
            code="unsupported-provider",
            provider=provider,
        )
    key = (native_status or "").strip().lower()
    if not key:
        raise SemanticStatusError("empty native status", code="empty-native-status", provider=provider)
    if key in SEMANTIC_STATUSES:
        return key
    for semantic, names in aliases.items():
        if key in names:
            return semantic
    raise SemanticStatusError(
        f"unknown native status for {provider}: {native_status}",
        code="unknown-native-status",
        provider=provider,
        nativeStatus=native_status,
    )




# PRD 066 R24 — normative facade schemas for threaded comments + typed relations.
COMMENT_FACADE_FIELDS: tuple[str, ...] = (
    "id",
    "body",
    "createdAt",
    "markers",
    "parentId",
    "resolvedAt",
    "resolvingCommentId",
    "threadStatus",
)
RELATION_FACADE_FIELDS: tuple[str, ...] = (
    "id",
    "type",
    "sourceIssueId",
    "targetIssueId",
    "direction",
)
NATIVE_RELATION_TYPES: frozenset[str] = frozenset(
    {"blocks", "blocked", "duplicate", "related", "similar"}
)


def comments_relations_schema_contract() -> dict[str, Any]:
    """PRD 066 R24 — facade thread/relation schema contract surface."""
    return {
        "verdict": "ok",
        "action": "comments-relations-schema-contract",
        "commentFields": list(COMMENT_FACADE_FIELDS),
        "relationFields": list(RELATION_FACADE_FIELDS),
        "flatCommentProviders": sorted(FLAT_COMMENT_PROVIDERS),
        "nativeRelationTypes": sorted(NATIVE_RELATION_TYPES),
        "threadSemantics": {
            "root": "top-level comment without parentId",
            "reply": "comment with parentId and no resolvedAt",
            "resolved": "thread root or reply with resolvedAt metadata",
        },
        "relationSemantics": {
            "outbound": "relations[] from current issue to relatedIssue",
            "inbound": "inverseRelations[] from issue to current issue",
            "issueRelationOnly": True,
        },
        "gap077AuthoringAccepted": False,
    }


def serialize_comments_relations_facade(
    comments: list[CommentRecord],
    relations: list[RelationRecord],
    *,
    provider: str,
) -> dict[str, Any]:
    """Serialize comments + relations for facade consumers (R24)."""
    normalized = (
        normalize_flat_provider_comments(comments)
        if provider in FLAT_COMMENT_PROVIDERS
        else list(comments)
    )
    return {
        "verdict": "ok",
        "action": "serialize-comments-relations-facade",
        "provider": provider,
        "comments": [serialize_comment_facade(comment) for comment in normalized],
        "threads": build_comment_threads(normalized),
        "relations": [serialize_relation_facade(relation) for relation in relations],
        "flatCommentPath": provider in FLAT_COMMENT_PROVIDERS,
    }


def issue_comments_relations_facade(record: Any, *, provider: str) -> dict[str, Any]:
    """Facade read helper for issue comments + typed relations (R17/R24)."""
    comments = list(getattr(record, "comments", []) or [])
    relations = list(getattr(record, "relations", []) or [])
    payload = serialize_comments_relations_facade(comments, relations, provider=provider)
    payload["issueId"] = str(getattr(record, "id", "") or "")
    payload["unitId"] = str(getattr(record, "unit_id", "") or "")
    if provider == "linear":
        payload["gap077AuthoringAccepted"] = False
    return payload


def assert_flat_comment_provider_non_regression(
    provider: str,
    comments: list[CommentRecord],
) -> dict[str, Any]:
    """R24 — GitHub/Jira must not claim threaded/resolved metadata."""
    if provider not in FLAT_COMMENT_PROVIDERS:
        return {"verdict": "pass", "action": "assert-flat-comment-provider", "provider": provider}
    for comment in comments:
        if comment.parent_id or comment.resolved_at or comment.resolving_comment_id:
            return {
                "verdict": "fail",
                "error": "flat-provider-thread-metadata-claim",
                "action": "assert-flat-comment-provider",
                "provider": provider,
                "commentId": comment.id,
            }
    return {"verdict": "pass", "action": "assert-flat-comment-provider", "provider": provider}


def operator_projection_capability_matrix() -> dict[str, Any]:
    """PRD 066 R1/R3 — shared operator-projection capability matrix skeleton."""
    return {
        "backends": ["github-issues", "github-projects", "jira", "linear"],
        "contractBackends": ["github-projects", "linear"],
        "rows": [dict(row) for row in OPERATOR_PROJECTION_MATRIX_ROWS],
        "statusTaxonomy": sorted(SEMANTIC_STATUSES),
        "statusAliases": {
            provider: {semantic: sorted(names) for semantic, names in mapping.items()}
            for provider, mapping in SEMANTIC_STATUS_ALIASES.items()
        },
        "r1BrowseContract": R1_BROWSE_CONTRACT,
    }


def operator_projection_adapter_complete_claim(matrix: dict[str, Any] | None = None) -> dict[str, Any]:
    """R3 — adapter-complete requires both Linear and Projects backends in the matrix."""
    payload = matrix or operator_projection_capability_matrix()
    required = ["github-projects", "linear"]
    backends = set(payload.get("backends") or [])
    contract_backends = set(payload.get("contractBackends") or [])
    present = [name for name in required if name in backends and name in contract_backends]
    # Skeleton stage: both backends are declared; answerability lands in later phases.
    answerable = {
        "linear": bool(payload.get("linearAnswerable")),
        "github-projects": bool(payload.get("projectsAnswerable")),
    }
    return {
        "verdict": "ok",
        "requiresBackends": required,
        "presentBackends": present,
        "answerable": answerable,
        "adapterComplete": present == required and all(answerable.values()),
    }


def operator_projection_contract() -> dict[str, Any]:
    """PRD 066 R1/R31 — provider-agnostic operator-projection API surface + browse contract."""
    matrix = operator_projection_capability_matrix()
    questions = [
        {
            "id": int(qid),
            "prompt": entry["prompt"],
            "cardVisibleFields": list(entry["cardVisibleFields"]),
        }
        for qid, entry in sorted(R1_BROWSE_CONTRACT["questions"].items(), key=lambda item: int(item[0]))
    ]
    ops = [
        {"name": "projection_refresh", "status": "shipped"},
        {"name": "probe_projection", "status": "shipped"},
        {"name": "operator_projection_contract", "status": "shipped"},
    ]
    return {
        "verdict": "ok",
        "action": "operator-projection-contract",
        "operations": ops,
        "r1BrowseQuestions": questions,
        "r1BrowseContract": R1_BROWSE_CONTRACT,
        "capabilityMatrix": matrix,
        "adapterCompleteClaim": operator_projection_adapter_complete_claim(matrix),
        "semanticStatuses": sorted(SEMANTIC_STATUSES),
        "commentsRelations": comments_relations_schema_contract(),
    }


def assert_r1_answerability_from_metadata(evidence: dict[str, Any]) -> dict[str, Any]:
    """R31 harness helper — R1 answers must come from card/list metadata; body-open fails."""
    missing: list[str] = []
    for qid, entry in R1_BROWSE_CONTRACT["questions"].items():
        row = evidence.get(qid) or evidence.get(int(qid))  # type: ignore[arg-type]
        if not isinstance(row, dict):
            missing.append(qid)
            continue
        if row.get("bodyOpened") is True:
            return {
                "verdict": "fail",
                "error": "r1-body-open",
                "question": qid,
                "bodyOpenIsFailure": True,
            }
        fields = {str(f) for f in (row.get("fields") or [])}
        required = {str(f) for f in entry["cardVisibleFields"]}
        if not required.issubset(fields):
            missing.append(qid)
    if missing:
        return {"verdict": "fail", "error": "r1-metadata-incomplete", "questions": missing}
    return {"verdict": "pass", "action": "assert-r1-answerability", "bodyOpenIsFailure": True}


def assert_r1_answerability_while_clean(
    root: Path,
    evidence: dict[str, Any],
    *,
    scope: str = "default",
) -> dict[str, Any]:
    """R28 — R1 harness fails closed while projection dirty."""
    if projection_is_dirty(root, scope=scope):
        ledger = load_projection_ledger(root, scope=scope)
        return {
            "verdict": "fail",
            "error": "projection-dirty",
            "action": "assert-r1-answerability",
            "dirtyReason": ledger.get("dirtyReason"),
            "checkpointGeneration": ledger.get("checkpointGeneration"),
        }
    return assert_r1_answerability_from_metadata(evidence)


def _imports_projection_mutations(path: Path) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    hits: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_name = alias.name.split(".")[0]
                if root_name in PROJECTION_MUTATION_MODULES:
                    hits.append(
                        {
                            "line": node.lineno,
                            "module": root_name,
                            "names": [alias.name],
                        }
                    )
        elif isinstance(node, ast.ImportFrom) and node.module:
            root_name = node.module.split(".")[0]
            imported = {alias.name for alias in node.names}
            if root_name in PROJECTION_MUTATION_MODULES:
                dangerous = sorted(imported & PROJECTION_MUTATION_NAMES) or sorted(imported)
                hits.append(
                    {
                        "line": node.lineno,
                        "module": root_name,
                        "names": dangerous,
                    }
                )
    return hits


def scan_projection_mutation_violations(
    root: Path, *, extra_paths: list[Path] | None = None
) -> list[dict[str, Any]]:
    violations: list[dict[str, Any]] = []
    candidates: list[Path] = []
    if extra_paths:
        candidates.extend(extra_paths)
    else:
        candidates.extend(sorted(root.glob(FACADE_WORKFLOW_SCAN_GLOB)))
    for script in candidates:
        if not script.is_file() or script.suffix != ".py":
            continue
        rel = _rel_script_path(root, script)
        if rel in PROJECTION_MUTATION_ALLOWLIST:
            continue
        hits = _imports_projection_mutations(script)
        if hits:
            violations.append({"path": rel, "imports": hits})
    return sorted(violations, key=lambda row: row["path"])


def lint_projection_mutations(root: Path, *, scope: str | None = None) -> dict[str, Any]:
    """PRD 066 R4 — fail closed when workflow scripts mutate Linear/Projects directly."""
    if scope:
        target = Path(scope)
        if not target.is_absolute():
            target = root / target
        violations = scan_projection_mutation_violations(root, extra_paths=[target])
        rel = _rel_script_path(root, target)
        allowed = rel in PROJECTION_MUTATION_ALLOWLIST
        if allowed and not violations:
            return {
                "verdict": "pass",
                "action": "lint-projection-mutations",
                "path": rel,
                "allowed": True,
                "violations": [],
            }
        if violations:
            return {
                "verdict": "fail",
                "action": "lint-projection-mutations",
                "path": rel,
                "allowed": allowed,
                "error": "projection-mutation-outside-allowlist",
                "violations": violations,
            }
        return {
            "verdict": "pass",
            "action": "lint-projection-mutations",
            "path": rel,
            "allowed": allowed,
            "violations": [],
        }

    violations = scan_projection_mutation_violations(root)
    result: dict[str, Any] = {
        "verdict": "pass" if not violations else "fail",
        "action": "lint-projection-mutations",
        "allowlist": sorted(PROJECTION_MUTATION_ALLOWLIST),
        "violations": violations,
    }
    if violations:
        result["error"] = "projection-mutation-outside-allowlist"
    return result


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



PRD_061_DEPENDS_TARGET = "061-prd-planning-store-interface-architecture"

# PRD 066 R22 — gap-079 absorb linkage verification
PRD_066_ABSORB_UNIT_ID = "066-prd-linear-planning-store-provider-and-operator-projection"
PRD_066_ABSORB_NUMBER = "066"
GAP_079_ABSORB_UNIT_ID = "gap-079-add-linear-as-a-new-planning-store-issue-trackin"
GAP_079_PLANNING_ISSUE_REF = "planning#267"


def _gap_absorb_target_match(candidate: str, gap_unit_id: str) -> bool:
    cand = candidate.strip()
    if not cand:
        return False
    if cand == gap_unit_id:
        return True
    if gap_unit_id.startswith("gap-079") and (
        cand == "gap-079" or cand.startswith("gap-079-")
    ):
        return True
    if cand.startswith("gap-079") and gap_unit_id.startswith("gap-079"):
        return True
    return False


def verify_absorb_linkage_066(
    root: Path,
    cfg: dict[str, Any],
    *,
    prd_unit_id: str = PRD_066_ABSORB_UNIT_ID,
    gap_unit_id: str = GAP_079_ABSORB_UNIT_ID,
    planning_issue: str = GAP_079_PLANNING_ISSUE_REF,
) -> dict[str, Any]:
    """Verify gap-079 absorb linkage via store get evidence (PRD 066 R22)."""
    from gap_backlog import schedule_label
    from planning_migrate_issue_store import (
        gap_unit_ids_scheduled_for_prd,
        issue_store_effective,
        parse_frontmatter_fields,
    )

    if not issue_store_effective(root, cfg):
        return {
            "verdict": "skipped",
            "action": "verify-absorb-linkage-066",
            "reason": "not-issue-store",
        }

    backend = get_backend(root, cfg, override="issue-store")
    prd_body_path = _default_body_path(prd_unit_id, "prd")
    gap_body_path = _default_body_path(gap_unit_id, "gap")
    prd_fetch = backend.get(prd_unit_id, prd_body_path)
    gap_fetch = backend.get(gap_unit_id, gap_body_path)
    if prd_fetch.verdict != "ok" or not prd_fetch.content:
        return {
            "verdict": "fail",
            "action": "verify-absorb-linkage-066",
            "error": "prd-missing",
            "prdUnitId": prd_unit_id,
        }
    if gap_fetch.verdict != "ok" or not gap_fetch.content:
        return {
            "verdict": "fail",
            "action": "verify-absorb-linkage-066",
            "error": "gap-missing",
            "gapUnitId": gap_unit_id,
        }

    prd_fm = parse_frontmatter_fields(prd_fetch.content)
    gap_fm = parse_frontmatter_fields(gap_fetch.content)
    absorbs = _parse_absorbs_targets(prd_fm.get("absorbs", ""))
    prd_absorbs_gap = any(_gap_absorb_target_match(item, gap_unit_id) for item in absorbs)
    schedule = schedule_label(PRD_066_ABSORB_NUMBER)
    gap_scheduled = str(gap_fm.get("status") or "").lower() == "scheduled"
    gap_schedule = str(gap_fm.get("schedule") or "").strip() == schedule
    absorbed_by = str(gap_fm.get("absorbed-by") or gap_fm.get("absorbed_by") or "").strip()
    gap_absorbed_by_prd = absorbed_by == prd_unit_id
    related = str(gap_fm.get("related") or "")
    planning_ref_ok = planning_issue in related
    scheduled_ids = gap_unit_ids_scheduled_for_prd(root, PRD_066_ABSORB_NUMBER, cfg)
    label_schedule_ok = gap_unit_id in scheduled_ids

    checks = {
        "prdAbsorbsGap": prd_absorbs_gap,
        "gapScheduled": gap_scheduled,
        "gapScheduleLabel": gap_schedule,
        "gapAbsorbedByPrd": gap_absorbed_by_prd,
        "planningIssueRef": planning_ref_ok,
        "issueStoreScheduleLabel": label_schedule_ok,
    }
    ok = all(checks.values())
    return {
        "verdict": "ok" if ok else "fail",
        "action": "verify-absorb-linkage-066",
        "prdUnitId": prd_unit_id,
        "gapUnitId": gap_unit_id,
        "planningIssue": planning_issue,
        "checks": checks,
    }


def doctor_absorb_linkage_066(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Doctor hook for PRD 066 gap-079 absorb linkage (R22)."""
    result = verify_absorb_linkage_066(root, cfg)
    if result.get("verdict") == "skipped":
        return {
            "verdict": "pass",
            "action": "doctor-absorb-linkage-066",
            "skipped": True,
            "reason": result.get("reason"),
        }
    if result.get("verdict") != "ok":
        return {
            "verdict": "fail",
            "action": "doctor-absorb-linkage-066",
            "error": "absorb-linkage-incomplete",
            "evidence": result,
        }
    return {
        "verdict": "pass",
        "action": "doctor-absorb-linkage-066",
        "checks": ["gap-079-absorbed-by-prd-066"],
        "evidence": result,
    }


GAP_PREREQ_NUMBERS = frozenset({"078", "079"})
ABSORB_GAP_NUMBERS = frozenset({"077", "104", "109"})
PRD_060_GAP_ABSORB_DENY = frozenset({"081", "096", "099", "100", "105", "112"})


def _gap_number_from_unit_id(unit_id: str) -> str | None:
    m = re.match(r"^gap-(\d{3})", unit_id, re.I)
    return m.group(1) if m else None


def _parse_depends_list(raw: str) -> list[str]:
    return _parse_absorbs_targets(raw or "")


def _depends_includes_061(depends: list[str]) -> bool:
    for item in depends:
        lowered = item.lower()
        if lowered in {"061", PRD_061_DEPENDS_TARGET.lower()}:
            return True
        if lowered.startswith("061-") or lowered.startswith("prd-061"):
            return True
    return False


def _merge_depends_frontmatter(content: str, target: str) -> tuple[str, bool]:
    pmis = _migrate_issue_store()
    fm = pmis.parse_frontmatter_fields(content)
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            body = content[end + 4 :].lstrip("\n")
    depends = _parse_depends_list(fm.get("depends", ""))
    if _depends_includes_061(depends):
        return content, False
    depends.append(target)
    lines = ["---"]
    for key, value in fm.items():
        if key == "depends":
            continue
        lines.append(f"{key}: {value}")
    lines.append("depends: [" + ", ".join(depends) + "]")
    lines.append("---")
    return "\n".join(lines) + "\n" + body.lstrip("\n"), True


def gate_prd_060_r1_r7(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    from planning_canonical import ARTIFACT_TYPE_UNRESOLVED, infer_artifact_type

    checks: list[dict[str, str]] = []
    ok = True
    if infer_artifact_type("issue:42") != ARTIFACT_TYPE_UNRESOLVED:
        checks.append({"check": "infer-artifact-type-opaque", "status": "fail"})
        ok = False
    else:
        checks.append({"check": "infer-artifact-type-opaque", "status": "ok"})
    if not callable(close_delivery_units):
        checks.append({"check": "close-delivery-units-present", "status": "fail"})
        ok = False
    else:
        checks.append({"check": "close-delivery-units-present", "status": "ok"})
    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        checks.append({"check": "issue-store-effective", "status": "skipped"})
    return {"verdict": "pass" if ok else "fail", "action": "rollout-after-060-r1-r7", "checks": checks}


def write_back_gap_prereqs_061(root: Path, cfg: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return {"verdict": "skipped", "action": "write-back-gap-prereqs", "reason": "not-issue-store"}
    gate = gate_prd_060_r1_r7(root, cfg)
    if gate.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "action": "write-back-gap-prereqs",
            "error": "prd-060-gate",
            "gate": gate,
        }
    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "fail", "action": "write-back-gap-prereqs", "error": "issue-store-backend-required"}
    results: list[dict[str, Any]] = []
    for record in pmis.list_gap_issue_records(root, cfg):
        unit_id = str(getattr(record, "unit_id", "") or "")
        num = _gap_number_from_unit_id(unit_id)
        if num not in GAP_PREREQ_NUMBERS:
            continue
        body_path = _default_body_path(unit_id, "gap")
        fetched = backend.get(unit_id, body_path)
        if fetched.verdict != "ok" or not fetched.content:
            results.append({"unitId": unit_id, "verdict": "fail", "error": "missing-content"})
            continue
        new_content, changed = _merge_depends_frontmatter(fetched.content, PRD_061_DEPENDS_TARGET)
        if not changed:
            results.append({"unitId": unit_id, "verdict": "ok", "skipped": True, "reason": "depends-present"})
            continue
        if dry_run:
            results.append({"unitId": unit_id, "verdict": "dry-run", "wouldUpdate": True})
            continue
        put_result = backend.put(unit_id, body_path, new_content)
        pmis.sync_gap_issue_labels(root, unit_id, new_content, cfg)
        results.append({"unitId": unit_id, "verdict": put_result.verdict, "hash": put_result.hash})
    if not results:
        return {"verdict": "ok", "action": "write-back-gap-prereqs", "dryRun": dry_run, "results": [], "note": "no-gap-078-079"}
    ok = all(r.get("verdict") in {"ok", "dry-run"} or r.get("skipped") for r in results)
    return {"verdict": "ok" if ok else "partial", "action": "write-back-gap-prereqs", "dryRun": dry_run, "results": results}


def resolve_absorbed_gaps_061(
    root: Path,
    cfg: dict[str, Any],
    *,
    dry_run: bool = False,
    force: bool = False,
    unit_id: str | None = None,
) -> dict[str, Any]:
    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return {"verdict": "skipped", "action": "resolve-absorbed-gaps-061", "reason": "not-issue-store"}
    if unit_id:
        num = _gap_number_from_unit_id(unit_id)
        if num in PRD_060_GAP_ABSORB_DENY:
            return {
                "verdict": "fail",
                "action": "resolve-absorbed-gaps-061",
                "error": "prd-060-gap-denylist",
                "unitId": unit_id,
            }
        targets = [unit_id]
    else:
        targets = []
        for record in pmis.list_gap_issue_records(root, cfg):
            uid = str(getattr(record, "unit_id", "") or "")
            num = _gap_number_from_unit_id(uid)
            if num in ABSORB_GAP_NUMBERS:
                targets.append(uid)
    gate = gate_prd_060_r1_r7(root, cfg)
    if not force and gate.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "action": "resolve-absorbed-gaps-061",
            "error": "prd-060-gate",
            "gate": gate,
        }
    results: list[dict[str, Any]] = []
    for uid in sorted(set(targets)):
        num = _gap_number_from_unit_id(uid)
        if num in PRD_060_GAP_ABSORB_DENY:
            return {
                "verdict": "fail",
                "action": "resolve-absorbed-gaps-061",
                "error": "prd-060-gap-denylist",
                "unitId": uid,
            }
        if dry_run:
            results.append({"unitId": uid, "verdict": "dry-run"})
            continue
        results.append(pmis.close_gap_issue(root, uid, cfg))
    ok = all(r.get("verdict") in {"pass", "dry-run"} for r in results)
    return {"verdict": "ok" if ok else "partial", "action": "resolve-absorbed-gaps-061", "dryRun": dry_run, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description="Planning store interface (PRD 034 + PRD 043)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in (
        "resolve-backend",
        "list-backends",
        "list-facade",
        "lint-facade-imports",
        "lint-projection-mutations",
        "operator-projection-contract",
        "linear-projection-schema",
        "comments-relations-schema",
        "issues-provider-registration",
        "resolve-issues",
        "resolve-store-location",
        "probe-issues-token",
        "probe-jira-init",
        "bitbucket-issue-store-guidance",
        "validate-project-key",
        "put",
        "get",
        "exists",
        "materialize",
        "materialize-from-store",
        "validate-local-synced",
        "canonical-hash",
        "freeze",
        "verify-frozen-hash",
        "link-brainstorm-prd",
        "mark-issue-tombstone",
        "mark-issue-transferred",
        "clear-issue-fixture",
        "close-delivery-units",
        "doctor",
        "cleanup",
        "progress-update",
        "migrate-orphan-phase-issues",
        "projection-refresh",
        "probe-projection",
        "write-back-gap-prereqs",
        "resolve-absorbed-gaps-061",
        "verify-absorb-linkage-066",
    ):
        sub.add_parser(name)
    args, rest = parser.parse_known_args()
    root = git_root(Path(args.root).resolve())
    cfg = load_workflow_config(root)
    if args.command == "list-facade":
        emit(facade_surface())
    elif args.command == "lint-facade-imports":
        scope = _optional(rest, "--path")
        result = lint_facade_imports(root, scope=scope)
        emit(result, 0 if result.get("verdict") == "pass" else 20)
    elif args.command == "lint-projection-mutations":
        scope = _optional(rest, "--path")
        result = lint_projection_mutations(root, scope=scope)
        emit(result, 0 if result.get("verdict") == "pass" else 20)
    elif args.command == "operator-projection-contract":
        emit(operator_projection_contract())
    elif args.command == "linear-projection-schema":
        emit(linear_projection_schema_contract())
    elif args.command == "comments-relations-schema":
        emit(comments_relations_schema_contract())
    elif args.command == "issues-provider-registration":
        emit(issues_provider_registration_footprint())
    elif args.command == "resolve-backend":

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
    elif args.command == "probe-jira-init":
        issues = resolve_issues_provider(cfg)
        if issues.get("provider") != "jira":
            emit({"verdict": "ok", "skipped": True, "reason": "not-jira"})
        token_env = resolve_issues_token_env(cfg, "jira")
        if not token_env or not token_present(token_env):
            fail("missing-token", tokenEnv=token_env)
        from planning_jira_probe import probe_jira_init
        result = probe_jira_init(cfg, os.environ.get(token_env, ""), root)
        emit(result, 0 if result.get("verdict") == "ok" else 2)
    elif args.command == "bitbucket-issue-store-guidance":
        guidance = bitbucket_issue_store_guidance(root, cfg)
        if guidance:
            emit(guidance)
        emit({"verdict": "ok", "skipped": True, "reason": "not-bitbucket-or-issues-configured"})
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
        unit_id = _require(rest, "--unit-id")
        body_path = _require(rest, "--body-path")
        dest = Path(_require(rest, "--dest"))
        if "--resync" in rest:
            result = materialize_with_resync(root, unit_id, body_path, dest)
            exit_code = 0 if result.get("verdict") == "ok" else 1
            emit(result, exit_code)
        backend = get_backend(root, cfg, override=_optional(rest, "--backend"))
        result = backend.materialize(unit_id, body_path, dest)
        emit(result.as_dict(), 0 if result.verdict == "ok" else 2)
    elif args.command == "materialize-from-store":
        units_file = _optional(rest, "--units-file")
        units_raw = _optional(rest, "--units-json")
        if units_file:
            units = json.loads(Path(units_file).read_text(encoding="utf-8"))
        elif units_raw:
            units = json.loads(units_raw)
        else:
            units = []
        result = materialize_from_store(root, cfg, units)
        emit(result, 0 if result.get("verdict") == "ok" else 2)

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

    elif args.command == "freeze":
        backend = get_backend(root, cfg, override="issue-store")
        if not isinstance(backend, IssueStoreBackend):
            fail("issue-store backend required")
        distill = "--no-distill" not in rest
        emit(backend.freeze(_require(rest, "--unit-id"), _require(rest, "--body-path"), distill=distill))
    elif args.command == "verify-frozen-hash":
        backend = get_backend(root, cfg, override="issue-store")
        if not isinstance(backend, IssueStoreBackend):
            fail("issue-store backend required")
        result = backend.verify_frozen_hash(_require(rest, "--unit-id"), _require(rest, "--body-path"))
        emit(result)
    elif args.command == "mark-issue-tombstone":
        client = IssuesClient(root, resolve_issues_provider(cfg).get("provider", "none"))
        client.mark_tombstone(_require(rest, "--issue-id"))
        emit({"verdict": "ok"})
    elif args.command == "mark-issue-transferred":
        client = IssuesClient(root, resolve_issues_provider(cfg).get("provider", "none"))
        client.mark_transferred(_require(rest, "--issue-id"))
        emit({"verdict": "ok"})
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
    elif args.command == "close-delivery-units":
        dry_run = "--dry-run" in rest
        result = close_delivery_units(root, cfg, _require(rest, "--prd-unit"), dry_run=dry_run)
        emit(result, 0 if result.get("verdict") in {"ready", "dry-run"} else 2)
    elif args.command == "projection-refresh":
        from planning_github_projects_v2 import refresh_projection, sample_projection_items

        dry_run = "--dry-run" in rest
        result = refresh_projection(root, cfg, dry_run=dry_run, items=sample_projection_items(root, cfg))
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "probe-projection":
        from planning_github_projects_v2 import projection_health

        result = projection_health(root, cfg)
        emit(result)
    elif args.command == "write-back-gap-prereqs":
        dry_run = "--dry-run" in rest
        result = write_back_gap_prereqs_061(root, cfg, dry_run=dry_run)
        emit(result, 0 if result.get("verdict") in {"ok", "skipped"} else 20)
    elif args.command == "resolve-absorbed-gaps-061":
        dry_run = "--dry-run" in rest
        force = "--force" in rest
        unit_id = _optional(rest, "--unit-id")
        result = resolve_absorbed_gaps_061(root, cfg, dry_run=dry_run, force=force, unit_id=unit_id)
        emit(result, 0 if result.get("verdict") in {"ok", "skipped"} else 20)
    elif args.command == "audit-closure-completeness":
        prd_unit = _require(rest, "--prd-unit")
        result = audit_closure_completeness(root, cfg, prd_unit)
        emit(result, 0 if result.get("verdict") == "ready" else 20)

    elif args.command == "verify-absorb-linkage-066":
        prd_unit = _optional(rest, "--prd-unit-id") or PRD_066_ABSORB_UNIT_ID
        gap_unit = _optional(rest, "--gap-unit-id") or GAP_079_ABSORB_UNIT_ID
        planning_issue = _optional(rest, "--planning-issue") or GAP_079_PLANNING_ISSUE_REF
        result = verify_absorb_linkage_066(
            root,
            cfg,
            prd_unit_id=prd_unit,
            gap_unit_id=gap_unit,
            planning_issue=planning_issue,
        )
        emit(result, 0 if result.get("verdict") in {"ok", "skipped"} else 20)
    elif args.command == "doctor":
        result = doctor(root, cfg)
        emit(result, 0 if result.get("verdict") == "pass" else 20)

    elif args.command == "progress-update":
        parent = _require(rest, "--parent-issue-id")
        phase_id = _require(rest, "--phase-id")
        action = _optional(rest, "--action") or "phase-done"
        provider = _optional(rest, "--provider")
        project_key = _optional(rest, "--project-key")
        task_list = _optional(rest, "--task-list")
        task_ref = _optional(rest, "--task-ref")
        checked_raw = _optional(rest, "--checked-phase-ids")
        checked = [x.strip() for x in checked_raw.split(",") if x.strip()] if checked_raw else None
        result = progress_update(
            root,
            parent_issue_id=parent,
            phase_id=phase_id,
            action=action,
            provider=provider,
            project_key=project_key,
            task_list=task_list,
            checked_phase_ids=checked,
            task_ref=task_ref,
        )
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "migrate-orphan-phase-issues":
        unit_id = _optional(rest, "--tasks-unit-id")
        dry_run = "--apply" not in rest
        result = migrate_orphan_phase_issues(root, cfg, tasks_unit_id=unit_id, dry_run=dry_run)
        emit(result, 0 if result.get("verdict") == "ok" else 20)
    elif args.command == "cleanup":
        apply = "--apply" in rest
        result = cleanup_separate_project_local_writes(root, cfg, apply=apply)
        emit(result, 0 if result.get("verdict") == "ok" else 20)


if __name__ == "__main__":
    main()
