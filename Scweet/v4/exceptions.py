from __future__ import annotations

from typing import Optional, Union


class ScweetError(Exception):
    """Base exception for v4 internals."""


class ConfigError(ScweetError):
    """Configuration parsing/validation error."""


class ManifestError(ScweetError):
    """Manifest loading/validation error."""


class AccountPoolExhausted(ScweetError):
    """No eligible account could be leased."""


class EngineError(ScweetError):
    """Engine-level runtime error."""


class ResumeError(ScweetError):
    """Resume mode/checkpoint error."""


class AccountSessionBuildError(ScweetError, ValueError):
    """Typed account-session bootstrap failure with stable classification metadata."""

    default_status_code = 599
    default_category = "transient"

    def __init__(
        self,
        code: str,
        reason: str,
        *,
        status_code: Optional[int] = None,
        category: Optional[str] = None,
    ) -> None:
        self.code = str(code or "session_build_error").strip() or "session_build_error"
        self.reason = str(reason or self.code).strip() or self.code
        self.status_code = int(status_code if status_code is not None else self.default_status_code)
        self.category = str(category or self.default_category).strip() or self.default_category
        super().__init__(f"{self.code}:{self.reason}")

    @property
    def metadata(self) -> dict[str, Union[str, int]]:
        return {
            "code": self.code,
            "reason": self.reason,
            "status_code": self.status_code,
            "category": self.category,
        }


class AccountSessionAuthError(AccountSessionBuildError):
    """Auth material is missing/invalid and account should be cooled as auth-failed."""

    default_status_code = 401
    default_category = "auth"


class AccountSessionRuntimeError(AccountSessionBuildError):
    """Unexpected account session runtime/bootstrap failure."""

    default_status_code = 500
    default_category = "runtime"


class AccountSessionTransientError(AccountSessionBuildError):
    """Transient account session failure that should not poison the account permanently."""

    default_status_code = 599
    default_category = "transient"
