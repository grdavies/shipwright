"""Codex lifecycle handler — processes stdin when registered events fire (PRD 352 R5)."""

from __future__ import annotations

import json
import sys

from hook_adapter import before_task_dispatch_stdio


def main(argv: list[str] | None = None) -> int:
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            raise ValueError("hook input must be an object")
        event = payload.get("hook_event_name") or payload.get("event")
        if not event and argv:
            event = argv[0]
        if not isinstance(event, str):
            raise ValueError("hook event is missing")
        event = "".join(c for c in event.lower() if c.isalnum())
        if event == "pretooluse":
            return before_task_dispatch_stdio(payload)
        if event not in {
            "sessionstart", "userpromptsubmit", "posttooluse", "stop",
            "subagentstart", "subagentstop",
        }:
            raise ValueError("unsupported hook event")
        # These events have no Codex policy action yet. Acknowledge the consumed
        # payload without running pre-tool checks or consuming dispatch records.
        print(json.dumps({}))
        return 0
    except (OSError, ValueError, TypeError):
        print("Shipwright Codex hook: invalid event payload", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
