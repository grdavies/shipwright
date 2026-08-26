#!/usr/bin/env python3
"""CapabilityPromotion registry — measured rollout states and family metric gates (PRD 332 R4–R5, R11–R12)."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from gate_evidence import utc_now

REGISTRY_VERSION = "CapabilityPromotion@v1"
DEFAULT_REGISTRY_REL = Path(".cursor/capability-promotion-registry.json")

STATE_SHADOW = "shadow"
STATE_CANDIDATE = "candidate"
STATE_ACTIVE = "active"
STATE_ROLLED_BACK = "rolled_back"

VALID_STATES = frozenset({STATE_SHADOW, STATE_CANDIDATE, STATE_ACTIVE, STATE_ROLLED_BACK})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_SHADOW: frozenset({STATE_CANDIDATE}),
    STATE_CANDIDATE: frozenset({STATE_ACTIVE}),
    STATE_ACTIVE: frozenset({STATE_ROLLED_BACK}),
    STATE_ROLLED_BACK: frozenset({STATE_SHADOW}),
}

DEFAULT_FAMILY_THRESHOLDS: dict[str, float | int] = {
    "minQualifyingRuns": 3,
    "maxFalsePositiveRate": 0.05,
    "maxVetoConflictRate": 0.02,
    "minShadowAgreement": 0.85,
}


class CapabilityPromotionError(ValueError):
    """Invalid promotion registry state or transition."""


class PromotionNotReadyError(CapabilityPromotionError):
    """Metrics or evidence do not satisfy promotion thresholds."""


@dataclass(frozen=True)
class FamilyThresholds:
    min_qualifying_runs: int
    max_false_positive_rate: float
    max_veto_conflict_rate: float
    min_shadow_agreement: float

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> FamilyThresholds:
        merged = dict(DEFAULT_FAMILY_THRESHOLDS)
        if raw:
            merged.update(dict(raw))
        min_runs = int(merged["minQualifyingRuns"])
        if min_runs < 1:
            raise CapabilityPromotionError("invalid-min-qualifying-runs")
        return cls(
            min_qualifying_runs=min_runs,
            max_false_positive_rate=float(merged["maxFalsePositiveRate"]),
            max_veto_conflict_rate=float(merged["maxVetoConflictRate"]),
            min_shadow_agreement=float(merged["minShadowAgreement"]),
        )

    def to_dict(self) -> dict[str, float | int]:
        return {
            "minQualifyingRuns": self.min_qualifying_runs,
            "maxFalsePositiveRate": self.max_false_positive_rate,
            "maxVetoConflictRate": self.max_veto_conflict_rate,
            "minShadowAgreement": self.min_shadow_agreement,
        }


@dataclass(frozen=True)
class QualifyingRun:
    run_id: str
    observed_at: str
    false_positive_rate: float
    veto_conflict_rate: float
    shadow_agreement: float
    evidence_ref: str
    evidence_fresh: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "observedAt": self.observed_at,
            "falsePositiveRate": self.false_positive_rate,
            "vetoConflictRate": self.veto_conflict_rate,
            "shadowAgreement": self.shadow_agreement,
            "evidenceRef": self.evidence_ref,
            "evidenceFresh": self.evidence_fresh,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> QualifyingRun:
        run_id = str(raw.get("runId") or "").strip()
        if not run_id:
            raise CapabilityPromotionError("run-id-required")
        evidence_ref = str(raw.get("evidenceRef") or "").strip()
        if not evidence_ref:
            raise CapabilityPromotionError("evidence-ref-required")
        observed_at = str(raw.get("observedAt") or "").strip()
        if not observed_at:
            raise CapabilityPromotionError("observed-at-required")
        return cls(
            run_id=run_id,
            observed_at=observed_at,
            false_positive_rate=float(raw.get("falsePositiveRate", 0.0)),
            veto_conflict_rate=float(raw.get("vetoConflictRate", 0.0)),
            shadow_agreement=float(raw.get("shadowAgreement", 0.0)),
            evidence_ref=evidence_ref,
            evidence_fresh=bool(raw.get("evidenceFresh")),
        )


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _validate_capability_id(capability_id: str) -> str:
    normalized = capability_id.strip()
    if not normalized:
        raise CapabilityPromotionError("capability-id-required")
    return normalized


def _validate_revision(revision: int) -> int:
    if not isinstance(revision, int) or revision < 1:
        raise CapabilityPromotionError("invalid-revision")
    return revision


def _validate_state(state: str) -> str:
    normalized = state.strip()
    if normalized not in VALID_STATES:
        raise CapabilityPromotionError("invalid-state")
    return normalized


def assert_transition_allowed(current_state: str, target_state: str) -> None:
    current = _validate_state(current_state)
    target = _validate_state(target_state)
    if current == target:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise CapabilityPromotionError(f"illegal-transition:{current}->{target}")


def build_revision_record(
    *,
    revision: int,
    state: str,
    capability_family: str,
    evidence_class: str,
    evidence_ref: str,
    thresholds: FamilyThresholds | Mapping[str, Any] | None = None,
    qualifying_runs: list[QualifyingRun] | None = None,
    prior_active: Mapping[str, Any] | None = None,
    updated_at: str | None = None,
) -> dict[str, Any]:
    rev = _validate_revision(revision)
    normalized_state = _validate_state(state)
    family = capability_family.strip()
    if not family:
        raise CapabilityPromotionError("capability-family-required")
    evidence_cls = evidence_class.strip()
    if not evidence_cls:
        raise CapabilityPromotionError("evidence-class-required")
    evidence_ref_text = evidence_ref.strip()
    if not evidence_ref_text:
        raise CapabilityPromotionError("evidence-ref-required")

    threshold_obj = (
        thresholds
        if isinstance(thresholds, FamilyThresholds)
        else FamilyThresholds.from_mapping(thresholds)
    )
    runs = [run.to_dict() if isinstance(run, QualifyingRun) else QualifyingRun.from_dict(run).to_dict()
            for run in (qualifying_runs or [])]

    record: dict[str, Any] = {
        "revision": rev,
        "state": normalized_state,
        "capabilityFamily": family,
        "evidenceClass": evidence_cls,
        "evidenceRef": evidence_ref_text,
        "thresholds": threshold_obj.to_dict(),
        "qualifyingRuns": runs,
        "updatedAt": updated_at or utc_now(),
    }
    if prior_active is not None:
        record["priorActive"] = dict(prior_active)
    return record


def build_capability_record(
    capability_id: str,
    *,
    capability_family: str,
    revisions: Mapping[int | str, Mapping[str, Any]],
    active_revision: int | None = None,
) -> dict[str, Any]:
    cap_id = _validate_capability_id(capability_id)
    family = capability_family.strip()
    if not family:
        raise CapabilityPromotionError("capability-family-required")
    if not revisions:
        raise CapabilityPromotionError("revisions-required")

    normalized_revisions: dict[str, dict[str, Any]] = {}
    for key, value in revisions.items():
        if not isinstance(value, Mapping):
            raise CapabilityPromotionError("revision-must-be-object")
        rev = _validate_revision(int(key))
        parsed = parse_revision_record(value)
        normalized_revisions[str(rev)] = parsed

    resolved_active = active_revision
    if resolved_active is None:
        for rev_key, rev_record in normalized_revisions.items():
            if rev_record.get("state") == STATE_ACTIVE:
                resolved_active = int(rev_key)
                break
    if resolved_active is None:
        raise CapabilityPromotionError("active-revision-required")

    active_key = str(_validate_revision(resolved_active))
    if active_key not in normalized_revisions:
        raise CapabilityPromotionError("active-revision-missing")

    return {
        "capabilityId": cap_id,
        "capabilityFamily": family,
        "activeRevision": int(active_key),
        "revisions": normalized_revisions,
    }


def parse_revision_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise CapabilityPromotionError("revision-must-be-object")
    rev = _validate_revision(int(record.get("revision", 0)))
    _validate_state(str(record.get("state") or ""))
    family = str(record.get("capabilityFamily") or "").strip()
    if not family:
        raise CapabilityPromotionError("capability-family-required")
    evidence_class = str(record.get("evidenceClass") or "").strip()
    if not evidence_class:
        raise CapabilityPromotionError("evidence-class-required")
    evidence_ref = str(record.get("evidenceRef") or "").strip()
    if not evidence_ref:
        raise CapabilityPromotionError("evidence-ref-required")
    thresholds = FamilyThresholds.from_mapping(record.get("thresholds"))
    runs_raw = record.get("qualifyingRuns") or []
    if not isinstance(runs_raw, list):
        raise CapabilityPromotionError("qualifying-runs-must-be-array")
    runs = [QualifyingRun.from_dict(item).to_dict() for item in runs_raw]
    parsed: dict[str, Any] = {
        "revision": rev,
        "state": str(record.get("state")),
        "capabilityFamily": family,
        "evidenceClass": evidence_class,
        "evidenceRef": evidence_ref,
        "thresholds": thresholds.to_dict(),
        "qualifyingRuns": runs,
        "updatedAt": str(record.get("updatedAt") or utc_now()),
    }
    prior_active = record.get("priorActive")
    if prior_active is not None:
        if not isinstance(prior_active, Mapping):
            raise CapabilityPromotionError("prior-active-must-be-object")
        parsed["priorActive"] = {
            "revision": _validate_revision(int(prior_active.get("revision", 0))),
            "evidenceRef": str(prior_active.get("evidenceRef") or "").strip(),
            "state": str(prior_active.get("state") or STATE_ACTIVE),
        }
        if not parsed["priorActive"]["evidenceRef"]:
            raise CapabilityPromotionError("prior-active-evidence-ref-required")
    return parsed


def parse_capability_record(record: Mapping[str, Any]) -> dict[str, Any]:
    cap_id = _validate_capability_id(str(record.get("capabilityId") or ""))
    family = str(record.get("capabilityFamily") or "").strip()
    if not family:
        raise CapabilityPromotionError("capability-family-required")
    revisions_raw = record.get("revisions")
    if not isinstance(revisions_raw, Mapping) or not revisions_raw:
        raise CapabilityPromotionError("revisions-required")
    revisions = {str(key): parse_revision_record(value) for key, value in revisions_raw.items()}
    active_revision = _validate_revision(int(record.get("activeRevision", 0)))
    if str(active_revision) not in revisions:
        raise CapabilityPromotionError("active-revision-missing")
    return {
        "capabilityId": cap_id,
        "capabilityFamily": family,
        "activeRevision": active_revision,
        "revisions": revisions,
    }


def build_registry(capabilities: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for capability_id, record in capabilities.items():
        normalized_id = _validate_capability_id(capability_id)
        if normalized_id in parsed:
            raise CapabilityPromotionError("duplicate-capability-id")
        entry = parse_capability_record({**dict(record), "capabilityId": normalized_id})
        parsed[normalized_id] = entry
    return {"version": REGISTRY_VERSION, "capabilities": parsed}


def parse_registry(document: Mapping[str, Any]) -> dict[str, Any]:
    if str(document.get("version") or "") != REGISTRY_VERSION:
        raise CapabilityPromotionError("invalid-version")
    capabilities_raw = document.get("capabilities")
    if not isinstance(capabilities_raw, Mapping):
        raise CapabilityPromotionError("capabilities-object-required")
    capabilities = {
        str(cap_id): parse_capability_record({**dict(record), "capabilityId": cap_id})
        for cap_id, record in capabilities_raw.items()
    }
    return {"version": REGISTRY_VERSION, "capabilities": capabilities}


def serialize_registry(document: Mapping[str, Any]) -> str:
    parsed = parse_registry(document)
    return canonical_json(parsed)


def registry_path(root: Path) -> Path:
    return root / DEFAULT_REGISTRY_REL


def read_registry(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"version": REGISTRY_VERSION, "capabilities": {}}
    document = json.loads(path.read_text(encoding="utf-8"))
    return parse_registry(document)


def write_registry(path: Path, document: Mapping[str, Any]) -> Path:
    parsed = parse_registry(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_registry(parsed) + "\n", encoding="utf-8")
    return path


def get_capability(registry: Mapping[str, Any], capability_id: str) -> dict[str, Any]:
    parsed = parse_registry(registry)
    entry = parsed["capabilities"].get(_validate_capability_id(capability_id))
    if entry is None:
        raise CapabilityPromotionError("capability-not-found")
    return deepcopy(entry)


def get_revision(capability: Mapping[str, Any], revision: int) -> dict[str, Any]:
    parsed = parse_capability_record(capability)
    key = str(_validate_revision(revision))
    record = parsed["revisions"].get(key)
    if record is None:
        raise CapabilityPromotionError("revision-not-found")
    return deepcopy(record)


def run_qualifies(run: QualifyingRun | Mapping[str, Any], thresholds: FamilyThresholds) -> bool:
    item = run if isinstance(run, QualifyingRun) else QualifyingRun.from_dict(run)
    if not item.evidence_fresh:
        return False
    if item.false_positive_rate > thresholds.max_false_positive_rate:
        return False
    if item.veto_conflict_rate > thresholds.max_veto_conflict_rate:
        return False
    if item.shadow_agreement < thresholds.min_shadow_agreement:
        return False
    return True


def qualifying_runs_for_promotion(
    runs: list[Mapping[str, Any] | QualifyingRun],
    thresholds: FamilyThresholds,
) -> list[QualifyingRun]:
    """Return qualifying runs in deterministic window order (observedAt, runId)."""
    parsed = [item if isinstance(item, QualifyingRun) else QualifyingRun.from_dict(item) for item in runs]
    eligible = [run for run in parsed if run_qualifies(run, thresholds)]
    return sorted(eligible, key=lambda run: (run.observed_at, run.run_id))


def evaluate_promotion_readiness(
    revision_record: Mapping[str, Any],
    *,
    target_state: str,
) -> dict[str, Any]:
    """Evaluate whether metrics satisfy thresholds for promotion to target_state."""
    parsed = parse_revision_record(revision_record)
    current_state = parsed["state"]
    target = _validate_state(target_state)
    assert_transition_allowed(current_state, target)
    thresholds = FamilyThresholds.from_mapping(parsed.get("thresholds"))
    eligible = qualifying_runs_for_promotion(parsed.get("qualifyingRuns") or [], thresholds)
    metrics = {
        "qualifyingRunCount": len(eligible),
        "requiredRunCount": thresholds.min_qualifying_runs,
        "falsePositiveRates": [run.false_positive_rate for run in eligible],
        "vetoConflictRates": [run.veto_conflict_rate for run in eligible],
        "shadowAgreements": [run.shadow_agreement for run in eligible],
    }
    ready = len(eligible) >= thresholds.min_qualifying_runs
    verdict = "ready" if ready else "not-ready"
    if not ready:
        raise PromotionNotReadyError(
            f"insufficient-qualifying-runs:{len(eligible)}<{thresholds.min_qualifying_runs}"
        )
    return {
        "verdict": verdict,
        "targetState": target,
        "metrics": metrics,
        "evaluatedAt": utc_now(),
    }


def upsert_revision(
    registry: Mapping[str, Any],
    capability_id: str,
    revision_record: Mapping[str, Any],
    *,
    set_active: bool = False,
) -> dict[str, Any]:
    parsed = parse_registry(registry)
    cap_id = _validate_capability_id(capability_id)
    revision = parse_revision_record(revision_record)
    rev_key = str(revision["revision"])

    if cap_id in parsed["capabilities"]:
        capability = deepcopy(parsed["capabilities"][cap_id])
    else:
        capability = {
            "capabilityId": cap_id,
            "capabilityFamily": revision["capabilityFamily"],
            "activeRevision": revision["revision"],
            "revisions": {},
        }

    existing = capability["revisions"].get(rev_key)
    if existing is not None:
        if canonical_json(existing) == canonical_json(revision):
            if set_active:
                capability["activeRevision"] = revision["revision"]
            parsed["capabilities"][cap_id] = capability
            return parsed
        if existing.get("state") != revision.get("state"):
            assert_transition_allowed(str(existing.get("state")), str(revision.get("state")))

    capability["revisions"][rev_key] = revision
    if set_active or rev_key not in capability["revisions"]:
        capability["activeRevision"] = revision["revision"]
    if set_active:
        capability["activeRevision"] = revision["revision"]
    parsed["capabilities"][cap_id] = parse_capability_record(capability)
    return parsed


def record_qualifying_run(
    registry: Mapping[str, Any],
    capability_id: str,
    revision: int,
    run: QualifyingRun | Mapping[str, Any],
    *,
    idempotent: bool = True,
) -> dict[str, Any]:
    parsed = parse_registry(registry)
    capability = get_capability(parsed, capability_id)
    rev_record = get_revision(capability, revision)
    item = run if isinstance(run, QualifyingRun) else QualifyingRun.from_dict(run)
    existing_ids = {str(entry.get("runId")) for entry in rev_record.get("qualifyingRuns") or []}
    if idempotent and item.run_id in existing_ids:
        return parsed
    updated_runs = list(rev_record.get("qualifyingRuns") or [])
    updated_runs.append(item.to_dict())
    rev_record["qualifyingRuns"] = updated_runs
    rev_record["updatedAt"] = utc_now()
    return upsert_revision(parsed, capability_id, rev_record)


def promote_revision(
    registry: Mapping[str, Any],
    capability_id: str,
    revision: int,
    *,
    target_state: str,
    force: bool = False,
) -> dict[str, Any]:
    parsed = parse_registry(registry)
    capability = get_capability(parsed, capability_id)
    rev_record = get_revision(capability, revision)
    current_state = str(rev_record.get("state"))
    target = _validate_state(target_state)
    if current_state == target:
        return parsed
    assert_transition_allowed(current_state, target)
    if not force:
        evaluate_promotion_readiness(rev_record, target_state=target)
    updated = deepcopy(rev_record)
    updated["state"] = target
    updated["updatedAt"] = utc_now()
    return upsert_revision(parsed, capability_id, updated, set_active=True)


def rollback_active_revision(
    registry: Mapping[str, Any],
    capability_id: str,
    revision: int,
    *,
    reason: str = "regression-detected",
) -> dict[str, Any]:
    parsed = parse_registry(registry)
    capability = get_capability(parsed, capability_id)
    rev_record = get_revision(capability, revision)
    if str(rev_record.get("state")) != STATE_ACTIVE:
        raise CapabilityPromotionError("rollback-requires-active-revision")

    prior_active = rev_record.get("priorActive")
    if not isinstance(prior_active, Mapping):
        raise CapabilityPromotionError("prior-active-required-for-rollback")

    prior_revision = _validate_revision(int(prior_active.get("revision", 0)))
    prior_key = str(prior_revision)
    if prior_key not in capability["revisions"]:
        raise CapabilityPromotionError("prior-active-revision-missing")

    rolled = deepcopy(rev_record)
    rolled["state"] = STATE_ROLLED_BACK
    rolled["rollback"] = {"reason": reason.strip() or "regression-detected", "at": utc_now()}
    rolled["updatedAt"] = utc_now()

    restored = deepcopy(capability["revisions"][prior_key])
    restored["state"] = STATE_ACTIVE
    restored["evidenceRef"] = str(prior_active.get("evidenceRef") or restored.get("evidenceRef"))
    restored["updatedAt"] = utc_now()
    restored.pop("priorActive", None)

    capability = deepcopy(capability)
    capability["revisions"][str(revision)] = rolled
    capability["revisions"][prior_key] = restored
    capability["activeRevision"] = prior_revision
    parsed["capabilities"][_validate_capability_id(capability_id)] = parse_capability_record(capability)
    return parsed


EvidenceDispositionFn = Callable[[str], str]


def default_evidence_disposition(evidence_ref: str) -> str:
    ref = evidence_ref.strip()
    if not ref:
        return "invalid"
    if ref.startswith("stale:"):
        return "stale"
    if ref.startswith("absent:"):
        return "absent"
    return "fresh"


def attach_run_from_evidence_ref(
    *,
    run_id: str,
    observed_at: str,
    false_positive_rate: float,
    veto_conflict_rate: float,
    shadow_agreement: float,
    evidence_ref: str,
    disposition_fn: EvidenceDispositionFn | None = None,
) -> QualifyingRun:
    checker = disposition_fn or default_evidence_disposition
    disposition = checker(evidence_ref)
    return QualifyingRun(
        run_id=run_id,
        observed_at=observed_at,
        false_positive_rate=false_positive_rate,
        veto_conflict_rate=veto_conflict_rate,
        shadow_agreement=shadow_agreement,
        evidence_ref=evidence_ref,
        evidence_fresh=disposition == "fresh",
    )
