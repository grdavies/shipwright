"""Memory body-cache backend adapter (PRD 082 phase 12 / R27)."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from memory_sot import resolve_memory_provider
from ..model import StoreResult
from ..repository import PlanningStoreBackend

from ._common import (
    FILE_BACKED_STORE_TXN_ID,
    content_hash,
    finalize_materialize_from_get,
    log_operation,
)

# Module-level indirection for unit-test monkeypatching.
_urlopen = urlopen
PLANNING_BODY_PROVIDER_TIMEOUT_SECONDS = 5
_RECALLIUM_ALLOWED_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
BANNED_MEMORY_CLASSES = frozenset({"discussion", "progress"})


def fail(error: str, exit_code: int = 2, **extra):
    from planning_store import fail as _fail

    _fail(error, exit_code, **extra)


def redact_content(content: str) -> str:
    from planning_store import redact_content as _redact_content

    return _redact_content(content)


def contains_raw_transcript(content: str) -> bool:
    from planning_store import contains_raw_transcript as _contains_raw_transcript

    return _contains_raw_transcript(content)


def _is_allowed_recallium_base(url: str) -> bool:
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.username or parsed.password:
        return False
    host = parsed.hostname
    if not host:
        return False
    if host in _RECALLIUM_ALLOWED_HOSTS:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _recallium_rest_base(cfg: dict[str, Any]) -> str | None:
    memory = cfg.get("memory")
    if not isinstance(memory, dict):
        return None
    connection = memory.get("connection")
    if not isinstance(connection, dict):
        return None
    base = str(connection.get("restBaseUrl") or "").strip().rstrip("/")
    if not base or not _is_allowed_recallium_base(base):
        return None
    return base


def _planning_body_provider_url(base: str, project: str, unit_id: str) -> str:
    quoted_project = urllib.parse.quote(project, safe="")
    quoted_unit = urllib.parse.quote(unit_id, safe="")
    return f"{base}/api/projects/{quoted_project}/planning-bodies/{quoted_unit}"


# Module-level indirection for unit-test monkeypatching (via planning_store re-export).
_urlopen = urlopen


def _dispatch_urlopen(req: Request, *, timeout: int) -> Any:
    import planning_store as ps

    opener = getattr(ps, "_urlopen", _urlopen)
    return opener(req, timeout=timeout)


def _provider_round_trip_put(base: str, project: str, unit_id: str, body_path: str, content: str) -> tuple[bool, str]:
    url = _planning_body_provider_url(base, project, unit_id)
    payload = json.dumps({"content": content, "bodyPath": body_path}).encode("utf-8")
    req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="PUT")
    try:
        with _dispatch_urlopen(req, timeout=PLANNING_BODY_PROVIDER_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if not (200 <= status < 300):
                return False, f"provider-http-{status}"
    except HTTPError as exc:
        exc.close()
        return False, f"provider-http-{exc.code}"
    except (URLError, OSError, ValueError) as exc:
        return False, f"provider-unreachable:{type(exc).__name__}"
    return True, "ok"


def _provider_round_trip_get(base: str, project: str, unit_id: str) -> tuple[bool, str, str | None]:
    url = _planning_body_provider_url(base, project, unit_id)
    req = Request(url, method="GET")
    try:
        with _dispatch_urlopen(req, timeout=PLANNING_BODY_PROVIDER_TIMEOUT_SECONDS) as resp:
            status = getattr(resp, "status", 200)
            if not (200 <= status < 300):
                return False, f"provider-http-{status}", None
            raw = resp.read()
            raw = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    except HTTPError as exc:
        code = exc.code
        exc.close()
        if code == 404:
            return False, "provider-not-found", None
        return False, f"provider-http-{code}", None
    except (URLError, OSError, ValueError) as exc:
        return False, f"provider-unreachable:{type(exc).__name__}", None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, "provider-invalid-response", None
    content = data.get("content") if isinstance(data, dict) else None
    if not isinstance(content, str):
        return False, "provider-invalid-response", None
    return True, "ok", content

class ReplicatedPlanningCacheBackend(PlanningStoreBackend):
    """PRD 057 R21 / PRD 091 R1 — replicated planning-body cache backend.

    21a made the local cache (`.cursor/sw-planning-cache/planning-bodies/`, gitignored per
    `.gitignore`) available unconditionally, independent of whether a memory provider
    is configured — see the R21a history below. 21b (this revision) adds a *real*
    round-trip through the configured provider's REST adapter on top of that cache:

    - `put()` always writes the local cache first (the R21a guarantee never
      regresses), then best-effort round-trips the redacted body through the
      Recallium REST adapter (`memory.provider: recallium` + a loopback-only
      `memory.connection.restBaseUrl`) via `_provider_round_trip_put`.
    - `get()` reads the local cache when present (fast path, unchanged from 21a).
      When the cache is missing — e.g. a fresh checkout on another machine, since
      the cache dir is gitignored — it attempts recovery through the same provider
      adapter (`_provider_round_trip_get`) and repopulates the local cache on
      success, before falling back to `missing`.
    - Any provider outage, timeout, non-2xx response, disallowed/unconfigured REST
      base, or non-`recallium` provider degrades to the R21a local-cache-only
      behavior — never a hard failure. See `_provider_round_trip_put`/`_get` and
      `_is_allowed_recallium_base`.
    - Round-trip bodies use a dedicated `/planning-bodies/<unitId>` REST resource,
      not the semantically-indexed memory-note REST collection: a full planning
      body is not a distilled memory note, and indexing raw bodies alongside them
      would pollute semantic search (see `core/providers/recallium.md`).

    `configured_provider()` still names whichever provider is configured for the
    skill's other memory operations (rules/decisions/etc. — see
    `core/skills/memory/SKILL.md`); frontmatter also records whether *this* body
    actually round-tripped (`providerRoundTrip`) and why not when it didn't
    (`providerRoundTripReason`).

    **R21a history:** prior to 21a, `_store_dir()` unconditionally called
    `fail(..., verdict="degraded")` (which `emit()` turns into `sys.exit(2)`)
    whenever no memory provider was configured — a hard CI failure for a purely
    local disk write. Removing that gate fixed the CI false-failure and the
    misleading-durability framing described in R21.
    """

    backend_id = "planning-cache"

    def memory_project(self) -> str:
        memory = self.cfg.get("memory")
        if isinstance(memory, dict) and isinstance(memory.get("project"), str) and memory["project"].strip():
            return memory["project"].strip()
        return self.root.name

    def configured_provider(self) -> str | None:
        return resolve_memory_provider(self.root, self.cfg)

    def _provider_rest_base(self) -> str | None:
        if self.configured_provider() != "recallium":
            return None
        return _recallium_rest_base(self.cfg)

    def _round_trip_unavailable_reason(self) -> str:
        provider = self.configured_provider()
        if not provider:
            return "provider-not-configured"
        if provider != "recallium":
            return f"provider-not-round-trippable:{provider}"
        return "provider-rest-base-unavailable"

    def _local_cache_dir_path(self) -> Path:
        return self.root / ".cursor" / "sw-planning-cache" / "planning-bodies" / self.memory_project()

    def _legacy_local_cache_dir(self) -> Path:
        return self.root / ".cursor" / "sw-memory" / "planning-bodies" / self.memory_project()

    def _migrate_legacy_cache_dir_if_needed(self) -> None:
        legacy = self._legacy_local_cache_dir()
        if not legacy.is_dir():
            return
        new = self._local_cache_dir_path()
        if new.is_dir():
            for item in legacy.iterdir():
                dest = new / item.name
                if dest.exists():
                    continue
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)
            try:
                shutil.rmtree(legacy)
            except OSError:
                pass
            legacy_parent = legacy.parent
            if legacy_parent.is_dir() and not any(legacy_parent.iterdir()):
                try:
                    legacy_parent.rmdir()
                except OSError:
                    pass
            return
        new.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(new))
        legacy_parent = legacy.parent
        if legacy_parent.is_dir() and not any(legacy_parent.iterdir()):
            try:
                legacy_parent.rmdir()
            except OSError:
                pass

    def _local_cache_dir(self) -> Path:
        self._migrate_legacy_cache_dir_if_needed()
        return self._local_cache_dir_path()

    def _unit_path(self, unit_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", unit_id)
        return self._local_cache_dir() / f"{safe_id}.md"

    def _validate_class(self, content_class: str | None) -> None:
        if content_class and content_class.lower() in BANNED_MEMORY_CLASSES:
            fail(f"memory backend bans content class: {content_class}", code="banned-class")

    def _validate_content(self, content: str) -> None:
        if contains_raw_transcript(content):
            fail("raw transcript content refused by memory backend", code="raw-transcript")

    def _write_cache_file(
        self,
        unit_id: str,
        body_path: str,
        redacted: str,
        *,
        provider_round_trip: bool,
        round_trip_reason: str,
    ) -> Path:
        store_dir = self._local_cache_dir()
        store_dir.mkdir(parents=True, exist_ok=True)
        target = self._unit_path(unit_id)
        frontmatter = (
            "---\n"
            f"unitId: {unit_id}\n"
            f"bodyPath: {body_path}\n"
            f"project: {self.memory_project()}\n"
            f"configuredProvider: {self.configured_provider() or 'none'}\n"
            f"providerRoundTrip: {'true' if provider_round_trip else 'false'}\n"
            f"providerRoundTripReason: {round_trip_reason}\n"
            "localCacheFallback: true\n"
            "---\n"
        )
        from planning_paths import atomic_write_text

        atomic_write_text(
            target,
            frontmatter + redacted,
            root=self.root,
            store_id=FILE_BACKED_STORE_TXN_ID,
        )
        return target

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        self._validate_class(content_class)
        self._validate_content(content)
        redacted = redact_content(content)

        base = self._provider_rest_base()
        if base is not None:
            round_trip_ok, round_trip_reason = _provider_round_trip_put(
                base, self.memory_project(), unit_id, body_path, redacted
            )
        else:
            round_trip_ok = False
            round_trip_reason = self._round_trip_unavailable_reason()

        self._write_cache_file(
            unit_id, body_path, redacted, provider_round_trip=round_trip_ok, round_trip_reason=round_trip_reason
        )
        notice = (
            "provider round-trip ok (recallium); local cache also updated"
            if round_trip_ok
            else f"provider round-trip unavailable ({round_trip_reason}) -- served from R21a local cache"
        )
        log_operation("put", unit_id, body_path, redacted, self.backend_id, notice=notice)
        return StoreResult(
            "ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted), notice=notice
        )

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._unit_path(unit_id)
        if path.is_file():
            raw = path.read_text(encoding="utf-8")
            body = raw.split("---", 2)[-1].lstrip("\n") if raw.startswith("---") else raw
            redacted = redact_content(body)
            log_operation("get", unit_id, body_path, redacted, self.backend_id)
            return StoreResult("ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted))

        # 21b: the local cache is gitignored, so a fresh checkout on another
        # machine (or a wiped `.cursor/sw-memory/`) never had it. Attempt genuine
        # recovery through the provider adapter before declaring the unit missing.
        base = self._provider_rest_base()
        if base is not None:
            ok, reason, recovered = _provider_round_trip_get(base, self.memory_project(), unit_id)
            if ok and recovered is not None:
                redacted = redact_content(recovered)
                self._write_cache_file(
                    unit_id, body_path, redacted, provider_round_trip=True, round_trip_reason="ok"
                )
                notice = "recovered via provider round-trip (recallium); local cache repopulated"
                log_operation("get", unit_id, body_path, redacted, self.backend_id, notice=notice)
                return StoreResult(
                    "ok", unit_id, body_path, self.backend_id, content=redacted, hash=content_hash(redacted), notice=notice
                )

        return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        present = self._unit_path(unit_id).is_file()
        if not present:
            base = self._provider_rest_base()
            if base is not None:
                ok, _reason, _content = _provider_round_trip_get(base, self.memory_project(), unit_id)
                present = ok
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)
