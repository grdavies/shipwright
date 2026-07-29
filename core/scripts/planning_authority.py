#!/usr/bin/env python3
"""PRD 082 phase 3 — planning authority decision object (R26)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from host_lib import load_workflow_config

import planning_authority_reasons as par
import planning_store as ps
from planning_projection_ledger import set_projection_dirty

_BACKEND_WRITE_LOG: list[dict[str, Any]] = []


@dataclass(frozen=True)
class AuthorityDecision:
    configured: str
    authorityState: str
    reason: str | None
    writeDisposition: str
    cacheValidity: str
    guidance: dict[str, Any] | str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        if out.get("guidance") is None:
            out.pop("guidance", None)
        return out


def clear_backend_write_log() -> None:
    _BACKEND_WRITE_LOG.clear()


def backend_write_log() -> list[dict[str, Any]]:
    return list(_BACKEND_WRITE_LOG)


def record_backend_write(
    backend_id: str,
    *,
    configured: str,
    operation: str = "write",
) -> None:
    _BACKEND_WRITE_LOG.append(
        {
            "backend": backend_id,
            "configured": configured,
            "operation": operation,
        }
    )


def resolve_authority(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    override: str | None = None,
    offline: bool = False,
    cache_available: bool = False,
    identity_mismatch: bool = False,
    ambiguous: bool = False,
    projection_available: bool = True,
) -> AuthorityDecision:
    """Resolve configured backend authority — no substituted effective backend id."""
    cfg = cfg if cfg is not None else load_workflow_config(root)
    configured = ps.resolve_backend_id(cfg, override=override)
    reason = par.resolve_fallback_reason(
        root,
        cfg,
        override=override,
        offline=offline,
        cache_available=cache_available,
        identity_mismatch=identity_mismatch,
        ambiguous=ambiguous,
        projection_available=projection_available,
    )
    if reason == par.REASON_OFFLINE_WITHOUT_CACHE:
        reason = par.REASON_STORE_UNAVAILABLE
    policy = par.policy_for_reason(reason)
    if policy.get("markProjectionDirty"):
        set_projection_dirty(root, reason=par.REASON_PROJECTION_UNAVAILABLE)
    return AuthorityDecision(
        configured=configured,
        authorityState=str(policy["authorityState"]),
        reason=reason,
        writeDisposition=str(policy["writeDisposition"]),
        cacheValidity=str(policy["cacheValidity"]),
        guidance=policy.get("guidance"),
    )


def substantive_deliver_allowed(decision: AuthorityDecision) -> bool:
    """True when substantive deliver entry is permitted (R26 phase 8)."""
    return decision.writeDisposition == "accept" and decision.authorityState == "online"


def deliver_resume_command(
    root: Path,
    *,
    phase_slug: str | None = None,
    reason: str | None = None,
) -> str:
    """Resume hint after an authority disposition halt (R26 phase 8)."""
    detail = f" ({reason})" if reason else ""
    if phase_slug:
        return (
            f"/sw-ship --phase-mode --from sw-execute  "
            f"# resume phase {phase_slug} after authority recovery{detail}"
        )
    return f"python3 scripts/planning_authority_probe.py {root} probe{detail}"


def apply_write_disposition(
    decision: AuthorityDecision,
    *,
    write_class: str = "substantive",
    target_backend: str | None = None,
) -> dict[str, Any]:
    """Apply write disposition for a write class; records backend write attempts."""
    backend = target_backend or decision.configured
    record_backend_write(backend, configured=decision.configured, operation=write_class)
    if write_class == "progress":
        return {"verdict": "ok", "disposition": "local-only", "backend": None}
    if decision.writeDisposition == "accept":
        return {"verdict": "ok", "disposition": "accept", "backend": decision.configured}
    if decision.writeDisposition == "refuse-ledger" and write_class == "projection":
        return {"verdict": "ok", "disposition": "refuse-ledger", "backend": decision.configured}
    if decision.writeDisposition == "refuse-ledger":
        return {"verdict": "ok", "disposition": "refuse-ledger", "backend": decision.configured}
    return {
        "verdict": "refused",
        "disposition": decision.writeDisposition,
        "reason": decision.reason,
        "backend": decision.configured,
    }
