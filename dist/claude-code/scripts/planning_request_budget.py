#!/usr/bin/env python3
"""Shared request-budget ledger for issue-derived views (PRD 046 R81, R93)."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths as pp  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402

LEDGER_STATE_REL = ".cursor/hooks/state/planning-request-budget.json"

DEFAULT_PROVIDER_CEILINGS: dict[str, dict[str, float | int]] = {
    "github-issues": {"maxCalls": 500, "maxPaginationDepth": 10, "alertThreshold": 0.8, "cacheTtlSeconds": 300},
    "gitlab-issues": {"maxCalls": 500, "maxPaginationDepth": 10, "alertThreshold": 0.8, "cacheTtlSeconds": 300},
    "jira": {"maxCalls": 300, "maxPaginationDepth": 5, "alertThreshold": 0.8, "cacheTtlSeconds": 180},
}

SCHEDULER_RESERVE_RATIO = 0.15


class BudgetExhausted(Exception):
    """Fail-closed budget exhaustion (R86)."""


def ledger_path(root: Path) -> Path:
    return pp.git_root(root) / LEDGER_STATE_REL


def _provider_budget_cfg(cfg: dict[str, Any], provider: str) -> dict[str, float | int]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    raw = store.get("requestBudget")
    if isinstance(raw, dict) and provider in raw and isinstance(raw[provider], dict):
        merged = dict(DEFAULT_PROVIDER_CEILINGS.get(provider, DEFAULT_PROVIDER_CEILINGS["github-issues"]))
        merged.update({k: v for k, v in raw[provider].items() if k in merged or k == "cacheTtlSeconds"})
        return merged
    return dict(DEFAULT_PROVIDER_CEILINGS.get(provider, DEFAULT_PROVIDER_CEILINGS["github-issues"]))


def load_ledger(root: Path) -> dict[str, Any]:
    path = ledger_path(root)
    if not path.is_file():
        return {"version": 1, "operations": {}, "alerts": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "operations": {}, "alerts": []}
    return data if isinstance(data, dict) else {"version": 1, "operations": {}, "alerts": []}


def save_ledger(root: Path, ledger: dict[str, Any]) -> None:
    path = ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


@dataclass
class RequestBudgetLedger:
    root: Path
    provider: str
    max_calls: int
    max_pagination_depth: int
    alert_threshold: float
    cache_ttl_seconds: int
    scheduler_reserve: int
    _operations: dict[str, int]

    @classmethod
    def from_config(cls, root: Path, provider: str) -> "RequestBudgetLedger":
        worktree = pp.git_root(root)
        cfg = load_workflow_config(worktree)
        budget = _provider_budget_cfg(cfg, provider)
        max_calls = int(budget.get("maxCalls", 500))
        reserve = max(1, int(max_calls * SCHEDULER_RESERVE_RATIO))
        ledger = load_ledger(root)
        ops = ledger.get("operations")
        if not isinstance(ops, dict):
            ops = {}
        return cls(
            root=root,
            provider=provider,
            max_calls=max_calls,
            max_pagination_depth=int(budget.get("maxPaginationDepth", 10)),
            alert_threshold=float(budget.get("alertThreshold", 0.8)),
            cache_ttl_seconds=int(budget.get("cacheTtlSeconds", 300)),
            scheduler_reserve=reserve,
            _operations={str(k): int(v) for k, v in ops.items()},
        )

    @property
    def total_charged(self) -> int:
        return sum(self._operations.values())

    def bulk_ceiling(self) -> int:
        return max(1, self.max_calls - self.scheduler_reserve)

    def charge(self, operation: str, count: int = 1, *, critical: bool = False) -> None:
        ceiling = self.max_calls if critical else self.bulk_ceiling()
        next_total = self.total_charged + count
        if next_total > ceiling:
            raise BudgetExhausted(
                f"index-incomplete: request budget exhausted ({next_total}/{ceiling} calls)"
            )
        threshold = int(ceiling * self.alert_threshold)
        if next_total >= threshold and self.total_charged < threshold:
            self._record_alert(operation, next_total, ceiling)
        self._operations[operation] = self._operations.get(operation, 0) + count
        self._persist()

    def _record_alert(self, operation: str, charged: int, ceiling: int) -> None:
        ledger = load_ledger(self.root)
        alerts = ledger.get("alerts")
        if not isinstance(alerts, list):
            alerts = []
        alerts.append({"operation": operation, "charged": charged, "ceiling": ceiling, "provider": self.provider})
        ledger["alerts"] = alerts[-20:]
        save_ledger(self.root, ledger)

    def _persist(self) -> None:
        ledger = load_ledger(self.root)
        ledger["operations"] = dict(self._operations)
        ledger["provider"] = self.provider
        ledger["countsOnly"] = True
        save_ledger(self.root, ledger)

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "totalCharged": self.total_charged,
            "bulkCeiling": self.bulk_ceiling(),
            "maxCalls": self.max_calls,
            "schedulerReserve": self.scheduler_reserve,
            "operations": dict(self._operations),
            "alertThreshold": self.alert_threshold,
            "cacheTtlSeconds": self.cache_ttl_seconds,
        }


def cmd_status(root: Path, _args: list[str]) -> None:
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    store = (cfg.get("planning") or {}).get("store") or {}
    provider = str(store.get("issuesProvider", "none"))
    ledger = RequestBudgetLedger.from_config(root, provider)
    print(json.dumps({
        "verdict": "pass",
        "action": "request-budget-status",
        "ledger": ledger.snapshot(),
        "alerts": load_ledger(root).get("alerts", []),
    }, indent=2))


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        print(json.dumps({"verdict": "fail", "error": "usage: planning_request_budget.py <root> status"}))
        raise SystemExit(2)
    root = Path(args[0]).resolve()
    if args[1] == "status":
        cmd_status(root, args[2:])
    else:
        print(json.dumps({"verdict": "fail", "error": f"unknown command: {args[1]}"}))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
