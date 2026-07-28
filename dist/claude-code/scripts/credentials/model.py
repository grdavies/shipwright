"""Credential model types and tri-state resolution (PRD 080 phase 1 / R3)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

_SECRET_REDACTION = "<redacted>"


class ResolutionState(str, Enum):
    RESOLVED = "resolved"
    EXPLICITLY_NO_AUTH = "explicitly-no-auth"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class CredentialRef:
    """Non-secret selector reference."""

    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", str(self.value).strip())

    @property
    def is_empty(self) -> bool:
        return not self.value

    def __repr__(self) -> str:
        return f"CredentialRef({self.value!r})"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Principal:
    """Resolved non-secret identity metadata."""

    profile: str
    account: str | None = None

    def __repr__(self) -> str:
        return f"Principal(profile={self.profile!r}, account={self.account!r})"

    def __str__(self) -> str:
        account = f" ({self.account})" if self.account else ""
        return f"{self.profile}{account}"


@dataclass(frozen=True, slots=True)
class Secret:
    """Opaque secret wrapper — value never surfaces in repr/str/serialization."""

    _value: str

    def __post_init__(self) -> None:
        if not isinstance(self._value, str):
            raise TypeError("Secret value must be str")

    @property
    def value(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return f"Secret({_SECRET_REDACTION!r})"

    def __str__(self) -> str:
        return _SECRET_REDACTION

    def __format__(self, format_spec: str) -> str:
        return _SECRET_REDACTION

    def to_public(self) -> dict[str, str]:
        return {"value": _SECRET_REDACTION}

    def __reduce__(self) -> tuple[type[Secret], tuple[str]]:
        return (Secret, (_SECRET_REDACTION,))


@dataclass(frozen=True, slots=True)
class ResolvedToken:
    token: Secret
    principal: Principal | None = None

    def __repr__(self) -> str:
        principal = f", principal={self.principal!r}" if self.principal else ""
        return f"ResolvedToken({self.token!r}{principal})"


@dataclass(frozen=True, slots=True)
class Resolution:
    """Tri-state credential resolution outcome."""

    state: ResolutionState
    ref: CredentialRef
    token: ResolvedToken | None = None
    reason: str | None = None

    @classmethod
    def resolved(cls, ref: CredentialRef, token: ResolvedToken) -> Resolution:
        if ref.is_empty:
            raise ValueError("empty credential reference cannot resolve")
        if not token.token.value.strip():
            raise ValueError("resolved outcome requires a non-empty token")
        return cls(state=ResolutionState.RESOLVED, ref=ref, token=token)

    @classmethod
    def explicitly_no_auth(cls, ref: CredentialRef, *, reason: str = "explicitly-no-auth") -> Resolution:
        if ref.is_empty:
            raise ValueError("empty credential reference cannot be explicitly-no-auth")
        return cls(
            state=ResolutionState.EXPLICITLY_NO_AUTH,
            ref=ref,
            token=None,
            reason=reason,
        )

    @classmethod
    def unresolved(cls, ref: CredentialRef, *, reason: str = "unresolved") -> Resolution:
        return cls(
            state=ResolutionState.UNRESOLVED,
            ref=ref,
            token=None,
            reason=reason,
        )

    @property
    def is_explicitly_unauthenticated(self) -> bool:
        return self.state is ResolutionState.EXPLICITLY_NO_AUTH

    def ensure_no_empty_token_coercion(self) -> None:
        """Fail closed when an empty token could imply unauthenticated success."""
        if self.ref.is_empty:
            raise ValueError("empty reference cannot yield authenticated or unauthenticated success")
        if self.state is ResolutionState.RESOLVED:
            if self.token is None or not self.token.token.value.strip():
                raise ValueError("resolved outcome requires a non-empty token")
        if self.state is ResolutionState.EXPLICITLY_NO_AUTH and self.token is not None:
            if self.token.token.value.strip():
                raise ValueError("explicitly-no-auth cannot carry a token")
        if self.state is ResolutionState.UNRESOLVED and self.token is not None:
            if self.token.token.value.strip():
                raise ValueError("unresolved outcome cannot carry a resolved token")

    def to_public_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "state": self.state.value,
            "ref": str(self.ref),
            "reason": self.reason,
        }
        if self.token is not None:
            payload["token"] = {
                "secret": self.token.token.to_public(),
                "principal": None
                if self.token.principal is None
                else {
                    "profile": self.token.principal.profile,
                    "account": self.token.principal.account,
                },
            }
        return payload

    def to_public_json(self) -> str:
        return json.dumps(self.to_public_dict(), sort_keys=True)


def redact_secret_value(raw: str) -> str:
    return _SECRET_REDACTION
