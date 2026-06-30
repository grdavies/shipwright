#!/usr/bin/env python3
"""Freeze + validate quality.* config for deliver runs (PRD 039 R30)."""
from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any
PIN_STATE_KEY = "qualityConfigPin"
FROZEN_KEYS = ("quality.provider", "quality.blockingTier")

def canonical_slice(cfg: dict[str, Any]) -> dict[str, Any]:
    quality = cfg.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    return {"quality": {"provider": quality.get("provider", "none"), "blockingTier": quality.get("blockingTier")}}

def checksum(cfg: dict[str, Any]) -> str:
    blob = json.dumps(canonical_slice(cfg), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

def pin_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return {"checksum": checksum(cfg), "keys": list(FROZEN_KEYS), "slice": canonical_slice(cfg)}

def validate_pin(pin: dict[str, Any] | None, cfg: dict[str, Any]) -> dict[str, Any]:
    if not pin:
        return {"verdict": "pass", "reason": "no-pin"}
    expected = str(pin.get("checksum") or "")
    actual = checksum(cfg)
    if expected and expected != actual:
        return {"verdict": "fail", "reason": "quality-config-mutation", "expected": expected, "actual": actual, "frozenKeys": list(FROZEN_KEYS)}
    return {"verdict": "pass", "checksum": actual}

def load_pin_from_deliver_state(root: Path) -> dict[str, Any] | None:
    cursor = root / ".cursor"
    if not cursor.is_dir():
        return None
    for path in sorted(cursor.glob("sw-deliver-state*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("migrated"):
            scoped = data.get("scopedPath")
            if isinstance(scoped, str):
                sp = root / scoped
                if sp.is_file():
                    try:
                        data = json.loads(sp.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        continue
        pin = data.get(PIN_STATE_KEY)
        if isinstance(pin, dict) and data.get("verdict") == "running":
            return pin
    return None
