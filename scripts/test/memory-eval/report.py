"""Thresholded regression summary for memory-eval leakage metrics (PRD 082 R33)."""
from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_BASELINE = SCRIPT_DIR / "baseline.json"


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _active_waivers(waivers: list[dict[str, Any]], today: date) -> dict[str, dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    for entry in waivers:
        metric = str(entry.get("metric", "")).strip()
        expires = entry.get("expires")
        if not metric or not isinstance(expires, str):
            continue
        try:
            expiry = _parse_date(expires)
        except ValueError:
            continue
        if expiry >= today:
            active[metric] = entry
    return active


def _threshold_violation(
    metric: str,
    value: float,
    rule: dict[str, Any],
) -> str | None:
    if "max" in rule and value > float(rule["max"]):
        return f"{metric}={value} exceeds max {rule['max']}"
    if "min" in rule and value < float(rule["min"]):
        return f"{metric}={value} below min {rule['min']}"
    return None


def compare_metrics(
    observed: dict[str, float],
    baseline: dict[str, Any],
    *,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    rules = baseline.get("metrics")
    if not isinstance(rules, dict):
        raise ValueError("baseline.metrics must be an object")

    waivers = baseline.get("waivers")
    if waivers is None:
        waivers = []
    if not isinstance(waivers, list):
        raise ValueError("baseline.waivers must be an array")

    active = _active_waivers(waivers, today)
    regressions: list[dict[str, Any]] = []
    waived: list[dict[str, Any]] = []
    passing: list[str] = []

    for metric, rule in sorted(rules.items()):
        if not isinstance(rule, dict):
            continue
        value = float(observed.get(metric, 0.0))
        violation = _threshold_violation(metric, value, rule)
        if violation is None:
            passing.append(metric)
            continue
        if metric in active:
            waived.append(
                {
                    "metric": metric,
                    "violation": violation,
                    "waiver": active[metric],
                }
            )
            continue
        regressions.append(
            {
                "metric": metric,
                "value": value,
                "rule": rule,
                "violation": violation,
                "resolution": "update baseline.json or add a documented waiver with expiry",
            }
        )

    unresolved = bool(regressions)
    return {
        "passing": passing,
        "waived": waived,
        "regressions": regressions,
        "unresolved": unresolved,
        "maintainerActionRequired": unresolved,
        "summary": (
            f"{len(regressions)} unresolved regression(s); "
            f"{len(waived)} waived; {len(passing)} passing"
        ),
    }


def load_baseline(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Memory-eval leakage regression report (PRD 082 R33)")
    parser.add_argument("--metrics-json", required=True, help="JSON object with metric values")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--out", type=Path, help="Optional output path for the report JSON")
    args = parser.parse_args(argv)

    observed = json.loads(args.metrics_json)
    if not isinstance(observed, dict):
        raise SystemExit("metrics-json must be a JSON object")

    report = compare_metrics(observed, load_baseline(args.baseline))
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 1 if report["unresolved"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
