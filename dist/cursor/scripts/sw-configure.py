#!/usr/bin/env python3
"""Single per-repo configurator for /sw-init (PRD 018 R29/R30/R32)."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def _plugin_root() -> Path:
    from sw_resolve_plugin_root import resolve_plugin_root

    return Path(resolve_plugin_root(SCRIPT_DIR))


def schema_path(root: Path) -> Path:
    plugin_root = _plugin_root()
    for candidate in (
        root / ".sw/config.schema.json",
        root / "core/sw-reference/config.schema.json",
        plugin_root / "core/sw-reference/config.schema.json",
        Path(os.environ.get("CURSOR_PLUGIN_ROOT", "")) / "core/sw-reference/config.schema.json",
        Path(os.environ.get("CURSOR_PLUGIN_ROOT", "")) / ".sw/config.schema.json",
    ):
        if candidate.is_file():
            return candidate
    return root / ".sw/config.schema.json"


def shipwright_version(root: Path) -> str:
    for candidate in (
        root / "version.txt",
        Path(os.environ.get("CURSOR_PLUGIN_ROOT", "")) / "version.txt",
    ):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8").strip()
    return "unknown"


def schema_version(root: Path) -> str:
    path = schema_path(root)
    if not path.is_file():
        return "unknown"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def cmd_drift_check(root: Path, config: str) -> int:
    config_path = config or str(root / ".cursor/workflow.config.json")
    sw_ver = shipwright_version(root)
    sch_ver = schema_version(root)
    stale = False
    configured: dict = {}
    if config_path and Path(config_path).is_file():
        cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
        configured = cfg.get("configuredWith") or {}
        if configured.get("shipwrightVersion") != sw_ver or configured.get("schemaVersion") != sch_ver:
            stale = True
    print(
        json.dumps(
            {
                "stale": stale,
                "configuredWith": configured,
                "current": {"shipwrightVersion": sw_ver, "schemaVersion": sch_ver},
                "notice": "config may be stale; run /sw-init to refresh" if stale else None,
            },
            indent=2,
        )
    )
    return 0


def cmd_write_draft(root: Path, *, accept: bool, write_verify: bool, config: str) -> int:
    out_path = config or "/tmp/sw-init-draft.json"
    detect = json.loads(
        subprocess.check_output(
            [sys.executable, str(SCRIPT_DIR / "detect-project-type.py"), "--root", str(root), "--propose"],
            text=True,
        )
    )
    draft: dict = {
        "doc": {"afterTasks": "confirm"},
        "delegation": {"mode": "bind-only"},
        "orchestration": {"planPolicy": "canonical"},
        "deliver": {"autonomy": {"mode": "autonomous", "maxRunMinutes": 1440, "maxIterations": 500}},
        "compound": {"autonomy": "supervised"},
        "guardrails": {"enforceBeforeSubmit": True, "requireRuleClass": False},
        "review": {"provider": "none"},
        "memory": {"provider": "in-repo", "sourceOfTruth": "auto"},
        "planning": {"store": {"backend": "in-repo-public"}},
        "configuredWith": {
            "shipwrightVersion": shipwright_version(root),
            "schemaVersion": schema_version(root),
        },
    }
    comm_defaults_path = root / "core/sw-reference/communication-routing.defaults.json"
    if comm_defaults_path.is_file():
        try:
            comm_defaults = json.loads(comm_defaults_path.read_text(encoding="utf-8"))
            if isinstance(comm_defaults, dict):
                draft["communication"] = comm_defaults
        except json.JSONDecodeError:
            pass
    if accept:
        draft["verifyGaps"] = detect.get("verifyGaps") or []
        draft["projectTypeDetection"] = {
            "matches": detect.get("matches", []),
            "ambiguous": detect.get("ambiguous", False),
        }
    elif write_verify:
        verify = {}
        for key, meta in (detect.get("proposals") or {}).items():
            if meta.get("safe") and meta.get("command"):
                verify[key] = meta["command"]
        if verify:
            draft["verify"] = verify
    Path(out_path).write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": "pass", "path": out_path, "verifyWritten": bool(draft.get("verify"))}, indent=2))
    return 0


def cmd_portability_check(root: Path, config: str) -> int:
    config_path = config or str(root / ".cursor/workflow.config.json")
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "verify-unconfigured.py"), "--config", config_path or "/nonexistent", "--json"],
        cwd=str(root),
        check=False,
    )
    detect_raw = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "detect-project-type.py"), "--root", str(root), "--propose"],
        capture_output=True,
        text=True,
        cwd=str(root),
    )
    detect = json.loads(detect_raw.stdout or "{}")
    drift = json.loads(
        subprocess.check_output([sys.executable, str(SCRIPT_DIR / "sw-configure.py"), "drift-check", "--config", config_path], text=True)
    )
    host_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "host-doctor.py"), "--root", str(root)],
        cwd=str(root),
        capture_output=True,
    )
    if host_proc.returncode == 0:
        gh = "present"
    elif subprocess.run(["which", "gh"], capture_output=True).returncode == 0:
        gh = "available"
    else:
        gh = "missing"
    lines = []
    if detect.get("verifyGaps"):
        lines.append(f"verify gaps: {', '.join(detect['verifyGaps'])}")
    lines.append(f"gh: {gh}")
    if drift.get("stale"):
        lines.append(drift.get("notice", "config stale"))
    if gh == "missing":
        lines.append("warning: host token missing — set host.tokenEnv for CI-readiness gate")
    print(json.dumps({"summary": lines, "gh": gh, "drift": drift}, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: sw-configure.py detect|schema-version|shipwright-version|"
            "drift-check|portability-check|write-draft",
            file=sys.stderr,
        )
        return 2 if args else 0
    cmd = args[0]
    rest = args[1:]
    root = REPO_ROOT
    config = ""
    accept = False
    write_verify = False
    i = 0
    while i < len(rest):
        token = rest[i]
        if token == "--config" and i + 1 < len(rest):
            config = rest[i + 1]
            i += 2
            continue
        if token == "--accept-defaults":
            accept = True
            i += 1
            continue
        if token == "--write-verify":
            write_verify = True
            i += 1
            continue
        if token == "--propose":
            i += 1
            continue
        i += 1

    if cmd == "detect":
        detect_args = ["--root", str(root)]
        if "--propose" in args:
            detect_args.append("--propose")
        return subprocess.run([sys.executable, str(SCRIPT_DIR / "detect-project-type.py"), *detect_args]).returncode
    if cmd == "schema-version":
        print(schema_version(root))
        return 0
    if cmd == "shipwright-version":
        print(shipwright_version(root))
        return 0
    if cmd == "drift-check":
        return cmd_drift_check(root, config)
    if cmd == "portability-check":
        return cmd_portability_check(root, config)
    if cmd == "write-draft":
        out = config or "/tmp/sw-init-draft.json"
        return cmd_write_draft(root, accept=accept, write_verify=write_verify, config=out)
    print(json.dumps({"verdict": "fail", "error": f"unknown command: {cmd}"}), file=sys.stderr)
    return 2


if __name__ == "__main__":
    run_module_main(main)
