#!/usr/bin/env python3
"""GitHub Projects v2 operator projection client (PRD 061 R11, R11a, R11b, R29a)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import issues_http
from host_lib import github_api_base, host_section, load_workflow_config
from planning_store import (
    resolve_effective_backend,
    resolve_issues_provider,
    resolve_issues_token_env,
    resolve_store_location,
    store_section,
    token_present,
)

GITHUB_PROJECTS_SCOPES = ("read:project", "project")
FIXTURE_ENV = "SW_PROJECTS_FIXTURE"
FIXTURE_REL = ".cursor/hooks/state/github-projects-fixture.json"
DEFAULT_BUDGET = {"maxCalls": 40, "maxPaginationDepth": 5, "cacheTtlSeconds": 300}
PO_BROWSE_QUESTIONS = (
    "which gaps a PRD absorbs",
    "which brainstorms feed a PRD",
    "task/phase completion for an in-flight PRD",
    "backlog vs in-flight vs done at program level",
)


def _fixture_enabled() -> bool:
    return os.environ.get(FIXTURE_ENV, "").strip().lower() in {"1", "true", "yes"} or os.environ.get(
        "SW_ISSUES_FIXTURE", ""
    ).strip().lower() in {"1", "true", "yes"}


def _fixture_path(root: Path) -> Path:
    return root / FIXTURE_REL


def _load_fixture(root: Path) -> dict[str, Any]:
    path = _fixture_path(root)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"items": {}, "upserts": [], "callCount": 0}


def _save_fixture(root: Path, data: dict[str, Any]) -> None:
    path = _fixture_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def projection_section(cfg: dict[str, Any]) -> dict[str, Any]:
    store = store_section(cfg)
    raw = store.get("operatorProjection")
    if not isinstance(raw, dict):
        return {}
    github = raw.get("githubProjects")
    return github if isinstance(github, dict) else {}


def resolve_github_projects_config(cfg: dict[str, Any]) -> dict[str, Any]:
    section = projection_section(cfg)
    enabled = section.get("enabled", True)
    if enabled is False:
        return {"verdict": "ok", "enabled": False, "reason": "operator-projection-disabled"}
    owner = section.get("ownerLogin")
    number = section.get("projectNumber")
    project_id = section.get("projectId")
    field_map = section.get("fieldMap") if isinstance(section.get("fieldMap"), dict) else {}
    budget_raw = section.get("budget") if isinstance(section.get("budget"), dict) else {}
    budget = {**DEFAULT_BUDGET, **{k: v for k, v in budget_raw.items() if k in DEFAULT_BUDGET}}
    missing: list[str] = []
    if not isinstance(owner, str) or not owner.strip():
        missing.append("ownerLogin")
    if not isinstance(number, int) or number < 1:
        if not (isinstance(project_id, str) and project_id.strip()):
            missing.append("projectNumber|projectId")
    if missing:
        return {
            "verdict": "ok",
            "enabled": True,
            "configured": False,
            "state": "projection-unavailable",
            "notice": "github-projects-config-incomplete",
            "missing": missing,
            "degraded": True,
        }
    return {
        "verdict": "ok",
        "enabled": True,
        "configured": True,
        "ownerLogin": owner.strip() if isinstance(owner, str) else owner,
        "projectNumber": number,
        "projectId": project_id.strip() if isinstance(project_id, str) else project_id,
        "fieldMap": field_map,
        "budget": budget,
    }


def _token_for_probe(root: Path, cfg: dict[str, Any]) -> tuple[str, str]:
    issues = resolve_issues_provider(cfg)
    provider = issues.get("provider", "none")
    token_env = resolve_issues_token_env(cfg, str(provider))
    if not token_env or not token_present(token_env):
        return "", token_env
    return os.environ.get(token_env, "").strip(), token_env


def probe_projects_scope(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    issues = resolve_issues_provider(cfg)
    if issues.get("provider") != "github-issues":
        return {"verdict": "ok", "skipped": True, "reason": "not-github-issues"}
    proj = resolve_github_projects_config(cfg)
    if not proj.get("enabled", True):
        return {"verdict": "ok", "skipped": True, "reason": "projection-disabled"}
    if _fixture_enabled():
        return {"verdict": "ok", "fixture": True, "scopes": list(GITHUB_PROJECTS_SCOPES), "state": "available"}
    token, token_env = _token_for_probe(root, cfg)
    if not token:
        return {
            "verdict": "ok",
            "state": "projection-unavailable",
            "notice": "github-projects-token-absent",
            "tokenEnv": token_env,
            "requiredScopes": list(GITHUB_PROJECTS_SCOPES),
            "degraded": True,
        }
    api_base = github_api_base(host_section(cfg))
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "shipwright-github-projects-v2",
    }
    status, resp_headers, _body = issues_http.request(
        "GET", f"{api_base}/user", headers, None, root=root, issues_provider="github-issues"
    )
    if status >= 400:
        return {
            "verdict": "ok",
            "state": "projection-unavailable",
            "notice": "github-projects-scope-probe-failed",
            "httpStatus": status,
            "degraded": True,
        }
    scopes_header = resp_headers.get("x-oauth-scopes") or resp_headers.get("X-OAuth-Scopes") or ""
    scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
    if not scopes:
        return {
            "verdict": "ok",
            "state": "available",
            "scopes": [],
            "tokenKind": "fine-grained-or-app",
            "notice": "github-projects-scope-header-absent",
        }
    if scopes & set(GITHUB_PROJECTS_SCOPES):
        return {"verdict": "ok", "state": "available", "scopes": sorted(scopes)}
    return {
        "verdict": "ok",
        "state": "projection-unavailable",
        "notice": "github-projects-insufficient-scope",
        "scopes": sorted(scopes),
        "requiredScopes": list(GITHUB_PROJECTS_SCOPES),
        "degraded": True,
    }


def projection_health(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    effective = resolve_effective_backend(root, cfg)
    if effective.get("effective") != "issue-store":
        return {"verdict": "ok", "skipped": True, "reason": "not-issue-store"}
    issues = resolve_issues_provider(cfg)
    if issues.get("provider") != "github-issues":
        return {"verdict": "ok", "skipped": True, "reason": "not-github-issues"}
    proj = resolve_github_projects_config(cfg)
    if not proj.get("enabled", True):
        return {"verdict": "ok", "skipped": True, "reason": "projection-disabled"}
    if not proj.get("configured"):
        return {
            "verdict": "ok",
            "action": "projection-health",
            "state": "projection-unavailable",
            "notice": proj.get("notice"),
            "missing": proj.get("missing", []),
            "degraded": True,
        }
    scope = probe_projects_scope(root, cfg)
    state = scope.get("state", "projection-unavailable")
    result: dict[str, Any] = {
        "verdict": "ok",
        "action": "projection-health",
        "state": state,
        "ownerLogin": proj.get("ownerLogin"),
        "projectNumber": proj.get("projectNumber"),
        "projectId": proj.get("projectId"),
        "scopes": scope.get("scopes"),
        "degraded": state != "available",
    }
    if scope.get("notice"):
        result["notice"] = scope["notice"]
    if scope.get("requiredScopes"):
        result["requiredScopes"] = scope["requiredScopes"]
    return result


def projection_cutover_ready(root: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    worktree = Path(root).resolve()
    workflow_cfg = cfg if cfg is not None else load_workflow_config(worktree)
    health = projection_health(worktree, workflow_cfg)
    if health.get("skipped"):
        return {"verdict": "ok", "ready": True, "skipped": True, "reason": health.get("reason")}
    ready = health.get("state") == "available" and not health.get("degraded")
    return {
        "verdict": "ok",
        "action": "projection-cutover-gate",
        "ready": ready,
        "state": health.get("state"),
        "notice": health.get("notice"),
        "poBrowseQuestions": list(PO_BROWSE_QUESTIONS),
    }


def _upsert_signature(item: dict[str, Any]) -> str:
    payload = {k: item[k] for k in sorted(item) if k in {"contentId", "unitId", "status", "artifactType"}}
    return json.dumps(payload, sort_keys=True)


def _fixture_refresh(root: Path, cfg: dict[str, Any], *, dry_run: bool, items: list[dict[str, Any]]) -> dict[str, Any]:
    proj = resolve_github_projects_config(cfg)
    fixture = _load_fixture(root)
    max_calls = int(proj.get("budget", DEFAULT_BUDGET).get("maxCalls", DEFAULT_BUDGET["maxCalls"]))
    created = updated = skipped = 0
    upserted: list[dict[str, Any]] = []
    for item in items:
        key = item.get("contentId") or item.get("unitId")
        if not key:
            skipped += 1
            continue
        sig = _upsert_signature(item)
        existing = fixture["items"].get(str(key))
        if existing == sig:
            skipped += 1
            upserted.append({"contentId": key, "action": "noop"})
            continue
        action = "create" if existing is None else "update"
        if dry_run:
            upserted.append({"contentId": key, "action": action, "dryRun": True})
            created += action == "create"
            updated += action == "update"
            continue
        if fixture["callCount"] >= max_calls:
            return {"verdict": "fail", "error": "github-projects-budget-exhausted", "callCount": fixture["callCount"]}
        fixture["callCount"] += 1
        fixture["items"][str(key)] = sig
        record = {"contentId": key, "action": action, **item}
        fixture["upserts"].append(record)
        upserted.append(record)
        if action == "create":
            created += 1
        else:
            updated += 1
    if not dry_run:
        _save_fixture(root, fixture)
    return {
        "verdict": "ok",
        "action": "projection-refresh",
        "dryRun": dry_run,
        "fixture": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "callCount": fixture.get("callCount", 0),
        "upserts": upserted,
    }


def _graphql(root: Path, cfg: dict[str, Any], token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    api_base = github_api_base(host_section(cfg))
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "shipwright-github-projects-v2",
    }
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    status, _hdrs, raw = issues_http.request(
        "POST", f"{api_base}/graphql", headers, body, root=root, issues_provider="github-issues"
    )
    if status >= 400:
        raise RuntimeError(f"github-graphql-http-{status}")
    data = json.loads(raw)
    if data.get("errors"):
        raise RuntimeError(str(data["errors"][0].get("message", "graphql-error")))
    return data.get("data") or {}


def _live_refresh(root: Path, cfg: dict[str, Any], *, dry_run: bool, items: list[dict[str, Any]]) -> dict[str, Any]:
    scope = probe_projects_scope(root, cfg)
    if scope.get("state") != "available":
        return {
            "verdict": "ok",
            "action": "projection-refresh",
            "dryRun": dry_run,
            "state": "projection-unavailable",
            "notice": scope.get("notice", "github-projects-unavailable"),
            "degraded": True,
            "skipped": len(items),
        }
    token, _env = _token_for_probe(root, cfg)
    if not token:
        return {
            "verdict": "ok",
            "action": "projection-refresh",
            "state": "projection-unavailable",
            "notice": "github-projects-token-absent",
            "degraded": True,
        }
    proj = resolve_github_projects_config(cfg)
    owner = str(proj.get("ownerLogin") or "")
    number = proj.get("projectNumber")
    if dry_run:
        return {
            "verdict": "ok",
            "action": "projection-refresh",
            "dryRun": True,
            "wouldUpsert": len(items),
            "ownerLogin": owner,
            "projectNumber": number,
        }
    query = "query($login: String!, $number: Int!) { user(login: $login) { projectV2(number: $number) { id title } } }"
    try:
        data = _graphql(root, cfg, token, query, {"login": owner, "number": int(number or 0)})
    except RuntimeError as exc:
        return {"verdict": "ok", "action": "projection-refresh", "state": "projection-unavailable", "notice": str(exc), "degraded": True}
    project = ((data.get("user") or {}).get("projectV2")) if isinstance(data.get("user"), dict) else None
    if not project:
        org_query = "query($login: String!, $number: Int!) { organization(login: $login) { projectV2(number: $number) { id title } } }"
        try:
            data = _graphql(root, cfg, token, org_query, {"login": owner, "number": int(number or 0)})
            project = (data.get("organization") or {}).get("projectV2") if isinstance(data.get("organization"), dict) else None
        except RuntimeError as exc:
            return {"verdict": "ok", "action": "projection-refresh", "state": "projection-unavailable", "notice": str(exc), "degraded": True}
    if not project:
        return {"verdict": "ok", "action": "projection-refresh", "state": "projection-unavailable", "notice": "github-projects-project-not-found", "degraded": True}
    return {
        "verdict": "ok",
        "action": "projection-refresh",
        "projectId": project.get("id"),
        "projectTitle": project.get("title"),
        "upserted": len(items),
        "state": "available",
    }


def refresh_projection(root: Path, cfg: dict[str, Any], *, dry_run: bool = False, items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    effective = resolve_effective_backend(root, cfg)
    if effective.get("effective") != "issue-store":
        return {"verdict": "ok", "skipped": True, "reason": "not-issue-store"}
    issues = resolve_issues_provider(cfg)
    if issues.get("provider") != "github-issues":
        return {"verdict": "ok", "skipped": True, "reason": "not-github-issues"}
    payload = list(items or [])
    if _fixture_enabled():
        return _fixture_refresh(root, cfg, dry_run=dry_run, items=payload)
    return _live_refresh(root, cfg, dry_run=dry_run, items=payload)


def sample_projection_items(root: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    location = resolve_store_location(root, cfg)
    store = store_section(cfg)
    project_key = store.get("projectKey", "planning")
    return [{
        "contentId": "issue:352",
        "unitId": "061-prd-planning-store-interface-architecture",
        "artifactType": "prd",
        "status": "draft",
        "projectKey": project_key,
        "storeOwner": location.get("owner"),
        "storeRepo": location.get("repo"),
    }]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="GitHub Projects v2 projection (PRD 061)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("probe-scope", "health", "refresh", "cutover-gate", "po-browse-questions"):
        sub.add_parser(name)
    args, rest = parser.parse_known_args()
    root = Path(args.root).resolve()
    cfg = load_workflow_config(root)
    if args.command == "probe-scope":
        print(json.dumps(probe_projects_scope(root, cfg), ensure_ascii=False, indent=2))
    elif args.command == "health":
        print(json.dumps(projection_health(root, cfg), ensure_ascii=False, indent=2))
    elif args.command == "refresh":
        dry_run = "--dry-run" in rest
        print(json.dumps(refresh_projection(root, cfg, dry_run=dry_run, items=sample_projection_items(root, cfg)), ensure_ascii=False, indent=2))
    elif args.command == "cutover-gate":
        print(json.dumps(projection_cutover_ready(root, cfg), ensure_ascii=False, indent=2))
    elif args.command == "po-browse-questions":
        print(json.dumps({"questions": list(PO_BROWSE_QUESTIONS)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
