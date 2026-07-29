"""End-to-end cross-project leakage metric with negative controls (PRD 082 R33)."""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS = SCRIPT_DIR.parents[1]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_cross_project_recall as recall  # noqa: E402

NEGATIVE_CONTROLS = (
    "unauthorized_caller",
    "inflated_authorized_projects",
    "spoofed_caller_project_key",
)

PUBLIC_POINTER = {
    "projectKey": "proj-a",
    "unitId": "leakage-eval",
    "memoryId": "m-leakage-eval",
    "visibility": "public",
    "excerpt": "authorized cross-project rationale for leakage eval",
}


@dataclass(frozen=True)
class ControlResult:
    control: str
    blocked: bool
    verdict: str
    error: str | None
    leakage_hits: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "control": self.control,
            "blocked": self.blocked,
            "verdict": self.verdict,
            "error": self.error,
            "leakageHits": self.leakage_hits,
        }


def _write_cfg(repo: Path, cfg: dict[str, Any]) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def base_cfg(*, project_key: str = "proj-b", trusted: list[str] | None = None) -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
        "memory": {
            "crossProjectTrustedSources": trusted or ["proj-a", "proj-c"],
        },
        "host": {"provider": "github"},
    }


def init_eval_repo(tmp_root: Path) -> Path:
    repo = tmp_root / "leakage-eval-repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "eval@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Eval"], cwd=repo, check=True)
    _write_cfg(repo, base_cfg())
    return repo


def _blocked_result(control: str, result: dict[str, Any]) -> ControlResult:
    hits = result.get("hits") or []
    leakage = len(hits) if result.get("verdict") == "pass" else 0
    verdict = str(result.get("verdict", ""))
    blocked = verdict in {"denied", "fail"} or leakage == 0
    if verdict == "pass" and leakage > 0:
        blocked = False
    return ControlResult(
        control=control,
        blocked=blocked,
        verdict=verdict,
        error=result.get("error"),
        leakage_hits=leakage,
    )


def run_unauthorized_caller(repo: Path) -> ControlResult:
    result = recall.recall_cross_project(
        repo,
        source_project_key="proj-z",
        query="",
        pointers=[PUBLIC_POINTER],
    )
    return _blocked_result("unauthorized_caller", result)


def run_inflated_authorized_projects(repo: Path) -> ControlResult:
    result = recall.recall_cross_project(
        repo,
        source_project_key="proj-z",
        query="",
        pointers=[],
        authorized_projects=["proj-z"],
    )
    return _blocked_result("inflated_authorized_projects", result)


def run_spoofed_caller_project_key(repo: Path) -> ControlResult:
    result = recall.recall_cross_project(
        repo,
        source_project_key="proj-a",
        caller_project_key="proj-attacker",
        query="",
        pointers=[PUBLIC_POINTER],
        authorized_projects=["proj-a"],
    )
    return _blocked_result("spoofed_caller_project_key", result)


def run_positive_control(repo: Path) -> ControlResult:
    result = recall.recall_cross_project(
        repo,
        source_project_key="proj-a",
        query="",
        pointers=[PUBLIC_POINTER],
        authorized_projects=["proj-a"],
    )
    return _blocked_result("authorized_caller", result)


def run_negative_controls(repo: Path) -> list[ControlResult]:
    return [
        run_unauthorized_caller(repo),
        run_inflated_authorized_projects(repo),
        run_spoofed_caller_project_key(repo),
    ]


def compute_leakage_metrics(repo: Path) -> dict[str, Any]:
    negative = run_negative_controls(repo)
    positive = run_positive_control(repo)
    blocked_count = sum(1 for row in negative if row.blocked)
    total_leakage = sum(row.leakage_hits for row in negative)
    if positive.blocked:
        authorized_recall = 0.0
    else:
        authorized_recall = 1.0 if positive.leakage_hits > 0 else 0.0
    return {
        "negativeControls": [row.to_dict() for row in negative],
        "positiveControl": positive.to_dict(),
        "metrics": {
            "negative_controls_blocked": float(blocked_count),
            "cross_project_leakage": float(total_leakage),
            "authorized_recall_rate": authorized_recall,
        },
        "allNegativeControlsBlocked": blocked_count == len(NEGATIVE_CONTROLS),
        "positiveControlPassed": not positive.blocked and positive.leakage_hits > 0,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile

    parser = argparse.ArgumentParser(description="Cross-project leakage metric (PRD 082 R33)")
    parser.add_argument("--repo", type=Path, help="Existing git worktree root")
    args = parser.parse_args(argv)

    if args.repo is not None:
        payload = compute_leakage_metrics(args.repo.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="sw-leakage-eval-") as tmp:
            repo = init_eval_repo(Path(tmp))
            payload = compute_leakage_metrics(repo)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
