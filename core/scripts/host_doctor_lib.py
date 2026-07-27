"""CI-status capability probe for host-doctor and deliver entry (PRD 079 R11, R12)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_gate_lib import EVIDENCE_VALID  # noqa: E402
from host_invoke import host_checks_evidence  # noqa: E402
from host_lib import resolve_provider, token_present  # noqa: E402

CapabilityResult = Literal["capable", "denied", "inconclusive"]

CI_STATUS_PROBE_CACHE_TTL_SECONDS = 300


def git_head_sha(root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def capability_from_checks_envelope(
    envelope: dict[str, Any],
    *,
    provider: str,
) -> CapabilityResult:
    if envelope.get("evidenceValidity") == EVIDENCE_VALID:
        return "capable"
    transport_class = str(envelope.get("transportClass") or "inconclusive")
    if transport_class == "auth-denied":
        return "denied"
    return "inconclusive"


def probe_ci_status_capability(root: Path) -> dict[str, Any]:
    """Probe effective CI-status read capability via the same checks path as the gate (R11)."""
    resolved = resolve_provider(root)
    provider = str(resolved.get("provider") or "none")
    token_env = str(resolved.get("tokenEnv") or "")

    if resolved.get("verdict") != "ok":
        return {
            "capability": "inconclusive",
            "provider": provider,
            "reasonCode": "host-unresolved",
            "tokenEnv": token_env or None,
            "cached": False,
            "cacheAdvisoryTtlSeconds": CI_STATUS_PROBE_CACHE_TTL_SECONDS,
        }

    if provider == "none":
        return {
            "capability": "capable",
            "provider": provider,
            "reasonCode": "local-evidence",
            "tokenEnv": None,
            "cached": False,
            "cacheAdvisoryTtlSeconds": CI_STATUS_PROBE_CACHE_TTL_SECONDS,
        }

    if token_env and not token_present(token_env):
        return {
            "capability": "denied",
            "provider": provider,
            "reasonCode": "missing-token",
            "tokenEnv": token_env,
            "cached": False,
            "cacheAdvisoryTtlSeconds": CI_STATUS_PROBE_CACHE_TTL_SECONDS,
        }

    head_sha = git_head_sha(root)
    if not head_sha:
        return {
            "capability": "inconclusive",
            "provider": provider,
            "reasonCode": "missing-head-sha",
            "tokenEnv": token_env or None,
            "cached": False,
            "cacheAdvisoryTtlSeconds": CI_STATUS_PROBE_CACHE_TTL_SECONDS,
        }

    envelope = host_checks_evidence(root, "checks", "--sha", head_sha)
    capability = capability_from_checks_envelope(envelope, provider=provider)
    return {
        "capability": capability,
        "provider": provider,
        "reasonCode": str(envelope.get("reasonCode") or capability),
        "transportClass": envelope.get("transportClass"),
        "tokenEnv": token_env or None,
        "headSha": head_sha,
        "cached": False,
        "cacheAdvisoryTtlSeconds": CI_STATUS_PROBE_CACHE_TTL_SECONDS,
    }


def ci_status_is_capable(result: dict[str, Any]) -> bool:
    return str(result.get("capability")) == "capable"
