"""Native keystore backend via ctypes (macOS Security / Windows CredRead) — PRD 080 phase 6 / R3."""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from dataclasses import dataclass
from typing import Final, Protocol

from credentials import failure_codes as fc
from credentials.model import Principal, ResolutionState, Secret
from credentials.platform_matrix import PlatformMatrixError, validate_backend_for_platform
from credentials.resolver import BackendResolveResult, RepositoryContext
from credentials.selector_store import SelectorEntry

_SERVICE_PREFIX: Final[str] = "shipwright.credential"
_ERR_SEC_ITEM_NOT_FOUND: Final[int] = -25300
_CRED_TYPE_GENERIC: Final[int] = 1
_ERROR_NOT_FOUND: Final[int] = 1168


class KeystoreServiceError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class KeystoreBindings(Protocol):
    def read_generic_secret(self, *, service: str, account: str) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class _DarwinBindings:
    def read_generic_secret(self, *, service: str, account: str) -> bytes | None:
        return _darwin_read_generic_secret(service, account)


@dataclass(frozen=True, slots=True)
class _WindowsBindings:
    def read_generic_secret(self, *, service: str, account: str) -> bytes | None:
        return _windows_read_generic_secret(service, account)


_BINDINGS: KeystoreBindings | None = None


def set_keystore_bindings(bindings: KeystoreBindings | None) -> None:
    global _BINDINGS
    _BINDINGS = bindings


def _active_bindings() -> KeystoreBindings:
    if _BINDINGS is not None:
        return _BINDINGS
    if sys.platform == "darwin":
        return _DarwinBindings()
    if sys.platform == "win32":
        return _WindowsBindings()
    raise KeystoreServiceError(fc.UNAVAILABLE_BACKEND)


def _darwin_read_generic_secret(service: str, account: str) -> bytes | None:
    security_path = ctypes.util.find_library("Security")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not security_path or not cf_path:
        raise KeystoreServiceError(fc.UNAVAILABLE_BACKEND)

    security = ctypes.CDLL(security_path)
    core_foundation = ctypes.CDLL(cf_path)

    core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
    core_foundation.CFStringCreateWithCString.argtypes = [
        ctypes.c_void_p,
        ctypes.c_char_p,
        ctypes.c_uint32,
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
    core_foundation.CFDataGetLength.restype = ctypes.c_long
    core_foundation.CFDataGetLength.argtypes = [ctypes.c_void_p]
    core_foundation.CFDataGetBytePtr.restype = ctypes.c_void_p
    core_foundation.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]

    security.SecItemCopyMatching.restype = ctypes.c_int32
    security.SecItemCopyMatching.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]

    k_cf_boolean_true = ctypes.c_void_p.in_dll(core_foundation, "kCFBooleanTrue")
    k_cf_string_encoding_utf8 = 0x08000100

    def _cfstr(value: str) -> ctypes.c_void_p:
        return ctypes.c_void_p(
            core_foundation.CFStringCreateWithCString(
                None,
                value.encode("utf-8"),
                k_cf_string_encoding_utf8,
            )
        )

    keys = [
        _cfstr("class"),
        _cfstr("svce"),
        _cfstr("acct"),
        _cfstr("r_Data"),
        _cfstr("m_Limit"),
    ]
    values = [
        _cfstr("genp"),
        _cfstr(service),
        _cfstr(account),
        ctypes.c_void_p(k_cf_boolean_true),
        _cfstr("m_LimitOne"),
    ]
    key_array = (ctypes.c_void_p * len(keys))(*keys)
    value_array = (ctypes.c_void_p * len(values))(*values)
    query = core_foundation.CFDictionaryCreate(
        None,
        key_array,
        value_array,
        len(keys),
        None,
        None,
    )
    result = ctypes.c_void_p()
    status = security.SecItemCopyMatching(query, ctypes.byref(result))
    for handle in (*keys, *values, query):
        if handle:
            core_foundation.CFRelease(handle)
    if status == _ERR_SEC_ITEM_NOT_FOUND:
        return None
    if status != 0:
        raise KeystoreServiceError(fc.UNAVAILABLE_BACKEND)
    if not result:
        return None
    length = core_foundation.CFDataGetLength(result)
    if length <= 0:
        core_foundation.CFRelease(result)
        return None
    raw_ptr = core_foundation.CFDataGetBytePtr(result)
    payload = ctypes.string_at(raw_ptr, length)
    core_foundation.CFRelease(result)
    return payload


def _windows_read_generic_secret(service: str, account: str) -> bytes | None:
    advapi32 = ctypes.windll.advapi32  # type: ignore[attr-defined]

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.c_uint32),
            ("Type", ctypes.c_uint32),
            ("TargetName", ctypes.c_wchar_p),
            ("Comment", ctypes.c_wchar_p),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", ctypes.c_uint32),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", ctypes.c_uint32),
            ("AttributeCount", ctypes.c_uint32),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", ctypes.c_wchar_p),
            ("UserName", ctypes.c_wchar_p),
        ]

    cred = ctypes.POINTER(CREDENTIALW)()
    target = f"{service}/{account}"
    if not advapi32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(cred)):
        if ctypes.GetLastError() == _ERROR_NOT_FOUND:
            return None
        raise KeystoreServiceError(fc.UNAVAILABLE_BACKEND)
    try:
        if not cred or cred.contents.CredentialBlobSize == 0:
            return None
        size = cred.contents.CredentialBlobSize
        return bytes(cred.contents.CredentialBlob[i] for i in range(size))
    finally:
        advapi32.CredFree(cred)


def keystore_service_name(ref: str) -> str:
    return f"{_SERVICE_PREFIX}.{ref.strip()}"


def keystore_account_name(entry: SelectorEntry) -> str:
    if entry.account and entry.account.strip():
        return entry.account.strip()
    if entry.hostname and entry.hostname.strip():
        return entry.hostname.strip()
    return entry.ref


def read_keystore_secret(entry: SelectorEntry) -> str | None:
    validate_backend_for_platform("keystore")
    service = keystore_service_name(entry.ref)
    account = keystore_account_name(entry)
    try:
        payload = _active_bindings().read_generic_secret(service=service, account=account)
    except KeystoreServiceError:
        raise
    except OSError:
        raise KeystoreServiceError(fc.UNAVAILABLE_BACKEND) from None
    if payload is None:
        return None
    return payload.decode("utf-8")


class KeystoreBackendAdapter:
    def resolve(
        self,
        entry: SelectorEntry,
        *,
        purpose: str,
        context: RepositoryContext,
    ) -> BackendResolveResult:
        _ = (purpose, context)
        try:
            validate_backend_for_platform(entry.backend)
        except PlatformMatrixError as exc:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=exc.code,
                backend=entry.backend,
            )
        try:
            token_payload = read_keystore_secret(entry)
        except KeystoreServiceError as exc:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=exc.code,
                backend=entry.backend,
            )
        if token_payload is None or not token_payload.strip():
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=fc.MISSING_KEYSTORE_ITEM,
                backend=entry.backend,
            )
        principal = Principal(
            profile=entry.account or entry.ref,
            account=entry.account,
        )
        opaque = Secret(token_payload)
        return BackendResolveResult(
            state=ResolutionState.RESOLVED,
            token=opaque,
            principal=principal,
            backend=entry.backend,
        )


_ADAPTER = KeystoreBackendAdapter()


def get_keystore_adapter() -> KeystoreBackendAdapter:
    return _ADAPTER


def register_keystore_backend() -> None:
    from credentials.resolver import register_backend_adapter

    register_backend_adapter("keystore", _ADAPTER)
