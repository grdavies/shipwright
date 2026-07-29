#!/usr/bin/env python3
"""Committed-tier repository visibility probe (PRD 082 phase 24 / R32).

The committed relaxation retaining internal IPs and emails applies only when the
host API confirms the repository is private. Every other outcome is treated as
external for relaxation purposes. Probes are never cached — each call re-evaluates.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from credentials.model import ResolutionState
from host_lib import (
    detect_provider_from_url,
    git_remote_url,
    github_api_base,
    host_section,
    load_workflow_config,
    parse_owner_repo,
    remote_name,
    resolve_host_credential,
)
import issues_broker
import issues_http
import memory_redact_allowlist as allowlist
from secret_patterns import DENY_PATTERNS

OUTCOMES = frozenset(
    {
        "confirmed-private",
        "public",
        "absent",
        "inconclusive",
        "rate-limited",
        "unprobeable",
    }
)

RELAXED_DETECTOR_NAMES = frozenset({"EMAIL", "INTERNAL_IP"})
_PROBE_OVERRIDE_ENV = "SW_MEMORY_VISIBILITY_PROBE"


def _relaxation_patterns() -> list[tuple[Any, str]]:
    return [(entry.pattern, entry.replacement) for entry in DENY_PATTERNS if entry.name in RELAXED_DETECTOR_NAMES]


def _probe_override() -> str | None:
    raw = os.environ.get(_PROBE_OVERRIDE_ENV, "").strip().lower()
    if not raw:
        legacy = os.environ.get("SW_VISIBILITY_REMOTE_PROBE", "").strip().lower()
        if legacy == "private":
            return "confirmed-private"
        if legacy in OUTCOMES:
            return legacy
        return None
    if raw == "private":
        return "confirmed-private"
    if raw in OUTCOMES:
        return raw
    return None


def _github_repo_private(
    root: Path, owner: str, repo: str, host: dict[str, Any], provider: str
) -> tuple[bool | None, str | None]:
    """Return (is_private, error_kind) where error_kind is rate-limited or inconclusive."""
    from issues_lib import IssueRateLimited

    credential = resolve_host_credential(root, provider=provider)
    if credential.state is ResolutionState.UNRESOLVED:
        return None, "inconclusive"
    token, _reason = issues_broker.token_from_credential(credential)
    base = github_api_base(host)
    url = f"{base}/repos/{owner}/{repo}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "shipwright-memory-visibility-probe",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif credential.state is not ResolutionState.EXPLICITLY_NO_AUTH:
        return None, "inconclusive"
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
            return None, "inconclusive"
        if status >= 400:
            return None, "inconclusive"
        data = json.loads(body)
    except IssueRateLimited:
        return None, "rate-limited"
    except (ConnectionError, json.JSONDecodeError, TimeoutError):
        return None, "inconclusive"
    if isinstance(data, dict) and "private" in data:
        return bool(data["private"]), None
    return None, "inconclusive"


def probe_repository_visibility(root: Path) -> dict[str, Any]:
    """Host-API repository visibility probe — always fresh, never cached."""
    override = _probe_override()
    cfg = load_workflow_config(root)
    host = host_section(cfg)
    remote = remote_name(cfg)
    remote_url = git_remote_url(root, remote)

    if override:
        return {
            "verdict": "ok",
            "outcome": override,
            "source": _PROBE_OVERRIDE_ENV if os.environ.get(_PROBE_OVERRIDE_ENV) else "SW_VISIBILITY_REMOTE_PROBE",
            "remoteUrl": remote_url,
            "cached": False,
        }

    if not remote_url:
        return {
            "verdict": "ok",
            "outcome": "absent",
            "source": "no-remote",
            "remoteUrl": None,
            "cached": False,
        }

    provider = detect_provider_from_url(remote_url)
    owner_repo = parse_owner_repo(remote_url)
    if not owner_repo or provider == "none":
        return {
            "verdict": "ok",
            "outcome": "unprobeable",
            "source": "unprobeable-remote",
            "remoteUrl": remote_url,
            "provider": provider,
            "cached": False,
        }

    owner, repo = owner_repo
    if provider != "github":
        return {
            "verdict": "ok",
            "outcome": "unprobeable",
            "source": "unsupported-provider",
            "remoteUrl": remote_url,
            "provider": provider,
            "cached": False,
        }

    is_private, error_kind = _github_repo_private(root, owner, repo, host, provider)
    if error_kind == "rate-limited":
        return {
            "verdict": "ok",
            "outcome": "rate-limited",
            "source": "host-api",
            "remoteUrl": remote_url,
            "provider": provider,
            "owner": owner,
            "repo": repo,
            "cached": False,
        }
    if is_private is None:
        return {
            "verdict": "ok",
            "outcome": error_kind or "inconclusive",
            "source": "host-api",
            "remoteUrl": remote_url,
            "provider": provider,
            "owner": owner,
            "repo": repo,
            "cached": False,
        }

    return {
        "verdict": "ok",
        "outcome": "confirmed-private" if is_private else "public",
        "source": "host-api",
        "remoteUrl": remote_url,
        "provider": provider,
        "owner": owner,
        "repo": repo,
        "cached": False,
    }


def committed_relaxation_applies(probe: dict[str, Any]) -> bool:
    return probe.get("outcome") == "confirmed-private"


def effective_destination(requested: str, probe: dict[str, Any]) -> str:
    """Map committed → external when the probe does not confirm private."""
    if requested == "committed" and not committed_relaxation_applies(probe):
        return "external"
    return requested


def apply_relaxation_detectors(text: str) -> tuple[str, int]:
    out = text
    total = 0
    for pattern, replacement in _relaxation_patterns():
        out, count = pattern.subn(replacement, out)
        total += count
    return out, total


def redact_with_visibility_probe(
    text: str,
    root: Path,
    *,
    destination: str = "committed",
    probe: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Redact for the committed tier with confirmed-private relaxation gating."""
    if destination not in allowlist.DESTINATION_VALUES:
        raise ValueError(f"invalid destination: {destination!r}")

    live_probe = probe if probe is not None else probe_repository_visibility(root)
    tier = effective_destination(destination, live_probe)

    redacted, provenance = allowlist.redact_document(text, destination=tier)
    relaxation_applied = committed_relaxation_applies(live_probe) and destination == "committed"
    if not relaxation_applied and destination == "committed":
        redacted, relax_count = apply_relaxation_detectors(redacted)
        provenance = {
            **provenance,
            "relaxationDetectorsApplied": relax_count,
            "committedRelaxation": False,
        }
    else:
        provenance = {**provenance, "committedRelaxation": relaxation_applied}

    provenance["visibilityProbe"] = {
        "outcome": live_probe.get("outcome"),
        "source": live_probe.get("source"),
        "effectiveDestination": tier,
    }
    return redacted, provenance


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Repository visibility probe for committed-tier redaction")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--json", action="store_true", help="Emit probe JSON")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    probe = probe_repository_visibility(root)
    if args.json:
        print(json.dumps(probe, indent=2))
    else:
        print(probe.get("outcome", "unknown"))
    return 0 if probe.get("verdict") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
