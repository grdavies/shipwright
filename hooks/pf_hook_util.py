"""Compatibility shim — canonical implementation lives in core/hooks/."""

from __future__ import annotations

import sys
from pathlib import Path

_CORE = Path(__file__).resolve().parent.parent / "core" / "hooks"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from pf_hook_util import *  # noqa: F403
