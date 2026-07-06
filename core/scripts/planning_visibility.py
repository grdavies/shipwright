#!/usr/bin/env python3
"""PRD 034 Phase 1 — per-unit visibility resolver (single authority)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import issues_http
import urllib.request
from pathlib import Path
from typing import Any

from host_lib import (
    detect_provider_from_url,
    git_remote_url,
    github_api_base,
    host_section,
    load_workflow_config,
    parse_owner_repo,
    remote_name,
    resolve_token_env,
)

VISIBILITY_VALUES = frozenset({"public", "private", "memory"})
VISIBILITY_PROFILES = frozenset({"all-private", "specs-public", "all-public"})

ADVISORY_CONTENT_CLASSES = frozenset({"brainstorm", "decision", "learnings", "gap"})
SPEC_CONTENT_CLASSES = frozenset({"prd", "tasks", "amendment"})

STATE_REL = Path(".cursor/hooks/state/planning-visibility.json")
CONFIG_REL = Path(".cursor/workflow.config.json")

REDACTED_BODY_MARKER = "[redacted:private-body]"

EMISSION_POINTS: dict[str, str] = {
    "index-active": "Unified INDEX active rows (PRD 034 R4)",
    "index-archive": "Unified INDEX archived rows (PRD 034 R4)",
    "legacy-gap-backlog": "033 legacy GAP-BACKLOG projection",
    "legacy-prd-index": "033 legacy PRD INDEX projection",
    "pr-diff": "PR diff planning-body paths",
    "dispatch-context": "Dispatch / subagent planning context",
    "spec-seed": "wave spec-seed body copy",
    "store-get": "planning.store get / list --json",
    "superseded-manifest": "SUPERSEDED manifest rows",
    "inflight-tuple": "Committed INDEX inFlight tuple (032 R13 handoff)",
    "reconciler-output": "033 reconciler emitted bodies",
    "run-log": "Deliver run logs",
    "handoff-032": "032 handoff artifacts",
    "issue-store-memory-pointer": "Issue-store brainstorm distillation pointer (PRD 043 R19)",
    "issue-store-freeze-record": "Issue-store freeze-record comment (PRD 043 R13)",
    "issue-store-comment": "Issue-store comment / overflow chunk write (PRD 043 R45)",
    "issue-store-put": "Issue-store put/create body write (PRD 043 R45)",
    "pull-in-confirm": "035 pull-in confirm lists",
}


def planning_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning")
    return planning if isinstance(planning, dict) else {}


def config_path(root: Path) -> Path | None:
    for rel in (CONFIG_REL, Path("workflow.config.json")):
        path = root / rel
        if path.is_file():
            return path
    return None


def state_path(root: Path) -> Path:
    return root / STATE_REL


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def normalize_visibility(raw: str | None) -> str:
    if raw is None:
        return "private"
    normalized = str(raw).strip().lower()
    if normalized in VISIBILITY_VALUES:
        return normalized
    return "private"


def content_class_for_unit(unit: dict[str, Any]) -> str:
    for key in ("contentClass", "content_class"):
        val = unit.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip().lower()
    unit_type = unit.get("type")
    if isinstance(unit_type, str) and unit_type.strip():
        return unit_type.strip().lower()
    return "prd"


def visibility_profile(cfg: dict[str, Any]) -> str:
    planning = planning_section(cfg)
    profile = planning.get("visibilityProfile")
    if isinstance(profile, str) and profile in VISIBILITY_PROFILES:
        return profile
    return "specs-public"


def profile_default_visibility(profile: str, content_class: str) -> str:
    if profile == "all-private":
        return "private"
    if profile == "all-public":
        return "public"
    cc = content_class.lower()
    if cc in ADVISORY_CONTENT_CLASSES:
        return "private"
    if cc in SPEC_CONTENT_CLASSES:
        return "public"
    return "private"


def resolve_unit_visibility(
    unit: dict[str, Any],
    cfg: dict[str, Any] | None = None,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    cfg = cfg or {}
    prof = profile if profile in VISIBILITY_PROFILES else visibility_profile(cfg)
    explicit = unit.get("visibility")
    cc = content_class_for_unit(unit)
    if explicit is not None and str(explicit).strip():
        resolved = normalize_visibility(str(explicit))
        source = "unit-field"
    else:
        resolved = profile_default_visibility(prof, cc)
        source = "profile-default"
    return {
        "visibility": resolved,
        "profile": prof,
        "contentClass": cc,
        "source": source,
    }


def _probe_override() -> str | None:
    raw = os.environ.get("SW_VISIBILITY_REMOTE_PROBE", "").strip().lower()
    if raw in ("public", "private", "absent"):
        return raw
    return None


def _github_repo_private(
    root: Path, owner: str, repo: str, host: dict[str, Any], provider: str
) -> bool | None:
    from issues_lib import IssueRateLimited

    token_env = resolve_token_env(host, provider)
    api_token = os.environ.get(token_env, "") if token_env else ""
    base = github_api_base(host)
    url = f"{base}/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "shipwright-planning-visibility",
    }
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    try:
        status, _, body = issues_http.http_request(
            "GET",
            url,
            headers,
            root=root,
            issues_provider="github-issues",
            timeout=15,
        )
        if status == 404:
            return None
        if status >= 400:
            if status == 403 and not api_token:
                return None
            return None
        data = json.loads(body)
    except (IssueRateLimited, ConnectionError, json.JSONDecodeError, TimeoutError):
        return None
    if isinstance(data, dict) and "private" in data:
        return bool(data["private"])
    return None


def probe_remote_visibility(root: Path) -> dict[str, Any]:
    override = _probe_override()
    if override:
        vis = override
        return {
            "verdict": "ok",
            "remoteVisibility": vis,
            "source": "SW_VISIBILITY_REMOTE_PROBE",
            "remoteUrl": git_remote_url(root, remote_name(load_workflow_config(root))),
        }

    cfg = load_workflow_config(root)
    host = host_section(cfg)
    remote = remote_name(cfg)
    remote_url = git_remote_url(root, remote)
    if not remote_url:
        return {
            "verdict": "ok",
            "remoteVisibility": "absent",
            "source": "no-remote",
            "remoteUrl": None,
        }

    provider = detect_provider_from_url(remote_url)
    owner_repo = parse_owner_repo(remote_url)
    if not owner_repo or provider == "none":
        return {
            "verdict": "ok",
            "remoteVisibility": "absent",
            "source": "unprobeable-remote",
            "remoteUrl": remote_url,
            "provider": provider,
        }

    owner, repo = owner_repo
    is_private: bool | None = None
    if provider == "github":
        is_private = _github_repo_private(root, owner, repo, host, provider)

    if is_private is None:
        return {
            "verdict": "ok",
            "remoteVisibility": "absent",
            "source": "probe-inconclusive",
            "remoteUrl": remote_url,
            "provider": provider,
        }

    return {
        "verdict": "ok",
        "remoteVisibility": "private" if is_private else "public",
        "source": "host-api",
        "remoteUrl": remote_url,
        "provider": provider,
        "owner": owner,
        "repo": repo,
    }


def resolve_default_profile(root: Path, *, write: bool = False) -> dict[str, Any]:
    probe = probe_remote_visibility(root)
    remote_vis = probe.get("remoteVisibility", "absent")
    if remote_vis == "public":
        profile = "all-private"
        ack = {"required": True, "recordedAt": None, "reason": "public-origin-remote"}
    else:
        profile = "specs-public"
        ack = {"required": False, "recordedAt": None, "reason": None}

    result: dict[str, Any] = {
        "verdict": "ok",
        "visibilityProfile": profile,
        "privacyAck": ack,
        "remoteProbe": probe,
    }

    if not write:
        return result

    cfg_path = config_path(root)
    if cfg_path is None:
        result["verdict"] = "fail"
        result["error"] = "missing-workflow-config"
        return result

    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        result["verdict"] = "fail"
        result["error"] = "invalid-workflow-config"
        return result

    planning = planning_section(cfg)
    planning["visibilityProfile"] = profile
    planning["privacyAck"] = ack
    cfg["planning"] = planning
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    state = load_state(root)
    state["visibilityProfile"] = profile
    state["privacyAck"] = ack
    state["remoteProbe"] = probe
    write_state(root, state)

    result["written"] = {"config": str(cfg_path.relative_to(root)), "state": str(STATE_REL)}
    return result




def _parse_file_frontmatter(path: Path) -> dict[str, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            out[key.strip()] = val.strip()
    return out


def _git_tracked(root: Path, rel: str) -> bool:
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", rel],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def check_tracked_public_at_freeze(root: Path, artifact_path: Path) -> dict[str, Any]:
    """PRD 050 R18 — all-private profile requires visibility: public on tracked freeze artifacts."""
    cfg = load_workflow_config(root)
    profile = visibility_profile(cfg)
    if profile != "all-private":
        return {"verdict": "pass", "skipped": True, "reason": "profile-not-all-private"}
    artifact = artifact_path.resolve()
    if not artifact.is_file():
        return {"verdict": "fail", "error": "artifact-missing", "path": str(artifact_path)}
    rel = str(artifact.relative_to(root.resolve()))
    if not _git_tracked(root, rel):
        return {"verdict": "pass", "skipped": True, "reason": "not-tracked", "path": rel}
    fm = _parse_file_frontmatter(artifact)
    resolved = resolve_unit_visibility(fm, cfg)["visibility"]
    if body_is_redacted(resolved):
        return {
            "verdict": "fail",
            "halt": "tracked-private-at-freeze",
            "path": rel,
            "visibilityProfile": profile,
            "resolvedVisibility": resolved,
            "remediation": (
                "add visibility: public to frontmatter before freeze when planning.visibilityProfile is all-private"
            ),
        }
    return {"verdict": "pass", "path": rel, "visibility": resolved}


def body_is_redacted(visibility: str) -> bool:
    return normalize_visibility(visibility) in {"private", "memory"}


def redact_body(body: str | None, visibility: str) -> str:
    if not body_is_redacted(visibility):
        return body or ""
    return REDACTED_BODY_MARKER


def redact_index_row(row: dict[str, Any], visibility: str) -> dict[str, Any]:
    vis = normalize_visibility(visibility)
    allowed = {"id", "title", "status", "type", "depends", "blocks", "supersedes", "extends", "absorbs", "visibility"}
    if body_is_redacted(vis):
        out = {k: row[k] for k in allowed if k in row}
        out["visibility"] = vis
        if row.get("opaqueTitle") is True:
            out["title"] = f"{row.get('id', 'unit')}: [private]"
        out.pop("body", None)
        out.pop("summary", None)
        return out
    return dict(row)


def _branch_token(branch: str) -> str:
    digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()
    return digest[:16]


def redact_inflight_tuple(tuple_data: dict[str, Any], visibility: str) -> dict[str, Any]:
    vis = normalize_visibility(visibility)
    if not body_is_redacted(vis):
        return dict(tuple_data)
    out = dict(tuple_data)
    branch = out.pop("branch", None)
    if isinstance(branch, str) and branch:
        out["branchToken"] = _branch_token(branch)
    run_id = out.get("runId")
    if isinstance(run_id, str) and run_id:
        out["runId"] = hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:16]
    return out


def emit_through_point(point_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    if point_id not in EMISSION_POINTS:
        return {"verdict": "fail", "error": "unknown-emission-point", "point": point_id}
    vis = normalize_visibility(str(payload.get("visibility", "private")))
    out: dict[str, Any] = {
        "verdict": "ok",
        "point": point_id,
        "visibility": vis,
    }
    if "body" in payload:
        out["body"] = redact_body(payload.get("body"), vis)
    if "row" in payload and isinstance(payload["row"], dict):
        out["row"] = redact_index_row(payload["row"], vis)
    if "tuple" in payload and isinstance(payload["tuple"], dict):
        out["tuple"] = redact_inflight_tuple(payload["tuple"], vis)
    return out


def _cmd_resolve_unit(args: argparse.Namespace) -> int:
    unit = json.loads(args.unit_json)
    cfg = load_workflow_config(Path(args.root))
    prof = args.profile if args.profile else None
    print(json.dumps(resolve_unit_visibility(unit, cfg, profile=prof), indent=2))
    return 0


def _cmd_resolve_default_profile(args: argparse.Namespace) -> int:
    result = resolve_default_profile(Path(args.root), write=bool(args.write))
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "ok" else 1


def _cmd_check_freeze_visibility(args: argparse.Namespace) -> int:
    root = Path(args.root)
    result = check_tracked_public_at_freeze(root, root / args.artifact)
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "pass" else 20


def _cmd_probe_remote(args: argparse.Namespace) -> int:
    print(json.dumps(probe_remote_visibility(Path(args.root)), indent=2))
    return 0


def _cmd_redact_body(args: argparse.Namespace) -> int:
    body = sys.stdin.read() if args.body is None else args.body
    print(redact_body(body, args.visibility))
    return 0


def _cmd_emit_point(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload_json)
    result = emit_through_point(args.point, payload)
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "ok" else 1


def _cmd_list_emission_points(_args: argparse.Namespace) -> int:
    print(json.dumps({"points": EMISSION_POINTS}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRD 034 planning visibility resolver")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    p_unit = sub.add_parser("resolve-unit", help="Resolve visibility for a unit frontmatter object")
    p_unit.add_argument("--unit-json", required=True, help="JSON object for unit frontmatter")
    p_unit.add_argument("--profile", default=None, choices=sorted(VISIBILITY_PROFILES))
    p_unit.set_defaults(func=_cmd_resolve_unit)

    p_prof = sub.add_parser("resolve-default-profile", help="Public-repo-aware default profile")
    p_prof.add_argument("--write", action="store_true", help="Persist profile + ack to config and state")
    p_prof.set_defaults(func=_cmd_resolve_default_profile)

    p_probe = sub.add_parser("probe-remote", help="Probe origin remote visibility")
    p_probe.set_defaults(func=_cmd_probe_remote)

    p_freeze = sub.add_parser("check-freeze-visibility", help="PRD 050 R18 freeze-time tracked-public guard")
    p_freeze.add_argument("artifact", help="Path to artifact relative to --root")
    p_freeze.set_defaults(func=_cmd_check_freeze_visibility)

    p_redact = sub.add_parser("redact-body", help="Redact a body for a visibility token")
    p_redact.add_argument("--visibility", required=True)
    p_redact.add_argument("--body", default=None)
    p_redact.set_defaults(func=_cmd_redact_body)

    p_emit = sub.add_parser("emit-point", help="Emit through a registered emission point")
    p_emit.add_argument("--point", required=True)
    p_emit.add_argument("--payload-json", required=True)
    p_emit.set_defaults(func=_cmd_emit_point)

    p_list = sub.add_parser("list-emission-points", help="List emission point registry")
    p_list.set_defaults(func=_cmd_list_emission_points)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
