"""Idempotent COMPLETION-LOG writer (PRD 042 R20)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _refuse_banned_living_doc_write(root: Path, *, action: str) -> dict[str, Any] | None:
    scripts = Path(__file__).resolve().parents[1]
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from planning_store import refuse_banned_living_doc_write

    return refuse_banned_living_doc_write(root, action=action)


def append_log_idempotent(root: Path, *, prd: str, phase: str, notes: str = "", pr: str = "", sha: str = "") -> dict[str, Any]:
    refusal = _refuse_banned_living_doc_write(root, action="append-log-idempotent")
    if refusal:
        return refusal
    prd = prd.zfill(3)
    log = root / "docs" / "prds" / "COMPLETION-LOG.md"
    text = log.read_text(encoding="utf-8")
    id_key = f"| {prd} | {phase} |"
    sha_key = sha[:7] if sha else ""
    if id_key in text and (not sha_key or sha_key in text):
        return {"verdict": "pass", "action": "append-log-idempotent", "skipped": True, "reason": "already-present"}
    date_s = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    detail_parts = [notes or "deliver complete"]
    if pr: detail_parts.append(f"PR #{pr}")
    if sha: detail_parts.append(f"SHA {sha[:7]}")
    detail = "; ".join(p for p in detail_parts if p)
    line = f"| {date_s} | {prd} | {phase} | {detail} |"
    if "_No entries yet._" in text:
        text = text.replace("_No entries yet._\n", "")
    marker = "| Date | PRD | Phase | Notes |"
    idx = text.find(marker)
    if idx == -1:
        raise SystemExit("COMPLETION-LOG header missing")
    insert_at = text.find("\n", idx) + 1
    insert_at = text.find("\n", insert_at) + 1
    text = text[:insert_at] + line + "\n" + text[insert_at:]
    log.write_text(text, encoding="utf-8")
    return {"verdict": "pass", "action": "append-log-idempotent", "appended": True, "line": line}
