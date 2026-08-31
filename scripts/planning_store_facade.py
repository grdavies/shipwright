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
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import issues_http

from credentials.model import (
    CredentialRef,
    Resolution,
    ResolutionState,
    ResolvedToken,
    Secret,
)
from credentials.resolver import RepositoryContext, resolve
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
from planning_notion_projection import (
    apply_dual_property_capability as apply_notion_dual_property_capability,
    assert_projection_mirrors_not_freeze_authority as assert_notion_projection_mirrors_not_freeze_authority,
    check_canonical_projection_split_brain as check_notion_canonical_projection_split_brain,
    dual_write_body_policy as notion_dual_write_body_policy,
    dual_write_projection_mirror as dual_write_notion_projection_mirror,
    encode_planning_edge as encode_notion_planning_edge,
    map_artifact_to_notion_entity,
    notion_entity_mapping,
    notion_projection_schema_contract,
    probe_dual_property_availability as probe_notion_dual_property_availability,
    project_graph_to_notion_layout,
    rebuild_projection_for_unit as rebuild_notion_projection_for_unit,
    resolve_canonical_freeze_body as resolve_notion_canonical_freeze_body,
)

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _planning_pkg_loader import load_package, load_submodule  # noqa: E402

_planning_pkg = load_package()
BARE_INTEGER_UNIT_ID = _planning_pkg.BARE_INTEGER_UNIT_ID
DECISION_ARTIFACT_TYPE = _planning_pkg.DECISION_ARTIFACT_TYPE
DECISION_GRAPH_FILENAME = _planning_pkg.DECISION_GRAPH_FILENAME
DECISION_GRAPH_UNIT_SUFFIX = _planning_pkg.DECISION_GRAPH_UNIT_SUFFIX
DECISION_ISSUE_TYPE_LABEL = _planning_pkg.DECISION_ISSUE_TYPE_LABEL
LEGACY_UNIT_MAP_PATH = _planning_pkg.LEGACY_UNIT_MAP_PATH
NATIVE_UNIT_ID_PATTERN = _planning_pkg.NATIVE_UNIT_ID_PATTERN
NATIVE_UNIT_ID_PREFIX = _planning_pkg.NATIVE_UNIT_ID_PREFIX
PROJECT_KEY_PATTERN = _planning_pkg.PROJECT_KEY_PATTERN
PROJECT_KEY_REGISTRY = _planning_pkg.PROJECT_KEY_REGISTRY
decision_graph_unit_id = _planning_pkg.decision_graph_unit_id
decision_graph_virtual_body_path = _planning_pkg.decision_graph_virtual_body_path
decision_record_virtual_body_path = _planning_pkg.decision_record_virtual_body_path
format_native_unit_id = _planning_pkg.format_native_unit_id
is_decision_graph_body_path = _planning_pkg.is_decision_graph_body_path
resolve_decision_put_path = _planning_pkg.resolve_decision_put_path
is_bare_integer_unit_id = _planning_pkg.is_bare_integer_unit_id
is_namespaced_native_unit_id = _planning_pkg.is_namespaced_native_unit_id
load_legacy_unit_map = _planning_pkg.load_legacy_unit_map
load_project_key_registry = _planning_pkg.load_project_key_registry
native_unit_id_prefix = _planning_pkg.native_unit_id_prefix
register_legacy_unit_mapping = _planning_pkg.register_legacy_unit_mapping
reject_bare_integer_unit_id = _planning_pkg.reject_bare_integer_unit_id
resolve_legacy_unit_id = _planning_pkg.resolve_legacy_unit_id
reverse_resolve_legacy_unit_id = _planning_pkg.reverse_resolve_legacy_unit_id
resolve_store_location = _planning_pkg.resolve_store_location
save_legacy_unit_map = _planning_pkg.save_legacy_unit_map
store_location_fingerprint = _planning_pkg.store_location_fingerprint
unit_id_lookup_candidates = _planning_pkg.unit_id_lookup_candidates
validate_project_key = _planning_pkg.validate_project_key
ISSUES_MIGRATION_HOOKS = _planning_pkg.ISSUES_MIGRATION_HOOKS
ORPHAN_MIGRATED_LABEL = _planning_pkg.ORPHAN_MIGRATED_LABEL
migrate_orphan_phase_issues = _planning_pkg.migrate_orphan_phase_issues
MATERIALIZE_MISSING_FROZEN_BODY = _planning_pkg.MATERIALIZE_MISSING_FROZEN_BODY
PlanningUnit = _planning_pkg.PlanningUnit
StoreResult = _planning_pkg.StoreResult
materialize_missing_result = _planning_pkg.materialize_missing_result
PlanningStoreBackend = _planning_pkg.PlanningStoreBackend

DEFAULT_BACKEND = "in-repo-public"
SHIPPED_BACKENDS = frozenset({"in-repo-public", "local-synced", "planning-cache", "issue-store"})
DEFERRED_BACKENDS = frozenset({"private-repo", "encryption-at-rest"})
# PRD 333 phase 7 — P2 planning-store spec stubs (metadata only; not in ALL_BACKENDS).
P2_PLANNING_STORE_STUBS = frozenset({"gitlab-planning-store"})
ALL_BACKENDS = SHIPPED_BACKENDS | DEFERRED_BACKENDS
BACKEND_CONFIG_ALIASES = {"memory": "planning-cache"}

def _linear_live_client_wired() -> bool:
    """PRD 066 R9 — recognize Linear in ISSUES_PROVIDERS only when live client exists."""
    from _planning_pkg_loader import load_providers_package

    return load_providers_package().linear.live_client_wired()


def _notion_live_client_wired() -> bool:
    """PRD 327 R9 — recognize Notion in ISSUES_PROVIDERS only when live client exists."""
    from _planning_pkg_loader import load_providers_package

    return load_providers_package().notion.live_client_wired()


_BASE_ISSUES_PROVIDERS = frozenset({"github-issues", "gitlab-issues", "jira", "none"})
_ISSUES_LIVE_RECOGNITION = frozenset({"linear"}) if _linear_live_client_wired() else frozenset()
if _notion_live_client_wired():
    _ISSUES_LIVE_RECOGNITION = _ISSUES_LIVE_RECOGNITION | frozenset({"notion"})
ISSUES_PROVIDERS = _BASE_ISSUES_PROVIDERS | _ISSUES_LIVE_RECOGNITION
# PRD 057 R7 / D1: gitlab-issues is a known-but-deferred provider — supported for
# config validation yet absent from the shipped set until a live adapter ships in a
# follow-up unit (originating gap-039). Selection therefore fails closed with the
# issues-provider-not-shipped fallback reason instead of an advertised round-trip.
# PRD 066 R9/R20 / PRD 086 R2: linear is recognized when the live client is wired;
# promoted to shipped after recorded stage1-dogfood-gate + oauth-docs-gate evidence.
DEFERRED_ISSUES_PROVIDERS = frozenset({"gitlab-issues"})
# PRD 090 R3 — shipped membership is derived from recorded green conformance evidence.
_REPO_ROOT = SCRIPT_DIR.parent


def resolve_shipped_issues_providers(root: Path | None = None) -> frozenset[str]:
    return load_submodule("provider_conformance").providers_with_green_conformance(root or _REPO_ROOT)


SHIPPED_ISSUES_PROVIDERS = resolve_shipped_issues_providers()

MIN_ISSUES_SCOPES: dict[str, list[str]] = {
    "github-issues": ["repo"],
    "gitlab-issues": ["api"],
    "jira": ["read:jira-work", "write:jira-work"],
    "linear": ["read", "write"],
    "notion": [],
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
ISSUE_STORE_TXN_ID = "issue-store"
FILE_BACKED_STORE_TXN_ID = "file-backed"
PUT_INCOMPLETE_LABEL = "sw:put-incomplete"


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


class PlanningIssueRefResolutionError(Exception):
    """Fail-closed planning issue ref resolution (PRD 275 R15/R16)."""

    def __init__(self, ref: str, error: str, **detail: Any) -> None:
        self.ref = ref
        self.error = error
        self.detail = detail
        super().__init__(f"{error}: {ref}")
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
    resolve_put_edge_projection,
    rewrite_chunk_manifest_ids,
    strip_markers_and_edges,
    canonical_content_from_operator,
    frontmatter_from_labels,
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
from planning_doc_review_transport import (  # noqa: E402
    TXN_VERBS,
    execute_doc_review_txn,
    require_github_issue_store,
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
    destination = planning_visibility.resolve_emission_destination("store-get")
    proc = subprocess.run(
        [str(SCRIPT_DIR / "memory-redact.py"), "--destination", destination],
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


ISSUES_CAPABILITY_INDEX_IDS: dict[str, str] = {
    "github-issues": "provider.providers.issues.github-issues",
    "gitlab-issues": "provider.providers.issues.gitlab-issues",
    "jira": "provider.providers.issues.jira",
    "linear": "provider.providers.issues.linear",
    "notion": "provider.providers.issues.notion",
    "none": "provider.providers.issues.none",
}

def issues_provider_registration_footprint() -> dict[str, Any]:
    """PRD 066 R16/R20 — registration touchpoints for issue-backed adapters."""
    from _planning_pkg_loader import load_providers_package

    linear_wired = _linear_live_client_wired()
    notion_wired = _notion_live_client_wired()
    live_recognized = _ISSUES_LIVE_RECOGNITION
    return {
        "verdict": "ok",
        "action": "issues-provider-registration",
        "issuesProviders": sorted(ISSUES_PROVIDERS),
        "shippedIssuesProviders": sorted(SHIPPED_ISSUES_PROVIDERS),
        "deferredIssuesProviders": sorted(DEFERRED_ISSUES_PROVIDERS),
        "rateLimitMap": dict(issues_http.ISSUES_PROVIDER_TO_RATELIMIT),
        "capabilityIndexIds": dict(ISSUES_CAPABILITY_INDEX_IDS),
        "migrationHooks": list(ISSUES_MIGRATION_HOOKS),
        "linear": load_providers_package().linear.registration_footprint(
            recognized="linear" in ISSUES_PROVIDERS,
            shipped="linear" in SHIPPED_ISSUES_PROVIDERS,
            live_client_wired=linear_wired,
        ),
        "notion": load_providers_package().notion.registration_footprint(
            recognized="notion" in ISSUES_PROVIDERS,
            shipped="notion" in SHIPPED_ISSUES_PROVIDERS,
            live_client_wired=notion_wired,
        ),
        "recognitionVsShipped": {
            provider: {
                "recognized": provider in ISSUES_PROVIDERS,
                "shipped": provider in SHIPPED_ISSUES_PROVIDERS,
                "deferred": provider in DEFERRED_ISSUES_PROVIDERS,
            }
            for provider in sorted(_BASE_ISSUES_PROVIDERS | live_recognized)
        },
    }


def planning_store_p2_stub_registration_footprint() -> dict[str, Any]:
    """PRD 333 phase 7 — P2 planning-store spec stubs (metadata only, not shipped)."""
    from _planning_pkg_loader import load_backends_package

    backends = load_backends_package()
    registration = backends.register_gitlab_planning_store_stub()
    return {
        "verdict": "ok",
        "action": "planning-store-p2-stub-registration",
        "stubs": {backends.GITLAB_PLANNING_STORE_BACKEND_ID: registration},
        "p2Stubs": sorted(P2_PLANNING_STORE_STUBS),
        "shippedBackends": sorted(SHIPPED_BACKENDS),
        "allBackends": sorted(ALL_BACKENDS),
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
    if provider == "linear":
        from _planning_pkg_loader import load_providers_package

        linear_result = load_providers_package().linear.doctor_stub_result(
            root,
            provider=provider,
            issues_providers=ISSUES_PROVIDERS,
            shipped_providers=SHIPPED_ISSUES_PROVIDERS,
        )
        if linear_result is not None:
            return linear_result
    if provider == "notion":
        from _planning_pkg_loader import load_providers_package

        notion_result = load_providers_package().notion.doctor_stub_result(
            root,
            provider=provider,
            issues_providers=ISSUES_PROVIDERS,
            shipped_providers=SHIPPED_ISSUES_PROVIDERS,
        )
        if notion_result is not None:
            return notion_result
    return {"verdict": "pass", "action": "doctor-issues-provider-stub", "provider": provider}


def resolve_issues_token_env(cfg: dict[str, Any], issues_provider: str = "") -> str:
    """Return an explicitly configured issues tokenEnv only — no implicit provider defaults."""
    _ = issues_provider
    issues = issues_section(cfg)
    token_env = issues.get("tokenEnv")
    if isinstance(token_env, str) and token_env.strip():
        return token_env.strip()
    return ""


_ISSUES_PROVIDER_TO_BROKER: dict[str, str] = {
    "github-issues": "github",
    "gitlab-issues": "gitlab",
    "jira": "jira",
    "linear": "linear",
    "notion": "notion",
}


def _issues_destination_endpoint(cfg: dict[str, Any], issues_provider: str) -> str:
    from _planning_pkg_loader import load_providers_package

    return load_providers_package().destination_endpoint(cfg, issues_provider)


def resolve_issues_credential(
    root: Path,
    *,
    issues_provider: str | None = None,
    destination_endpoint: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> Resolution:
    """Resolve the planning issue-store credential through the broker (tri-state)."""
    resolved_cfg = cfg if cfg is not None else load_workflow_config(root)
    provider_info = resolve_issues_provider(resolved_cfg)
    provider = issues_provider or str(provider_info.get("provider") or "none")
    issues = issues_section(resolved_cfg)
    cred_ref_raw = issues.get("credentialRef")
    token_env = resolve_issues_token_env(resolved_cfg, provider)
    api_base = destination_endpoint or _issues_destination_endpoint(resolved_cfg, provider)
    project_id = resolved_cfg.get("projectId")
    project_id_str = (
        project_id.strip() if isinstance(project_id, str) and project_id.strip() else "unpaired"
    )
    remote = remote_name(resolved_cfg)
    remote_url = git_remote_url(root, remote)
    parsed = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    repo_slug = f"{parsed[0]}/{parsed[1]}" if parsed else ""
    broker_provider = _ISSUES_PROVIDER_TO_BROKER.get(provider, provider)

    if isinstance(cred_ref_raw, str) and cred_ref_raw.strip():
        ref = CredentialRef(cred_ref_raw.strip())
        context = RepositoryContext(
            remote=remote_url or remote,
            repo_slug=repo_slug,
            project_id=project_id_str,
            destination_endpoint=api_base or "https://api.github.com",
        )
        return resolve(
            ref,
            provider=broker_provider if broker_provider not in {"none", ""} else "github",
            purpose="planning",
            context=context,
        )

    if token_env:
        # One-release tokenEnv alias — explicit configured name only (no DEFAULT_ISSUES_TOKEN_ENV).
        value = os.environ.get(token_env, "")
        alias_ref = CredentialRef(f"tokenEnv:{token_env}")
        if value.strip():
            return Resolution.resolved(alias_ref, ResolvedToken(Secret(value)))
        return Resolution.unresolved(alias_ref, reason="missing-token")

    if provider in {"none", ""} or not api_base:
        return Resolution.explicitly_no_auth(
            CredentialRef("issues-none"),
            reason="no-issues-credential",
        )
    return Resolution.explicitly_no_auth(
        CredentialRef("issues-unauthenticated"),
        reason="no-issues-credential",
    )


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


def _legacy_kill_switch_shim_warnings() -> list[str]:
    """Warn-only legacy env shim — cannot affect resolved behavior (PRD 080 R8)."""
    import planning_backend_control as pbc

    return pbc.legacy_kill_switch_env_shim()


def _effective_backend_disable_active(
    root: Path,
    cfg: dict[str, Any],
    *,
    override: str | None = None,
) -> bool:
    import planning_backend_control as pbc

    return pbc.is_forced_file_store_fallback(root, cfg, override=override)


def _authority_resolution(root: Path, cfg: dict[str, Any], *, override: str | None = None):
    import planning_authority as pa

    return pa.resolve_authority(root, cfg, override=override)


def authority_io_block(
    resolved: dict[str, Any],
    *,
    operation: str = "read",
) -> dict[str, Any] | None:
    """Return a fail-closed payload when authority blocks the requested operation."""
    state = str(resolved.get("authorityState") or "")
    reason = resolved.get("reason")
    if reason == "identity-mismatch":
        return {
            "verdict": "fail",
            "error": "identity-mismatch",
            "reason": reason,
            "operation": operation,
            "configured": resolved.get("configured"),
        }
    if state == "blocked":
        return {
            "verdict": "fail",
            "error": "authority-blocked",
            "reason": reason,
            "operation": operation,
            "configured": resolved.get("configured"),
        }
    if operation == "write" and state == "read-only":
        return {
            "verdict": "fail",
            "error": "authority-read-only",
            "reason": reason,
            "operation": operation,
            "configured": resolved.get("configured"),
        }
    return None


def resolve_effective_backend(root: Path, cfg: dict[str, Any], *, override: str | None = None) -> dict[str, Any]:
    """Resolve backend authority — configured id only; no silent substitution (PRD 082 R26)."""
    import planning_authority_reasons as par

    decision = _authority_resolution(root, cfg, override=override)
    configured = decision.configured
    shim_warnings = _legacy_kill_switch_shim_warnings()
    out: dict[str, Any] = {
        "verdict": "ok",
        "configured": configured,
        "backend": configured,
        "effective": configured,
        "authorityState": decision.authorityState,
        "writeDisposition": decision.writeDisposition,
        "cacheValidity": decision.cacheValidity,
        "reason": decision.reason,
        "fallback": decision.reason is not None,
        "shipped": configured in SHIPPED_BACKENDS,
        "deferred": configured in DEFERRED_BACKENDS,
    }
    if decision.reason:
        out["fallbackReason"] = decision.reason
    if decision.guidance:
        out["guidance"] = decision.guidance
    if decision.reason == par.REASON_KILL_SWITCH:
        out["killSwitch"] = True
        out["notice"] = KILL_SWITCH_NOTICE
    elif decision.reason and configured == "issue-store":
        out["notice"] = ISSUE_STORE_FALLBACK_NOTICE
    if shim_warnings:
        out["legacyShimWarnings"] = shim_warnings
    return out


def _providers_pkg():
    from _planning_pkg_loader import load_providers_package

    return load_providers_package()


def _probe_rate_limited_result(exc: Exception) -> dict[str, Any] | None:
    from _planning_pkg_loader import load_submodule

    return load_submodule("providers._common").probe_rate_limited_result(exc)


def _github_probe_headers(token: str) -> dict[str, str]:
    return _providers_pkg().github.probe_headers(token)


def _github_fine_grained_probe(token: str, cfg: dict[str, Any], root: Path, *, required: set[str]) -> dict[str, Any]:
    return _providers_pkg().github.fine_grained_probe(token, cfg, root, required=required)


def _github_native_links_capable_probe(token: str, cfg: dict[str, Any], root: Path, *, owner: str, repo: str) -> bool:
    return _providers_pkg().github.native_links_capable_probe(token, cfg, root, owner=owner, repo=repo)


def _attach_github_native_links_capable(probe: dict[str, Any], token: str, cfg: dict[str, Any], root: Path) -> None:
    _providers_pkg().github.attach_native_links_capable(probe, token, cfg, root)


def _gitlab_native_links_capable_probe(token: str, cfg: dict[str, Any], root: Path, *, owner: str, project: str) -> bool:
    return _providers_pkg().gitlab.native_links_capable_probe(token, cfg, root, owner=owner, project=project)


def _jira_native_links_capable_probe(token: str, cfg: dict[str, Any], root: Path) -> bool:
    return _providers_pkg().jira.native_links_capable_probe(token, cfg, root)


def _attach_gitlab_native_links_capable(probe: dict[str, Any], token: str, cfg: dict[str, Any], root: Path) -> None:
    _providers_pkg().gitlab.attach_native_links_capable(probe, token, cfg, root)


def _attach_jira_native_links_capable(probe: dict[str, Any], token: str, cfg: dict[str, Any], root: Path) -> None:
    _providers_pkg().jira.attach_native_links_capable(probe, token, cfg, root)


def _github_scope_probe(token: str, cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    return _providers_pkg().github.scope_probe(token, cfg, root)


def _gitlab_scope_probe(token: str, cfg: dict[str, Any], root: Path) -> dict[str, Any]:
    return _providers_pkg().gitlab.scope_probe(token, cfg, root)


def probe_issues_token(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    return _providers_pkg().probe_issues_token(root, cfg)


def _jira_scope_probe(root: Path, cfg: dict[str, Any], token: str) -> dict[str, Any]:
    return _providers_pkg().jira.scope_probe(root, cfg, token)


def jira_privacy_create_gate(root: Path, cfg: dict[str, Any], unit_id: str, body_path: str, content: str) -> None:
    _providers_pkg().jira.privacy_create_gate(root, cfg, unit_id, body_path, content)


def _jira_store_project_browse_private(root: Path, cfg: dict[str, Any], project_key: str) -> bool | None:
    return _providers_pkg().jira.store_project_browse_private(root, cfg, project_key)


def _github_store_repo_private(root: Path, cfg: dict[str, Any], owner: str, repo: str) -> bool | None:
    return _providers_pkg().github.store_repo_private(root, cfg, owner, repo)


def _gitlab_store_project_private(root: Path, cfg: dict[str, Any], owner: str, project: str) -> bool | None:
    return _providers_pkg().gitlab.store_project_private(root, cfg, owner, project)


def parse_visibility_from_content(content: str) -> str | None:
    if content.lstrip().startswith("{"):
        try:
            doc = json.loads(content)
        except json.JSONDecodeError:
            doc = None
        if isinstance(doc, dict):
            metadata = doc.get("metadata")
            if isinstance(metadata, dict):
                vis = metadata.get("visibility")
                if vis is not None and str(vis).strip():
                    return str(vis).strip()
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



# Backend adapters (PRD 082 phase 12 / R27) — imported after module helpers are defined.
from _planning_pkg_loader import load_backends_package  # noqa: E402

_backends = load_backends_package()
ISSUE_STORE_TXN_ID = _backends.ISSUE_STORE_TXN_ID
ISSUE_UNIT_INDEX = _backends.ISSUE_UNIT_INDEX
PUT_JOURNAL_PATH = _backends.PUT_JOURNAL_PATH
InRepoPublicBackend = _backends.InRepoPublicBackend
IssueStoreBackend = _backends.IssueStoreBackend
LocalSyncedBackend = _backends.LocalSyncedBackend
ReplicatedPlanningCacheBackend = _backends.ReplicatedPlanningCacheBackend
issue_index_key = _backends.issue_index_key
load_issue_unit_index = _backends.load_issue_unit_index
load_put_journal = _backends.load_put_journal
mutate_issue_unit_index = _backends.mutate_issue_unit_index
mutate_put_journal = _backends.mutate_put_journal
read_issue_unit_index_locked = _backends.read_issue_unit_index_locked
read_put_journal_locked = _backends.read_put_journal_locked
save_issue_unit_index = _backends.save_issue_unit_index
save_put_journal = _backends.save_put_journal
from _planning_pkg_loader import load_submodule  # noqa: E402

_common = load_submodule("backends._common")
FILE_BACKED_STORE_TXN_ID = _common.FILE_BACKED_STORE_TXN_ID
finalize_materialize_from_get = _common.finalize_materialize_from_get

# Re-export memory round-trip hooks for test monkeypatching (PRD 057 R21b).
_planning_cache_backend = load_submodule("backends.memory_cache")

_urlopen = _planning_cache_backend._urlopen
_provider_round_trip_put = _planning_cache_backend._provider_round_trip_put
_provider_round_trip_get = _planning_cache_backend._provider_round_trip_get
_recallium_rest_base = _planning_cache_backend._recallium_rest_base
_is_allowed_recallium_base = _planning_cache_backend._is_allowed_recallium_base


BACKEND_CLASSES: dict[str, type[PlanningStoreBackend]] = {
    "in-repo-public": InRepoPublicBackend,
    "issue-store": IssueStoreBackend,
    "local-synced": LocalSyncedBackend,
    "planning-cache": ReplicatedPlanningCacheBackend,
    "private-repo": DeferredBackend,
    "encryption-at-rest": DeferredBackend,
}


def resolve_backend_id(cfg: dict[str, Any], *, override: str | None = None) -> str:
    if override:
        override = BACKEND_CONFIG_ALIASES.get(override, override)
    if override and override in ALL_BACKENDS:
        return override
    store = store_section(cfg)
    pinned = store.get("pinnedBackend")
    if isinstance(pinned, str):
        pinned = BACKEND_CONFIG_ALIASES.get(pinned, pinned)
    if isinstance(pinned, str) and pinned in ALL_BACKENDS:
        return pinned
    backend = store.get("backend", DEFAULT_BACKEND)
    if isinstance(backend, str):
        backend = BACKEND_CONFIG_ALIASES.get(backend, backend)
    if isinstance(backend, str) and backend in ALL_BACKENDS:
        return backend
    return DEFAULT_BACKEND


def get_backend(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    override: str | None = None,
    operation: str = "read",
) -> PlanningStoreBackend:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    effective = resolve_effective_backend(root, cfg, override=override)
    blocked = authority_io_block(effective, operation=operation)
    if blocked is not None:
        raise PlanningStoreAuthorityError(blocked)
    backend_id = effective["configured"]
    cls = BACKEND_CLASSES[backend_id]
    if backend_id in DEFERRED_BACKENDS:
        return cls(root, cfg, backend_id)
    return cls(root, cfg)


def _resync_backup_path(dest_path: Path) -> Path:
    return dest_path.parent / f"{dest_path.name}.pre-resync.bak"


_TASK_REF_RE = re.compile(r"^(\d+)\.(\d+)$")


def normalize_task_ref(raw: str) -> str:
    """Canonical dotted task ref (PRD 070 R3)."""
    text = str(raw or "").strip()
    m = _TASK_REF_RE.match(text)
    if not m:
        raise ValueError(f"invalid task ref: {raw!r}")
    return f"{int(m.group(1))}.{int(m.group(2))}"


def resolve_task_ref_aliases(
    raw_refs: list[str] | set[str],
    *,
    known_refs: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve ambiguous or duplicate task refs to canonical form (PRD 070 R3)."""
    canonical_map: dict[str, list[str]] = {}
    blockers: list[dict[str, str]] = []
    for raw in raw_refs:
        text = str(raw or "").strip()
        if not text:
            continue
        for part in (p.strip() for p in text.split(",") if p.strip()):
            try:
                canon = normalize_task_ref(part)
            except ValueError:
                blockers.append({"ref": part, "reason": "invalid-format"})
                continue
            aliases = canonical_map.setdefault(canon, [])
            if part not in aliases:
                aliases.append(part)
    if blockers:
        return {
            "verdict": "fail",
            "error": "unresolvable-task-refs",
            "blockers": blockers,
        }
    canonical_refs = sorted(canonical_map.keys())
    if known_refs is not None:
        unknown = [ref for ref in canonical_refs if ref not in known_refs]
        if unknown:
            return {
                "verdict": "fail",
                "error": "unknown-task-refs",
                "refs": unknown,
                "known": sorted(known_refs),
            }
    return {
        "verdict": "ok",
        "canonical": canonical_refs,
        "aliases": canonical_map,
        "duplicates": {k: v for k, v in canonical_map.items() if len(v) > 1},
    }


def reconcile_ledger_task_refs(
    ledger_tasks: dict[str, Any],
    checkbox_refs: dict[str, bool],
) -> dict[str, Any]:
    """Merge ledger entries under canonical task refs; fail-closed on conflict (PRD 070 R3)."""
    if not isinstance(ledger_tasks, dict):
        ledger_tasks = {}
    all_keys = set(ledger_tasks.keys()) | set(checkbox_refs.keys())
    if not all_keys:
        return {"verdict": "ok", "tasks": {}}
    resolution = resolve_task_ref_aliases(all_keys)
    if resolution.get("verdict") != "ok":
        return resolution
    resolved: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    for canon in resolution.get("canonical") or []:
        aliases = resolution.get("aliases", {}).get(canon, [canon])
        entries: list[dict[str, Any]] = []
        for alias in aliases:
            entry = ledger_tasks.get(alias)
            if isinstance(entry, dict):
                entries.append(entry)
        if not entries:
            continue
        done_vals = {bool(entry.get("done")) for entry in entries}
        if len(done_vals) > 1:
            conflicts.append(
                {
                    "ref": canon,
                    "aliases": aliases,
                    "reason": "conflicting-done-state",
                }
            )
            continue
        resolved[canon] = entries[-1]
    if conflicts:
        return {
            "verdict": "fail",
            "error": "ambiguous-task-refs",
            "conflicts": conflicts,
        }
    return {"verdict": "ok", "tasks": resolved, "aliases": resolution.get("aliases") or {}}


def _apply_ledger_checks(body: str, ledger_tasks: dict[str, Any]) -> tuple[str, int, int]:
    """Re-apply ledger-recorded checks onto a freshly materialized body (PRD 059 R9)."""
    from checkbox_diff import parse_task_checkboxes, toggle_checkbox

    applied = 0
    already_matching = 0
    checkboxes = parse_task_checkboxes(body)
    reconciled = reconcile_ledger_task_refs(ledger_tasks, checkboxes)
    if reconciled.get("verdict") != "ok":
        return body, applied, already_matching
    ledger_tasks = reconciled.get("tasks") or {}
    alias_map = reconciled.get("aliases") or {}
    updated = body
    for ref, entry in sorted(ledger_tasks.items()):
        if not isinstance(entry, dict) or not entry.get("done"):
            continue
        if checkboxes.get(ref, False):
            already_matching += 1
            continue
        toggle_ref = ref
        for alias in alias_map.get(ref, [ref]):
            if alias in checkboxes:
                toggle_ref = alias
                break
        try:
            updated = toggle_checkbox(updated, toggle_ref, done=True)
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
    reconciled = reconcile_ledger_task_refs(ledger_tasks if isinstance(ledger_tasks, dict) else {}, checkboxes)
    if reconciled.get("verdict") != "ok":
        return [
            {
                "ref": "",
                "kind": "blocker",
                "reason": reconciled.get("error") or "ambiguous-task-refs",
                "detail": reconciled,
            }
        ]
    ledger_tasks = reconciled.get("tasks") or {}
    divergences: list[dict[str, Any]] = []
    for ref, checked in checkboxes.items():
        try:
            canon = normalize_task_ref(ref)
        except ValueError:
            if checked:
                divergences.append(
                    {"ref": ref, "kind": "blocker", "reason": "invalid-checkbox-ref"}
                )
            continue
        entry = ledger_tasks.get(canon)
        if not entry:
            if checked:
                divergences.append(
                    {"ref": canon, "kind": "stale", "reason": "checkbox-checked-missing-ledger"}
                )
            continue
        ledger_done = bool(entry.get("done"))
        if ledger_done != checked:
            divergences.append(
                {
                    "ref": canon,
                    "kind": "divergence",
                    "reason": "checkbox-ledger-mismatch",
                    "checkbox": checked,
                    "ledger": ledger_done,
                }
            )
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
    if not _effective_backend_disable_active(root, cfg):
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


def _fm_field_as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _resolve_prd_absorption_context(
    prd_record: Any,
    prd_unit: str,
    full_body: str,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Resolve PRD frontmatter + edges for anchored absorption discovery (PRD 070 R1)."""
    edges = parse_edges_block(full_body) or {}
    pmis = _migrate_issue_store()
    if has_raw_yaml_frontmatter(full_body):
        raw_content = strip_markers_and_edges(full_body)
        return pmis.parse_frontmatter_fields(raw_content), edges
    if is_hybrid_operator_body(full_body):
        hybrid = frontmatter_from_labels(
            list(getattr(prd_record, "labels", []) or []),
            unit_id=prd_unit,
            operator_body=full_body,
        )
        fm = {key: _fm_field_as_str(hybrid.get(key)) for key in hybrid}
        stripped = strip_markers_and_edges(full_body)
        if stripped.startswith("---"):
            yaml_fm = pmis.parse_frontmatter_fields(stripped)
            for key, value in yaml_fm.items():
                if value:
                    fm[key] = value
        return fm, edges
    raw_content = strip_markers_and_edges(full_body)
    return pmis.parse_frontmatter_fields(raw_content), edges


def _is_gap_unit_absorb_target(target: str) -> bool:
    """True when ``target`` already names a gap unit id (gap-* or contains ``gap``)."""
    value = target.strip()
    return bool(value) and ("gap" in value or value.startswith("gap-"))


def _is_planning_issue_absorb_ref(target: str) -> bool:
    """True for bare planning-issue numbers used as absorb targets (gap-309).

    Hybrid PRD ``sw-edges`` often store ``\"691\"`` / ``planning#691`` rather than
    ``gap-*`` unit ids. Those refs are delivery-grade once resolved via the issue store.
    """
    raw = target.strip()
    if not raw or _is_gap_unit_absorb_target(raw):
        return False
    normalized = _normalize_planning_issue_ref(raw)
    return bool(re.fullmatch(r"(?:planning#|#)?\d+", normalized, flags=re.IGNORECASE))


def _iter_numeric_absorb_refs(
    fm: dict[str, str],
    edges: dict[str, Any] | None,
) -> list[str]:
    """Collect unique numeric / planning# absorb targets from frontmatter + edges."""
    refs: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        value = raw.strip()
        if not value or not _is_planning_issue_absorb_ref(value):
            return
        key = _normalize_planning_issue_ref(value)
        if key in seen:
            return
        seen.add(key)
        refs.append(value)

    for target in _parse_absorbs_targets(fm.get("absorbs", "")):
        _add(target)
    for edge in (edges or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        rel = str(edge.get("rel") or edge.get("relationship") or "depends").strip().lower()
        if rel != "absorbs":
            continue
        _add(str(edge.get("target", "")).strip())
    return refs


def _eligible_open_gap_unit_id(record: Any) -> str | None:
    """Return gap unit id when ``record`` is an eligible open gap, else ``None``."""
    from planning_canonical import gap_status_from_labels

    try:
        artifact_type = _resolve_planning_issue_artifact_type(record)
    except PlanningIssueRefResolutionError:
        return None
    if artifact_type != "gap":
        return None
    labels = list(getattr(record, "labels", []) or [])
    gap_status = gap_status_from_labels(labels)
    if gap_status == "open":
        unit_id = str(getattr(record, "unit_id", "") or "").strip()
        return unit_id or None
    if gap_status is None and str(getattr(record, "state", "")) == "open":
        unit_id = str(getattr(record, "unit_id", "") or "").strip()
        return unit_id or None
    return None


def _collect_eligible_open_gaps_for_numeric_ref(
    root: Path,
    cfg: dict[str, Any],
    ref: str,
    *,
    backend: "IssueStoreBackend",
    gap_catalog: list[Any] | None = None,
) -> list[str]:
    """Collect eligible open gap unit ids matching a numeric planning-issue absorb ref."""
    pmis = _migrate_issue_store()
    key_result = pmis.validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        raise PlanningIssueRefResolutionError(
            ref,
            "invalid-project-key",
            message=str(key_result.get("message") or "invalid project key"),
        )
    project_key = str(key_result["projectKey"])
    normalized = _normalize_planning_issue_ref(ref)
    m = re.search(r"(?:planning#|#)?(\d+)$", normalized, re.I)
    if not m:
        raise PlanningIssueRefResolutionError(ref, "absorb-ref-invalid")
    issue_num = int(m.group(1))
    client = backend._client
    matches: list[str] = []
    seen: set[str] = set()

    def _consider(record: Any) -> None:
        gap_id = _eligible_open_gap_unit_id(record)
        if gap_id and gap_id not in seen:
            seen.add(gap_id)
            matches.append(gap_id)

    record = _lookup_planning_issue_record_for_ref(
        client,
        project_key=project_key,
        issue_num=issue_num,
        ref=ref,
    )
    if record is not None:
        _consider(record)

    records = gap_catalog
    if records is None:
        try:
            records = _search_issue_records(
                client,
                project_key=project_key,
                artifact_type="gap",
            )
        except (
            IssueCapabilityError,
            IssueBudgetExhausted,
            IssueTombstone,
            IssueTransferred,
        ) as exc:
            raise _planning_issue_ref_provider_error(ref, exc) from exc
    needles = {
        normalized,
        f"planning#{issue_num}",
        f"#{issue_num}",
    }
    for item in records:
        unit_id = str(getattr(item, "unit_id", "") or "").strip()
        if not unit_id:
            continue
        if int(getattr(item, "number", 0) or 0) == issue_num:
            _consider(item)
            continue
        body = reassemble_body(item.body, item.comments)
        gap_fm = pmis.parse_frontmatter_fields(strip_markers_and_edges(body))
        related = str(gap_fm.get("related") or "")
        if any(needle and needle in related for needle in needles):
            _consider(item)
    return matches


def _resolve_numeric_absorb_ref_to_gap(
    root: Path,
    cfg: dict[str, Any],
    ref: str,
    *,
    backend: "IssueStoreBackend",
    gap_catalog: list[Any] | None = None,
) -> str:
    """Resolve one numeric absorb ref to exactly one eligible open gap (PRD 278 R6/D5)."""
    matches = _collect_eligible_open_gaps_for_numeric_ref(
        root, cfg, ref, backend=backend, gap_catalog=gap_catalog
    )
    if not matches:
        raise PlanningIssueRefResolutionError(ref, "absorb-gap-unresolved")
    if len(matches) > 1:
        raise PlanningIssueRefResolutionError(
            ref,
            "absorb-gap-ambiguous",
            candidates=matches,
        )
    return matches[0]


def _resolve_numeric_absorb_refs_to_gaps(
    root: Path,
    cfg: dict[str, Any],
    refs: list[str],
    *,
    backend: "IssueStoreBackend | None" = None,
    fail_closed: bool = True,
) -> tuple[set[str], list[dict[str, str]]]:
    """Resolve bare issue-number absorb refs to gap unit ids (gap-309 / PRD 275 path).

  When ``fail_closed`` is true (closeout default), 0-match and N>1 per ref raise
  ``PlanningIssueRefResolutionError`` (typed not-ready). Provider/API faults also raise.
    """
    delivery_grade: set[str] = set()
    skipped: list[dict[str, str]] = []
    if not refs:
        return delivery_grade, skipped
    shared = backend
    if shared is None:
        candidate = get_backend(root, cfg, override="issue-store")
        shared = candidate if isinstance(candidate, IssueStoreBackend) else None
    if shared is None:
        if fail_closed and refs:
            raise PlanningIssueRefResolutionError(refs[0], "issue-store-backend-required")
        return delivery_grade, skipped

    gap_catalog: list[Any] | None = None
    if len(refs) > 1:
        client = shared._client
        pmis = _migrate_issue_store()
        key_result = pmis.validate_project_key(root, cfg)
        if key_result.get("verdict") == "ok":
            project_key = str(key_result["projectKey"])
            try:
                gap_catalog = _search_issue_records(
                    client,
                    project_key=project_key,
                    artifact_type="gap",
                )
            except (
                IssueCapabilityError,
                IssueBudgetExhausted,
                IssueTombstone,
                IssueTransferred,
            ) as exc:
                raise _planning_issue_ref_provider_error(refs[0], exc) from exc

    for ref in refs:
        try:
            gap_id = _resolve_numeric_absorb_ref_to_gap(
                root, cfg, ref, backend=shared, gap_catalog=gap_catalog
            )
        except PlanningIssueRefResolutionError:
            if fail_closed:
                raise
            skipped.append({"ref": ref, "reason": "absorb-gap-unresolved"})
            continue
        delivery_grade.add(gap_id)
    return delivery_grade, skipped


def discover_absorbed_units_anchored(
    fm: dict[str, str],
    edges: dict[str, Any] | None,
) -> tuple[set[str], list[dict[str, str]]]:
    """Discover absorbed gap units from anchored markers only (PRD 070 R1).

    Uses ``absorbs`` and hybrid ``sw-edges`` absorbs relationships from YAML
    frontmatter or hybrid-operator bodies. Free-text prose mentions and schedule
    labels are never treated as absorbed.

    Gap unit id targets (``gap-*`` / containing ``gap``) are collected here.
    Bare planning-issue number absorbs are resolved in ``_gap_closure_evidence``
    via the issue store (gap-309) — this helper stays pure / offline.
    """
    delivery_grade: set[str] = set()
    skipped: list[dict[str, str]] = []

    for target in _parse_absorbs_targets(fm.get("absorbs", "")):
        if _is_gap_unit_absorb_target(target):
            delivery_grade.add(target)

    related_only: set[str] = set()
    for edge in (edges or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        target = str(edge.get("target", "")).strip()
        if not target or not _is_gap_unit_absorb_target(target):
            continue
        rel = str(edge.get("rel") or edge.get("relationship") or "depends").strip().lower()
        if rel == "absorbs":
            delivery_grade.add(target)
        else:
            related_only.add(target)

    for gap_id in sorted(related_only - delivery_grade):
        skipped.append({"unitId": gap_id, "reason": "related-only-not-delivery-grade"})

    return delivery_grade, skipped


_SHORT_GAP_NUMBER_RE = re.compile(r"^gap-(\d+)$")


def _is_short_gap_number_target(target: str) -> bool:
    """True for bare ``gap-NNN`` absorb targets (not slug-suffixed unit ids)."""
    return bool(_SHORT_GAP_NUMBER_RE.fullmatch(target.strip()))


def _collect_gap_units_matching_absorb_target(
    root: Path,
    cfg: dict[str, Any],
    target: str,
    *,
    backend: "IssueStoreBackend",
    gap_catalog: list[Any] | None = None,
) -> list[str]:
    """Collect gap unit ids that match an absorb target (prefix-safe / gap-NNN)."""
    from planning_gap_capture import gap_absorb_target_match

    needle = target.strip()
    if not needle:
        return []

    matches: list[str] = []
    seen: set[str] = set()

    def _add(unit_id: str) -> None:
        uid = unit_id.strip()
        if not uid or uid in seen:
            return
        seen.add(uid)
        matches.append(uid)

    body_path = _default_body_path(needle, "gap")
    direct = _lookup_issue_record(backend, needle, body_path)
    if direct is not None:
        _add(str(getattr(direct, "unit_id", "") or needle))
        return matches

    pmis = _migrate_issue_store()
    key_result = pmis.validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        raise PlanningIssueRefResolutionError(
            needle,
            "invalid-project-key",
            message=str(key_result.get("message") or "invalid project key"),
        )
    project_key = str(key_result["projectKey"])
    records = gap_catalog
    if records is None:
        try:
            records = _search_issue_records(
                backend._client,
                project_key=project_key,
                artifact_type="gap",
            )
        except (
            IssueCapabilityError,
            IssueBudgetExhausted,
            IssueTombstone,
            IssueTransferred,
        ) as exc:
            raise _planning_issue_ref_provider_error(needle, exc) from exc
    for item in records:
        try:
            artifact_type = _resolve_planning_issue_artifact_type(item)
        except PlanningIssueRefResolutionError:
            continue
        if artifact_type != "gap":
            continue
        unit_id = str(getattr(item, "unit_id", "") or "").strip()
        if unit_id and gap_absorb_target_match(needle, unit_id):
            _add(unit_id)
    return matches


def _resolve_short_gap_absorb_to_unit(
    root: Path,
    cfg: dict[str, Any],
    target: str,
    *,
    backend: "IssueStoreBackend",
    gap_catalog: list[Any] | None = None,
) -> str:
    """Resolve ``gap-NNN`` to exactly one store unit id — fail closed on 0/N>1."""
    matches = _collect_gap_units_matching_absorb_target(
        root, cfg, target, backend=backend, gap_catalog=gap_catalog
    )
    if not matches:
        raise PlanningIssueRefResolutionError(target, "gap-unit-unresolved")
    if len(matches) > 1:
        raise PlanningIssueRefResolutionError(
            target,
            "gap-unit-ambiguous",
            candidates=matches,
        )
    return matches[0]


def _canonicalize_short_gap_absorb_targets(
    root: Path,
    cfg: dict[str, Any],
    gap_ids: set[str],
    *,
    fail_closed: bool = True,
) -> tuple[set[str], list[dict[str, str]]]:
    """Expand bare ``gap-NNN`` delivery-grade targets to slug-suffixed unit ids.

    Prevents ``resolve_delivery_linked_units`` from silently dropping short
    ``sw-edges`` absorbs when the store only indexes full unit ids.
    """
    skipped: list[dict[str, str]] = []
    if not gap_ids:
        return set(), skipped
    shorts = sorted(g for g in gap_ids if _is_short_gap_number_target(g))
    if not shorts:
        return set(gap_ids), skipped

    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        if fail_closed:
            raise PlanningIssueRefResolutionError(
                shorts[0],
                "issue-store-backend-required",
            )
        for short in shorts:
            skipped.append({"unitId": short, "reason": "issue-store-backend-required"})
        return {g for g in gap_ids if not _is_short_gap_number_target(g)}, skipped

    gap_catalog: list[Any] | None = None
    out = {g for g in gap_ids if not _is_short_gap_number_target(g)}
    for short in shorts:
        try:
            resolved = _resolve_short_gap_absorb_to_unit(
                root, cfg, short, backend=backend, gap_catalog=gap_catalog
            )
        except PlanningIssueRefResolutionError:
            if fail_closed:
                raise
            skipped.append({"unitId": short, "reason": "gap-unit-unresolved"})
            continue
        out.add(resolved)
    return out, skipped


def _gap_closure_evidence(
    fm: dict[str, str],
    edges: dict[str, Any] | None,
    prd_num: str | None,
    root: Path,
    cfg: dict[str, Any],
) -> tuple[set[str], list[dict[str, str]]]:
    """Classify gap units for closure: delivery-grade vs related-only skip (PRD 060 R6).

    Resolves bare planning-issue absorb targets (``sw-edges`` / ``absorbs``) to gap
    unit ids through the issue store so closeout does not silently drop them (gap-309).
    Also expands bare ``gap-NNN`` targets to slug-suffixed unit ids so short
    ``sw-edges`` absorbs are not silently omitted from the closure snapshot.
    """
    _ = prd_num  # schedule labels are not anchored absorption markers (PRD 070 R1)
    delivery_grade, skipped = discover_absorbed_units_anchored(fm, edges)
    numeric_refs = _iter_numeric_absorb_refs(fm, edges)
    resolved, resolve_skipped = _resolve_numeric_absorb_refs_to_gaps(
        root, cfg, numeric_refs, fail_closed=True
    )
    delivery_grade |= resolved
    skipped.extend(resolve_skipped)
    delivery_grade, short_skipped = _canonicalize_short_gap_absorb_targets(
        root, cfg, delivery_grade, fail_closed=True
    )
    skipped.extend(short_skipped)
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
    refs = parse_planning_issues_refs(fm.get("planningIssues", ""))
    if not refs:
        return out, skip
    backend = get_backend(root, cfg, override="issue-store")
    shared_backend = backend if isinstance(backend, IssueStoreBackend) else None
    for ref in refs:
        skip_meta: dict[str, str] = {}
        try:
            gap_id = resolve_planning_issue_ref_to_gap(
                root, cfg, ref, backend=shared_backend, skip_meta=skip_meta
            )
        except PlanningIssueRefResolutionError as exc:
            raise PlanningIssueRefResolutionError(
                exc.ref,
                exc.error,
                prdUnitId=prd_unit_id,
                **exc.detail,
            ) from exc
        if not gap_id:
            reason = skip_meta.get("reason", "planning-issue-unresolved")
            entry: dict[str, str] = {"ref": ref, "reason": reason}
            for key, value in skip_meta.items():
                if key != "reason" and value:
                    entry[key] = value
            skip.append(entry)
            continue
        if gap_has_absorb_provenance(
            root, cfg, gap_id, prd_unit_id, fm, prd_num=prd_num, edges=edges
        ):
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


_PLANNING_ISSUE_TYPE_SOURCES: tuple[str, ...] = (
    "labels",
    "record",
    "marker",
    "frontmatter",
)


def _planning_issue_artifact_type_evidence(record: Any) -> list[tuple[str, str]]:
    """Named artifact-type evidence sources for planning issue refs (PRD 275 R16)."""
    labels = list(getattr(record, "labels", []) or [])
    evidence: list[tuple[str, str]] = []
    from_labels = artifact_type_from_labels(labels)
    if from_labels and is_resolved_artifact_type(from_labels):
        evidence.append(("labels", from_labels))
    record_type = str(getattr(record, "artifact_type", "") or "").strip()
    if record_type and is_resolved_artifact_type(record_type):
        evidence.append(("record", record_type))
    body = str(getattr(record, "body", "") or "")
    from_marker = parse_body_marker(body, MARKER_ARTIFACT_TYPE) or ""
    if from_marker and is_resolved_artifact_type(from_marker):
        evidence.append(("marker", from_marker))
    full_body = reassemble_body(body, getattr(record, "comments", None) or [])
    stripped = strip_markers_and_edges(full_body)
    from_content = artifact_type_from_content(stripped) or ""
    if from_content and is_resolved_artifact_type(from_content):
        evidence.append(("frontmatter", from_content))
    return evidence


def _resolve_planning_issue_artifact_type(record: Any) -> str:
    evidence = _planning_issue_artifact_type_evidence(record)
    if not evidence:
        return ""
    types = {artifact_type for _, artifact_type in evidence}
    if len(types) > 1:
        raise PlanningIssueRefResolutionError(
            "",
            "artifact-type-conflict",
            sources={source: artifact_type for source, artifact_type in evidence},
        )
    return evidence[0][1]


def _planning_issue_ref_provider_error(ref: str, exc: Exception) -> PlanningIssueRefResolutionError:
    if isinstance(exc, IssueCapabilityError):
        return PlanningIssueRefResolutionError(ref, "issue-capability-error")
    if isinstance(exc, IssueBudgetExhausted):
        return PlanningIssueRefResolutionError(ref, "issue-budget-exhausted")
    if isinstance(exc, IssueTombstone):
        return PlanningIssueRefResolutionError(ref, "lifecycle-tombstone")
    if isinstance(exc, IssueTransferred):
        return PlanningIssueRefResolutionError(ref, "issue-transferred")
    return PlanningIssueRefResolutionError(ref, "issue-provider-error")


def _gap_unit_from_planning_issue_record(
    record: Any,
    *,
    ref: str,
    skip_meta: dict[str, str] | None,
) -> str | None:
    artifact_type = _resolve_planning_issue_artifact_type(record)
    unit_id = str(getattr(record, "unit_id", "") or "").strip()
    if artifact_type == "gap" and unit_id:
        return unit_id
    if artifact_type and artifact_type != "gap":
        if skip_meta is not None:
            skip_meta["reason"] = "planning-issue-nongap"
            skip_meta["artifactType"] = artifact_type
        return None
    if skip_meta is not None:
        skip_meta["reason"] = "planning-issue-unresolved"
    return None


def _lookup_planning_issue_record_for_ref(
    client: Any,
    *,
    project_key: str,
    issue_num: int | None,
    ref: str,
) -> Any | None:
    """Resolve a planning issue record for a numeric ref (direct get, then catalog by number)."""
    if issue_num is not None:
        getter = getattr(client, "issue_get", None) or getattr(client, "get", None)
        if callable(getter):
            try:
                return getter(str(issue_num))
            except IssueNotFound:
                pass
            except (
                IssueCapabilityError,
                IssueBudgetExhausted,
                IssueTombstone,
                IssueTransferred,
            ) as exc:
                raise _planning_issue_ref_provider_error(ref, exc) from exc
        try:
            for record in _search_issue_records(client, project_key=project_key):
                if int(getattr(record, "number", 0) or 0) == issue_num:
                    return record
        except (
            IssueCapabilityError,
            IssueBudgetExhausted,
            IssueTombstone,
            IssueTransferred,
        ) as exc:
            raise _planning_issue_ref_provider_error(ref, exc) from exc
    return None


def resolve_planning_issue_ref_to_gap(
    root: Path,
    cfg: dict[str, Any],
    ref: str,
    *,
    backend: "IssueStoreBackend | None" = None,
    gap_catalog: list[Any] | None = None,
    skip_meta: dict[str, str] | None = None,
) -> str | None:
    """Map a planning issue ref to a gap unit id (PRD 275 R4/R5, R7).

    Returns a gap ``unit_id`` only when artifact type evidence resolves to ``gap``.
    Positive non-gap classification yields ``None`` with ``planning-issue-nongap`` in
    ``skip_meta`` when provided. Provider/scope/auth failures raise
    ``PlanningIssueRefResolutionError`` (not-ready) rather than silent skip.

    Numeric refs resolve via ``issue_get`` (O(1)) — never a full gap catalog search per
    ref. Catalog search is only the fallback for non-numeric / related-field matching, and
    callers may pass a shared ``gap_catalog`` to avoid N+1 list fetches.
    """
    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return None
    if backend is None:
        backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return None
    key_result = pmis.validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        raise PlanningIssueRefResolutionError(
            ref,
            "invalid-project-key",
            message=str(key_result.get("message") or "invalid project key"),
        )
    project_key = str(key_result["projectKey"])
    normalized = _normalize_planning_issue_ref(ref)
    issue_num = None
    m = re.search(r"(?:planning#|#)?(\d+)$", normalized, re.I)
    if m:
        issue_num = int(m.group(1))
    client = backend._client

    if issue_num is not None:
        record = _lookup_planning_issue_record_for_ref(
            client,
            project_key=project_key,
            issue_num=issue_num,
            ref=ref,
        )
        if record is not None:
            return _gap_unit_from_planning_issue_record(
                record, ref=ref, skip_meta=skip_meta
            )

    records = gap_catalog
    if records is None:
        try:
            records = _search_issue_records(
                client,
                project_key=project_key,
                artifact_type="gap",
            )
        except (
            IssueCapabilityError,
            IssueBudgetExhausted,
            IssueTombstone,
            IssueTransferred,
        ) as exc:
            raise _planning_issue_ref_provider_error(ref, exc) from exc
    for record in records:
        unit_id = str(getattr(record, "unit_id", "") or "").strip()
        if not unit_id:
            continue
        if issue_num is not None and int(getattr(record, "number", 0) or 0) == issue_num:
            return _gap_unit_from_planning_issue_record(
                record, ref=ref, skip_meta=skip_meta
            )
        body = reassemble_body(record.body, record.comments)
        gap_fm = pmis.parse_frontmatter_fields(strip_markers_and_edges(body))
        related = str(gap_fm.get("related") or "")
        needles = {
            normalized,
            f"planning#{issue_num}" if issue_num else "",
            f"#{issue_num}" if issue_num else "",
        }
        if any(n and n in related for n in needles):
            return _gap_unit_from_planning_issue_record(
                record, ref=ref, skip_meta=skip_meta
            )
    if skip_meta is not None:
        skip_meta["reason"] = "planning-issue-unresolved"
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
    """True when ``gap_unit_id`` is provenance-bound to ``prd_unit_id`` for closure (R7).

    Accepts gap unit id absorb targets and bare planning-issue number absorbs
    resolved through the issue store (gap-309).
    """
    from planning_gap_capture import gap_absorb_target_match

    absorbs = _parse_absorbs_targets(prd_fm.get("absorbs", ""))
    if any(gap_absorb_target_match(item, gap_unit_id) for item in absorbs):
        return True
    _ = prd_num  # schedule labels are not anchored absorption markers (PRD 070 R1)
    for edge in (edges or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        target = str(edge.get("target", "")).strip()
        rel = str(edge.get("rel") or edge.get("relationship") or "").strip().lower()
        if rel == "absorbs" and gap_absorb_target_match(target, gap_unit_id):
            return True
    backend = get_backend(root, cfg, override="issue-store")
    shared = backend if isinstance(backend, IssueStoreBackend) else None
    numeric_refs = _iter_numeric_absorb_refs(prd_fm, edges)
    if numeric_refs and shared is not None:
        resolved, _skipped = _resolve_numeric_absorb_refs_to_gaps(
            root, cfg, numeric_refs, backend=shared, fail_closed=False
        )
        if any(gap_absorb_target_match(item, gap_unit_id) for item in resolved):
            return True
    if shared is not None:
        gap_path = _default_body_path(gap_unit_id, "gap")
        gap_record = _lookup_issue_record(shared, gap_unit_id, gap_path)
        if gap_record is not None:
            gap_content = strip_markers_and_edges(
                reassemble_body(gap_record.body, gap_record.comments)
            )
            gap_fm = _migrate_issue_store().parse_frontmatter_fields(gap_content)
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


_DOCTOR_ISSUE_CATALOG: ContextVar[dict[str, list[Any]] | None] = ContextVar(
    "doctor_issue_catalog",
    default=None,
)


def _doctor_catalog_records(catalog: dict[str, list[Any]]) -> list[Any]:
    return [record for records in catalog.values() for record in records]


def _search_issue_records(
    client: Any,
    *,
    project_key: str,
    artifact_type: str | None = None,
    unit_id: str | None = None,
    labels: list[str] | None = None,
) -> list[Any]:
    catalog = _DOCTOR_ISSUE_CATALOG.get()
    if catalog is None:
        search = getattr(client, "issue_search", None)
        if not callable(search):
            return []
        return list(
            search(
                project_key=project_key,
                artifact_type=artifact_type,
                unit_id=unit_id,
                labels=labels,
            )
        )
    records = _doctor_catalog_records(catalog)
    if artifact_type:
        records = [record for record in records if _record_artifact_type(record) == artifact_type]
    if unit_id:
        records = [
            record
            for record in records
            if str(getattr(record, "unit_id", "") or "") == unit_id
        ]
    if labels:
        required = set(labels)
        records = [
            record
            for record in records
            if required.issubset(set(getattr(record, "labels", []) or []))
        ]
    return records


def _lookup_issue_record(
    backend: "IssueStoreBackend",
    unit_id: str,
    body_path: str,
    *,
    expected_types: set[str] | None = None,
) -> Any:
    catalog = _DOCTOR_ISSUE_CATALOG.get()
    if catalog is not None:
        if expected_types is None:
            try:
                expected_types = {require_artifact_type(body_path)}
            except ArtifactTypeUnresolved:
                expected_types = set()
        for candidate in unit_id_lookup_candidates(backend.root, unit_id):
            for record in catalog.get(candidate, []):
                if expected_types and _record_artifact_type(record) not in expected_types:
                    continue
                return record
        return None
    try:
        return backend._lookup_record(unit_id, body_path)
    except IssueNotFound:
        return None
    except (IssueTombstone, IssueTransferred, IssueBudgetExhausted) as exc:
        handle_issue_client_error(exc)
        return None


def _find_linked_brainstorm_record(
    backend: "IssueStoreBackend",
    prd_unit_id: str,
) -> Any | None:
    catalog = _DOCTOR_ISSUE_CATALOG.get()
    if catalog is None:
        return backend._find_linked_brainstorm(prd_unit_id)
    for record in _doctor_catalog_records(catalog):
        if _record_artifact_type(record) != "brainstorm":
            continue
        full_body = reassemble_body(record.body, record.comments)
        edges = parse_edges_block(full_body) or {}
        if any(
            isinstance(edge, dict) and edge.get("target") == prd_unit_id
            for edge in edges.get("edges") or []
        ):
            return record
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
    if artifact_type == "decision":
        from planning.identity import (
            DECISION_GRAPH_UNIT_SUFFIX,
            decision_graph_virtual_body_path,
            decision_record_virtual_body_path,
        )

        if unit_id.endswith(DECISION_GRAPH_UNIT_SUFFIX):
            return decision_graph_virtual_body_path(unit_id)
        return decision_record_virtual_body_path(unit_id)
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
    fm, edges = _resolve_prd_absorption_context(prd_record, prd_unit, full_body)

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
    linked = _find_linked_brainstorm_record(backend, prd_unit)
    if linked is not None:
        brainstorm_unit = str(getattr(linked, "unit_id", "") or brainstorm_unit)
    if brainstorm_unit and brainstorm_unit not in units:
        units[brainstorm_unit] = {
            "unitId": brainstorm_unit,
            "artifactType": "brainstorm",
            "bodyPath": _default_body_path(brainstorm_unit, "brainstorm"),
        }

    try:
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
    except PlanningIssueRefResolutionError as exc:
        return {
            "verdict": "not-ready",
            "error": exc.error,
            "prdUnitId": prd_unit,
            "planningIssueRef": exc.ref,
            **exc.detail,
        }
    for gap_id in sorted(gap_ids):
        if gap_id in units:
            continue
        body_path = _default_body_path(gap_id, "gap")
        if _lookup_issue_record(backend, gap_id, body_path) is not None:
            units[gap_id] = {"unitId": gap_id, "artifactType": "gap", "bodyPath": body_path}
            continue
        # Last-chance expand for any residual short form (or prefix-only) targets.
        if _is_short_gap_number_target(gap_id):
            try:
                resolved = _resolve_short_gap_absorb_to_unit(
                    root, cfg, gap_id, backend=backend
                )
            except PlanningIssueRefResolutionError as exc:
                return {
                    "verdict": "not-ready",
                    "error": exc.error,
                    "prdUnitId": prd_unit,
                    "planningIssueRef": exc.ref,
                    **exc.detail,
                }
            resolved_path = _default_body_path(resolved, "gap")
            if _lookup_issue_record(backend, resolved, resolved_path) is not None:
                units[resolved] = {
                    "unitId": resolved,
                    "artifactType": "gap",
                    "bodyPath": resolved_path,
                }
                continue
        gap_skipped.append({"unitId": gap_id, "reason": "gap-unit-not-found"})

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
    from wave_state import load_hierarchy_map

    hmap = load_hierarchy_map(state)
    hentry = (hmap.get("phases") or {}).get(str(phase_id))
    if isinstance(hentry, dict) and hentry.get("doneSynced"):
        return True
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
        # parent-checkbox mode stores phaseId-only stubs — no per-phase issues to close.
        # Only consider entries that already carry an issueId or explicit unitId.
        if not issue_id and not unit_id:
            continue
        if not unit_id and tasks_unit_id:
            unit_id = f"{tasks_unit_id}-phase-{phase_id}"
        _add(str(phase_id), issue_id, unit_id)

    if candidates or not tasks_unit_id:
        return candidates

    # parent-checkbox hierarchy has no per-phase issues — do not fan out a full tasks search.
    if str(hmap.get("mode") or "") == "parent-checkbox":
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
    linked_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Close phase sub-issues marked done in deliver ledger or via ``sw:phase:N:done`` (PRD 060 R5)."""
    from planning_progress import phase_done_label

    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return {"verdict": "ok", "skipped": True, "reason": "issue-store-required", "prdUnitId": prd_unit_id}

    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "fail", "error": "issue-store-backend-required", "prdUnitId": prd_unit_id}

    snapshot = linked_snapshot if isinstance(linked_snapshot, dict) else None
    if snapshot is None:
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
    was_closed = _record_is_closed(record, artifact_type)
    if was_closed:
        # R13 — already-closed frozen units still get idempotent stale-hash repair.
        if FROZEN_LABEL in list(record.labels) or bool(record.locked):
            repin = backend.repin_freeze_after_close(record)
            if repin.get("verdict") != "ok":
                return {
                    "unitId": unit_id,
                    "artifactType": artifact_type,
                    "priorState": prior_state,
                    "resultingState": "complete",
                    "action": "noop",
                    "verdict": "fail",
                    "error": "freeze-repin-failed",
                    "alreadyClosed": True,
                    "partialApply": bool(repin.get("partialApply")),
                    "repin": repin,
                }
            return {
                "unitId": unit_id,
                "artifactType": artifact_type,
                "priorState": prior_state,
                "resultingState": "complete",
                "action": "noop" if repin.get("action") == "noop" else "repin",
                "verdict": "pass",
                "alreadyClosed": True,
                "hash": repin.get("hash"),
                "repin": repin,
            }
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
    frozen = FROZEN_LABEL in list(record.labels) or bool(record.locked)
    if frozen:
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
    after = backend._client.issue_get(updated.id)
    if before_body is not None:
        after_body = reassemble_body(after.body, after.comments)
        # Close may change state/labels (hash) but must not rewrite operator body.
        if before_body != after_body:
            return {
                "unitId": unit_id,
                "artifactType": artifact_type,
                "priorState": prior_state,
                "verdict": "fail",
                "error": "locked-body-mutated",
            }
    # R1 — re-pin newest freeze hash after close mutation (state+labels in hash).
    if frozen:
        repin = backend.repin_freeze_after_close(after)
        if repin.get("verdict") != "ok":
            return {
                "unitId": unit_id,
                "artifactType": artifact_type,
                "priorState": prior_state,
                "resultingState": "complete",
                "action": "close",
                "verdict": "fail",
                "error": "freeze-repin-failed",
                "partialApply": True,
                "closedOk": True,
                "priorHash": before_hash,
                "repin": repin,
            }
        return {
            "unitId": unit_id,
            "artifactType": artifact_type,
            "priorState": prior_state,
            "resultingState": "complete",
            "action": "close",
            "verdict": "pass",
            "hash": repin.get("hash"),
            "priorHash": before_hash,
            "repin": repin,
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
    if open_remaining:
        verdict = "not-ready"
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
        "skipped": skipped + list(snap.get("skipped") or []),
        "openRemaining": open_remaining,
        "absorbedUnits": sorted(expected_gaps),
        "planningIssues": snap.get("planningIssues") or [],
        "tasksResolution": tasks_note,
        "resumeCommand": resume,
    }


def _doctor_prd_has_absorption_evidence(record: Any, unit_id: str) -> bool:
    """Return whether a PRD can contribute absorbed units without provider lookups."""
    full_body = reassemble_body(
        str(getattr(record, "body", "") or ""),
        list(getattr(record, "comments", []) or []),
    )
    fm, edges = _resolve_prd_absorption_context(record, unit_id, full_body)
    if _parse_absorbs_targets(fm.get("absorbs", "")):
        return True
    if parse_planning_issues_refs(fm.get("planningIssues", "")):
        return True
    for edge in (edges or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        target = str(edge.get("target", "")).strip()
        rel = str(edge.get("rel") or edge.get("relationship") or "depends").strip().lower()
        if target and rel == "absorbs":
            return True
    return False


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
    if not _doctor_prd_has_absorption_evidence(record, unit_id):
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


def _doctor_issue_catalog(records: list[Any]) -> dict[str, list[Any]]:
    catalog: dict[str, list[Any]] = {}
    for record in records:
        unit_id = str(getattr(record, "unit_id", "") or "").strip()
        if unit_id:
            catalog.setdefault(unit_id, []).append(record)
    return catalog


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
        existing_catalog = _DOCTOR_ISSUE_CATALOG.get()
        records = (
            _doctor_catalog_records(existing_catalog)
            if existing_catalog is not None
            else list(search(project_key=project_key))
        )
        token = (
            None
            if existing_catalog is not None
            else _DOCTOR_ISSUE_CATALOG.set(_doctor_issue_catalog(records))
        )
        try:
            for record in records:
                if _record_artifact_type(record) != "prd":
                    continue
                unit_id = str(getattr(record, "unit_id", "") or "")
                if not unit_id:
                    continue
                _doctor_absorb_pollution_check_prd(root, cfg, record, unit_id, pollution)
        finally:
            if token is not None:
                _DOCTOR_ISSUE_CATALOG.reset(token)

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


def _prd_side_absorbs_gap(
    prd_fm: dict[str, str],
    edges: dict[str, Any] | None,
    gap_unit_id: str,
) -> bool:
    """True when PRD frontmatter or sw-edges declares an absorbs edge for ``gap_unit_id``."""
    from planning_gap_capture import gap_absorb_target_match

    absorbs = _parse_absorbs_targets(prd_fm.get("absorbs", ""))
    if any(gap_absorb_target_match(item, gap_unit_id) for item in absorbs):
        return True
    for edge in (edges or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        target = str(edge.get("target", "")).strip()
        rel = str(edge.get("rel") or edge.get("relationship") or "").strip().lower()
        if rel == "absorbs" and gap_absorb_target_match(target, gap_unit_id):
            return True
    return False


def _gap_absorbed_by_unit_id(gap_fm: dict[str, str]) -> str:
    return str(gap_fm.get("absorbed-by") or gap_fm.get("absorbed_by") or "").strip()


def _resolve_gap_absorption_frontmatter(
    gap_record: Any,
    gap_unit_id: str,
    full_body: str,
) -> dict[str, str]:
    """Resolve gap frontmatter including hybrid sw-frontmatter-extra (PRD 094 R18)."""
    pmis = _migrate_issue_store()
    if has_raw_yaml_frontmatter(full_body):
        raw_content = strip_markers_and_edges(full_body)
        return pmis.parse_frontmatter_fields(raw_content)
    if is_hybrid_operator_body(full_body):
        hybrid = frontmatter_from_labels(
            list(getattr(gap_record, "labels", []) or []),
            unit_id=gap_unit_id,
            operator_body=full_body,
        )
        fm = {key: _fm_field_as_str(hybrid.get(key)) for key in hybrid}
        stripped = strip_markers_and_edges(full_body)
        if stripped.startswith("---"):
            yaml_fm = pmis.parse_frontmatter_fields(stripped)
            for key, value in yaml_fm.items():
                if value:
                    fm[key] = value
        return fm
    raw_content = strip_markers_and_edges(full_body)
    return pmis.parse_frontmatter_fields(raw_content)


def _doctor_absorb_asymmetry_check_gap(
    backend: IssueStoreBackend,
    gap_unit_id: str,
    gap_record: Any,
    prd_cache: dict[str, tuple[dict[str, str], dict[str, Any]] | None],
    asymmetries: list[dict[str, str]],
) -> None:
    full_body = reassemble_body(gap_record.body, gap_record.comments)
    gap_fm = _resolve_gap_absorption_frontmatter(gap_record, gap_unit_id, full_body)
    prd_unit_id = _gap_absorbed_by_unit_id(gap_fm)
    if not prd_unit_id:
        return

    if prd_unit_id not in prd_cache:
        prd_record = None
        prd_unit = ""
        for candidate in _prd_unit_id_alias_candidates(prd_unit_id):
            body_path = _default_body_path(candidate, "prd")
            prd_record = _lookup_issue_record(
                backend,
                candidate,
                body_path,
                expected_types={"prd", "amendment"},
            )
            if prd_record is not None and _record_artifact_type(prd_record) in {"prd", "amendment"}:
                prd_unit = candidate
                break
        if prd_record is None:
            prd_cache[prd_unit_id] = None
        else:
            prd_body = reassemble_body(prd_record.body, prd_record.comments)
            prd_fm, edges = _resolve_prd_absorption_context(prd_record, prd_unit, prd_body)
            prd_cache[prd_unit_id] = (prd_fm, edges)

    cached = prd_cache.get(prd_unit_id)
    if cached is None:
        asymmetries.append(
            {
                "gapUnitId": gap_unit_id,
                "prdUnitId": prd_unit_id,
                "reason": "prd-not-found",
            }
        )
        return

    prd_fm, edges = cached
    if not _prd_side_absorbs_gap(prd_fm, edges, gap_unit_id):
        asymmetries.append(
            {
                "gapUnitId": gap_unit_id,
                "prdUnitId": prd_unit_id,
                "reason": "gap-absorbed-by-without-prd-absorbs",
            }
        )


def doctor_absorb_asymmetry(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Report PRD/gap asymmetry where gap ``absorbed-by`` lacks PRD-side absorbs (PRD 094 R18)."""
    pmis = _migrate_issue_store()
    if not pmis.issue_store_effective(root, cfg):
        return {"verdict": "pass", "action": "doctor-absorb-asymmetry", "skipped": True}
    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "pass", "action": "doctor-absorb-asymmetry", "skipped": True}
    key_result = pmis.validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return {"verdict": "fail", "action": "doctor-absorb-asymmetry", "error": key_result.get("error")}

    project_key = str(key_result["projectKey"])
    asymmetries: list[dict[str, str]] = []
    prd_cache: dict[str, tuple[dict[str, str], dict[str, Any]] | None] = {}
    catalog = _DOCTOR_ISSUE_CATALOG.get()
    gap_records = (
        _search_issue_records(
            backend._client,
            project_key=project_key,
            artifact_type="gap",
        )
        if catalog is not None
        else pmis.list_gap_issue_records(root, cfg)
    )
    for record in gap_records:
        unit_id = str(getattr(record, "unit_id", "") or "")
        if not unit_id:
            continue
        _doctor_absorb_asymmetry_check_gap(backend, unit_id, record, prd_cache, asymmetries)

    if asymmetries:
        return {
            "verdict": "fail",
            "action": "doctor-absorb-asymmetry",
            "error": "absorb-asymmetry",
            "asymmetries": asymmetries,
            "resumeCommand": "python3 scripts/planning_store.py doctor",
        }
    return {"verdict": "pass", "action": "doctor-absorb-asymmetry", "checks": ["no-asymmetry"]}


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



def _load_deliver_state_for_prd(root: Path, prd_unit_id: str) -> dict[str, Any] | None:
    """Best-effort load of deliver run state matching ``prd_unit_id`` (for phase closure)."""
    try:
        from wave_json_io import read_json
        from wave_state import enumerate_run_scoped_dirs, load_deliver_state
    except Exception:  # noqa: BLE001
        return None

    needle = str(prd_unit_id or "").strip()
    prd_num = _prd_number_from_unit_id(needle) or ""
    candidates: list[Path] = []
    try:
        for entry in enumerate_run_scoped_dirs(root):
            sp = root / str(entry.get("statePath") or "")
            if sp.is_file():
                candidates.append(sp)
    except Exception:  # noqa: BLE001
        pass
    # Also consider scoped slug state files
    cursor = root / ".cursor"
    if cursor.is_dir():
        for path in cursor.glob("sw-deliver-state*.json"):
            if path.is_file():
                candidates.append(path)

    for path in candidates:
        try:
            data = read_json(path)
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(data, dict) or data.get("migrated"):
            continue
        source = str(data.get("source_task_list") or "")
        pin = data.get("planningStorePin") if isinstance(data.get("planningStorePin"), dict) else {}
        unit = str(pin.get("unitId") or data.get("prd_number") or "")
        if needle and (
            needle in source
            or needle == unit
            or (prd_num and (prd_num == str(data.get("prd_number") or "") or f"/{prd_num}-" in source))
        ):
            return data
    try:
        return load_deliver_state(root)
    except Exception:  # noqa: BLE001
        return None


def close_delivery_units(
    root: Path,
    cfg: dict[str, Any],
    prd_unit_id: str,
    *,
    dry_run: bool = False,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Close linked PRD/tasks/brainstorm/gap units after retrospective merge (PRD 059 R16-R24)."""
    if state is None:
        state = _load_deliver_state_for_prd(root, prd_unit_id)
    if prd_unit_id == "337-prd-workflow-runtime-autonomy-lifecycle":
        from prd339_cross_prd_gate import prd339_absorb_acceptance_milestone

        gate = prd339_absorb_acceptance_milestone(root)
        if gate.get("verdict") != "ready":
            return {
                "verdict": "not-ready",
                "action": "close-delivery-units",
                "error": "prd339-cross-prd-gate",
                "cause": gate.get("cause"),
                "prdUnitId": prd_unit_id,
                "prd339Gate": gate,
                "resumeCommand": gate.get("resumeCommand"),
            }
    snapshot = resolve_delivery_linked_units(root, cfg, prd_unit_id)
    if snapshot.get("verdict") != "ok":
        return snapshot
    backend = get_backend(root, cfg, override="issue-store")
    if not isinstance(backend, IssueStoreBackend):
        return {"verdict": "fail", "error": "issue-store-backend-required", "prdUnitId": prd_unit_id}

    phase_closure = close_done_phase_sub_issues(
        root,
        cfg,
        prd_unit_id,
        state=state,
        dry_run=dry_run,
        linked_snapshot=snapshot,
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


def _doctor_identity_signals_present(cfg: dict[str, Any]) -> bool:
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    return bool(str(cfg.get("projectId") or "").strip()) or bool(str(memory.get("project") or "").strip())


def doctor_repository_context_identity(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Configured vs derived project identity hygiene (PRD 089 R4)."""
    from credentials.resolver import repo_slug_from_remote
    from host_lib import git_remote_url, remote_name
    from repository_context import derive_project_id_without_config, resolve_project_id

    store = store_section(cfg)
    backend = str(store.get("backend") or DEFAULT_BACKEND).strip()
    if backend != "issue-store" and not _doctor_identity_signals_present(cfg):
        return {
            "verdict": "pass",
            "action": "doctor",
            "skipped": True,
            "reason": "not-issue-store-no-identity-signals",
        }

    remote = git_remote_url(root, remote_name(cfg)) or ""
    slug = repo_slug_from_remote(remote)
    path_name = root.name

    configured = str(cfg.get("projectId") or "").strip() or None
    derived = derive_project_id_without_config(slug, path_name)
    resolved = resolve_project_id(cfg, slug, path_name)
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    memory_project = str(memory.get("project") or "").strip() or None

    identity = {
        "configuredProjectId": configured,
        "derivedProjectId": derived,
        "resolvedProjectId": resolved,
        "memoryProject": memory_project,
    }

    if not configured and memory_project and memory_project != derived:
        return {
            "verdict": "fail",
            "action": "doctor",
            "halt": "repository-context-identity-conflict",
            "error": (
                "memory.project differs from derived project id without top-level projectId override"
            ),
            "identity": identity,
            "remediation": (
                "set top-level projectId explicitly or align memory.project with derived identity"
            ),
        }

    checks = ["repository-context-identity"]
    if configured and derived and configured != derived:
        checks.append("project-id-explicit-overrides-derived")

    return {
        "verdict": "pass",
        "action": "doctor",
        "checks": checks,
        "identity": identity,
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


def doctor_tracked_prd_bodies(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Fail closed when tracked docs/prds bodies remain in the code repo (PRD 280 R11)."""
    from planning_artifact_handle import issue_store_separate_project_effective

    if not issue_store_separate_project_effective(root, cfg):
        return {
            "verdict": "pass",
            "action": "doctor-tracked-prd-bodies",
            "skipped": True,
            "reason": "not-separate-project-issue-store",
        }
    tracked = tracked_planning_body_paths(root)
    prd_paths = sorted(path for path in tracked if path.startswith("docs/prds/"))
    if prd_paths:
        return {
            "verdict": "fail",
            "action": "doctor-tracked-prd-bodies",
            "halt": "tracked-prd-bodies-in-code-repo",
            "error": "tracked docs/prds bodies forbidden in code repo under issue-store",
            "paths": prd_paths,
            "remediation": (
                "run planning_store cleanup for legacy tracked bodies or migrate authoring to issue-store"
            ),
        }
    return {
        "verdict": "pass",
        "action": "doctor-tracked-prd-bodies",
        "checks": ["no-tracked-docs-prds-bodies"],
    }


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

    identity = doctor_repository_context_identity(root, cfg)
    if identity.get("verdict") == "fail":
        return identity
    if identity.get("skipped"):
        skipped_reasons.append(str(identity.get("reason") or "repository-context-identity-skipped"))
    else:
        checks.extend(identity.get("checks", []))

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

    catalog_token = None
    pmis = _migrate_issue_store()
    if pmis.issue_store_effective(root, cfg):
        backend = get_backend(root, cfg, override="issue-store")
        key_result = pmis.validate_project_key(root, cfg)
        if isinstance(backend, IssueStoreBackend) and key_result.get("verdict") == "ok":
            records = list(
                backend._client.issue_search(
                    project_key=str(key_result["projectKey"]),
                )
            )
            catalog_token = _DOCTOR_ISSUE_CATALOG.set(_doctor_issue_catalog(records))
    try:
        pollution = doctor_absorb_pollution(root, cfg)
        if pollution.get("verdict") == "fail":
            return pollution
        if pollution.get("checks"):
            checks.extend(pollution.get("checks", []))

        asymmetry = doctor_absorb_asymmetry(root, cfg)
        if asymmetry.get("verdict") == "fail":
            return asymmetry
        if asymmetry.get("checks"):
            checks.extend(asymmetry.get("checks", []))
    finally:
        if catalog_token is not None:
            _DOCTOR_ISSUE_CATALOG.reset(catalog_token)

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
    if backend.get("configured") != "issue-store":
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
    if backend.get("configured") != "issue-store":
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
        "name": "notion_projection_schema",
        "status": "shipped",
        "description": "Notion operator schema: database entity map, dual_property edges, freeze mirrors (PRD 327 R5)",
    },
    {
        "name": "comments_relations_schema",
        "status": "shipped",
        "description": "Facade thread parentage, resolved metadata, typed relation edges (PRD 066 R17/R24)",
    },
    {
        "name": "post_review_finding",
        "status": "shipped",
        "description": "Post one persona finding comment for an open doc-review round (PRD 341 R1)",
    },
    {
        "name": "open_review_manifest",
        "status": "shipped",
        "description": "Open the doc-review round manifest on the artifact issue body (PRD 341 R1)",
    },
    {
        "name": "read_review_manifest",
        "status": "shipped",
        "description": "Read pins and manifest for an open doc-review round (PRD 341 R1)",
    },
    {
        "name": "verify_review_manifest",
        "status": "shipped",
        "description": "Verify doc-review round integrity before synthesis (PRD 341 R1)",
    },
    {
        "name": "complete_review_round",
        "status": "shipped",
        "description": "Close a verified doc-review round (PRD 341 R1)",
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
    {
        "row": "prd",
        "linear": "project",
        "github-projects": "project-item",
        "notion": "prd-database-page",
        "r1": [1, 2, 3, 4],
    },
    {
        "row": "brainstorm",
        "linear": "document",
        "github-projects": "draft-or-issue-field",
        "notion": "brainstorm-database-page",
        "r1": [2],
    },
    {
        "row": "gap",
        "linear": "issue+gap-label",
        "github-projects": "issue+gap-field",
        "notion": "gap-database-page",
        "r1": [1],
    },
    {
        "row": "phase",
        "linear": "milestone",
        "github-projects": "phase-field",
        "notion": "phase-database-page+date",
        "r1": [3],
    },
    {
        "row": "task",
        "linear": "issue/sub-issue",
        "github-projects": "issue-item",
        "notion": "task-database-page",
        "r1": [3],
    },
    {
        "row": "progress",
        "linear": "native-status",
        "github-projects": "status-field",
        "notion": "Status-property",
        "r1": [3, 4],
    },
    {
        "row": "program",
        "linear": "initiative-or-substitute-views",
        "github-projects": "program-discriminator",
        "notion": "select-or-database-row",
        "r1": [4],
    },
    {
        "row": "cycle-wave",
        "linear": "cycle",
        "github-projects": "degraded-optional",
        "notion": "date-window-optional",
        "r1": [],
    },
)

FACADE_WORKFLOW_SCAN_GLOB = "scripts/*.py"

FACADE_BYPASS_BASELINE = frozenset({
    "scripts/planning_discover.py",
    "scripts/planning_scheduler.py",
})

DOC_REVIEW_FACADE_ACTION_TO_VERB: dict[str, str] = {
    "open_review_manifest": "doc-review-round-open",
    "post_review_finding": "doc-review-round-post",
    "read_review_manifest": "doc-review-round-read",
    "verify_review_manifest": "doc-review-round-verify",
    "complete_review_round": "doc-review-round-close",
}
DOC_REVIEW_FACADE_OPERATIONS = frozenset(DOC_REVIEW_FACADE_ACTION_TO_VERB)

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
    blocked = authority_io_block(effective, operation="read")
    if blocked is not None:
        return blocked
    if effective.get("configured") != "issue-store":
        return {
            "verdict": "fail",
            "error": "--issue requires issue-store configured backend",
            "configuredBackend": effective.get("configured"),
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
    blocked = authority_io_block(effective, operation="read")
    if blocked is not None:
        return blocked
    if effective.get("configured") != "issue-store":
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


class PlanningStoreAuthorityError(RuntimeError):
    """Authority gate blocked a planning-store operation."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(str(payload.get("error") or "authority-blocked"))
        self.payload = payload


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
    if provider == "notion":
        payload["commentMutation"] = "degraded"
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


def _projects_live_client_wired() -> bool:
    """PRD 085 R18 — recognize GitHub Projects only when live client exists."""
    from _planning_pkg_loader import load_submodule

    return load_submodule("providers.github_projects").live_client_wired()


def operator_projection_capability_matrix() -> dict[str, Any]:
    """PRD 066 R1/R3 — shared operator-projection capability matrix skeleton."""
    payload: dict[str, Any] = {
        "backends": ["github-issues", "github-projects", "jira", "linear", "notion"],
        "contractBackends": ["github-projects", "linear"],
        "rows": [dict(row) for row in OPERATOR_PROJECTION_MATRIX_ROWS],
        "statusTaxonomy": sorted(SEMANTIC_STATUSES),
        "statusAliases": {
            provider: {semantic: sorted(names) for semantic, names in mapping.items()}
            for provider, mapping in SEMANTIC_STATUS_ALIASES.items()
        },
        "r1BrowseContract": R1_BROWSE_CONTRACT,
        "linearAnswerable": _linear_live_client_wired(),
        "projectsAnswerable": _projects_live_client_wired(),
    }
    return payload


def operator_projection_adapter_complete_claim(matrix: dict[str, Any] | None = None) -> dict[str, Any]:
    """R3 — adapter-complete requires both Linear and Projects backends in the matrix."""
    payload = matrix or operator_projection_capability_matrix()
    required = ["github-projects", "linear"]
    backends = set(payload.get("backends") or [])
    contract_backends = set(payload.get("contractBackends") or [])
    present = [name for name in required if name in backends and name in contract_backends]
    # PRD 085 R18 — skeleton stage until live-probe producers populate answerability.
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


def external_intake_txn(
    root: Path,
    cfg: dict[str, Any],
    *,
    verb: str,
    issue_id: str | None = None,
    signal_id: str | None = None,
    title: str | None = None,
    signal_class: str = "unknown",
    comment: str | None = None,
    gap_unit_id: str | None = None,
    priority: str = "medium",
    tier: str = "build",
    gap_class: str = "external",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Planning-store txn verbs for external issue triage lifecycle (PRD 280 R1–R3)."""
    from planning_external_intake import (
        TXN_VERBS,
        VERB_TO_STATE,
        append_transition,
        gap_promotion_labels,
        initial_external_intake_block,
        outcome_for_verb,
        parse_external_intake_block,
        sync_external_intake_labels,
        upsert_external_intake_block,
        validate_transition,
    )

    if verb not in TXN_VERBS:
        return {"verdict": "fail", "action": verb, "error": "unknown-external-intake-verb", "verb": verb}

    backend = resolve_effective_backend(root, cfg)
    if backend.get("configured") != "issue-store":
        return {"verdict": "fail", "action": verb, "error": "issue-store-required"}

    provider = str(resolve_issues_provider(cfg).get("provider") or "none")
    pk = validate_project_key(root, cfg)
    if pk.get("verdict") != "ok":
        return pk
    project_key = str(pk["projectKey"])
    client = IssuesClient(root, provider)

    if verb == "external-intake-receive":
        if not signal_id or not title:
            return {"verdict": "fail", "action": verb, "error": "signal-id-and-title-required"}
        block = initial_external_intake_block(signal_id=signal_id, signal_class=signal_class)
        body = upsert_external_intake_block("", block)
        labels = sync_external_intake_labels([], "received")
        if dry_run:
            return {"verdict": "ok", "action": verb, "dryRun": True, "state": "received", "signalId": signal_id}
        created = client.issue_create(
            title=title,
            body=body,
            labels=labels,
            project_key=project_key,
            artifact_type="external",
            unit_id=f"external-{signal_id}",
        )
        return {
            "verdict": "ok",
            "action": verb,
            "issueId": str(created.id),
            "state": "received",
            "signalId": signal_id,
        }

    if not issue_id:
        return {"verdict": "fail", "action": verb, "error": "issue-id-required", "verb": verb}

    try:
        current = client.issue_get(str(issue_id))
    except Exception as exc:  # noqa: BLE001
        return {"verdict": "fail", "action": verb, "error": str(exc), "issueId": issue_id}

    block = parse_external_intake_block(current.body)
    if not block:
        return {"verdict": "fail", "action": verb, "error": "missing-external-intake-block", "issueId": issue_id}

    from_state = str(block.get("state") or "")
    to_state = VERB_TO_STATE[verb]
    try:
        validate_transition(from_state, to_state)
    except ValueError as exc:
        return {
            "verdict": "fail",
            "action": verb,
            "error": str(exc),
            "issueId": issue_id,
            "fromState": from_state,
            "toState": to_state,
        }

    note = comment or ""
    updated_block = append_transition(
        block,
        verb=verb,
        from_state=from_state,
        to_state=to_state,
        note=note,
    )
    body = upsert_external_intake_block(current.body, updated_block)
    labels = sync_external_intake_labels(list(current.labels), to_state)

    if verb == "external-intake-promote" and gap_unit_id:
        from planning_github_client import merge_external_gap_promotion_labels

        labels = merge_external_gap_promotion_labels(
            labels,
            unit_id=gap_unit_id,
            priority=priority,
            tier=tier,
            gap_class=gap_class,
        )
        updated_block["promotedUnitId"] = gap_unit_id
        body = upsert_external_intake_block(body, updated_block)

    outcome = outcome_for_verb(verb)
    if outcome:
        updated_block["outcome"] = outcome
        body = upsert_external_intake_block(body, updated_block)

    if dry_run:
        return {
            "verdict": "ok",
            "action": verb,
            "dryRun": True,
            "issueId": issue_id,
            "fromState": from_state,
            "toState": to_state,
            "outcome": outcome,
        }

    redacted_comment = redact_content(comment) if comment else None
    if labels != list(current.labels):
        current = client.issue_label(str(issue_id), labels, if_match=current.etag)
    if body != current.body:
        current = client.issue_update(str(issue_id), body=body, if_match=current.etag)
    if redacted_comment:
        client.issue_comment(str(issue_id), redacted_comment)

    return {
        "verdict": "ok",
        "action": verb,
        "issueId": issue_id,
        "fromState": from_state,
        "toState": to_state,
        "outcome": outcome,
        "promotedUnitId": gap_unit_id,
        "gapLabels": gap_promotion_labels(
            unit_id=gap_unit_id,
            priority=priority,
            tier=tier,
            gap_class=gap_class,
        )
        if gap_unit_id
        else None,
    }


def external_intake_run_pipeline(
    root: Path,
    cfg: dict[str, Any],
    *,
    issue_id: str,
    duplicate: bool = False,
    through: str = "actionability",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validation pipeline classify→duplicate→verify→actionability (PRD 280 R3)."""
    steps = ["external-intake-classify"]
    if duplicate:
        steps.append("external-intake-duplicate-check")
    steps.append("external-intake-verify")
    if through == "actionability":
        steps.append("external-intake-actionability")
    results: list[dict[str, Any]] = []
    for step in steps:
        result = external_intake_txn(root, cfg, verb=step, issue_id=issue_id, dry_run=dry_run)
        results.append(result)
        if result.get("verdict") != "ok":
            return {
                "verdict": "fail",
                "action": "external-intake-pipeline",
                "issueId": issue_id,
                "failedStep": step,
                "results": results,
            }
    return {
        "verdict": "ok",
        "action": "external-intake-pipeline",
        "issueId": issue_id,
        "through": through,
        "results": results,
    }


def _doc_review_facade_invoke(
    root: Path,
    cfg: dict[str, Any],
    *,
    action: str,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    persona: str | None = None,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    ordered_comment_ids: list[str] | None = None,
    idempotency_key: str | None = None,
    body_path: str | None = None,
) -> dict[str, Any]:
    verb = DOC_REVIEW_FACADE_ACTION_TO_VERB.get(action)
    if verb is None:
        return {
            "verdict": "fail",
            "action": action,
            "error": "unknown-doc-review-facade-operation",
            "operation": action,
        }
    result = _doc_review_transport_txn(
        root,
        cfg,
        verb=verb,
        issue_id=issue_id,
        unit_id=unit_id,
        round_id=round_id,
        persona=persona,
        payload=payload,
        dry_run=dry_run,
        ordered_comment_ids=ordered_comment_ids,
        manifest_idempotency_key=idempotency_key,
        body_path=body_path,
    )
    if isinstance(result, dict):
        result["facadeOperation"] = action
    return result


def open_review_manifest(
    root: Path,
    cfg: dict[str, Any],
    *,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    idempotency_key: str | None = None,
    ordered_comment_ids: list[str] | None = None,
    body_path: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Facade entry — open doc-review round manifest after exhaustive pins (PRD 341 R9/R36)."""
    return _doc_review_facade_invoke(
        root,
        cfg,
        action="open_review_manifest",
        issue_id=issue_id,
        unit_id=unit_id,
        round_id=round_id,
        dry_run=dry_run,
        ordered_comment_ids=ordered_comment_ids,
        idempotency_key=idempotency_key,
        body_path=body_path,
    )


def post_review_finding(
    root: Path,
    cfg: dict[str, Any],
    *,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    persona: str | None = None,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Facade entry — post one persona finding comment (PRD 341 phase 1 / R1)."""
    return _doc_review_facade_invoke(
        root,
        cfg,
        action="post_review_finding",
        issue_id=issue_id,
        unit_id=unit_id,
        round_id=round_id,
        persona=persona,
        payload=payload,
        dry_run=dry_run,
    )


def read_review_manifest(
    root: Path,
    cfg: dict[str, Any],
    *,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Facade entry — read doc-review manifest and pins (PRD 341 phase 1 / R1)."""
    return _doc_review_facade_invoke(
        root,
        cfg,
        action="read_review_manifest",
        issue_id=issue_id,
        unit_id=unit_id,
        round_id=round_id,
        dry_run=dry_run,
    )


def verify_review_manifest(
    root: Path,
    cfg: dict[str, Any],
    *,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Facade entry — verify doc-review round integrity (PRD 341 phase 1 / R1)."""
    return _doc_review_facade_invoke(
        root,
        cfg,
        action="verify_review_manifest",
        issue_id=issue_id,
        unit_id=unit_id,
        round_id=round_id,
        dry_run=dry_run,
    )


def complete_review_round(
    root: Path,
    cfg: dict[str, Any],
    *,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Facade entry — re-verify, OCC-close, append completion receipt (PRD 341 R22/R23/D21)."""
    return _doc_review_facade_invoke(
        root,
        cfg,
        action="complete_review_round",
        issue_id=issue_id,
        unit_id=unit_id,
        round_id=round_id,
        dry_run=dry_run,
    )


def doc_review_txn(
    root: Path,
    cfg: dict[str, Any],
    *,
    verb: str,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    persona: str | None = None,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Deprecated bootstrap entry — use facade operations (PRD 341 phase 1 / R1)."""
    if verb in DOC_REVIEW_FACADE_ACTION_TO_VERB.values() or verb in TXN_VERBS:
        return {
            "verdict": "fail",
            "action": verb,
            "error": "doc-review-use-facade-operation",
            "facadeOperations": sorted(DOC_REVIEW_FACADE_OPERATIONS),
        }
    return {"verdict": "fail", "action": verb, "error": "unknown-doc-review-verb", "verb": verb}


class _DocReviewBudgetClient:
    """Charge ``document-review`` on each listing/revalidation ``issue_get`` (R40/D8)."""

    def __init__(self, client: Any, ledger: Any) -> None:
        self._client = client
        self._ledger = ledger
        self._list_pages = 0
        self.last_budget_failure: dict[str, Any] | None = None

    def issue_get(self, issue_id: str) -> Any:
        from planning_doc_review_transport import (
            DOC_REVIEW_BUDGET_OPERATION,
            budget_exhausted_failure,
        )
        from planning_request_budget import BudgetExhausted

        self._list_pages += 1
        depth = int(getattr(self._ledger, "max_pagination_depth", 0) or 0)
        if depth and self._list_pages > depth:
            self.last_budget_failure = budget_exhausted_failure(
                detail="pagination-depth",
                pages=self._list_pages,
                maxPaginationDepth=depth,
            )
            raise BudgetExhausted("doc-review pagination depth exhausted")
        try:
            # Listing/revalidation always charge the dedicated class (critical = within facade txn).
            self._ledger.charge(DOC_REVIEW_BUDGET_OPERATION, critical=True)
        except BudgetExhausted as exc:
            self.last_budget_failure = budget_exhausted_failure(
                detail=str(exc),
                pages=self._list_pages,
                maxCalls=getattr(self._ledger, "max_calls", None),
            )
            raise
        return self._client.issue_get(issue_id)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _doc_review_transport_txn(
    root: Path,
    cfg: dict[str, Any],
    *,
    verb: str,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    persona: str | None = None,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
    ordered_comment_ids: list[str] | None = None,
    manifest_idempotency_key: str | None = None,
    body_path: str | None = None,
    authorize_from_cache: bool = False,
) -> dict[str, Any]:
    """Issue-store doc-review transport verbs (facade-internal)."""
    if verb not in TXN_VERBS:
        return {"verdict": "fail", "action": verb, "error": "unknown-doc-review-verb", "verb": verb}

    # Cache cannot authorize open or complete (R40/D8).
    if authorize_from_cache and verb in {
        "doc-review-round-open",
        "doc-review-round-close",
        "doc-review-round-verify",
    }:
        return {
            "verdict": "fail",
            "action": verb,
            "error": "doc-review-cache-not-authoritative",
            "verb": verb,
        }

    effective = resolve_effective_backend(root, cfg)
    provider = str(resolve_issues_provider(cfg).get("provider") or "none")
    blocked = require_github_issue_store(effective=effective, provider=provider)
    if blocked is not None:
        blocked["action"] = verb
        return blocked

    if not issue_id or not unit_id or not round_id:
        return {"verdict": "fail", "action": verb, "error": "issue-unit-round-required"}

    pk = validate_project_key(root, cfg)
    if pk.get("verdict") != "ok":
        return {"verdict": "fail", "action": verb, "error": pk.get("message") or "invalid project key"}

    # R3 — credentials only through resolver/broker (never ambient env / selector body).
    fixture_mode = (os.environ.get("SW_ISSUES_FIXTURE") or "").strip() == "1"
    if not fixture_mode:
        from credentials.model import ResolutionState

        resolution = resolve_issues_credential(root, issues_provider=provider, cfg=cfg)
        if resolution.state is ResolutionState.UNRESOLVED:
            return {
                "verdict": "fail",
                "action": verb,
                "error": "doc-review-credentials-unresolved",
                "reason": resolution.reason or "unresolved",
            }
        if str(resolution.ref).startswith("tokenEnv:"):
            # tokenEnv alias is resolver-mediated but still ambient — refuse for doc-review (R3).
            return {
                "verdict": "fail",
                "action": verb,
                "error": "doc-review-credentials-ambient-refused",
                "reason": "credentialRef-required",
            }

    client = IssuesClient(root, provider)
    from planning.backends.issues import (
        assert_doc_review_authorship,
        resolve_doc_review_author_principal,
    )
    from planning_request_budget import BudgetExhausted, RequestBudgetLedger

    ledger = RequestBudgetLedger.from_config(root, provider)
    budget_client = _DocReviewBudgetClient(client, ledger)

    whoami = resolve_doc_review_author_principal(budget_client)
    if whoami.get("verdict") != "ok":
        whoami = dict(whoami)
        whoami["action"] = verb
        return whoami
    author_id = str(whoami["authorPrincipal"])

    claimed = None
    if isinstance(payload, dict):
        for key in ("authorId", "author", "authorPrincipal", "claimedAuthor"):
            raw = payload.get(key)
            if raw is not None and str(raw).strip():
                claimed = str(raw).strip()
                break
    # Payload claims never prove authorship — refuse when they disagree with whoami.
    if claimed is not None:
        rejected = assert_doc_review_authorship(
            expected_principal=author_id,
            comment_author_id=author_id,
            payload_claimed_author=claimed,
        )
        if rejected is not None:
            rejected["action"] = verb
            return rejected

    try:
        return execute_doc_review_txn(
            budget_client,
            verb=verb,
            issue_id=str(issue_id),
            unit_id=unit_id,
            round_id=round_id,
            persona=persona,
            payload=payload,
            dry_run=dry_run,
            author_id=author_id,
            ordered_comment_ids=ordered_comment_ids,
            manifest_idempotency_key=manifest_idempotency_key,
            body_path=body_path,
        )
    except BudgetExhausted:
        failure = budget_client.last_budget_failure or {
            "verdict": "fail",
            "error": "doc-review-budget-exhausted",
            "budgetClass": "document-review",
        }
        failure = dict(failure)
        failure["action"] = verb
        return failure


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
    """Delegate CLI to planning.cli (PRD 082 phase 14 / R27)."""
    from planning.cli import main as cli_main
    cli_main()
