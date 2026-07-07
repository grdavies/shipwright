#!/usr/bin/env python3
"""Planning store + visibility doctor checks (PRD 034 R16, R21, R27)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
import planning_visibility

TOKEN_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)


def sanitize(value):
    if isinstance(value, str):
        out = value
        for pat in TOKEN_PATTERNS:
            out = pat.sub("[REDACTED:TOKEN]", out)
        return out
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    return value


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    raw = proc.stdout.strip() or proc.stderr.strip() or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"verdict": "fail", "error": "invalid-json", "raw": raw[:200]}


def classify_issue_store_probe(probe: dict) -> dict:
    """Classify an issue-store token/reachability probe outcome (PRD 057 R30).

    Distinguishes an absent token (``store-token-absent`` — advisory, never a
    silent pass) from any other probe failure (``probe-failed`` — fail-closed).
    Pure function over the ``probe-issues-token`` result shape; no I/O.
    """
    if probe.get("verdict") == "ok":
        if probe.get("skipped"):
            return {"check": "store-reachability", "status": "ok", "reason": probe.get("reason")}
        return {"check": "store-reachability", "status": "ok", "provider": probe.get("provider")}
    error = probe.get("error")
    if error in {"missing-token", "missing-token-env"}:
        token_env = probe.get("tokenEnv")
        return {
            "check": "store-token-absent",
            "status": "advisory",
            "provider": probe.get("provider"),
            "tokenEnv": token_env,
            "remediation": f"Set {token_env or '<tokenEnv>'} to enable live issue-store checks (advisory only; file-store parity unaffected).",
        }
    return {
        "check": "probe-failed",
        "status": "fail",
        "provider": probe.get("provider"),
        "error": error,
        "message": probe.get("message"),
    }


def wave_regression_check(root: Path) -> dict | None:
    """Wave-rollback local/store drift finding (PRD 057 R31). Fail-open, advisory-only wiring."""
    try:
        import planning_store as ps

        cfg = ps.load_workflow_config(root)
        return ps.wave_regression_finding(root, cfg)
    except Exception:  # noqa: BLE001 — doctor check is advisory / fail-open
        return None


def gap_resolution_partial_finding(root: Path) -> dict | None:
    """Open-issue-plus-resolved-label mismatch finding (PRD 057 R4).

    ``close_gap_issue`` (``scripts/planning_migrate_issue_store.py``) closes the
    gap issue and applies the ``sw:gap-resolved`` label in a single
    ``issue_update`` call; if that call fails or is interrupted after the
    provider applies part of the update, a gap issue can be left with the
    resolved label but still open. Under issue-store ``separate-project`` there
    is no local canonical gap file to cross-check against, so this mismatch has
    no other detection surface. Fail-open (returns ``None``) so an
    unreachable/non-issue-store backend never breaks the doctor sweep.
    """
    try:
        import planning_store as ps
        from planning_canonical import GAP_LABEL_RESOLVED
        from planning_migrate_issue_store import issue_store_effective, list_gap_issue_records

        cfg = ps.load_workflow_config(root)
        if not issue_store_effective(root, cfg):
            return None
        records = list_gap_issue_records(root, cfg)
    except Exception:  # noqa: BLE001 — doctor check is advisory / fail-open
        return None
    mismatched = sorted(
        str(getattr(record, "unit_id", ""))
        for record in records
        if GAP_LABEL_RESOLVED in getattr(record, "labels", [])
        and getattr(record, "state", "") != "closed"
    )
    if not mismatched:
        return None
    return {
        "check": "gap-resolution-partial",
        "status": "drift",
        "unitIds": mismatched,
        "remediation": (
            "retry close_gap_issue(root, unit_id) via `gap-backlog.py flip --resolve` "
            "or `living-status-gap-resolve.py --absorbing-prd <NNN>`"
        ),
    }


def parked_frontier_finding(root: Path) -> dict | None:
    """Over-parked-frontier drift finding (PRD 057 R28).

    When the graph-eligible frontier is non-empty but every candidate is parked
    or unrunnable (no frozen task list), scheduling would be exhausted — surface
    it as drift with the exact unpark remediation. Fail-open (returns ``None``)
    if the graph cannot be read, so the doctor never crashes on this check.
    """
    try:
        import planning_deliver_gate as pdg
        import planning_graph as pg
        import planning_park as park

        eligible = pg.order_eligible(pg.discover_units(root))
        if not eligible:
            return None
        parked_map = park.load_parked(root)
        parked: list[str] = []
        unrunnable: list[str] = []
        runnable: list[str] = []
        for unit_id in eligible:
            if unit_id in parked_map:
                parked.append(unit_id)
            elif not pdg.task_list_for_unit(root, unit_id):
                unrunnable.append(unit_id)
            else:
                runnable.append(unit_id)
    except Exception:  # noqa: BLE001 — doctor check is advisory / fail-open
        return None
    if runnable:
        # Frontier still has a runnable candidate; report parked count only when present.
        if not parked:
            return None
        return {
            "check": "parked-frontier",
            "status": "ok",
            "parkedUnits": parked,
            "runnableUnits": runnable,
        }
    return {
        "check": "over-parked-frontier",
        "status": "drift",
        "parkedUnits": parked,
        "unrunnableUnits": unrunnable,
        "eligible": eligible,
        "remediation": park.UNPARK_REMEDIATION,
    }


PRIVACY_NOTICE_REL = Path("core/sw-reference/planning-privacy-notice.md")
PRIVACY_ACK_REMEDIATION = "python3 scripts/planning_visibility.py --root . record-privacy-ack"


def planning_visibility_deprecation_finding(cfg: dict) -> dict | None:
    """R29 (gap-028) — surfaces `planning_visibility.deprecated_visibility_key_warning`
    as a doctor finding when the live config still sets the deprecated
    `visibilityProfile` key directly."""
    return planning_visibility.deprecated_visibility_key_warning(cfg)


def privacy_ack_required_finding(cfg: dict) -> dict | None:
    """R15 (gap-046) — flags a live config with `privacyAck.required: true` and
    `recordedAt: null`: the operator has not yet acknowledged the privacy notice for
    a public-origin remote (or public store host), so private-tier planning bodies
    should not be assumed safe. Names the exact remediation command. Pure function
    over the loaded config; no I/O beyond what the caller already did."""
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    ack = planning.get("privacyAck") if isinstance(planning.get("privacyAck"), dict) else {}
    if not ack.get("required"):
        return None
    if ack.get("recordedAt"):
        return None
    return {
        "check": "privacy-ack-required",
        "status": "action-required",
        "reason": ack.get("reason"),
        "remediation": PRIVACY_ACK_REMEDIATION,
    }


def privacy_notice_key_reconciliation_finding(root: Path) -> dict | None:
    """R15 (gap-046) — reconciles the notice-doc's acknowledgement wording against
    the `recordedAt` key that `planning_visibility.py` actually writes (the doc
    historically described a since-renamed `ackedAt` key). Fail-open (returns
    ``None``) when the doc is missing or already reconciled."""
    path = root / PRIVACY_NOTICE_REL
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if "recordedAt" in text:
        return None
    if "ackedAt" not in text:
        return None
    return {
        "check": "privacy-notice-key-stale",
        "status": "drift",
        "path": str(PRIVACY_NOTICE_REL),
        "staleKey": "ackedAt",
        "expectedKey": "recordedAt",
        "remediation": f"update {PRIVACY_NOTICE_REL} to reference planning.privacyAck.recordedAt (the key planning_visibility.py writes), not ackedAt",
    }


def source_missing_finding(root: Path) -> dict | None:
    """Untagged-legacy-unit finding for shared planning repos (PRD 057 R12).

    Discovery/scheduler/gap-capture scoping never hides an untagged unit from
    the default (or an explicit) `sw:source:<owner>/<repo>` scope; this
    advisory finding is the companion surfacing so an operator can decide
    whether to backfill a `source:` tag. Fail-open (returns ``None``) if
    discovery cannot run, so the doctor never crashes on this check.
    """
    try:
        import planning_discover as pdisc

        untagged = sorted(u.id for u in pdisc.discover_units(root) if not u.source)
    except Exception:  # noqa: BLE001 — doctor check is advisory / fail-open
        return None
    if not untagged:
        return None
    return {
        "check": "sw:source-missing",
        "status": "advisory",
        "untaggedUnits": untagged,
        "remediation": (
            "add a `source:` frontmatter hint (or sw:source:<owner>/<repo> label) to scope "
            "these units to a product repo"
        ),
    }


def doctor(root: Path, *, sweep: bool) -> dict:
    checks: list[dict] = []
    warnings: list[str] = []
    verdict = "ok"

    backend_data = run_json([
        sys.executable, str(SCRIPT_DIR / "planning_store.py"), "--root", str(root), "resolve-backend",
    ])
    store_backend = backend_data.get("backend", "in-repo-public")
    checks.append({"check": "store-backend", "status": "ok", "backend": store_backend})

    reach = run_json([
        sys.executable, str(SCRIPT_DIR / "planning_store.py"), "--root", str(root),
        "exists", "--unit-id", "__doctor-probe__", "--body-path", "__doctor-probe__.md",
    ])
    if store_backend == "in-repo-public":
        if reach.get("verdict") in {"ok", "missing"}:
            checks.append({"check": "store-reachability", "status": "ok", "backend": store_backend})
        else:
            checks.append({"check": "store-reachability", "status": "fail", "backend": store_backend})
            warnings.append("in-repo-public-unreachable")
            verdict = "fail"
    elif store_backend == "local-synced":
        cfg_path = None
        for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
            if candidate.is_file():
                cfg_path = candidate
                break
        sync_path = ""
        if cfg_path:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            sync_path = (
                ((cfg.get("planning") or {}).get("store") or {}).get("localSynced") or {}
            ).get("path") or ""
        if not sync_path:
            checks.append({"check": "local-synced-path", "status": "fail", "reason": "missing-path"})
            warnings.append("local-synced-backend-without-path")
            verdict = "fail"
        else:
            data = run_json([
                sys.executable, str(SCRIPT_DIR / "planning_store.py"), "--root", str(root),
                "validate-local-synced", "--path", sync_path,
            ])
            if data.get("verdict") == "ok":
                checks.append({"check": "local-synced-path", "status": "ok", "path": sync_path})
                checks.append({"check": "store-reachability", "status": "ok", "backend": store_backend})
                for w in data.get("warnings") or []:
                    warnings.append(str(w))
                    if verdict == "ok":
                        verdict = "degraded"
            else:
                checks.append({"check": "local-synced-path", "status": "fail", "path": sync_path})
                checks.append({"check": "store-reachability", "status": "fail", "backend": store_backend})
                warnings.append("local-synced-path-validation-failed")
                verdict = "fail"
    elif store_backend == "memory":
        from memory_sot import resolve_memory_provider

        provider = resolve_memory_provider(root) or ""
        if not provider:
            checks.append({
                "check": "memory-provider",
                "status": "degraded",
                "reason": "no-provider",
                "remediation": "set memory.provider in workflow.config.json or add .cursor/sw-memory.provider",
            })
            checks.append({
                "check": "store-reachability",
                "status": "degraded",
                "backend": store_backend,
                "remediation": "configure memory.provider or switch planning.store.backend to in-repo-public",
            })
            warnings.append("memory-backend-degrade-open-no-provider")
            if verdict == "ok":
                verdict = "degraded"
        else:
            checks.append({"check": "memory-provider", "status": "ok", "provider": provider})
            checks.append({"check": "store-reachability", "status": "ok", "backend": store_backend, "provider": provider})
    elif store_backend == "issue-store":
        probe = run_json([
            sys.executable, str(SCRIPT_DIR / "planning_store.py"), "--root", str(root), "probe-issues-token",
        ])
        finding = classify_issue_store_probe(probe)
        finding["backend"] = store_backend
        checks.append(finding)
        if finding["check"] == "store-token-absent":
            warnings.append("store-token-absent")
            if verdict == "ok":
                verdict = "degraded"
        elif finding["check"] == "probe-failed":
            warnings.append("probe-failed")
            verdict = "fail"

    cfg_path = root / ".cursor/workflow.config.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
        host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
        checks.append({
            "check": "credential-surface",
            "status": "ok",
            "memoryProvider": memory.get("provider"),
            "hostTokenEnv": host.get("tokenEnv"),
            "note": "env-var names only; no secrets in config",
        })

        deprecated_visibility_finding = planning_visibility_deprecation_finding(cfg)
        if deprecated_visibility_finding is not None:
            checks.append(deprecated_visibility_finding)
            warnings.append("visibility-tier-key-deprecated")
            if verdict == "ok":
                verdict = "degraded"

        ack_finding = privacy_ack_required_finding(cfg)
        if ack_finding is not None:
            checks.append(ack_finding)
            warnings.append("privacy-ack-required")
            if verdict == "ok":
                verdict = "degraded"

    notice_finding = privacy_notice_key_reconciliation_finding(root)
    if notice_finding is not None:
        checks.append(notice_finding)
        warnings.append("privacy-notice-key-stale")
        if verdict == "ok":
            verdict = "degraded"

    parked_finding = parked_frontier_finding(root)
    if parked_finding is not None:
        checks.append(parked_finding)
        if parked_finding.get("status") == "drift":
            warnings.append("over-parked-frontier")
            if verdict == "ok":
                verdict = "degraded"

    source_finding = source_missing_finding(root)
    if source_finding is not None:
        checks.append(source_finding)
        warnings.append("sw:source-missing")
        if verdict == "ok":
            verdict = "degraded"

    regression_finding = wave_regression_check(root)
    if regression_finding is not None:
        checks.append(regression_finding)
        if regression_finding.get("status") == "drift":
            warnings.append("wave-regression")
            verdict = "fail"

    gap_resolution_finding = gap_resolution_partial_finding(root)
    if gap_resolution_finding is not None:
        checks.append(gap_resolution_finding)
        if gap_resolution_finding.get("status") == "drift":
            warnings.append("gap-resolution-partial")
            if verdict == "ok":
                verdict = "degraded"

    swept: list[str] = []
    if sweep:
        materialized_roots: list[Path] = []
        repo_mat = root / ".cursor" / "planning-materialized"
        if repo_mat.is_dir():
            materialized_roots.append(repo_mat)
        worktrees = root / ".sw-worktrees"
        if worktrees.is_dir():
            for wt in worktrees.iterdir():
                mat = wt / ".cursor" / "planning-materialized"
                if mat.is_dir():
                    materialized_roots.append(mat)
        cursor = root / ".cursor"
        if cursor.is_dir():
            for state_file in cursor.glob("sw-deliver-state*.json"):
                try:
                    state = json.loads(state_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                pin = state.get("planningStorePin") or {}
                for rel in pin.get("materializedPaths") or []:
                    rel_path = Path(str(rel))
                    if rel_path.parts and rel_path.parts[0] == ".cursor":
                        candidate = root / rel_path.parts[0]
                        for part in rel_path.parts[1:]:
                            if part == "planning-materialized":
                                candidate = candidate / part
                                break
                            candidate = candidate / part
                        if candidate.name == "planning-materialized" and candidate.is_dir():
                            materialized_roots.append(candidate)
        unique_roots = sorted({str(p.resolve()) for p in materialized_roots})
        if unique_roots:
            sweep_out = run_json([
                sys.executable, str(SCRIPT_DIR / "planning_materialize.py"), "--root", str(root),
                "sweep-orphans", "--paths-json", json.dumps(unique_roots),
            ])
            swept = sweep_out.get("swept") or []
            checks.append({
                "check": "orphan-materialized-sweep",
                "status": "ok",
                "candidates": len(unique_roots),
                "swept": len(swept),
            })
        else:
            checks.append({"check": "orphan-materialized-sweep", "status": "ok", "candidates": 0, "swept": 0})

    return sanitize({
        "verdict": verdict,
        "backend": store_backend,
        "warnings": warnings,
        "checks": checks,
        "swept": swept,
        "notes": "local/synced is convenience-not-security; not the public-repo template default (R16)",
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planning store + visibility doctor")
    parser.add_argument("--root", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--no-sweep", action="store_true")
    args = parser.parse_args(argv)
    out = doctor(args.root.resolve(), sweep=not args.no_sweep)
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    run_module_main(main)
