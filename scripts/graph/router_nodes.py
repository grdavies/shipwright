#!/usr/bin/env python3
"""First-class router decisions with durable, idempotent events."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class RouteDecision:
    router_id: str
    input_hash: str
    selected_route: str
    rule_version: str
    classifier_model: str
    confidence: float
    overrides: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.router_id):
            raise ValueError("invalid router id")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("route confidence must be between zero and one")

    def as_event(self) -> dict[str, Any]:
        value = asdict(self)
        return {
            "routerId": value["router_id"],
            "inputHash": value["input_hash"],
            "selectedRoute": value["selected_route"],
            "ruleVersion": value["rule_version"],
            "classifierModel": value["classifier_model"],
            "confidence": value["confidence"],
            "overrides": list(value["overrides"]),
        }


def hash_route_input(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RouteDecisionJournal:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, event_id: str, decision: RouteDecision) -> dict[str, Any]:
        if not _SAFE_ID.fullmatch(event_id):
            raise ValueError("invalid route event id")
        path = self.root / f"{event_id}.json"
        event = {"eventId": event_id, **decision.as_event()}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != event:
                raise ValueError("route event id already records another decision")
            return existing
        fd, temporary_name = tempfile.mkstemp(prefix=f".{event_id}.", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(event, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return event

    def read(self, event_id: str) -> dict[str, Any]:
        path = self.root / f"{event_id}.json"
        if not path.is_file():
            raise KeyError(event_id)
        return json.loads(path.read_text(encoding="utf-8"))
