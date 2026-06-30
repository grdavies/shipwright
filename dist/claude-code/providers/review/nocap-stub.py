#!/usr/bin/env python3
"""Gate-incompatible stub: declares no per-head-state capability."""
from __future__ import annotations
import json

def main() -> int:
    print(json.dumps({
        "capabilities": {"perHeadState": False},
        "perHeadState": "in-flight",
        "perHeadLanded": False,
        "reviewedHead": None,
        "statusContext": "absent",
        "inProgressMarker": False,
        "skipped": False,
        "minutesSinceHeadPush": 0,
    }))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
