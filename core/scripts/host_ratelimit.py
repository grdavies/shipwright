#!/usr/bin/env python3
"""Shared host HTTP rate-limit retry wrapper (PRD 026 R35–R42, TR10)."""

from __future__ import annotations

import argparse
import email.utils
import json
import math
import random
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from host_lib import DEFAULT_RATE_LIMIT, resolve_rate_limit, host_section, load_workflow_config

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

REDACT_PATTERNS = (
    re.compile(r"(?i)(authorization|token|bearer)\s*[:=]\s*\S+"),
    re.compile(r"(?i)(x-access-token|x-api-key)\s*:\s*\S+"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9\-_]{20,}"),
)


def normalize_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    return {str(k).lower(): str(v) for k, v in headers.items()}


def header_int(headers: dict[str, str], *names: str) -> int | None:
    for name in names:
        val = headers.get(name.lower())
        if val is None:
            continue
        try:
            return int(val.strip())
        except ValueError:
            continue
    return None


def parse_retry_after(headers: dict[str, str]) -> float | None:
    raw = headers.get("retry-after")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(int(raw)))
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(raw)
            return max(0.0, dt.timestamp() - time.time())
        except (TypeError, ValueError, OSError):
            return None


def parse_reset_epoch(headers: dict[str, str], provider: str) -> float | None:
    keys = {
        "github": ("x-ratelimit-reset",),
        "gitlab": ("ratelimit-reset",),
        "bitbucket": ("x-ratelimit-reset", "ratelimit-reset"),
    }.get(provider, ("x-ratelimit-reset", "ratelimit-reset"))
    epoch = header_int(headers, *keys)
    if epoch is not None:
        return max(0.0, float(epoch) - time.time())
    for key in ("ratelimit-resettime",):
        raw = headers.get(key)
        if not raw:
            continue
        try:
            dt = email.utils.parsedate_to_datetime(raw.strip())
            return max(0.0, dt.timestamp() - time.time())
        except (TypeError, ValueError, OSError):
            continue
    return None


def remaining_count(headers: dict[str, str], provider: str) -> int | None:
    keys = {
        "github": ("x-ratelimit-remaining",),
        "gitlab": ("ratelimit-remaining",),
        "bitbucket": ("x-ratelimit-remaining", "ratelimit-remaining"),
    }.get(provider, ("x-ratelimit-remaining", "ratelimit-remaining"))
    return header_int(headers, *keys)


def is_near_limit(headers: dict[str, str], provider: str, threshold: int) -> bool:
    if headers.get("x-ratelimit-nearlimit", "").lower() == "true":
        return True
    rem = remaining_count(headers, provider)
    return rem is not None and rem <= threshold


def _github_rate_limit_body_hint(body: str) -> bool:
    lower = body.lower()
    return any(
        phrase in lower
        for phrase in (
            "rate limit exceeded",
            "secondary rate limit",
            "abuse detection",
        )
    )


def is_throttled(
    status_code: int,
    headers: dict[str, str],
    provider: str,
    *,
    body: str = "",
) -> bool:
    if status_code == 429:
        return True
    if status_code == 403 and provider == "github":
        resource = headers.get("x-ratelimit-resource", "").lower()
        if resource in {"search", "graphql", "integration_manifest"}:
            rem = remaining_count(headers, provider)
            if rem == 0:
                return True
        if _github_rate_limit_body_hint(body):
            return True
        rem = remaining_count(headers, provider)
        if rem == 0:
            return True
    return False


def compute_backoff_ms(attempt: int, base_ms: int, cap_ms: int, jitter: bool) -> int:
    exp = min(cap_ms, int(base_ms * (2 ** max(0, attempt - 1))))
    if not jitter:
        return exp
    return random.randint(0, exp)


def compute_wait_seconds(
    *,
    status_code: int,
    headers: dict[str, str],
    attempt: int,
    provider: str,
    config: dict[str, Any],
    body: str = "",
) -> tuple[float, str]:
    norm = normalize_headers(headers)
    if is_throttled(status_code, norm, provider, body=body):
        retry_after = parse_retry_after(norm)
        if retry_after is not None:
            return retry_after, "retry-after"
        rem = remaining_count(norm, provider)
        reset_wait = parse_reset_epoch(norm, provider)
        if rem == 0 and reset_wait is not None:
            return reset_wait, "reset"
        backoff_ms = compute_backoff_ms(
            attempt,
            int(config.get("baseBackoffMs", DEFAULT_RATE_LIMIT["baseBackoffMs"])),
            int(config.get("capBackoffMs", DEFAULT_RATE_LIMIT["capBackoffMs"])),
            bool(config.get("jitter", True)),
        )
        return backoff_ms / 1000.0, "backoff"
    threshold = int(config.get("nearLimitThreshold", DEFAULT_RATE_LIMIT["nearLimitThreshold"]))
    if is_near_limit(norm, provider, threshold):
        backoff_ms = compute_backoff_ms(
            attempt,
            int(config.get("baseBackoffMs", DEFAULT_RATE_LIMIT["baseBackoffMs"])),
            int(config.get("capBackoffMs", DEFAULT_RATE_LIMIT["capBackoffMs"])),
            bool(config.get("jitter", True)),
        )
        return backoff_ms / 1000.0, "near-limit"
    return 0.0, "none"


def redact_log_line(line: str) -> str:
    out = line
    for pattern in REDACT_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out


@dataclass
class RequestResult:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""


@dataclass
class TransportOutcome:
    verdict: str
    status_code: int | None = None
    attempts: int = 0
    cumulative_wait_ms: int = 0
    reason: str = ""
    retryable: bool = False
    logs: list[str] = field(default_factory=list)
    result: RequestResult | None = None

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "verdict": self.verdict,
            "attempts": self.attempts,
            "cumulativeWaitMs": self.cumulative_wait_ms,
            "reason": self.reason,
            "retryable": self.retryable,
            "logs": self.logs,
        }
        if self.status_code is not None:
            payload["statusCode"] = self.status_code
        if self.result is not None:
            payload["headers"] = self.result.headers
        return payload


class SerialGate:
    def __init__(self, lock_path: Path | None = None):
        self.lock_path = lock_path
        self._last_mutating_at = 0.0

    def acquire(self) -> None:
        if not self.lock_path:
            return
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                fd = self.lock_path.open("x")
                fd.write(str(time.time()))
                fd.close()
                return
            except FileExistsError:
                time.sleep(0.05)
        raise TimeoutError(f"serial gate timeout: {self.lock_path}")

    def release(self) -> None:
        if self.lock_path and self.lock_path.exists():
            self.lock_path.unlink(missing_ok=True)

    def pace_mutating(self, min_delay_ms: int) -> None:
        if min_delay_ms <= 0:
            return
        elapsed_ms = (time.time() - self._last_mutating_at) * 1000
        if self._last_mutating_at and elapsed_ms < min_delay_ms:
            time.sleep((min_delay_ms - elapsed_ms) / 1000.0)
        self._last_mutating_at = time.time()


def execute_with_retry(
    *,
    provider: str,
    config: dict[str, Any],
    method: str,
    request_fn: Callable[[], RequestResult],
    sleep_fn: Callable[[float], None] = time.sleep,
    serial_gate: SerialGate | None = None,
) -> TransportOutcome:
    max_attempts = int(config.get("maxAttempts", DEFAULT_RATE_LIMIT["maxAttempts"]))
    max_cumulative_ms = int(config.get("maxCumulativeWaitMs", DEFAULT_RATE_LIMIT["maxCumulativeWaitMs"]))
    min_mutating_ms = int(config.get("mutatingMinDelayMs", DEFAULT_RATE_LIMIT["mutatingMinDelayMs"]))
    cumulative_ms = 0
    logs: list[str] = []
    gate = serial_gate or SerialGate()

    for attempt in range(1, max_attempts + 1):
        gate.acquire()
        try:
            if method.upper() in MUTATING_METHODS:
                gate.pace_mutating(min_mutating_ms)
            result = request_fn()
        finally:
            gate.release()

        headers = normalize_headers(result.headers)
        if not is_throttled(result.status_code, headers, provider, body=result.body or ""):
            near_threshold = int(config.get("nearLimitThreshold", DEFAULT_RATE_LIMIT["nearLimitThreshold"]))
            if is_near_limit(headers, provider, near_threshold) and attempt < max_attempts:
                wait_s, reason = compute_wait_seconds(
                    status_code=result.status_code,
                    headers=headers,
                    attempt=attempt,
                    provider=provider,
                    config=config,
                    body=result.body or "",
                )
                if wait_s > 0 and reason == "near-limit":
                    wait_ms = int(math.ceil(wait_s * 1000))
                    if cumulative_ms + wait_ms > max_cumulative_ms:
                        return TransportOutcome(
                            verdict="rate-limited",
                            status_code=result.status_code,
                            attempts=attempt,
                            cumulative_wait_ms=cumulative_ms,
                            reason="cumulative-wait-exhausted",
                            retryable=True,
                            logs=logs,
                        )
                    logs.append(redact_log_line(f"host-transport attempt={attempt} waitMs={wait_ms} reason={reason}"))
                    cumulative_ms += wait_ms
                    sleep_fn(wait_s)
                    continue
            return TransportOutcome(
                verdict="ok",
                status_code=result.status_code,
                attempts=attempt,
                cumulative_wait_ms=cumulative_ms,
                reason="success",
                retryable=False,
                logs=logs,
                result=result,
            )

        wait_s, reason = compute_wait_seconds(
            status_code=result.status_code,
            headers=headers,
            attempt=attempt,
            provider=provider,
            config=config,
            body=result.body or "",
        )
        wait_ms = int(math.ceil(wait_s * 1000))
        if wait_ms <= 0:
            wait_ms = int(config.get("baseBackoffMs", DEFAULT_RATE_LIMIT["baseBackoffMs"]))
            reason = "backoff"
        if cumulative_ms + wait_ms > max_cumulative_ms:
            return TransportOutcome(
                verdict="rate-limited",
                status_code=result.status_code,
                attempts=attempt,
                cumulative_wait_ms=cumulative_ms,
                reason="cumulative-wait-exhausted",
                retryable=True,
                logs=logs,
            )
        logs.append(redact_log_line(f"host-transport attempt={attempt} waitMs={wait_ms} reason={reason}"))
        cumulative_ms += wait_ms
        if attempt >= max_attempts:
            return TransportOutcome(
                verdict="rate-limited",
                status_code=result.status_code,
                attempts=attempt,
                cumulative_wait_ms=cumulative_ms,
                reason="retry-exhausted",
                retryable=True,
                logs=logs,
            )
        sleep_fn(wait_s)

    return TransportOutcome(
        verdict="rate-limited",
        attempts=max_attempts,
        cumulative_wait_ms=cumulative_ms,
        reason="retry-exhausted",
        retryable=True,
        logs=logs,
    )


def load_config_from_root(root: Path) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    return resolve_rate_limit(host_section(cfg))


def main() -> None:
    parser = argparse.ArgumentParser(description="Host rate-limit policy helpers")
    sub = parser.add_subparsers(dest="cmd", required=True)

    compute = sub.add_parser("compute-wait")
    compute.add_argument("--provider", required=True)
    compute.add_argument("--status", type=int, required=True)
    compute.add_argument("--headers-json", default="{}")
    compute.add_argument("--attempt", type=int, default=1)
    compute.add_argument("--config-json", default="{}")

    sim = sub.add_parser("simulate")
    sim.add_argument("--provider", required=True)
    sim.add_argument("--responses-json", required=True)
    sim.add_argument("--config-json", default="{}")
    sim.add_argument("--method", default="GET")

    args = parser.parse_args()

    if args.cmd == "compute-wait":
        headers = json.loads(args.headers_json)
        config = {**DEFAULT_RATE_LIMIT, **json.loads(args.config_json)}
        wait_s, reason = compute_wait_seconds(
            status_code=args.status,
            headers=normalize_headers(headers),
            attempt=args.attempt,
            provider=args.provider,
            config=config,
        )
        print(json.dumps({"waitSeconds": wait_s, "reason": reason}, indent=2))
        return

    if args.cmd == "simulate":
        responses = json.loads(args.responses_json)
        config = {**DEFAULT_RATE_LIMIT, **json.loads(args.config_json)}
        index = {"value": 0}

        def request_fn() -> RequestResult:
            i = index["value"]
            index["value"] += 1
            row = responses[min(i, len(responses) - 1)]
            return RequestResult(
                status_code=int(row.get("status", 200)),
                headers=row.get("headers") or {},
                body=row.get("body", ""),
            )

        sleeps: list[float] = []

        def record_sleep(seconds: float) -> None:
            sleeps.append(seconds)

        outcome = execute_with_retry(
            provider=args.provider,
            config=config,
            method=args.method,
            request_fn=request_fn,
            sleep_fn=record_sleep,
            serial_gate=SerialGate(),
        )
        payload = outcome.to_json()
        payload["sleeps"] = sleeps
        print(json.dumps(payload, indent=2))
        return

    parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
