#!/usr/bin/env python3
"""Python helper to invoke host verbs via scripts/host.sh (PRD 026 Phase 2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


def host_verb(root: Path, verb: str, **kwargs: Any) -> dict[str, Any]:
    cmd = ["bash", str(SCRIPT_DIR / "host.sh"), "--root", str(root.resolve()), verb]
    for key, val in kwargs.items():
        if val is None:
            continue
        cmd.extend([f"--{key}", str(val)])
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    raw = proc.stdout.strip() or proc.stderr.strip() or "{}"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"verdict": "fail", "verb": verb, "reason": "invalid-json", "raw": raw}
    payload["_exitCode"] = proc.returncode
    return payload


def host_data(root: Path, verb: str, **kwargs: Any) -> Any:
    out = host_verb(root, verb, **kwargs)
    if out.get("verdict") not in ("ok",):
        return None
    return out.get("data")


def host_ok(root: Path, verb: str, **kwargs: Any) -> bool:
    return host_verb(root, verb, **kwargs).get("verdict") == "ok"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Invoke a host verb")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("verb")
    parser.add_argument("kv", nargs="*", help="pairs: --key value")
    args = parser.parse_args()
    kwargs: dict[str, Any] = {}
    kv = args.kv
    i = 0
    while i < len(kv):
        if kv[i].startswith("--") and i + 1 < len(kv):
            kwargs[kv[i][2:]] = kv[i + 1]
            i += 2
        else:
            i += 1
    print(json.dumps(host_verb(args.root, args.verb, **kwargs), indent=2))
