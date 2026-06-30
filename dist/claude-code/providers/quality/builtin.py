#!/usr/bin/env python3
"""Built-in quality harness — primary-language churn + complexity proxy (PRD 039 R6)."""
from __future__ import annotations
import json, os, re, subprocess, sys
from collections import Counter
from pathlib import Path

EXT_LANG = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript", ".go": "go", ".rs": "rust"}

def detect_language(files: list[str]) -> str | None:
    counts: Counter[str] = Counter()
    for f in files:
        ext = Path(f).suffix.lower()
        lang = EXT_LANG.get(ext)
        if lang:
            counts[lang] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]

def diff_churn(root: Path, files: list[str]) -> int:
    total = 0
    for f in files:
        proc = subprocess.run(["git", "-C", str(root), "diff", "--numstat", "--", f], capture_output=True, text=True)
        for line in (proc.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                total += int(parts[0]) + int(parts[1])
    return total

def complexity_proxy(root: Path, files: list[str], lang: str) -> float:
    if lang != "python":
        return 0.0
    score = 0.0
    for f in files:
        if not f.endswith(".py"):
            continue
        p = root / f
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        score += len(re.findall(r"\b(if|for|while|elif|except)\b", text)) * 0.1
    return round(score, 3)

def main() -> int:
    root = Path(os.environ.get("SW_QUALITY_ROOT", ".")).resolve()
    raw = os.environ.get("SW_CHANGED_FILES", "")
    files = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    lang = detect_language(files)
    if not lang:
        print(json.dumps({"verdict": "none", "provider": "builtin", "skipped": True, "reason": "unresolved primary language"}))
        return 0
    churn = diff_churn(root, files) if files else 0
    complexity = complexity_proxy(root, files, lang)
    metrics = {"coupling": "unavailable", "cohesion": "unavailable", "complexity": complexity, "churn": churn}
    metric_delta = dict(metrics)
    verdict = "clean" if churn < 20 and complexity < 1.0 else ("advise" if churn < 80 else "poor")
    hints = []
    if verdict != "clean":
        hints.append(f"review structural churn ({churn} lines) in {lang} touched files")
    print(json.dumps({
        "verdict": verdict,
        "provider": "builtin",
        "language": lang,
        "metrics": metrics,
        "metricDelta": metric_delta,
        "perFile": [],
        "refactorHints": hints,
    }))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
