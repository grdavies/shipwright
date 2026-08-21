#!/usr/bin/env python3
"""Health check: stale pre-port layout + Python floor + tokenEnv deprecation (R34/R2)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from _sw.cli import build_parser, run_module_main
from _sw.interpreter import probe

SHELL_SUFFIXES = {".sh", ".bash", ".ps1"}
HOOK_NAMES = ("pre-commit", "pre-push", "commit-msg")
TOKENENV_MIGRATE_REMEDIATION = (
    "python3 scripts/sw-configure.py credential migrate"
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


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

    try:
        from effective_config_gen import check_drift

        drift_errors = check_drift(target)
        for err in drift_errors:
            issues.append(f"effective-config:{err}")
            remediation.append("python3 scripts/effective_config_gen.py all --write")
    except ImportError:
        pass

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
        description="Detect stale layout, Python floor, and tokenEnv deprecation issues.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Repository root to diagnose (default: plugin/repo root)",
    )
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else repo_root()
    out = diagnose(root)
    print(json.dumps(out, indent=2))
    return 0 if out["verdict"] == "pass" else 1


if __name__ == "__main__":
    run_module_main(main)
