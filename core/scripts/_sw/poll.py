"""Condition-based event wait primitive with backoff and jitter (R15–R17)."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

DEFAULT_POLL_SECONDS = 45.0
DEFAULT_MAX_WAIT_MINUTES = 20.0
DEFAULT_PHASE_TIMEOUT_MINUTES = 240.0

WAITMAP_PATH = Path(__file__).with_name("waitmap.json")


@dataclass(frozen=True)
class PollConfig:
    interval_seconds: float
    max_wait_seconds: float
    backoff_multiplier: float = 1.5
    jitter: str = "full"


@dataclass(frozen=True)
class PollResult:
    satisfied: bool
    attempts: int
    elapsed_seconds: float
    last_value: Any = None


class PollTimeoutError(TimeoutError):
    def __init__(self, message: str, *, attempts: int, elapsed_seconds: float) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.elapsed_seconds = elapsed_seconds


def _repo_root() -> Path:
    env = os.environ.get("SW_REPO_ROOT", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def _config_paths(root: Path) -> list[Path]:
    return [
        root / ".cursor" / "workflow.config.json",
        root / "workflow.config.json",
    ]


def load_workflow_config(root: Path | None = None) -> dict[str, Any]:
    root = root or _repo_root()
    for path in _config_paths(root):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _nested_get(config: dict[str, Any], *keys: str, default: Any = None) -> Any:
    cur: Any = config
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def load_poll_config(root: Path | None = None) -> PollConfig:
    config = load_workflow_config(root)
    poll_seconds = float(_nested_get(config, "checks", "watch", "pollSeconds", default=DEFAULT_POLL_SECONDS))
    max_wait_minutes = float(
        _nested_get(config, "checks", "watch", "maxWaitMinutes", default=DEFAULT_MAX_WAIT_MINUTES)
    )
    return PollConfig(
        interval_seconds=max(0.1, poll_seconds),
        max_wait_seconds=max(1.0, max_wait_minutes * 60.0),
    )


def load_phase_timeout_minutes(root: Path | None = None) -> float:
    config = load_workflow_config(root)
    return float(
        _nested_get(
            config,
            "deliver",
            "watchdog",
            "phaseTimeoutMinutes",
            default=DEFAULT_PHASE_TIMEOUT_MINUTES,
        )
    )


def load_waitmap() -> dict[str, Any]:
    if not WAITMAP_PATH.is_file():
        return {"sites": []}
    try:
        data = json.loads(WAITMAP_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"sites": []}
    except json.JSONDecodeError:
        return {"sites": []}


def notify_on_output_cadence(root: Path | None = None) -> tuple[float, float]:
    cfg = load_poll_config(root)
    return cfg.interval_seconds, cfg.max_wait_seconds


def _sleep_with_jitter(interval: float, attempt: int, cfg: PollConfig) -> None:
    if cfg.jitter == "none":
        time.sleep(min(interval, cfg.max_wait_seconds))
        return
    if cfg.jitter == "full":
        delay = random.uniform(0.0, min(interval, cfg.max_wait_seconds))
    else:
        delay = interval
    backoff = interval * (cfg.backoff_multiplier ** max(0, attempt - 1))
    time.sleep(min(delay, backoff, cfg.max_wait_seconds))


def poll_until(
    predicate: Callable[[], Any],
    *,
    config: PollConfig | None = None,
    root: Path | None = None,
    timeout_seconds: float | None = None,
) -> PollResult:
    cfg = config or load_poll_config(root)
    deadline = time.monotonic() + (timeout_seconds if timeout_seconds is not None else cfg.max_wait_seconds)
    attempts = 0
    start = time.monotonic()
    last_value: Any = None
    while True:
        attempts += 1
        value = predicate()
        last_value = value
        if value:
            return PollResult(True, attempts, time.monotonic() - start, last_value)
        if time.monotonic() >= deadline:
            elapsed = time.monotonic() - start
            raise PollTimeoutError(
                f"poll_until timed out after {elapsed:.1f}s ({attempts} attempts)",
                attempts=attempts,
                elapsed_seconds=elapsed,
            )
        _sleep_with_jitter(cfg.interval_seconds, attempts, cfg)
