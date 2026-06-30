#!/usr/bin/env python3
"""Single per-repo configurator for /sw-init (PRD 018 R29/R30/R32). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, subprocess, sys
    from pathlib import Path

    root, out_path, accept, write_verify, sw_ver, sch_ver = sys.argv[1:7]
    accept = accept == "1"
    write_verify = write_verify == "1"

    detect = json.loads(subprocess.check_output(
        ["bash", str(Path(root)/"scripts/detect-project-type.py"), "--root", root, "--propose"],
        text=True,
    ))

    draft = {
        "doc": {"afterTasks": "confirm"},
        "delegation": {"mode": "bind-only"},
        "orchestration": {"planPolicy": "canonical"},
        "deliver": {"autonomy": {"mode": "autonomous", "maxRunMinutes": 1440, "maxIterations": 500}},
        "compound": {"autonomy": "supervised"},
        "guardrails": {"enforceBeforeSubmit": True, "requireRuleClass": False},
        "review": {"provider": "none"},
        "memory": {"provider": "in-repo", "sourceOfTruth": "auto"},
        "planning": {
            "store": {"backend": "in-repo-public"},
        },
        "configuredWith": {"shipwrightVersion": sw_ver, "schemaVersion": sch_ver},
    }

    comm_defaults_path = Path(root) / "core/sw-reference/communication-routing.defaults.json"
    if comm_defaults_path.is_file():
        try:
            comm_defaults = json.loads(comm_defaults_path.read_text(encoding="utf-8"))
            if isinstance(comm_defaults, dict):
                draft["communication"] = comm_defaults
        except json.JSONDecodeError:
            pass

    if accept:
        draft["verifyGaps"] = detect.get("verifyGaps") or []
        draft["projectTypeDetection"] = {"matches": detect.get("matches", []), "ambiguous": detect.get("ambiguous", False)}
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

if __name__ == "__main__":
    run_module_main(main)
