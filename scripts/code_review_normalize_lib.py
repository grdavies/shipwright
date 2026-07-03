#!/usr/bin/env python3
"""Normalize complete ce-code-review payloads (requirement filter + verdict map)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_VERDICT_MAP = {
    "ready to merge": "ready",
    "ready with fixes": "ready-with-fixes",
    "not ready": "not-ready",
}


def _map_verdict(raw: str) -> str:
    key = (raw or "").strip().lower()
    return _VERDICT_MAP.get(key, "not-ready")


def _is_requirement_stage(title: str) -> bool:
    t = title or ""
    return bool(re.search(r"requirement", t, re.I))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--repo-root", default=str(Path.cwd()))
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    data = json.loads(Path(ns.input).read_text(encoding="utf-8"))
    findings_in = data.get("findings") or []
    findings_out = []
    for item in findings_in:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "")
        if _is_requirement_stage(title):
            continue
        findings_out.append(item)
    out = {
        "status": "complete",
        "verdict": _map_verdict(str(data.get("verdict") or "")),
        "findings": findings_out,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
