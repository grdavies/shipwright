#!/usr/bin/env python3
"""Shared PRD 056 union loader + no-restatement gate (PRD 057 R22).

Loads the authoritative PRD 056 union from the issue store (issue #218 in the
`grdavies/planning` project) and detects when a new requirement restates PRD 056
union R1-R20 text instead of referencing it by id.

The store fetch degrades to skip-with-advisory (green) when the effective backend
is not an issue-store or the store token is absent, so file-store / offline-CI
runs stay deterministically green (R30). A local `--union-056-source` override
lets fixtures exercise the restatement comparison without live store access.
"""
from __future__ import annotations

import contextlib
import difflib
import io
import re
from pathlib import Path
from typing import Any

import doc_format

UNION_056_UNIT_ID = "056-prd-issue-store-deliver-progress-native-links"
UNION_056_BODY_PATH = (
    "docs/prds/056-issue-store-deliver-progress-native-links/"
    "056-prd-issue-store-deliver-progress-native-links.md"
)
UNION_056_ISSUE = 218
UNION_056_MAX_RID = 20
RESTATEMENT_RATIO = 0.90

_BOILERPLATE = re.compile(r"\(blocker\)|\(gap-[0-9a-z;.\s-]+\)", re.I)
_MARKUP = re.compile(r"[`*_]+")
_WS = re.compile(r"\s+")


def normalize_requirement_text(text: str) -> str:
    lowered = text.lower()
    lowered = _BOILERPLATE.sub(" ", lowered)
    lowered = _MARKUP.sub("", lowered)
    lowered = _WS.sub(" ", lowered)
    return lowered.strip()


def extract_requirements(text: str) -> list[dict[str, str]]:
    return [{"id": rid, "text": body} for rid, body in doc_format.extract_rd_bullets(text)]


def _rid_in_range(rid: str, max_rid: int) -> bool:
    key = doc_format.id_sort_key(rid)
    return key[0] == "R" and isinstance(key[1], int) and 1 <= key[1] <= max_rid


def _skip(reason: str) -> dict[str, Any]:
    return {"status": "skipped", "reason": reason, "requirements": []}


def load_056_union(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    source: str | None = None,
    max_rid: int = UNION_056_MAX_RID,
) -> dict[str, Any]:
    """Return the PRD 056 union R1-R{max_rid} requirements or a skip advisory."""
    if source:
        candidate = Path(source)
        if not candidate.is_absolute():
            candidate = root / source
        if not candidate.is_file():
            return _skip(f"source-not-found:{source}")
        reqs = extract_requirements(candidate.read_text(encoding="utf-8"))
        scoped = [r for r in reqs if _rid_in_range(r["id"], max_rid)]
        return {"status": "loaded", "source": f"file:{source}", "requirements": scoped}

    try:
        import planning_store
    except Exception:  # pragma: no cover - import guarded for offline determinism
        return _skip("store-module-unavailable")

    resolved_cfg = cfg if cfg is not None else planning_store.load_workflow_config(root)
    effective = planning_store.resolve_effective_backend(root, resolved_cfg)
    if effective.get("effective") != "issue-store":
        return _skip("backend-not-issue-store")

    provider = planning_store.resolve_issues_provider(resolved_cfg).get("provider", "")
    token_env = planning_store.resolve_issues_token_env(resolved_cfg, provider)
    if not token_env or not planning_store.token_present(token_env):
        return _skip("store-token-absent")

    # The store `get` primitive is side-effecting: on integrity/reachability
    # failures it prints a verdict to stdout and raises SystemExit via
    # planning_store.fail(). Isolate stdout and catch SystemExit so a cross-cutting
    # advisory gate never hard-fails or corrupts the caller's JSON on store infra
    # problems — degrade to skip-with-advisory instead (R30 posture).
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            backend = planning_store.get_backend(root, resolved_cfg)
            result = backend.get(UNION_056_UNIT_ID, UNION_056_BODY_PATH)
    except SystemExit:
        return _skip("store-read-failed")
    except Exception:
        return _skip("store-unreachable")

    if getattr(result, "verdict", None) != "ok" or not getattr(result, "content", None):
        return _skip(f"store-{getattr(result, 'verdict', 'error')}")

    reqs = extract_requirements(result.content)
    scoped = [r for r in reqs if _rid_in_range(r["id"], max_rid)]
    return {
        "status": "loaded",
        "source": f"issue-store#{UNION_056_ISSUE}",
        "issue": UNION_056_ISSUE,
        "requirements": scoped,
    }


def check_no_restatement(
    new_reqs: list[dict[str, str]],
    union_056: list[dict[str, str]],
    *,
    ratio: float = RESTATEMENT_RATIO,
) -> list[dict[str, Any]]:
    """Flag new requirements whose text closely restates a PRD 056 union entry."""
    norm_056 = [(r["id"], normalize_requirement_text(r["text"])) for r in union_056]
    norm_056 = [(rid, txt) for rid, txt in norm_056 if txt]
    findings: list[dict[str, Any]] = []
    for req in new_reqs:
        candidate = normalize_requirement_text(req.get("text", ""))
        if not candidate:
            continue
        best_id: str | None = None
        best_ratio = 0.0
        for old_id, old_text in norm_056:
            score = difflib.SequenceMatcher(None, candidate, old_text).ratio()
            if score > best_ratio:
                best_ratio = score
                best_id = old_id
        if best_id is not None and best_ratio >= ratio:
            findings.append(
                {
                    "newId": req.get("id"),
                    "restates056Id": best_id,
                    "ratio": round(best_ratio, 4),
                }
            )
    return findings


def evaluate(
    new_reqs: list[dict[str, str]],
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    source: str | None = None,
    ratio: float = RESTATEMENT_RATIO,
) -> dict[str, Any]:
    """Load the 056 union and run the no-restatement gate against ``new_reqs``."""
    union = load_056_union(root, cfg, source=source)
    if union["status"] == "skipped":
        return {
            "verdict": "skipped",
            "advisory": True,
            "reason": union["reason"],
            "union056Source": None,
            "restatements": [],
        }
    findings = check_no_restatement(new_reqs, union["requirements"], ratio=ratio)
    return {
        "verdict": "restated" if findings else "pass",
        "advisory": False,
        "union056Source": union.get("source"),
        "union056Count": len(union["requirements"]),
        "restatements": findings,
    }
