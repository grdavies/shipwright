"""Per-platform credential backend availability matrix (PRD 080 phase 6 / R3)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from typing import Final

from credentials import failure_codes as fc

KEYSTORE_LINUX_REMEDIATION_CODE: Final[str] = "platform-keystore-unavailable"
KEYSTORE_LINUX_REMEDIATION_HINT: Final[str] = (
    "the keystore backend is unavailable on Linux and in containers; "
    "use the environment or github_cli backend instead"
)


class HostPlatform(str, Enum):
    DARWIN = "darwin"
    WINDOWS = "win32"
    LINUX = "linux"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class PlatformMatrixError(Exception):
    code: str
    hint: str

    def __str__(self) -> str:
        return f"{self.code}: {self.hint}"


def detect_host_platform() -> HostPlatform:
    name = sys.platform
    if name == "darwin":
        return HostPlatform.DARWIN
    if name == "win32":
        return HostPlatform.WINDOWS
    if name.startswith("linux"):
        return HostPlatform.LINUX
    return HostPlatform.OTHER


def is_running_in_container() -> bool:
    if os.environ.get("container", "").strip().lower() in {"docker", "podman"}:
        return True
    if os.environ.get("KUBERNETES_SERVICE_HOST", "").strip():
        return True
    try:
        return os.path.exists("/.dockerenv")
    except OSError:
        return False


def keystore_supported_on_host() -> bool:
    platform = detect_host_platform()
    if platform not in {HostPlatform.DARWIN, HostPlatform.WINDOWS}:
        return False
    if is_running_in_container():
        return False
    return True


def validate_backend_for_platform(backend: str) -> None:
    """Fail closed when a backend is selected on an unsupported host."""
    if backend != "keystore":
        return
    if keystore_supported_on_host():
        return
    raise PlatformMatrixError(
        code=KEYSTORE_LINUX_REMEDIATION_CODE,
        hint=KEYSTORE_LINUX_REMEDIATION_HINT,
    )


def keystore_failure_for_platform() -> tuple[str, str]:
    """Return (failure_code, hint) when keystore cannot run on this host."""
    if keystore_supported_on_host():
        return fc.UNAVAILABLE_BACKEND, fc.failure_detail(fc.UNAVAILABLE_BACKEND).hint
    return KEYSTORE_LINUX_REMEDIATION_CODE, KEYSTORE_LINUX_REMEDIATION_HINT
