#!/usr/bin/env python3
"""Health check: stale pre-port layout + Python floor + tokenEnv deprecation (R34/R2)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from _sw.cli import build_parser, run_module_main
from _sw.interpreter import probe

SHELL_SUFFIXES = {".sh", ".bash", ".ps1"}
HOOK_NAMES = ("pre-commit", "pre-push", "commit-msg")
TOKENENV_MIGRATE_REMEDIATION = (
    "python3 scripts/sw-configure.py credential migrate"
)
PROFILE_REFRESH_REMEDIATION = "python3 scripts/doctor.py profile-refresh --confirm"


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_workflow_config_path(target: Path) -> Path | None:
    from shipwright_paths import workflow_config_path

    return workflow_config_path(target)


def _append_tokenenv_deprecations(
    root: Path,
    issues: list[str],
    remediation: list[str],
) -> None:
    """Surface tokenEnv-alias bindings via the credential config surface (PRD 087 R2)."""
    try:
        from credentials.config_surface import (
            ConfigSurfaceError,
            DeprecationPhase,
            resolve_config_surface,
        )
        from host_lib import load_workflow_config
    except ImportError:  # pragma: no cover - scripts path always present in-repo
        return

    cfg = load_workflow_config(root)
    if not cfg:
        return
    try:
        surface_result = resolve_config_surface(
            cfg,
            deprecation_phase=DeprecationPhase.DEPRECATION,
        )
    except ConfigSurfaceError:
        # Config-surface failures belong to credentials-doctor; skip here.
        return

    for surface in (surface_result.host, surface_result.planning, surface_result.memory):
        if surface.source != "tokenEnv-alias":
            continue
        issues.append(f"tokenenv-deprecation:{surface.surface}")
        remediation.append(TOKENENV_MIGRATE_REMEDIATION)


def profile_completeness_report(target: Path) -> dict[str, Any]:
    """Report curated profile keys that are unset or deprecated (PRD 324 R12)."""
    config_path = resolve_workflow_config_path(target)
    if config_path is None:
        return {
            "verdict": "skip",
            "reason": "no-workflow-config",
            "unset": [],
            "deprecated": [],
            "refreshAvailable": False,
        }

    from init_profile_report import classify_profile, OPERATOR_CHOICE, leaf_get_optional

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        return {
            "verdict": "fail",
            "error": "invalid-workflow-config",
            "unset": [],
            "deprecated": [],
            "refreshAvailable": False,
        }

    report = classify_profile(repo_root(), config=cfg)
    rows = report.get("rows") or []
    unset = [
        row
        for row in rows
        if row.get("tier") == "curated" and row.get("status") == "unset"
    ]
    deprecated = [
        row
        for row in rows
        if row.get("tier") == "curated" and row.get("status") == "deprecated"
    ]
    refreshable = []
    for row in unset:
        rec = row.get("recommended")
        if rec in (OPERATOR_CHOICE, "bundled defaults", None):
            continue
        path_tuple = tuple(str(row.get("path", "")).split("."))
        if leaf_get_optional(cfg, path_tuple) is not None:
            continue
        refreshable.append(row)

    verdict = "pass"
    if unset or deprecated:
        verdict = "warn"
    return {
        "verdict": verdict,
        "configPath": config_path.relative_to(target).as_posix(),
        "unset": unset,
        "deprecated": deprecated,
        "refreshAvailable": bool(refreshable),
        "refreshablePaths": [row.get("path") for row in refreshable],
    }


def profile_refresh(target: Path, *, confirm: bool) -> dict[str, Any]:
    """Consent-gated refresh — fills unset curated keys only; never overwrites operator values."""
    config_path = resolve_workflow_config_path(target)
    if config_path is None:
        return {"verdict": "fail", "error": "no-workflow-config"}

    report = profile_completeness_report(target)
    if not confirm:
        return {
            "verdict": "confirm-required",
            "unset": report.get("unset", []),
            "deprecated": report.get("deprecated", []),
            "refreshablePaths": report.get("refreshablePaths", []),
            "hint": (
                "profile refresh writes only unset curated keys; "
                "operator-set and deprecated values are never overwritten"
            ),
            "remediation": PROFILE_REFRESH_REMEDIATION,
        }

    from init_profile_report import OPERATOR_CHOICE, leaf_get_optional

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(cfg, dict):
        return {"verdict": "fail", "error": "invalid-workflow-config"}

    applied: list[str] = []
    for row in report.get("unset", []):
        rec = row.get("recommended")
        if rec in (OPERATOR_CHOICE, "bundled defaults", None):
            continue
        path_tuple = tuple(str(row.get("path", "")).split("."))
        if leaf_get_optional(cfg, path_tuple) is not None:
            continue
        _set_nested(cfg, path_tuple, rec)
        applied.append(str(row.get("path")))

    if not applied:
        return {
            "verdict": "pass",
            "written": False,
            "reason": "nothing-to-refresh",
            "applied": [],
        }

    config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return {
        "verdict": "pass",
        "written": True,
        "applied": applied,
        "configPath": config_path.relative_to(target).as_posix(),
    }


def _set_nested(doc: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cur: dict[str, Any] = doc
    for key in path[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[path[-1]] = value


def _append_profile_completeness(
    target: Path,
    issues: list[str],
    remediation: list[str],
) -> None:
    report = profile_completeness_report(target)
    if report.get("verdict") == "skip":
        return
    for row in report.get("unset", []):
        path = row.get("path")
        if path:
            issues.append(f"profile-unset:{path}")
    for row in report.get("deprecated", []):
        path = row.get("path")
        if path:
            issues.append(f"profile-deprecated:{path}")
    if report.get("refreshAvailable"):
        remediation.append(PROFILE_REFRESH_REMEDIATION)


STATE_ROOT_MIGRATE_REMEDIATION = (
    "python3 scripts/doctor.py state-root-migrate --confirm"
)


def legacy_layout_report(target: Path) -> dict[str, Any]:
    """Detect legacy .cursor/.sw state-root layout and surface stale fences (R6/R13)."""
    import state_root_migrate as srm

    try:
        detection = srm.detect_legacy_layout(target)
    except srm.StateRootMigrateError as exc:
        # Inventory may be absent in fixture repos; doctor must stay functional (R13).
        if exc.code in {"inventory-missing", "inventory-unreadable", "inventory-malformed"}:
            return {
                "verdict": "pass",
                "legacyPresent": False,
                "moves": [],
                "moveCount": 0,
                "staleFence": None,
                "remediation": None,
                "skipped": True,
                "skipReason": exc.code,
            }
        raise
    fence = detection.get("staleFence")
    moves = detection.get("moves") or []
    return {
        "verdict": "warn" if moves or fence else "pass",
        "legacyPresent": bool(detection.get("legacyPresent")),
        "moves": moves,
        "moveCount": detection.get("moveCount", len(moves)),
        "staleFence": fence,
        "remediation": STATE_ROOT_MIGRATE_REMEDIATION if moves or fence else None,
    }


def state_root_migrate_consent(
    target: Path,
    *,
    confirm: bool,
    plugin_root: Path | None = None,
) -> dict[str, Any]:
    """Consent gate enumerating every move; decline leaves legacy paths functional (R13)."""
    import state_root_migrate as srm

    try:
        # Skew refusal must precede the consent gate (R54).
        result = srm.relocate(
            target,
            confirm=confirm,
            plugin_root=plugin_root,
            holder=f"doctor-state-root-migrate:{os.getpid()}",
        )
    except srm.StateRootMigrateError as exc:
        payload = exc.as_dict()
        payload["consentOffered"] = False
        return payload

    if result.get("verdict") == "confirm-required":
        return {
            **result,
            "consentOffered": True,
            "hint": (
                "Review the enumerated moves. Declining (omit --confirm) leaves the "
                "repository fully functional on legacy paths. Pass --confirm to relocate."
            ),
            "remediation": STATE_ROOT_MIGRATE_REMEDIATION,
        }
    return {**result, "consentOffered": True}



TEMPLATE_OVERRIDE_DRIFT_REMEDIATION = (
    "Review .shipwright/templates overrides against updated core defaults; "
    "refresh baselines with python3 -c "
    "\"from template_resolve import record_core_baselines; "
    "record_core_baselines(__import__('pathlib').Path('.'))\" "
    "after intentionally accepting the new core, or update the override."
)


def _append_template_override_drift(
    root: Path,
    issues: list[str],
    remediation: list[str],
) -> None:
    """Surface overrides that shadow a core template whose default changed (R41)."""
    try:
        from template_resolve import diagnose_override_drift
    except ImportError:  # pragma: no cover
        return
    findings = diagnose_override_drift(root)
    for finding in findings:
        rel = finding.get("path") or "unknown"
        issues.append(f"template-override-drift:{rel}")
    if findings and TEMPLATE_OVERRIDE_DRIFT_REMEDIATION not in remediation:
        remediation.append(TEMPLATE_OVERRIDE_DRIFT_REMEDIATION)


def diagnose(root: Path | None = None) -> dict[str, Any]:
    """Run repo-wide doctor checks against ``root`` (defaults to plugin root)."""
    target = root if root is not None else repo_root()
    issues: list[str] = []
    remediation: list[str] = []

    for rel in ("hooks", "core/hooks", "scripts"):
        base = target / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() in SHELL_SUFFIXES and path.is_file():
                issues.append(f"stale-shell:{path.relative_to(target).as_posix()}")
    for hook in HOOK_NAMES:
        py_hook = target / "core" / "hooks" / f"{hook}.py"
        sh_hook = target / "hooks" / f"{hook}.sh"
        if sh_hook.is_file() and not py_hook.is_file():
            issues.append(f"missing-python-hook:{hook}")
            remediation.append("Run: python3 scripts/install.py")

    try:
        result = probe()
        python_ok = result.ok
        python_detail = result.version_text
    except Exception as exc:  # pragma: no cover
        python_ok = False
        python_detail = str(exc)

    if not python_ok:
        issues.append(f"python-floor:{python_detail}")
        remediation.append("Install CPython >= 3.9 and ensure python3 is on PATH")

    _append_tokenenv_deprecations(target, issues, remediation)
    _append_profile_completeness(target, issues, remediation)

    layout = legacy_layout_report(target)
    if layout.get("legacyPresent"):
        issues.append(f"legacy-state-root:{layout.get('moveCount', 0)}-moves")
        if layout.get("remediation"):
            remediation.append(layout["remediation"])
    if layout.get("staleFence"):
        issues.append("stale-state-root-migrate-fence")
        remediation.append(
            "python3 scripts/state_root_migrate.py fence-release --root <repo>"
        )

    try:
        from effective_config_gen import check_drift

        if (target / "core/sw-reference/generated/effective-config.json").is_file():
            drift_errors = check_drift(target)
            for err in drift_errors:
                issues.append(f"effective-config:{err}")
                remediation.append("python3 scripts/effective_config_gen.py all --write")
    except ImportError:
        pass

    _append_template_override_drift(target, issues, remediation)

    verdict = "pass" if not issues else "warn"
    return {
        "verdict": verdict,
        "issues": issues,
        "remediation": remediation,
        "python": python_detail,
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="doctor",
        description="Detect stale layout, Python floor, tokenEnv deprecation, and profile completeness.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root to diagnose (default: plugin/repo root)",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("diagnose", help="Run full doctor checks (default)")
    sub.add_parser("profile-check", help="Profile completeness report only")
    refresh_p = sub.add_parser("profile-refresh", help="Consent-gated curated profile refresh")
    refresh_p.add_argument(
        "--confirm",
        action="store_true",
        help="Apply refresh for unset curated keys only",
    )
    sub.add_parser("legacy-layout", help="Report legacy state-root layout and proposed moves")
    migrate_p = sub.add_parser(
        "state-root-migrate",
        help="Consent-gated state-root relocation (enumerates moves; requires --confirm)",
    )
    migrate_p.add_argument(
        "--confirm",
        action="store_true",
        help="Consent to relocate after reviewing the enumerated move set",
    )
    migrate_p.add_argument(
        "--plugin-root",
        default=None,
        help="Installed plugin root for redirect-map skew comparison",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else repo_root()
    command = args.command or "diagnose"

    if command == "profile-check":
        out = profile_completeness_report(root)
        print(json.dumps(out, indent=2))
        return 0 if out.get("verdict") in ("pass", "skip") else 1

    if command == "profile-refresh":
        out = profile_refresh(root, confirm=bool(args.confirm))
        print(json.dumps(out, indent=2))
        if out.get("verdict") == "confirm-required":
            return 1
        return 0 if out.get("verdict") == "pass" else 1

    if command == "legacy-layout":
        out = legacy_layout_report(root)
        print(json.dumps(out, indent=2))
        return 0 if out.get("verdict") == "pass" else 1

    if command == "state-root-migrate":
        plugin_root = Path(args.plugin_root).resolve() if getattr(args, "plugin_root", None) else None
        out = state_root_migrate_consent(
            root,
            confirm=bool(args.confirm),
            plugin_root=plugin_root,
        )
        print(json.dumps(out, indent=2))
        if out.get("verdict") in ("pass",):
            return 0
        return 1

    out = diagnose(root)
    print(json.dumps(out, indent=2))
    return 0 if out["verdict"] == "pass" else 1


if __name__ == "__main__":
    run_module_main(main)
