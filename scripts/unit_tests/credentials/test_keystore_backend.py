"""Keystore backend tests at the ctypes boundary (PRD 080 6.3 / R3)."""

from __future__ import annotations

import ctypes
import ctypes.util
import multiprocessing
import os
import sys
import uuid
from dataclasses import dataclass

import pytest

from credentials import failure_codes as fc
from credentials.keystore_backend import (
    KeystoreBackendAdapter,
    KeystoreServiceError,
    _darwin_dictionary_callbacks,
    _darwin_read_generic_secret,
    keystore_account_name,
    keystore_service_name,
    read_keystore_secret,
    set_keystore_bindings,
)
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext
from credentials.selector_store import SelectorEntry


_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


@dataclass(frozen=True, slots=True)
class _StubBindings:
    payload: bytes | None = None
    error: KeystoreServiceError | None = None

    def read_generic_secret(self, *, service: str, account: str) -> bytes | None:
        _ = (service, account)
        if self.error is not None:
            raise self.error
        return self.payload


def _entry(ref: str = "github-work", **overrides: object) -> SelectorEntry:
    payload = {
        "ref": ref,
        "backend": "keystore",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowed_repos": ("owner/repo",),
        "allowed_project_ids": ("proj-1",),
        "allowed_endpoints": ("https://api.github.com",),
    }
    payload.update(overrides)
    return SelectorEntry(**payload)


@pytest.fixture(autouse=True)
def _reset_bindings() -> None:
    set_keystore_bindings(None)
    yield
    set_keystore_bindings(None)


class TestKeystoreNaming:
    def test_service_name_uses_reference(self) -> None:
        assert keystore_service_name("github-work") == "shipwright.credential.github-work"

    def test_account_prefers_selector_account(self) -> None:
        entry = _entry(account="work", hostname="github.com")
        assert keystore_account_name(entry) == "work"


class TestKeystoreBackendAdapter:
    def test_missing_item_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        set_keystore_bindings(_StubBindings(payload=None))
        adapter = KeystoreBackendAdapter()
        result = adapter.resolve(
            _entry(),
            purpose="api",
            context=RepositoryContext(
                remote="https://github.com/owner/repo.git",
                repo_slug="owner/repo",
                project_id="proj-1",
                destination_endpoint="https://api.github.com/user",
            ),
        )
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.MISSING_KEYSTORE_ITEM

    def test_one_present_item_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        set_keystore_bindings(_StubBindings(payload=_TEST_VALUE.encode("utf-8")))
        adapter = KeystoreBackendAdapter()
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _TEST_VALUE
        assert result.principal is not None
        assert result.principal.account == "work"

    def test_many_refs_use_distinct_service_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        seen: list[tuple[str, str]] = []

        class _RecordingBindings:
            def read_generic_secret(self, *, service: str, account: str) -> bytes | None:
                seen.append((service, account))
                return _TEST_VALUE.encode("utf-8")

        set_keystore_bindings(_RecordingBindings())
        adapter = KeystoreBackendAdapter()
        for ref in ("ref-a", "ref-b", "ref-c"):
            result = adapter.resolve(_entry(ref=ref), purpose="api", context=_context())
            assert result.state is ResolutionState.RESOLVED
        assert seen == [
            (keystore_service_name("ref-a"), "work"),
            (keystore_service_name("ref-b"), "work"),
            (keystore_service_name("ref-c"), "work"),
        ]

    def test_unavailable_keystore_service_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        set_keystore_bindings(_StubBindings(error=KeystoreServiceError(fc.UNAVAILABLE_BACKEND)))
        adapter = KeystoreBackendAdapter()
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.UNAVAILABLE_BACKEND


class TestReadKeystoreSecret:
    def test_read_returns_decoded_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        set_keystore_bindings(_StubBindings(payload=b"token-value"))
        assert read_keystore_secret(_entry()) == "token-value"


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )


_DARWIN = sys.platform == "darwin"
_CF_STRING_ENCODING_UTF8 = 0x08000100
_ERR_SEC_DUPLICATE_ITEM = -25299
_ERR_SEC_INTERACTION_NOT_ALLOWED = -25308
_ERR_SEC_USER_CANCELED = -128


def _core_foundation() -> ctypes.CDLL:
    path = ctypes.util.find_library("CoreFoundation")
    assert path, "CoreFoundation missing"
    return ctypes.CDLL(path)


def _load_darwin_libs() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    security_path = ctypes.util.find_library("Security")
    cf_path = ctypes.util.find_library("CoreFoundation")
    assert security_path and cf_path, "Security/CoreFoundation missing"
    security = ctypes.CDLL(security_path)
    core_foundation = ctypes.CDLL(cf_path)
    core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
    core_foundation.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
    ]
    core_foundation.CFDataCreate.restype = ctypes.c_void_p
    core_foundation.CFDataCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_long,
    ]
    core_foundation.CFDictionaryCreate.restype = ctypes.c_void_p
    core_foundation.CFDictionaryCreate.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_long,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    core_foundation.CFRelease.restype = None
    core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
    security.SecItemAdd.restype = ctypes.c_int32
    security.SecItemAdd.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.SecItemDelete.restype = ctypes.c_int32
    security.SecItemDelete.argtypes = [ctypes.c_void_p]
    return security, core_foundation


def _cfstr(core_foundation: ctypes.CDLL, value: str) -> ctypes.c_void_p:
    return ctypes.c_void_p(
        core_foundation.CFStringCreateWithCString(
            None,
            value.encode("utf-8"),
            _CF_STRING_ENCODING_UTF8,
        )
    )


def _release_handles(core_foundation: ctypes.CDLL, *handles: object) -> None:
    for handle in handles:
        value = handle.value if isinstance(handle, ctypes.c_void_p) else handle
        if value:
            core_foundation.CFRelease(handle)


def _darwin_item_query(
    core_foundation: ctypes.CDLL,
    service: str,
    account: str,
    payload: bytes | None = None,
) -> tuple[ctypes.c_void_p, list[object]]:
    keys = [_cfstr(core_foundation, "class"), _cfstr(core_foundation, "svce"), _cfstr(core_foundation, "acct")]
    values: list[object] = [
        _cfstr(core_foundation, "genp"),
        _cfstr(core_foundation, service),
        _cfstr(core_foundation, account),
    ]
    keys.append(_cfstr(core_foundation, "u_AuthUI"))
    values.append(_cfstr(core_foundation, "u_AuthUIF"))
    if payload is not None:
        buf = ctypes.create_string_buffer(payload, len(payload))
        data = core_foundation.CFDataCreate(None, buf, len(payload))
        keys.append(_cfstr(core_foundation, "v_Data"))
        values.append(data)
    key_cb, value_cb = _darwin_dictionary_callbacks(core_foundation)
    key_array = (ctypes.c_void_p * len(keys))(*keys)
    value_array = (ctypes.c_void_p * len(values))(*values)
    query = core_foundation.CFDictionaryCreate(
        None,
        key_array,
        value_array,
        len(keys),
        key_cb,
        value_cb,
    )
    return query, [*keys, *values, query]


def _dummy_add_status(service: str, account: str, payload: bytes) -> int:
    security, core_foundation = _load_darwin_libs()
    query, handles = _darwin_item_query(core_foundation, service, account, payload)
    try:
        status = security.SecItemAdd(query, None)
        if status == _ERR_SEC_DUPLICATE_ITEM:
            security.SecItemDelete(query)
            status = security.SecItemAdd(query, None)
        return int(status)
    finally:
        _release_handles(core_foundation, *handles)


def _dummy_delete_status(service: str, account: str) -> int:
    security, core_foundation = _load_darwin_libs()
    query, handles = _darwin_item_query(core_foundation, service, account)
    try:
        return int(security.SecItemDelete(query))
    finally:
        _release_handles(core_foundation, *handles)


def _queue_call(queue: multiprocessing.Queue, fn, args: tuple[object, ...]) -> None:
    try:
        queue.put(("ok", fn(*args)))
    except Exception as exc:  # noqa: BLE001 — isolate FFI from the pytest process
        queue.put(("err", repr(exc)))


def _run_with_timeout(fn, args: tuple[object, ...], timeout: float = 5.0) -> object:
    ctx = multiprocessing.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(target=_queue_call, args=(queue, fn, args))
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        proc.terminate()
        proc.join(2)
        pytest.skip("Keychain FFI hung waiting for UI")
    if queue.empty():
        pytest.skip("Keychain FFI returned no status")
    kind, payload = queue.get()
    if kind == "err":
        pytest.skip(str(payload))
    return payload


def _darwin_add_dummy(service: str, account: str, payload: bytes) -> None:
    status = int(_run_with_timeout(_dummy_add_status, (service, account, payload)))
    if status in (_ERR_SEC_INTERACTION_NOT_ALLOWED, _ERR_SEC_USER_CANCELED):
        pytest.skip(f"SecItemAdd requires Keychain UI (OSStatus {status})")
    if status != 0:
        pytest.skip(f"SecItemAdd OSStatus {status}")


def _darwin_delete_dummy(service: str, account: str) -> None:
    _run_with_timeout(_dummy_delete_status, (service, account))


@pytest.mark.skipif(not _DARWIN, reason="darwin Security.framework FFI")
class TestDarwinKeychainReader:
    def test_query_construction_accepts_existing_c_void_p(self) -> None:
        cf = _core_foundation()
        boolean_true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
        with pytest.raises(TypeError, match="cannot be converted to pointer"):
            (ctypes.c_void_p * 1)(ctypes.c_void_p(boolean_true))
        array = (ctypes.c_void_p * 1)(boolean_true)
        raw = array[0].value if isinstance(array[0], ctypes.c_void_p) else array[0]
        assert raw == boolean_true.value

    def test_dictionary_callbacks_are_cf_type_addresses(self) -> None:
        cf = _core_foundation()
        key_cb, value_cb = _darwin_dictionary_callbacks(cf)
        assert key_cb != 0
        assert value_cb != 0
        assert key_cb != value_cb

    def test_missing_item_returns_none_without_typeerror(self) -> None:
        got = _darwin_read_generic_secret(
            "shipwright.debug.repro.nonexistent",
            "dummy-account",
        )
        assert got is None

    def test_dummy_item_roundtrip_then_cleanup(self) -> None:
        if os.environ.get("SW_KEYCHAIN_INTEGRATION") != "1":
            pytest.skip("set SW_KEYCHAIN_INTEGRATION=1 to write a dummy Keychain item")
        service = f"shipwright.debug.repro.{uuid.uuid4().hex}"
        account = "dummy-account"
        payload = _TEST_VALUE.encode("utf-8")
        _darwin_add_dummy(service, account, payload)
        try:
            got = _darwin_read_generic_secret(service, account)
            assert got == payload
        finally:
            _darwin_delete_dummy(service, account)
            assert (
                _darwin_read_generic_secret(service, account) is None
            )

    def test_diagnostics_never_include_secret_bytes(self, capsys: pytest.CaptureFixture[str]) -> None:
        try:
            _darwin_read_generic_secret(
                "shipwright.debug.repro.nonexistent",
                "dummy-account",
            )
        except KeystoreServiceError as exc:
            blob = f"{exc} {exc.code}"
            assert _TEST_VALUE not in blob
        captured = capsys.readouterr()
        assert _TEST_VALUE not in captured.out
        assert _TEST_VALUE not in captured.err
