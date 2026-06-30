#!/usr/bin/env python3
"""Opt-in baseline capture for verification-gate attribution."""
from __future__ import annotations
import argparse, json, os, sys, tempfile
from pathlib import Path
from _sw.cli import run_module_main
import evidence_read as er

def copy_baseline(src: Path, dst: Path) -> int:
    if not src.is_file():
        print(f"source missing: {src}", file=sys.stderr); return 1
    try: er.safe_json_load(src)
    except (PermissionError, json.JSONDecodeError):
        print(f"source invalid JSON: {src}", file=sys.stderr); return 1
    data = er.safe_json_load(src)
    fd, tmp = tempfile.mkstemp(prefix=dst.name, dir=str(dst.parent))
    os.close(fd); tmp_p = Path(tmp); tmp_p.chmod(0o600)
    tmp_p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp_p.replace(dst); dst.chmod(0o600); return 0

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("capture", nargs="?")
    p.add_argument("--from", dest="from_"); p.add_argument("--to")
    p.add_argument("--gate-from"); p.add_argument("--gate-to")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not ns.from_ or not ns.to:
        print("Usage: verify-baseline capture --from STATUS --to BASELINE", file=sys.stderr); return 2
    rc = copy_baseline(Path(ns.from_), Path(ns.to))
    if rc: return rc
    if ns.gate_from or ns.gate_to:
        if not (ns.gate_from and ns.gate_to):
            print("both --gate-from and --gate-to required together", file=sys.stderr); return 2
        return copy_baseline(Path(ns.gate_from), Path(ns.gate_to))
    return 0
if __name__ == "__main__": run_module_main(main)
