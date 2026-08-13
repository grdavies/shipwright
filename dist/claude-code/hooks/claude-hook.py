#!/usr/bin/env python3
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
sys.path.insert(0, str(_REPO / "platforms" / "claude-code"))
import hook_adapter
if __name__ == "__main__":
    raise SystemExit(hook_adapter.dispatch(_REPO))
