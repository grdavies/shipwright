#!/usr/bin/env python3
"""Pre-push secret scan chokepoint (R41/R50/R51). Fail-closed on scanner error."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def main() -> int:
    git_root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    if len(sys.argv) > 1 and sys.argv[1] == "inflight-tuple":
        from inflight_signal import main as inflight_main
        sys.argv = [sys.argv[0], str(git_root), "validate", *sys.argv[2:]]
        return inflight_main()
    from secret_scan import main as scan_main
    return scan_main()

if __name__ == "__main__":
    raise SystemExit(main())
