#!/usr/bin/env python3
"""Shared request-budget ledger for issue-derived views (PRD 046 R81, R93; PRD 066 R13)."""

from __future__ import annotations

import json
import os
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
RUN_LEDGER_FILE = "planning-request-budget.json"

DEFAULT_PROVIDER_CEILINGS: dict[str, dict[str, float | int]] = {
    "github-issues": {"maxCalls": 750, "maxPaginationDepth": 10, "alertThreshold": 0.8, "cacheTtlSeconds": 300},
    "gitlab-issues": {"maxCalls": 500, "maxPaginationDepth": 10, "alertThreshold": 0.8, "cacheTtlSeconds": 300},
    "jira": {"maxCalls": 300, "maxPaginationDepth": 5, "alertThreshold": 0.8, "cacheTtlSeconds": 180},
    # PRD 066 R13 — dual budgets: request count + GraphQL complexity points.
    "linear": {
        "maxCalls": 500,
        "maxComplexityPoints": 250000,
        "maxPaginationDepth": 10,
        "alertThreshold": 0.8,
        "cacheTtlSeconds": 180,
    },
}

BUDGET_SCHEMA_VERSION = 2
DEFAULT_QUERY_COMPLEXITY_CAP = 10000
DUAL_BUDGET_PROVIDERS = frozenset({"linear"})

SCHEDULER_RESERVE_RATIO = 0.15


class BudgetExhausted(Exception):
    """Fail-closed budget exhaustion (R86)."""


def ledger_path(root: Path) -> Path:
    repo_root = pp.git_root(root)
    run_dir = (os.environ.get("SW_RUN_DIR") or "").strip()
    if run_dir:
        run_path = Path(run_dir)
        if not run_path.is_absolute():
            run_path = repo_root / run_path
        return run_path / RUN_LEDGER_FILE
    phase_slug = (os.environ.get("SW_PHASE_SLUG") or "").strip()
    if phase_slug:
        return repo_root / ".cursor" / "sw-deliver-runs" / phase_slug / RUN_LEDGER_FILE
    return repo_root / LEDGER_STATE_REL


def _provider_budget_cfg(cfg: dict[str, Any], provider: str) -> dict[str, float | int]:
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    raw = store.get("requestBudget")
    if isinstance(raw, dict) and provider in raw and isinstance(raw[provider], dict):
        merged = dict(DEFAULT_PROVIDER_CEILINGS.get(provider, DEFAULT_PROVIDER_CEILINGS["github-issues"]))
        merged.update({k: v for k, v in raw[provider].items() if k in merged or k in {"cacheTtlSeconds", "maxComplexityPoints"}})
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



def _provider_ledger_slices(ledger: dict[str, Any], provider: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load per-provider ops/complexity; fall back to legacy top-level count-only ops."""
    providers = ledger.get("providers")
    if isinstance(providers, dict) and isinstance(providers.get(provider), dict):
        entry = providers[provider]
        ops = entry.get("operations") if isinstance(entry.get("operations"), dict) else {}
        complexity = entry.get("complexity") if isinstance(entry.get("complexity"), dict) else {}
        return ops, complexity
    # Legacy single-provider ledger (pre-R13 dual-budget schema).
    if ledger.get("provider") in (None, provider) or provider not in DUAL_BUDGET_PROVIDERS:
        ops = ledger.get("operations") if isinstance(ledger.get("operations"), dict) else {}
        complexity = ledger.get("complexity") if isinstance(ledger.get("complexity"), dict) else {}
        return ops, complexity
    return {}, {}

@dataclass
class RequestBudgetLedger:
    root: Path
    provider: str
    max_calls: int
    max_pagination_depth: int
    alert_threshold: float
    cache_ttl_seconds: int
    scheduler_reserve: int
    max_complexity_points: int
    _operations: dict[str, int]
    _complexity: dict[str, int]

    @classmethod
    def from_config(cls, root: Path, provider: str) -> "RequestBudgetLedger":
        worktree = pp.git_root(root)
        cfg = load_workflow_config(worktree)
        budget = _provider_budget_cfg(cfg, provider)
        max_calls = int(budget.get("maxCalls", 500))
        reserve = max(1, int(max_calls * SCHEDULER_RESERVE_RATIO))
        ledger = load_ledger(root)
        ops, complexity = _provider_ledger_slices(ledger, provider)
        return cls(
            root=root,
            provider=provider,
            max_calls=max_calls,
            max_pagination_depth=int(budget.get("maxPaginationDepth", 10)),
            alert_threshold=float(budget.get("alertThreshold", 0.8)),
            cache_ttl_seconds=int(budget.get("cacheTtlSeconds", 300)),
            scheduler_reserve=reserve,
            max_complexity_points=int(budget.get("maxComplexityPoints", 0)),
            _operations={str(k): int(v) for k, v in ops.items()},
            _complexity={str(k): int(v) for k, v in complexity.items()},
        )

    @property
    def dual_budget(self) -> bool:
        return self.provider in DUAL_BUDGET_PROVIDERS or self.max_complexity_points > 0

    @property
    def total_charged(self) -> int:
        return sum(self._operations.values())

    @property
    def total_complexity_charged(self) -> int:
        return sum(self._complexity.values())

    def bulk_ceiling(self) -> int:
        return max(1, self.max_calls - self.scheduler_reserve)

    def complexity_ceiling(self) -> int:
        if self.max_complexity_points <= 0:
            return 0
        reserve = max(1, int(self.max_complexity_points * SCHEDULER_RESERVE_RATIO))
        return max(1, self.max_complexity_points - reserve)

    def charge(self, operation: str, count: int = 1, *, complexity: int = 0, critical: bool = False) -> None:
        ceiling = self.max_calls if critical else self.bulk_ceiling()
        next_total = self.total_charged + count
        if next_total > ceiling:
            raise BudgetExhausted(
                f"index-incomplete: request budget exhausted ({next_total}/{ceiling} calls)"
            )
        if self.dual_budget and complexity:
            c_ceiling = self.max_complexity_points if critical else self.complexity_ceiling()
            next_complexity = self.total_complexity_charged + complexity
            if c_ceiling and next_complexity > c_ceiling:
                raise BudgetExhausted(
                    f"index-incomplete: complexity budget exhausted ({next_complexity}/{c_ceiling} points)"
                )
            threshold_c = int(c_ceiling * self.alert_threshold) if c_ceiling else 0
            if threshold_c and next_complexity >= threshold_c and self.total_complexity_charged < threshold_c:
                self._record_alert(operation, next_complexity, c_ceiling, dimension="complexity")
            self._complexity[operation] = self._complexity.get(operation, 0) + complexity
        threshold = int(ceiling * self.alert_threshold)
        if next_total >= threshold and self.total_charged < threshold:
            self._record_alert(operation, next_total, ceiling, dimension="requests")
        self._operations[operation] = self._operations.get(operation, 0) + count
        self._persist()

    def cache_ttl(self, *, critical: bool = False) -> int:
        """Critical call-sites must bypass TTL cache and revalidate live."""
        return 0 if critical else self.cache_ttl_seconds

    def _record_alert(
        self, operation: str, charged: int, ceiling: int, *, dimension: str = "requests"
    ) -> None:
        ledger = load_ledger(self.root)
        alerts = ledger.get("alerts")
        if not isinstance(alerts, list):
            alerts = []
        alerts.append(
            {
                "operation": operation,
                "charged": charged,
                "ceiling": ceiling,
                "provider": self.provider,
                "dimension": dimension,
            }
        )
        ledger["alerts"] = alerts[-20:]
        save_ledger(self.root, ledger)

    def _persist(self) -> None:
        ledger = load_ledger(self.root)
        providers = ledger.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        entry: dict[str, Any] = {"operations": dict(self._operations)}
        if self.dual_budget:
            entry["complexity"] = dict(self._complexity)
            entry["countsOnly"] = False
            ledger["schemaVersion"] = BUDGET_SCHEMA_VERSION
        else:
            entry["countsOnly"] = True
        providers[self.provider] = entry
        ledger["providers"] = providers
        # Count-only top-level mirror for the active non-dual provider (R13/G3 byte-compat).
        if not self.dual_budget:
            ledger["operations"] = dict(self._operations)
            ledger["provider"] = self.provider
            ledger["countsOnly"] = True
            ledger.pop("complexity", None)
        else:
            # Dual-budget providers do not clobber count-only top-level ops.
            ledger["countsOnly"] = False
        save_ledger(self.root, ledger)

    def snapshot(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "provider": self.provider,
            "totalCharged": self.total_charged,
            "bulkCeiling": self.bulk_ceiling(),
            "maxCalls": self.max_calls,
            "schedulerReserve": self.scheduler_reserve,
            "operations": dict(self._operations),
            "alertThreshold": self.alert_threshold,
            "cacheTtlSeconds": self.cache_ttl_seconds,
            "countsOnly": not self.dual_budget,
        }
        if self.dual_budget:
            out["schemaVersion"] = BUDGET_SCHEMA_VERSION
            out["maxComplexityPoints"] = self.max_complexity_points
            out["totalComplexityCharged"] = self.total_complexity_charged
            out["complexityCeiling"] = self.complexity_ceiling()
            out["complexity"] = dict(self._complexity)
            out["countsOnly"] = False
        return out


def plan_queries_under_complexity_cap(
    units: list[dict[str, Any]],
    *,
    max_complexity: int = DEFAULT_QUERY_COMPLEXITY_CAP,
) -> list[list[dict[str, Any]]]:
    """Split work units into batches that respect per-query complexity cap (R13)."""
    if max_complexity <= 0:
        raise ValueError("max_complexity must be positive")
    batches: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_cost = 0
    for unit in units:
        estimate = int(unit.get("estimate") or 0)
        if estimate > max_complexity:
            # Single oversized unit still gets its own batch (caller must further fragment).
            if current:
                batches.append(current)
                current = []
                current_cost = 0
            batches.append([unit])
            continue
        if current and current_cost + estimate > max_complexity:
            batches.append(current)
            current = []
            current_cost = 0
        current.append(unit)
        current_cost += estimate
    if current:
        batches.append(current)
    return batches



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
