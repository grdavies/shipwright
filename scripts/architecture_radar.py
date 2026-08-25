#!/usr/bin/env python3
"""Architecture health radar — scan, explain, emit-candidates (PRD 280 R1–R6)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import codebase_intelligence_signals as cis
from _sw.cli import run_module_main

RADAR_ARTIFACT_ROOT = ".cursor/sw-architecture-radar"
DISPOSITIONS = frozenset({"gap-candidate", "decision-candidate", "observe-only"})

SIGNAL_WEIGHTS: dict[str, float] = {
    "git-churn": 2.0,
    "reverts": 5.0,
    "import-fanout": 1.0,
    "review-findings": 3.0,
    "gap-linkage": 4.0,
    "test-fragility": 2.0,
    "activity-bias": 0.0,
}
ACTIVITY_BIAS_MULTIPLIER = 1.5


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def radar_root(root: Path) -> Path:
    return root / RADAR_ARTIFACT_ROOT


def module_path_for_file(file_path: str) -> str:
    """Map a repo-relative file path to a module directory key."""
    path = file_path.strip().strip("/")
    if not path:
        return "."
    parts = Path(path).parts
    if len(parts) == 1:
        return parts[0]
    return str(Path(*parts[:-1]))


def new_scan_id(root: Path) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    digest = hashlib.sha256(f"{stamp}:{root.resolve()}".encode()).hexdigest()[:8]
    return f"{stamp}-{digest}"


def _signal_maps(signals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in signals:
        kind = str(item.get("signal") or "")
        if kind:
            out[kind] = item
    return out


def _aggregate_by_module(signals: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_module: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    maps = _signal_maps(signals)
    for kind, payload in maps.items():
        by_path = payload.get("byPath") if isinstance(payload.get("byPath"), dict) else {}
        for file_path, value in by_path.items():
            mod = module_path_for_file(str(file_path))
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            by_module[mod][kind] += numeric
    return by_module


def _evidence_entry(
    *,
    signal: str,
    value: float,
    window: str | int | None,
    source: str,
) -> dict[str, Any]:
    return {
        "signal": signal,
        "value": value,
        "window": window,
        "source": source,
    }


def _build_evidence(mod: str, module_signals: dict[str, float], maps: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for kind, total in sorted(module_signals.items(), key=lambda kv: (-kv[1], kv[0])):
        if total <= 0:
            continue
        payload = maps.get(kind, {})
        window = payload.get("windowDays") or payload.get("lastPrs")
        evidence.append(
            _evidence_entry(
                signal=kind,
                value=round(total, 3),
                window=window,
                source=f"codebase_intelligence_signals:{kind}",
            )
        )
    if not evidence:
        evidence.append(
            _evidence_entry(signal="baseline", value=0.0, window=None, source="architecture_radar:scan")
        )
    return evidence


def _raw_score(module_signals: dict[str, float], *, activity_active: bool) -> float:
    score = 0.0
    for kind, total in module_signals.items():
        weight = SIGNAL_WEIGHTS.get(kind, 1.0)
        score += total * weight
    if activity_active:
        score *= ACTIVITY_BIAS_MULTIPLIER
    return score


def _normalize_strength(raw: float, max_raw: float) -> int:
    if max_raw <= 0:
        return 0
    scaled = int(round((raw / max_raw) * 100))
    return max(0, min(100, scaled))


def _disposition(strength: int, evidence: list[dict[str, Any]]) -> str:
    signals = {str(item.get("signal")) for item in evidence}
    high_risk = bool(signals & {"reverts", "gap-linkage", "review-findings"})
    if strength >= 70 and high_risk:
        return "gap-candidate"
    if strength >= 45:
        return "decision-candidate"
    return "observe-only"


def _improvement_text(mod: str, evidence: list[dict[str, Any]]) -> str:
    kinds = [str(item.get("signal")) for item in evidence if item.get("value")]
    if "import-fanout" in kinds:
        return f"Consider extracting a narrower interface boundary for `{mod}` to reduce import fan-out."
    if "reverts" in kinds:
        return f"Stabilize `{mod}` with clearer contracts and targeted tests after repeated reverts."
    if "git-churn" in kinds:
        return f"Review cohesion of `{mod}`; high churn may indicate mixed responsibilities."
    return f"Observe `{mod}` for emerging complexity; no immediate structural change recommended."


def _locality_effect(mod: str) -> str:
    return (
        f"Changes to `{mod}` are likely localized to this directory subtree; "
        "refactors should preserve public entry points used by sibling modules."
    )


def build_candidate(
    mod: str,
    module_signals: dict[str, float],
    maps: dict[str, dict[str, Any]],
    *,
    activity_paths: set[str],
    max_raw: float,
) -> dict[str, Any]:
    activity_active = any(module_path_for_file(path) == mod for path in activity_paths)
    if not activity_active:
        for path in activity_paths:
            if path.startswith(mod + "/") or mod.startswith(path + "/"):
                activity_active = True
                break
    raw = _raw_score(module_signals, activity_active=activity_active)
    evidence = _build_evidence(mod, module_signals, maps)
    if activity_active:
        evidence.append(
            _evidence_entry(
                signal="activity-bias",
                value=ACTIVITY_BIAS_MULTIPLIER,
                window=maps.get("activity-bias", {}).get("lastPrs"),
                source="codebase_intelligence_signals:activity-bias",
            )
        )
    strength = _normalize_strength(raw, max_raw)
    disposition = _disposition(strength, evidence)
    return {
        "modulePath": mod,
        "strength": strength,
        "evidence": evidence,
        "improvement": _improvement_text(mod, evidence),
        "localityEffect": _locality_effect(mod),
        "disposition": disposition,
        "activityBiasApplied": activity_active,
    }


def score_candidates(root: Path, signals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    collected = signals if signals is not None else cis.collect_all(root).get("signals") or []
    if not isinstance(collected, list):
        fail("invalid signals payload")
    maps = _signal_maps(collected)
    by_module = _aggregate_by_module(collected)
    activity_paths = set((maps.get("activity-bias") or {}).get("byPath") or {})

    raw_scores: dict[str, float] = {}
    for mod, module_signals in by_module.items():
        activity_active = any(
            module_path_for_file(path) == mod or path.startswith(mod + "/") or mod.startswith(path + "/")
            for path in activity_paths
        )
        raw_scores[mod] = _raw_score(module_signals, activity_active=activity_active)
    max_raw = max(raw_scores.values()) if raw_scores else 0.0

    candidates = [
        build_candidate(mod, module_signals, maps, activity_paths=activity_paths, max_raw=max_raw)
        for mod, module_signals in sorted(by_module.items(), key=lambda kv: (-raw_scores.get(kv[0], 0.0), kv[0]))
    ]
    candidates.sort(key=lambda item: (-int(item.get("strength") or 0), str(item.get("modulePath"))))
    return {
        "verdict": "pass",
        "readOnly": True,
        "scannedAt": utc_now(),
        "config": cis.intelligence_config(root),
        "candidateCount": len(candidates),
        "candidates": candidates,
        "signals": collected,
    }


def write_scan_artifacts(root: Path, scan: dict[str, Any], *, scan_id: str | None = None) -> dict[str, Any]:
    sid = scan_id or new_scan_id(root)
    base = radar_root(root) / sid
    base.mkdir(parents=True, exist_ok=True)
    candidates_path = base / "candidates.json"
    scan_path = base / "scan.json"
    meta = {
        "scanId": sid,
        "scannedAt": scan.get("scannedAt") or utc_now(),
        "readOnly": True,
        "candidateCount": scan.get("candidateCount", 0),
        "config": scan.get("config") or {},
    }
    candidates_doc = {
        "scanId": sid,
        "scannedAt": meta["scannedAt"],
        "readOnly": True,
        "candidates": scan.get("candidates") or [],
    }
    candidates_path.write_text(json.dumps(candidates_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scan_path.write_text(json.dumps({**meta, "candidatesPath": str(candidates_path.relative_to(root))}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    last_path = radar_root(root) / "last.json"
    last_path.parent.mkdir(parents=True, exist_ok=True)
    last_path.write_text(
        json.dumps(
            {
                "scanId": sid,
                "scannedAt": meta["scannedAt"],
                "scanDir": str(base.relative_to(root)),
                "candidatesPath": str(candidates_path.relative_to(root)),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "scanId": sid,
        "scanDir": str(base.relative_to(root)),
        "candidatesPath": str(candidates_path.relative_to(root)),
        "scanPath": str(scan_path.relative_to(root)),
        "lastPath": str(last_path.relative_to(root)),
    }


def load_scan(root: Path, scan_id: str | None = None) -> dict[str, Any]:
    if scan_id:
        candidates_path = radar_root(root) / scan_id / "candidates.json"
        if not candidates_path.is_file():
            fail("scan not found", scanId=scan_id)
        return json.loads(candidates_path.read_text(encoding="utf-8"))
    last_path = radar_root(root) / "last.json"
    if not last_path.is_file():
        fail("no radar scan artifacts found", halt="architecture-radar-missing")
    last = json.loads(last_path.read_text(encoding="utf-8"))
    candidates_path = root / str(last.get("candidatesPath") or "")
    if not candidates_path.is_file():
        fail("latest candidates artifact missing", scanId=last.get("scanId"))
    return json.loads(candidates_path.read_text(encoding="utf-8"))


def cmd_scan(root: Path) -> dict[str, Any]:
    scored = score_candidates(root)
    paths = write_scan_artifacts(root, scored)
    return {
        "verdict": "pass",
        "action": "scan",
        "readOnly": True,
        **paths,
        "candidateCount": scored.get("candidateCount", 0),
        "topCandidates": (scored.get("candidates") or [])[:5],
    }


def cmd_explain(root: Path, module_path: str, *, scan_id: str | None = None) -> dict[str, Any]:
    if scan_id:
        doc = load_scan(root, scan_id)
        candidates = doc.get("candidates") or []
    else:
        scored = score_candidates(root)
        candidates = scored.get("candidates") or []
    target = module_path.strip().strip("/")
    match = next((item for item in candidates if str(item.get("modulePath")) == target), None)
    if match is None:
        fail("module not found in scan", modulePath=target)
    return {
        "verdict": "pass",
        "action": "explain",
        "readOnly": True,
        "modulePath": target,
        "candidate": match,
    }


def emit_gap_drafts(
    root: Path,
    candidates: list[dict[str, Any]],
    *,
    confirm: bool,
    put_gap_draft_fn: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gap_candidates = [c for c in candidates if str(c.get("disposition")) == "gap-candidate"]
    emitted: list[dict[str, Any]] = []
    skipped = {
        "nonGapDisposition": len(candidates) - len(gap_candidates),
        "confirmRequired": 0,
    }
    if not confirm:
        skipped["confirmRequired"] = len(gap_candidates)
        return {
            "verdict": "pass",
            "action": "emit-candidates",
            "readOnly": True,
            "confirm": False,
            "gapCaptureInvoked": False,
            "emitted": emitted,
            "skipped": skipped,
        }
    if put_gap_draft_fn is None:
        from planning_gap_capture import put_gap_draft as put_gap_draft_fn  # noqa: PLC0415

    for item in gap_candidates:
        mod = str(item.get("modulePath") or "module")
        signal_id = f"radar-{hashlib.sha256(mod.encode()).hexdigest()[:12]}"
        title = f"Architecture radar: review `{mod}`"
        payload = {
            "source": "architecture-radar",
            "modulePath": mod,
            "strength": item.get("strength"),
            "disposition": item.get("disposition"),
            "evidence": item.get("evidence") or [],
            "improvement": item.get("improvement"),
        }
        out = put_gap_draft_fn(root, signal_id=signal_id, title=title, payload=payload)
        emitted.append(out)
    return {
        "verdict": "pass",
        "action": "emit-candidates",
        "readOnly": True,
        "confirm": True,
        "gapCaptureInvoked": True,
        "emitted": emitted,
        "skipped": skipped,
    }


def explore_radar_adapter(root: Path) -> dict[str, Any]:
    """Explore-facing radar adapter with explicit degraded status (PRD 331 R17, R42)."""
    try:
        scored = score_candidates(root)
        candidates = scored.get("candidates") or []
        return {
            "verdict": "ok",
            "source": "radar",
            "status": "available",
            "blocking": False,
            "nonBlocking": True,
            "candidateCount": len(candidates),
            "topCandidates": candidates[:5],
            "readOnly": True,
        }
    except SystemExit as exc:
        return {
            "verdict": "degraded",
            "source": "radar",
            "status": "degraded",
            "blocking": False,
            "nonBlocking": True,
            "cause": "radar-unavailable",
            "candidateCount": 0,
            "topCandidates": [],
            "readOnly": True,
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 — explore adapter must not block
        return {
            "verdict": "degraded",
            "source": "radar",
            "status": "degraded",
            "blocking": False,
            "nonBlocking": True,
            "cause": "radar-provider-failure",
            "candidateCount": 0,
            "topCandidates": [],
            "readOnly": True,
            "error": str(exc),
        }


def explore_vocabulary_adapter(root: Path) -> dict[str, Any]:
    """Explore-facing vocabulary adapter with explicit degraded status (PRD 331 R18, R42)."""
    try:
        from domain_vocabulary import list_terms

        listed = list_terms(root)
        terms = listed.get("terms") if isinstance(listed.get("terms"), list) else []
        compact = [
            {
                "slug": item.get("slug"),
                "canonicalName": (item.get("term") or {}).get("canonicalName"),
                "definition": (item.get("term") or {}).get("definition"),
            }
            for item in terms
            if isinstance(item, dict)
        ]
        status = "available" if compact else "absent"
        return {
            "verdict": "ok" if compact else "degraded",
            "source": "vocabulary",
            "status": status,
            "blocking": False,
            "nonBlocking": True,
            "termCount": len(compact),
            "terms": compact[:20],
            "readOnly": True,
        }
    except SystemExit:
        return {
            "verdict": "degraded",
            "source": "vocabulary",
            "status": "degraded",
            "blocking": False,
            "nonBlocking": True,
            "cause": "vocabulary-unavailable",
            "termCount": 0,
            "terms": [],
            "readOnly": True,
        }
    except Exception as exc:  # noqa: BLE001 — explore adapter must not block
        return {
            "verdict": "degraded",
            "source": "vocabulary",
            "status": "degraded",
            "blocking": False,
            "nonBlocking": True,
            "cause": "vocabulary-provider-failure",
            "termCount": 0,
            "terms": [],
            "readOnly": True,
            "error": str(exc),
        }


def cmd_emit_candidates(root: Path, *, confirm: bool, scan_id: str | None = None) -> dict[str, Any]:
    doc = load_scan(root, scan_id)
    candidates = doc.get("candidates") or []
    if not candidates:
        scored = score_candidates(root)
        paths = write_scan_artifacts(root, scored, scan_id=scan_id)
        candidates = scored.get("candidates") or []
    else:
        paths = {"scanId": doc.get("scanId"), "candidatesPath": str((radar_root(root) / (scan_id or doc.get("scanId", "")) / "candidates.json").relative_to(root)) if scan_id or doc.get("scanId") else None}
    emit_info = emit_gap_drafts(root, candidates, confirm=confirm)
    return {**emit_info, **{k: v for k, v in paths.items() if v}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Architecture health radar (PRD 280)")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="Scan repo signals and write candidate artifacts")
    explain = sub.add_parser("explain", help="Explain scoring for one modulePath")
    explain.add_argument("module_path", help="Module path from scan output")
    explain.add_argument("--scan-id")

    emit_cmd = sub.add_parser("emit-candidates", help="Emit gap drafts for gap-candidate dispositions")
    emit_cmd.add_argument("--scan-id")
    emit_cmd.add_argument("--confirm", action="store_true", help="Human gate: invoke gap capture")

    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "scan":
        emit(cmd_scan(root))
    if args.command == "explain":
        emit(cmd_explain(root, args.module_path, scan_id=getattr(args, "scan_id", None)))
    if args.command == "emit-candidates":
        emit(cmd_emit_candidates(root, confirm=bool(args.confirm), scan_id=getattr(args, "scan_id", None)))
    fail(f"unknown command: {args.command}")
    return 0


if __name__ == "__main__":
    run_module_main(main)
