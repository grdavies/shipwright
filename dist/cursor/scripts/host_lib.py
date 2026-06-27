#!/usr/bin/env python3
"""Host provider resolution, remote config, and token helpers (PRD 026 Phase 1)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
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

def main() -> None:
    parser = argparse.ArgumentParser(description="Host provider resolution helpers")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("resolve")
    sub.add_parser("remote-name")
    sub.add_parser("token-status")

    detect = sub.add_parser("detect-url")
    detect.add_argument("url")

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
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
