from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

AccountRecord = Mapping[str, Any]
AccountRecordOut = dict[str, Any]


@dataclass(frozen=True)
class ProvisioningPlan:
    """Configuration describing how account provisioning should behave.

    Phase 1 note: This is a skeleton intended to define stable seams for later
    implementation. No provisioning logic is executed by this module yet.
    """

    provision_on_init: bool = True
    bootstrap_strategy: str = "auto"  # auto|token_only|nodriver_only|none
    store_credentials: bool = False
    verify_account_session: bool = False  # optional, off by default


@dataclass(frozen=True)
class ProvisioningEvent:
    code: str
    message: str
    level: str = "info"  # info|warning|error
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProvisioningResult:
    imported: int = 0
    reused: int = 0
    bootstrapped: int = 0
    repaired: int = 0
    failed: int = 0
    events: list[ProvisioningEvent] = field(default_factory=list)


BootstrapFromAuthTokenFn = Callable[[AccountRecord], Optional[AccountRecordOut]]
BootstrapFromCredentialsFn = Callable[[AccountRecord], Optional[AccountRecordOut]]
VerifyAccountSessionFn = Callable[[Any], bool]


def bootstrap_from_auth_token(account: AccountRecord) -> Optional[AccountRecordOut]:
    """Placeholder seam for auth_token -> cookies/csrf bootstrap (API-only).

    Expected behavior (future phase): if `account` contains an `auth_token` but
    lacks usable cookies/csrf, return an updated account record with the missing
    fields populated. Return None to indicate bootstrap could not be performed.
    """

    raise NotImplementedError("bootstrap_from_auth_token is not implemented (Phase 1 skeleton).")


def bootstrap_from_credentials(account: AccountRecord) -> Optional[AccountRecordOut]:
    """Placeholder seam for credentials -> cookies/csrf bootstrap (nodriver).

    Expected behavior (future phase): use a headless login flow to obtain
    cookies/auth material, then return an updated account record.
    """

    raise NotImplementedError("bootstrap_from_credentials is not implemented (Phase 1 skeleton).")


def verify_account_session(account_session: Any) -> bool:
    """Optional placeholder seam for verifying a live account session.

    Phase 1 note: Verification is intentionally off by default and not
    implemented yet. Callers should only invoke this when explicitly enabled.
    """

    raise NotImplementedError("verify_account_session is not implemented (Phase 1 skeleton).")

