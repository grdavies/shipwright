"""PRD 350 memory observation gate (R21–R24, R28).

Observation-mode writes land in the ``observations`` namespace with
``status: pending_human_review``. Direct ``rules`` / ``policy`` writes while
``SW_CAPTURE_RUN_ID`` is set raise ``PromotionGateError`` and redirect here.

Sub-agent routing contract (R23): events with ``provenanceKind: sub_agent_feed``
that carry memory-candidate markers must not be processed by a sub-agent-local
preflight. After the parent consolidates sidecars, call
``route_sub_agent_memory_candidates`` (wave_journal) which invokes
``write_observation`` on the parent only.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_provider_catalog import get_provider, load_catalog
from memory_rules_promote import configured_provider

OBSERVATION_STATUS = "pending_human_review"
OBSERVATION_PENDING_TAG = "sw:observation-pending"
CAPTURE_RUN_ENV = "SW_CAPTURE_RUN_ID"


class PromotionGateError(Exception):
    """Raised when an agent-context write targets rules/policy during a capture run."""

    def __init__(self, message: str, *, redirected: bool = False, cause: str = "promotion-gate") -> None:
        super().__init__(message)
        self.redirected = redirected
        self.cause = cause


def capture_run_id() -> str | None:
    raw = os.environ.get(CAPTURE_RUN_ENV, "").strip()
    return raw or None


def observations_dir(root: Path) -> Path:
    return root / ".cursor" / "sw-memory" / "observations"


def provider_supports_observation(root: Path) -> bool:
    """Return True when the active provider advertises observation status support."""
    try:
        provider = configured_provider(root)
    except Exception:
        return False
    try:
        catalog = load_catalog(root)
        row = get_provider(catalog, provider) if catalog else None
    except Exception:
        row = None
    if not isinstance(row, dict):
        return False
    caps = row.get("capabilities") if isinstance(row.get("capabilities"), dict) else {}
    statuses = caps.get("statuses") or row.get("statuses") or []
    if isinstance(statuses, list) and "observation" in statuses:
        return True
    return bool(caps.get("observation") or row.get("supportsObservation"))


def write_observation(
    root: Path,
    *,
    summary: str,
    source_event_id: str | None = None,
    run_id: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Write an observation-state memory record (R21).

    Prefers the provider ``observations`` namespace with
    ``status: pending_human_review``. Falls back to tagging
    ``sw:observation-pending`` when the provider lacks observation support.
    """
    root = root.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(
        f"{run_id or ''}:{source_event_id or ''}:{summary}".encode()
    ).hexdigest()[:12]
    obs_id = f"obs-{stamp}-{digest}"
    use_native = provider_supports_observation(root)
    tag_list = list(tags or [])
    fallback = False
    if not use_native:
        fallback = True
        if OBSERVATION_PENDING_TAG not in tag_list:
            tag_list.append(OBSERVATION_PENDING_TAG)

    record = {
        "id": obs_id,
        "namespace": "observations",
        "status": OBSERVATION_STATUS,
        "summary": summary[:500],
        "sourceEventId": source_event_id,
        "runId": run_id or capture_run_id(),
        "tags": tag_list,
        "fallbackPendingTag": fallback,
    }
    out_dir = observations_dir(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{obs_id}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ref = f"observations/{obs_id}"
    result: dict[str, Any] = {
        "verdict": "ok",
        "mode": "observation",
        "status": OBSERVATION_STATUS,
        "namespace": "observations",
        "observationRef": ref,
        "observationId": obs_id,
        "path": str(path),
        "fallbackPendingTag": fallback,
    }
    if fallback:
        result["warning"] = (
            "provider lacks observation status; wrote with "
            f"{OBSERVATION_PENDING_TAG} tag for manual promotion"
        )
    return result


def _log_gate_error(root: Path, run_id: str | None, payload: dict[str, Any]) -> None:
    if not run_id:
        return
    try:
        from wave_journal import _append_error

        _append_error(root, run_id, payload)
    except Exception:
        # Best-effort — never block the gate on logging failures.
        pass


def enforce_promotion_gate(
    *,
    namespace: str | None = None,
    status: str | None = None,
    category: str | None = None,
    root: Path | None = None,
    summary: str | None = None,
    source_event_id: str | None = None,
) -> None:
    """Reject rules/policy writes during capture runs; redirect to observation (R22).

    Raises ``PromotionGateError`` when blocked. No-op when ``SW_CAPTURE_RUN_ID``
    is unset (memory-audit exemption) or the target is not rules/policy.
    """
    if not capture_run_id():
        return
    ns = (namespace or category or "").strip().lower()
    st = (status or "").strip().lower()
    blocked = ns in {"rules", "policy", "rule"} or st in {"policy", "rule"}
    if not blocked:
        return
    root = (root or Path(".")).resolve()
    run_id = capture_run_id()
    _log_gate_error(
        root,
        run_id,
        {
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "kind": "PromotionGateError",
            "message": (
                f"blocked rules/policy write (namespace={ns!r} status={st!r}); "
                "redirected to observation mode"
            ),
            "namespace": ns,
            "status": st,
        },
    )
    try:
        write_observation(
            root,
            summary=summary or f"redirected from {ns or st} write",
            source_event_id=source_event_id,
            run_id=run_id,
        )
    except Exception as exc:
        raise PromotionGateError(
            f"direct rules/policy write blocked; observation redirect failed: {exc}",
            redirected=False,
        ) from exc
    raise PromotionGateError(
        "direct rules/policy write blocked during capture run; redirected to observation",
        redirected=True,
    )


__all__ = [
    "CAPTURE_RUN_ENV",
    "OBSERVATION_PENDING_TAG",
    "OBSERVATION_STATUS",
    "PromotionGateError",
    "capture_run_id",
    "enforce_promotion_gate",
    "observations_dir",
    "provider_supports_observation",
    "write_observation",
]
