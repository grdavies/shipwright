"""Semantic near-duplicate detection helpers (PRD 064 R24/R25)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import planning_index_gen as pig
import planning_paths as pp

TOKEN_RE = re.compile(r"[a-z0-9]+")
PROBLEM_SECTION = re.compile(r"^##\s+Problem\s*$", re.MULTILINE | re.IGNORECASE)

TERMINAL_GAP_STATUSES = frozenset({"resolved", "superseded"})
OPEN_GAP_STATUSES = frozenset({"open", "scheduled", ""})

DEFAULT_NEAR_DUPLICATE: dict[str, Any] = {
    "enabled": True,
    "highThreshold": 0.85,
    "softThreshold": 0.65,
    "featureDim": 256,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_workflow_config(root: Path) -> dict[str, Any]:
    root = root.resolve()
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def resolve_near_duplicate_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_NEAR_DUPLICATE)
    gap = (cfg or {}).get("gapCheck") if isinstance(cfg, dict) else None
    near = gap.get("nearDuplicate") if isinstance(gap, dict) else None
    if isinstance(near, dict):
        if "enabled" in near:
            merged["enabled"] = bool(near.get("enabled"))
        if near.get("highThreshold") is not None:
            merged["highThreshold"] = float(near["highThreshold"])
        if near.get("softThreshold") is not None:
            merged["softThreshold"] = float(near["softThreshold"])
        if near.get("featureDim") is not None:
            merged["featureDim"] = int(near["featureDim"])
    merged["featureDim"] = max(int(merged.get("featureDim") or 256), 32)
    merged["highThreshold"] = min(max(float(merged["highThreshold"]), 0.0), 1.0)
    merged["softThreshold"] = min(max(float(merged["softThreshold"]), 0.0), 1.0)
    if merged["softThreshold"] > merged["highThreshold"]:
        merged["softThreshold"] = merged["highThreshold"]
    return merged


def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall((text or "").lower())


def feature_vector(text: str, *, dim: int = 256) -> dict[int, float]:
    """Deterministic signed feature hashing (stdlib-only, no embeddings)."""
    vec: dict[int, float] = {}
    for token in tokenize(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        h = int.from_bytes(digest[:8], "big")
        idx = h % dim
        sign = 1.0 if (h >> 8) & 1 else -1.0
        vec[idx] = vec.get(idx, 0.0) + sign
    return vec


def cosine_similarity(a: dict[int, float], b: dict[int, float]) -> float:
    if not a or not b:
        return 0.0
    dot = 0.0
    for key, aval in a.items():
        bval = b.get(key)
        if bval is not None:
            dot += aval * bval
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


def combine_title_summary(title: str, summary: str = "") -> str:
    title = (title or "").strip()
    summary = (summary or "").strip()
    if title and summary:
        return f"{title}\n{summary}"
    return title or summary


def extract_gap_summary(root: Path, unit: pig.PlanningUnit) -> str:
    body_path = pp.git_root(root) / unit.body_path
    if not body_path.is_file():
        return ""
    try:
        text = body_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    fm = pig.parse_frontmatter(text)
    if isinstance(fm, dict):
        summary = str(fm.get("summary") or "").strip()
        if summary:
            return summary
    match = PROBLEM_SECTION.search(text)
    if not match:
        return ""
    tail = text[match.end() :].lstrip("\n")
    for line in tail.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


def corpus_item_from_unit(root: Path, unit: pig.PlanningUnit) -> dict[str, Any]:
    summary = extract_gap_summary(root, unit)
    return {
        "unitId": unit.id,
        "title": (unit.title or "").strip(),
        "summary": summary,
        "status": (unit.status or "open").strip() or "open",
        "text": combine_title_summary(unit.title or "", summary),
    }


def load_gap_corpus(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for unit in pig.discover_units(root):
        if unit.type != "gap":
            continue
        title = (unit.title or "").strip()
        if not title:
            continue
        items.append(corpus_item_from_unit(root, unit))
    return items


def classify_match_tier(
    similarity: float,
    status: str,
    config: dict[str, Any],
) -> str | None:
    normalized = (status or "open").strip().lower() or "open"
    high = float(config.get("highThreshold") or DEFAULT_NEAR_DUPLICATE["highThreshold"])
    soft = float(config.get("softThreshold") or DEFAULT_NEAR_DUPLICATE["softThreshold"])
    if normalized in TERMINAL_GAP_STATUSES and similarity >= high:
        return "high-terminal"
    if normalized in OPEN_GAP_STATUSES and similarity >= soft:
        return "soft-open"
    return None


def scan_candidate(
    candidate_text: str,
    corpus: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Two-tier flag-for-review scan; never auto-suppress (KD5)."""
    cfg = config or dict(DEFAULT_NEAR_DUPLICATE)
    dim = int(cfg.get("featureDim") or DEFAULT_NEAR_DUPLICATE["featureDim"])
    text = (candidate_text or "").strip()
    if not text:
        return {
            "verdict": "clear",
            "autoSuppress": False,
            "matches": [],
            "candidateText": "",
            "scannedAt": utc_now(),
        }
    cand_vec = feature_vector(text, dim=dim)
    matches: list[dict[str, Any]] = []
    for item in corpus:
        item_text = str(item.get("text") or combine_title_summary(item.get("title", ""), item.get("summary", "")))
        if not item_text.strip():
            continue
        similarity = cosine_similarity(cand_vec, feature_vector(item_text, dim=dim))
        tier = classify_match_tier(similarity, str(item.get("status") or "open"), cfg)
        if not tier:
            continue
        matches.append(
            {
                "unitId": item.get("unitId"),
                "title": item.get("title"),
                "status": item.get("status"),
                "similarity": round(similarity, 6),
                "tier": tier,
                "flagForReview": True,
            }
        )
    matches.sort(key=lambda row: (-float(row.get("similarity") or 0.0), str(row.get("unitId") or "")))
    return {
        "verdict": "flag-for-review" if matches else "clear",
        "autoSuppress": False,
        "matches": matches,
        "candidateText": text,
        "thresholds": {
            "high": cfg.get("highThreshold"),
            "soft": cfg.get("softThreshold"),
        },
        "scannedAt": utc_now(),
    }


def format_handoff_summary(scan: dict[str, Any]) -> str:
    """Human-confirm handoff block for gap-check / brainstorm intake."""
    matches = scan.get("matches") or []
    if not matches:
        return "Near-duplicate scan: no semantic matches flagged."
    lines = [
        "Near-duplicate scan (flag-for-review only — never auto-suppress):",
        f"Candidate: {scan.get('candidateText', '')[:240]}",
        "Matches:",
    ]
    for match in matches:
        lines.append(
            "- {unitId} ({status}) similarity={similarity:.3f} tier={tier} — confirm before capture/proceed".format(
                unitId=match.get("unitId"),
                status=match.get("status"),
                similarity=float(match.get("similarity") or 0.0),
                tier=match.get("tier"),
            )
        )
    lines.append("Action: human must confirm whether to proceed, merge, or defer.")
    return "\n".join(lines)


def persist_scan(path: Path, scan: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
