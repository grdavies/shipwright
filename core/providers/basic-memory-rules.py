#!/usr/bin/env python3
"""Basic Memory out-of-band rule-fetcher for hooks (PRD 075).

Emits JSON rules to stdout for guardrail injection. Agent-session ops use Basic Memory
MCP; this script is the hook transport only (catalog ``hookTransport.ruleFetch:
out-of-band-script``).

Phase boundary: registration path + non-applicable gate live here. Full dual-mode host
gating, rules-folder filter, fixed-argv fetch, and mode-partitioned TTL cache are filled
in by the rules-script transport phase — until then, when ``memory.provider`` is
``basic-memory``, this script fail-closes (empty rules + error) rather than inventing a
silent transport.

Default: non-applicable unless ``memory.provider`` is ``basic-memory``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROVIDER_ID = "basic-memory"
MAX_OUTPUT_BYTES = 64_000


def _emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    text = json.dumps(payload, ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        payload = {
            "ok": False,
            "applicable": payload.get("applicable", True),
            "provider": PROVIDER_ID,
            "rules": [],
            "error": "rules payload exceeds size cap",
        }
        text = json.dumps(payload, ensure_ascii=False)
    print(text)
    return exit_code


def _load_memory_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        memory = data.get("memory")
        return memory if isinstance(memory, dict) else {}
    return {}


def main(argv: list[str] | None = None) -> int:
    _ = argv  # fixed-argv contract — no free-form caller args
    root = Path.cwd()
    memory = _load_memory_config(root)
    provider = str(memory.get("provider") or "").strip()
    if provider != PROVIDER_ID:
        return _emit(
            {
                "ok": True,
                "applicable": False,
                "provider": PROVIDER_ID,
                "rules": [],
                "reason": f"memory.provider is {provider!r}, not {PROVIDER_ID!r}",
            }
        )

    # Fail closed until dual-mode transport is implemented (no silent empty success).
    fail_closed = True
    bm = memory.get("basicMemory")
    if isinstance(bm, dict) and "failClosed" in bm:
        fail_closed = bool(bm.get("failClosed"))

    return _emit(
        {
            "ok": False,
            "applicable": True,
            "provider": PROVIDER_ID,
            "rules": [],
            "failClosed": fail_closed,
            "error": (
                "basic-memory rules transport not yet implemented "
                "(dual-mode fetch pending); failClosed=%s" % fail_closed
            ),
        },
        exit_code=1 if fail_closed else 0,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
