#!/usr/bin/env python3
"""Memory backend provider round-trip fixture (PRD 057 R21 / 21b).

Proves, fully offline and deterministically (fake Recallium REST transport
via `planning_store._urlopen` monkeypatch, no network, no live server):

1. **Zero: no provider configured stays local-cache-only (21a unchanged)** —
   `MemoryLocalCacheBackend.put`/`get` round-trip content byte-exact through
   the gitignored local cache alone when no memory provider is configured,
   `providerRoundTrip: false` / `providerRoundTripReason: provider-not-configured`
   is recorded, and no network call is attempted.
2. **One: a successful provider round-trip is real, not just local-cache
   theater** — with `memory.provider: recallium` and a reachable (fake)
   REST base, `put()` calls the provider adapter and the local cache records
   `providerRoundTrip: true`.
3. **Many: cross-machine recovery through the provider** — deleting the
   local cache file after a successful `put()` (simulating a fresh checkout
   on another machine, since the cache dir is gitignored) still lets `get()`
   recover the exact original content through the provider adapter and
   repopulate the local cache.
4. **Boundaries: the loopback-only SSRF guard blocks non-local REST bases**
   — a `restBaseUrl` pointing at a non-loopback host is never dialed;
   `_is_allowed_recallium_base` rejects it and the round-trip degrades to
   `provider-rest-base-unavailable`, never raising and never leaking the
   body to an untrusted host.
5. **Exceptions: a provider outage degrades to the R21a local cache, not a
   failure** — a connection-refused/timeout transport still yields a `put()`
   verdict of `ok` served from the local cache (`providerRoundTripReason`
   starts with `provider-unreachable:`), and a subsequent `get()` still
   returns the exact content from the local cache.
6. **Interfaces: `exists()` also consults the provider when the local cache
   is absent** — mirrors the `get()` recovery path so callers relying on
   `exists()` for a fresh checkout are not falsely told a unit is missing.
7. **Simple: a provider 404 (never written) with no local cache is a clean
   `missing`, not a crash** — proves the not-found path degrades cleanly all
   the way through.

No network, no live Recallium server required.

ZOMBIES: Zero (no provider) · One (successful round-trip) · Many
(cross-machine recovery) · Boundaries (SSRF guard) · Exceptions (provider
outage fallback) · Interfaces (`exists()` recovery) · Simple (clean 404 miss).
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_store as ps  # noqa: E402

RECALLIUM_CFG = {
    "planning": {"store": {"backend": "memory"}},
    "memory": {
        "provider": "recallium",
        "project": "roundtrip-fixture",
        "connection": {"restBaseUrl": "http://localhost:8001"},
    },
}

NO_PROVIDER_CFG = {"planning": {"store": {"backend": "memory"}}}


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class FakeRecalliumTransport:
    """In-memory stand-in for the Recallium `/planning-bodies/<unitId>` REST resource."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, str]] = {}
        self.calls: list[tuple[str, str]] = []

    def urlopen(self, req, timeout: float = 5):  # noqa: ANN001 - matches urlopen signature loosely
        method = req.get_method()
        url = req.full_url
        self.calls.append((method, url))
        if method == "PUT":
            payload = json.loads(req.data.decode("utf-8"))
            self.store[url] = payload
            return _FakeResponse(200)
        if method == "GET":
            if url not in self.store:
                # `_provider_round_trip_get` is expected to `.close()` this on
                # catch (matches real `urlopen` 404s); a real `fp` here keeps
                # the fake as close to the live shape as `HTTPError` allows.
                raise HTTPError(url, 404, "not found", {}, io.BytesIO(b""))
            return _FakeResponse(200, json.dumps(self.store[url]).encode("utf-8"))
        raise AssertionError(f"unexpected method {method}")


class UnreachableTransport:
    def urlopen(self, req, timeout: float = 5):  # noqa: ANN001
        raise URLError("connection refused (fixture)")


def _new_backend(tmp_root: Path, cfg: dict) -> "ps.MemoryLocalCacheBackend":
    (tmp_root / ".cursor").mkdir(parents=True, exist_ok=True)
    return ps.MemoryLocalCacheBackend(tmp_root, cfg)


def check_zero_no_provider_stays_local_cache_only() -> dict:
    original = ps._urlopen
    calls_made: list[object] = []
    ps._urlopen = lambda *a, **k: calls_made.append((a, k)) or (_ for _ in ()).throw(
        AssertionError("network dialed despite no provider configured")
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _new_backend(Path(tmp), NO_PROVIDER_CFG)
            put_result = backend.put("001-zero", "docs/prds/001-zero/001-zero.md", "zero content")
            got = backend.get("001-zero", "docs/prds/001-zero/001-zero.md")
            frontmatter = backend._unit_path("001-zero").read_text(encoding="utf-8")
    finally:
        ps._urlopen = original
    ok = (
        put_result.verdict == "ok"
        and got.content == "zero content"
        and "providerRoundTrip: false" in frontmatter
        and "providerRoundTripReason: provider-not-configured" in frontmatter
        and not calls_made
    )
    return {
        "name": "zero-no-provider-stays-local-cache-only",
        "ok": ok,
        "detail": f"putVerdict={put_result.verdict} contentMatch={got.content == 'zero content'} networkCalls={len(calls_made)}",
    }


def check_one_successful_round_trip_is_real() -> dict:
    transport = FakeRecalliumTransport()
    original = ps._urlopen
    ps._urlopen = transport.urlopen
    try:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _new_backend(Path(tmp), RECALLIUM_CFG)
            put_result = backend.put("002-one", "docs/prds/002-one/002-one.md", "one content")
            frontmatter = backend._unit_path("002-one").read_text(encoding="utf-8")
    finally:
        ps._urlopen = original
    put_calls = [c for c in transport.calls if c[0] == "PUT"]
    ok = (
        put_result.verdict == "ok"
        and put_result.notice is not None
        and "provider round-trip ok" in put_result.notice
        and "providerRoundTrip: true" in frontmatter
        and "providerRoundTripReason: ok" in frontmatter
        and len(put_calls) == 1
        and "/planning-bodies/002-one" in put_calls[0][1]
    )
    return {
        "name": "one-successful-round-trip-is-real",
        "ok": ok,
        "detail": f"notice={put_result.notice!r} putCalls={len(put_calls)}",
    }


def check_many_cross_machine_recovery_through_provider() -> dict:
    transport = FakeRecalliumTransport()
    original = ps._urlopen
    ps._urlopen = transport.urlopen
    try:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _new_backend(Path(tmp), RECALLIUM_CFG)
            backend.put("003-many", "docs/prds/003-many/003-many.md", "many content")
            cache_path = backend._unit_path("003-many")
            cache_existed_before = cache_path.is_file()
            cache_path.unlink()  # simulate a fresh checkout on another machine
            recovered = backend.get("003-many", "docs/prds/003-many/003-many.md")
            cache_repopulated = cache_path.is_file()
            frontmatter = cache_path.read_text(encoding="utf-8") if cache_repopulated else ""
    finally:
        ps._urlopen = original
    ok = (
        cache_existed_before
        and recovered.verdict == "ok"
        and recovered.content == "many content"
        and cache_repopulated
        and "providerRoundTrip: true" in frontmatter
    )
    return {
        "name": "many-cross-machine-recovery-through-provider",
        "ok": ok,
        "detail": (
            f"cacheExistedBefore={cache_existed_before} recoveredVerdict={recovered.verdict} "
            f"contentMatch={recovered.content == 'many content'} cacheRepopulated={cache_repopulated}"
        ),
    }


def check_boundary_ssrf_guard_blocks_non_loopback_base() -> dict:
    disallowed_cfg = {
        "planning": {"store": {"backend": "memory"}},
        "memory": {
            "provider": "recallium",
            "project": "roundtrip-fixture",
            "connection": {"restBaseUrl": "http://evil.example.com:8001"},
        },
    }
    original = ps._urlopen
    dialed: list[object] = []
    ps._urlopen = lambda *a, **k: dialed.append((a, k)) or (_ for _ in ()).throw(
        AssertionError("network dialed despite disallowed non-loopback base")
    )
    try:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _new_backend(Path(tmp), disallowed_cfg)
            put_result = backend.put("004-boundary", "x", "boundary content")
    finally:
        ps._urlopen = original
    direct_guard_checks = (
        ps._is_allowed_recallium_base("http://evil.example.com:8001") is False
        and ps._is_allowed_recallium_base("http://localhost:8001") is True
        and ps._is_allowed_recallium_base("http://127.0.0.1:8001") is True
        and ps._is_allowed_recallium_base("http://[::1]:8001") is True
        and ps._is_allowed_recallium_base("ftp://localhost:8001") is False
        and ps._is_allowed_recallium_base("http://user:pass@localhost:8001") is False
    )
    ok = (
        put_result.verdict == "ok"
        and put_result.notice is not None
        and "provider-rest-base-unavailable" in put_result.notice
        and not dialed
        and direct_guard_checks
    )
    return {
        "name": "boundary-ssrf-guard-blocks-non-loopback-base",
        "ok": ok,
        "detail": f"notice={put_result.notice!r} dialed={len(dialed)} directGuardChecks={direct_guard_checks}",
    }


def check_exceptions_provider_outage_degrades_to_local_cache() -> dict:
    original = ps._urlopen
    ps._urlopen = UnreachableTransport().urlopen
    try:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _new_backend(Path(tmp), RECALLIUM_CFG)
            put_result = backend.put("005-exceptions", "x", "outage content")
            got = backend.get("005-exceptions", "x")
    finally:
        ps._urlopen = original
    ok = (
        put_result.verdict == "ok"
        and put_result.notice is not None
        and "provider-unreachable:" in put_result.notice
        and got.verdict == "ok"
        and got.content == "outage content"
    )
    return {
        "name": "exceptions-provider-outage-degrades-to-local-cache",
        "ok": ok,
        "detail": f"putNotice={put_result.notice!r} getVerdict={got.verdict} contentMatch={got.content == 'outage content'}",
    }


def check_interfaces_exists_consults_provider_when_cache_absent() -> dict:
    transport = FakeRecalliumTransport()
    original = ps._urlopen
    ps._urlopen = transport.urlopen
    try:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _new_backend(Path(tmp), RECALLIUM_CFG)
            backend.put("006-interfaces", "x", "interfaces content")
            cache_path = backend._unit_path("006-interfaces")
            cache_path.unlink()
            exists_result = backend.exists("006-interfaces", "x")
            still_absent_locally = not cache_path.is_file()
    finally:
        ps._urlopen = original
    ok = exists_result.verdict == "ok" and still_absent_locally
    return {
        "name": "interfaces-exists-consults-provider-when-cache-absent",
        "ok": ok,
        "detail": f"existsVerdict={exists_result.verdict} stillAbsentLocally={still_absent_locally}",
    }


def check_simple_never_written_is_clean_missing() -> dict:
    transport = FakeRecalliumTransport()
    original = ps._urlopen
    ps._urlopen = transport.urlopen
    try:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _new_backend(Path(tmp), RECALLIUM_CFG)
            got = backend.get("007-never-written", "x")
            exists_result = backend.exists("007-never-written", "x")
    finally:
        ps._urlopen = original
    ok = got.verdict == "missing" and got.reason == "not-found" and exists_result.verdict == "missing"
    return {
        "name": "simple-never-written-is-clean-missing",
        "ok": ok,
        "detail": f"getVerdict={got.verdict} getReason={got.reason} existsVerdict={exists_result.verdict}",
    }


def main() -> int:
    checks = [
        check_zero_no_provider_stays_local_cache_only(),
        check_one_successful_round_trip_is_real(),
        check_many_cross_machine_recovery_through_provider(),
        check_boundary_ssrf_guard_blocks_non_loopback_base(),
        check_exceptions_provider_outage_degrades_to_local_cache(),
        check_interfaces_exists_consults_provider_when_cache_absent(),
        check_simple_never_written_is_clean_missing(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "memory-roundtrip",
        "rid": "R21",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
