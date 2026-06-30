#!/usr/bin/env python3
"""Host provider resolution, remote config, and token helpers (PRD 026 Phase 1)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

VALID_PROVIDERS = frozenset({"github", "gitlab", "bitbucket", "none"})

DEFAULT_RATE_LIMIT: dict[str, Any] = {
    "maxAttempts": 5,
    "baseBackoffMs": 1000,
    "capBackoffMs": 60000,
    "maxCumulativeWaitMs": 300000,
    "jitter": True,
    "nearLimitThreshold": 5,
    "mutatingMinDelayMs": 1000,
}

DEFAULT_TOKEN_ENV: dict[str, str] = {
    "github": "GITHUB_TOKEN",
    "gitlab": "GITLAB_TOKEN",
    "bitbucket": "BITBUCKET_TOKEN",
    "none": "",
}

HOST_VERBS = (
    "resolve-pr-for-branch",
    "pr-create",
    "pr-view",
    "pr-list",
    "pr-head",
    "pr-close",
    "checks",
    "review-threads",
    "repo-meta",
    "merge",
)

PUBLIC_HOST_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(^|\.)github\.com$", re.I), "github"),
    (re.compile(r"(^|\.)gitlab\.com$", re.I), "gitlab"),
    (re.compile(r"(^|\.)bitbucket\.org$", re.I), "bitbucket"),
)


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def host_section(cfg: dict[str, Any]) -> dict[str, Any]:
    host = cfg.get("host")
    return host if isinstance(host, dict) else {}


def remote_name(cfg: dict[str, Any]) -> str:
    host = host_section(cfg)
    remote = host.get("remote")
    if isinstance(remote, str) and remote.strip():
        return remote.strip()
    return "origin"


def parse_git_remote_url(url: str) -> str:
    url = url.strip()
    if url.startswith("git@"):
        host_part = url.split(":", 1)[0]
        return host_part.removeprefix("git@")
    parsed = urlparse(url)
    return parsed.hostname or ""


def detect_provider_from_url(url: str | None) -> str:
    if not url or not url.strip():
        return "none"
    host = parse_git_remote_url(url)
    if not host:
        return "none"
    for pattern, provider in PUBLIC_HOST_PATTERNS:
        if pattern.search(host):
            return provider
    lower = host.lower()
    if "github" in lower:
        return "github"
    if "gitlab" in lower:
        return "gitlab"
    if "bitbucket" in lower:
        return "bitbucket"
    return "none"


def git_remote_url(root: Path, remote: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", remote],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    return out or None


def resolve_rate_limit(host: dict[str, Any]) -> dict[str, Any]:
    raw = host.get("rateLimit")
    merged = dict(DEFAULT_RATE_LIMIT)
    if isinstance(raw, dict):
        for key in DEFAULT_RATE_LIMIT:
            if key in raw:
                merged[key] = raw[key]
    return merged


def resolve_token_env(host: dict[str, Any], provider: str) -> str:
    token_env = host.get("tokenEnv")
    if isinstance(token_env, str) and token_env.strip():
        return token_env.strip()
    return DEFAULT_TOKEN_ENV.get(provider, "")


def token_present(token_env: str) -> bool:
    if not token_env:
        return True
    return bool(os.environ.get(token_env))


def resolve_provider(root: Path) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    host = host_section(cfg)
    remote = remote_name(cfg)
    configured = host.get("provider")
    remote_url = git_remote_url(root, remote)
    detected = detect_provider_from_url(remote_url)

    if isinstance(configured, str) and configured.strip():
        provider = configured.strip()
    else:
        provider = detected

    if provider not in VALID_PROVIDERS:
        return {
            "verdict": "fail",
            "error": "unknown_provider",
            "provider": provider,
            "allowed": sorted(VALID_PROVIDERS),
        }

    token_env = resolve_token_env(host, provider)
    has_token = token_present(token_env)
    base_url = host.get("baseUrl") if isinstance(host.get("baseUrl"), str) else None
    api_base_url = host.get("apiBaseUrl") if isinstance(host.get("apiBaseUrl"), str) else None

    result: dict[str, Any] = {
        "verdict": "ok",
        "provider": provider,
        "remote": remote,
        "remoteUrl": remote_url,
        "detected": detected,
        "configured": configured,
        "tokenEnv": token_env,
        "tokenPresent": has_token,
        "baseUrl": base_url,
        "apiBaseUrl": api_base_url,
        "rateLimit": resolve_rate_limit(host),
    }
    if provider != "none" and token_env and not has_token:
        result["degraded"] = True
        result["degradedReason"] = "missing-token"
    return result


def token_status(root: Path) -> dict[str, Any]:
    resolved = resolve_provider(root)
    if resolved.get("verdict") != "ok":
        return resolved
    provider = resolved["provider"]
    token_env = resolved.get("tokenEnv", "")
    if provider == "none" or not token_env:
        return {
            "verdict": "ok",
            "provider": provider,
            "tokenEnv": token_env,
            "present": True,
            "degraded": False,
        }
    present = token_present(token_env)
    out: dict[str, Any] = {
        "verdict": "ok" if present else "degraded",
        "provider": provider,
        "tokenEnv": token_env,
        "present": present,
        "degraded": not present,
    }
    if not present:
        out["reason"] = "missing-token"
        out["message"] = f"Set {token_env} for host API access (value never logged)."
    return out


def remote_ref(remote: str, branch: str) -> str:
    return f"{remote}/{branch}"


def remote_heads_ref(remote: str, branch: str) -> str:
    return f"refs/remotes/{remote}/{branch}"



def parse_owner_repo(url: str | None) -> tuple[str, str] | None:
    if not url or not url.strip():
        return None
    cleaned = url.strip().removesuffix(".git")
    path = ""
    if cleaned.startswith("git@"):
        path = cleaned.split(":", 1)[-1] if ":" in cleaned else ""
    else:
        path = urlparse(cleaned).path.lstrip("/")
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None


def github_api_base(host: dict[str, Any]) -> str:
    api = host.get("apiBaseUrl")
    if isinstance(api, str) and api.strip():
        return api.strip().rstrip("/")
    return "https://api.github.com"



def gitlab_api_base(host: dict[str, Any]) -> str:
    api = host.get("apiBaseUrl")
    if isinstance(api, str) and api.strip():
        return api.strip().rstrip("/")
    base = host.get("baseUrl")
    if isinstance(base, str) and base.strip():
        return base.strip().rstrip("/") + "/api/v4"
    return "https://gitlab.com/api/v4"


def bitbucket_api_base(host: dict[str, Any]) -> str:
    api = host.get("apiBaseUrl")
    if isinstance(api, str) and api.strip():
        return api.strip().rstrip("/")
    return "https://api.bitbucket.org/2.0"


def url_encode_project(owner: str, repo: str) -> str:
    from urllib.parse import quote

    return quote(f"{owner}/{repo}", safe="")


def phase_mode_active() -> bool:
    raw = os.environ.get("SW_PHASE_MODE", "")
    return raw.lower() in ("1", "true", "yes")


def default_base_branch(root: Path) -> str:
    cfg = load_workflow_config(root)
    base = cfg.get("defaultBaseBranch")
    if isinstance(base, str) and base.strip():
        return base.strip()
    return "main"


def two_track_config(root: Path) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    docs = cfg.get("docs") if isinstance(cfg.get("docs"), dict) else {}
    two = docs.get("twoTrack") if isinstance(docs.get("twoTrack"), dict) else {}
    return {
        "allowDirectTrunk": bool(two.get("allowDirectTrunk", False)),
        "protectionProbeTtlSeconds": int(two.get("protectionProbeTtlSeconds") or 300),
    }


def probe_cache_path(root: Path) -> Path:
    return root / ".cursor" / "sw-branch-protection-probe.json"


def read_probe_cache(root: Path, branch: str, ttl_seconds: int) -> dict[str, Any] | None:
    path = probe_cache_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    entry = data.get(branch) if isinstance(data, dict) else None
    if not isinstance(entry, dict):
        return None
    probed_at = entry.get("probedAt")
    if not isinstance(probed_at, (int, float)):
        return None
    if time.time() - float(probed_at) > ttl_seconds:
        return None
    return entry


def write_probe_cache(root: Path, branch: str, entry: dict[str, Any]) -> None:
    path = probe_cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}
    data[branch] = entry
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def probe_github_branch_protection(root: Path, branch: str) -> dict[str, Any]:
    """Probe branch protection via GitHub REST (no GitHub CLI)."""
    import io
    from contextlib import redirect_stdout

    from _sw.host_transport import urllib_request

    resolved = resolve_provider(root)
    if resolved.get("verdict") != "ok":
        return {
            "verdict": "ambiguous",
            "protected": None,
            "route": "pr",
            "reason": "provider-unresolved",
        }
    provider = resolved.get("provider")
    if provider != "github":
        return {
            "verdict": "ambiguous",
            "protected": None,
            "route": "pr",
            "reason": f"unsupported-provider:{provider}",
        }
    token_env = resolved.get("tokenEnv") or ""
    if token_env and not token_present(token_env):
        return {
            "verdict": "ambiguous",
            "protected": None,
            "route": "pr",
            "reason": "missing-token",
        }
    remote_url = resolved.get("remoteUrl")
    owner_repo = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    if not owner_repo:
        return {
            "verdict": "ambiguous",
            "protected": None,
            "route": "pr",
            "reason": "owner-repo-unresolved",
        }
    owner, repo = owner_repo
    host = host_section(load_workflow_config(root))
    api_base = github_api_base(host)
    url = f"{api_base}/repos/{owner}/{repo}/branches/{branch}/protection"
    with redirect_stdout(io.StringIO()):
        transport = urllib_request(
            method="GET",
            url=url,
            root=root,
            provider="github",
            token_env=token_env,
        )
    status = int(transport.get("status") or 0)
    body = str(transport.get("body") or "")
    if transport.get("verdict") == "ok" and status == 200:
        return {
            "verdict": "ok",
            "protected": True,
            "route": "pr",
            "reason": "branch-protected",
        }
    if status == 404 or "Branch not protected" in body:
        return {
            "verdict": "ok",
            "protected": False,
            "route": "direct",
            "reason": "branch-unprotected",
        }
    return {
        "verdict": "ambiguous",
        "protected": None,
        "route": "pr",
        "reason": "probe-failed",
        "detail": body.strip()[:200],
    }


def is_public_remote_template(root: Path) -> bool:
    resolved = resolve_provider(root)
    if resolved.get("verdict") != "ok":
        return False
    provider = resolved.get("provider")
    remote_url = resolved.get("remoteUrl")
    if not isinstance(remote_url, str):
        return False
    detected = detect_provider_from_url(remote_url)
    return provider in {"github", "gitlab", "bitbucket"} and detected == provider


def probe_branch_protection(root: Path, branch: str | None = None, *, use_cache: bool = True) -> dict[str, Any]:
    target = branch or default_base_branch(root)
    cfg = two_track_config(root)
    ttl = cfg["protectionProbeTtlSeconds"]
    if use_cache:
        cached = read_probe_cache(root, target, ttl)
        if cached:
            cached = dict(cached)
            cached["cached"] = True
            return cached

    live = probe_github_branch_protection(root, target)
    entry = {
        **live,
        "branch": target,
        "probedAt": time.time(),
        "allowDirectTrunk": cfg["allowDirectTrunk"],
        "publicTemplate": is_public_remote_template(root),
    }
    if live.get("verdict") == "ok":
        if cfg["allowDirectTrunk"] and live.get("protected") is False:
            entry["route"] = "direct"
        else:
            entry["route"] = "pr"
    else:
        entry["route"] = "pr"
    if entry.get("publicTemplate") and entry.get("route") == "direct":
        entry["autoMergeAllowed"] = False
    else:
        entry["autoMergeAllowed"] = entry.get("route") == "pr"
    write_probe_cache(root, target, entry)
    entry["cached"] = False
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(description="Host provider resolution helpers")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("resolve")
    sub.add_parser("remote-name")
    sub.add_parser("token-status")

    detect = sub.add_parser("detect-url")
    detect.add_argument("url")

    protection = sub.add_parser("branch-protection-probe")
    protection.add_argument("--branch", default=None)
    protection.add_argument("--no-cache", action="store_true")

    args = parser.parse_args()
    root = args.root.resolve()

    if args.cmd == "resolve":
        print(json.dumps(resolve_provider(root), indent=2))
    elif args.cmd == "remote-name":
        cfg = load_workflow_config(root)
        print(remote_name(cfg))
    elif args.cmd == "token-status":
        print(json.dumps(token_status(root), indent=2))
    elif args.cmd == "detect-url":
        print(json.dumps({"provider": detect_provider_from_url(args.url)}, indent=2))
    elif args.cmd == "branch-protection-probe":
        print(
            json.dumps(
                probe_branch_protection(root, args.branch, use_cache=not args.no_cache),
                indent=2,
            )
        )
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
