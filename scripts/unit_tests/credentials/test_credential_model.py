"""Unit tests for credential model and tri-state resolution (PRD 080 1.3 / R3)."""

from __future__ import annotations

import importlib
import json

import pytest

from credentials import (
    CredentialRef,
    Principal,
    Resolution,
    ResolutionState,
    ResolvedToken,
    Secret,
    backend_module_name,
    list_backends,
    load_backend,
    resolve,
)
from credentials.model import redact_secret_value


_TEST_VALUE = "unit-test-credential-value-abcdef"


def _token(value: str = _TEST_VALUE) -> ResolvedToken:
    return ResolvedToken(token=Secret(value), principal=Principal(profile="work", account="acct"))


class TestCredentialRef:
    def test_empty_reference_is_marked_empty(self) -> None:
        ref = CredentialRef("   ")
        assert ref.is_empty

    def test_single_valid_reference_preserves_value(self) -> None:
        ref = CredentialRef("github-work")
        assert not ref.is_empty
        assert str(ref) == "github-work"

    def test_many_distinct_references_remain_independent(self) -> None:
        refs = [CredentialRef(f"ref-{index}") for index in range(3)]
        assert [ref.value for ref in refs] == ["ref-0", "ref-1", "ref-2"]


class TestResolutionTriState:
    def test_empty_reference_is_unresolved(self) -> None:
        ref = CredentialRef("")
        outcome = resolve(ref)
        assert outcome.state is ResolutionState.UNRESOLVED
        with pytest.raises(ValueError, match="empty reference"):
            outcome.ensure_no_empty_token_coercion()

    def test_valid_reference_can_resolve_with_token(self) -> None:
        ref = CredentialRef("github-work")
        outcome = Resolution.resolved(ref, _token())
        assert outcome.state is ResolutionState.RESOLVED
        assert outcome.token is not None
        outcome.ensure_no_empty_token_coercion()

    def test_explicit_no_auth_is_distinct_from_unresolved(self) -> None:
        ref = CredentialRef("public-read")
        outcome = Resolution.explicitly_no_auth(ref)
        assert outcome.state is ResolutionState.EXPLICITLY_NO_AUTH
        assert outcome.is_explicitly_unauthenticated
        outcome.ensure_no_empty_token_coercion()

    def test_unresolved_carries_reason(self) -> None:
        ref = CredentialRef("missing-entry")
        outcome = Resolution.unresolved(ref, reason="selector-missing")
        assert outcome.state is ResolutionState.UNRESOLVED
        assert outcome.reason == "selector-missing"
        outcome.ensure_no_empty_token_coercion()


class TestEmptyTokenCoercion:
    def test_empty_token_cannot_resolve(self) -> None:
        ref = CredentialRef("github-work")
        with pytest.raises(ValueError, match="non-empty token"):
            Resolution.resolved(ref, ResolvedToken(token=Secret("   ")))

    def test_empty_reference_cannot_be_explicitly_no_auth(self) -> None:
        with pytest.raises(ValueError, match="empty credential reference"):
            Resolution.explicitly_no_auth(CredentialRef(""))

    def test_empty_reference_cannot_resolve(self) -> None:
        with pytest.raises(ValueError, match="empty credential reference"):
            Resolution.resolved(CredentialRef(""), _token())

    def test_empty_token_cannot_imply_unauthenticated_success(self) -> None:
        ref = CredentialRef("")
        outcome = Resolution.unresolved(ref, reason="empty-reference")
        with pytest.raises(ValueError, match="empty reference"):
            outcome.ensure_no_empty_token_coercion()


class TestSecretRedaction:
    def test_secret_redacts_repr_and_str(self) -> None:
        wrapped = Secret(_TEST_VALUE)
        assert _TEST_VALUE not in repr(wrapped)
        assert _TEST_VALUE not in str(wrapped)
        assert wrapped.value == _TEST_VALUE

    def test_resolution_public_json_redacts_secret(self) -> None:
        ref = CredentialRef("github-work")
        outcome = Resolution.resolved(ref, _token())
        payload = json.loads(outcome.to_public_json())
        serialized = json.dumps(payload)
        assert _TEST_VALUE not in serialized
        assert payload["state"] == "resolved"
        assert payload["token"]["secret"]["value"] == "<redacted>"


class TestPackageSurface:
    _IMPLEMENTED_BACKENDS = frozenset({"keystore"})

    def test_importing_backends_has_no_secret_side_effects(self) -> None:
        for backend in list_backends():
            module_name = backend_module_name(backend)
            if backend in self._IMPLEMENTED_BACKENDS:
                module = importlib.import_module(module_name)
                assert module is not None
            else:
                with pytest.raises(ModuleNotFoundError):
                    importlib.import_module(module_name)
            assert load_backend(backend)() is None

    def test_redact_secret_value_is_constant(self) -> None:
        assert redact_secret_value(_TEST_VALUE) == "<redacted>"
