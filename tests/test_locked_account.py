"""X locks an account and still answers HTTP 200 with an empty timeline.

The body carries code 326, ``"kind": "Permissions"``, ``"name": "AuthorizationError"`` and a bounce to
``https://twitter.com/account/access``. Captured 2026-09-07 from a real Followers request. Without the
mapping, that answer counts as a successful empty page: the engine keeps leasing the locked account, and
the user never learns that one visit to the unlock page repairs it.
"""

from __future__ import annotations

from Scweet.api_engine import (
    ACCOUNT_LOCKED_CODES,
    ACCOUNT_LOCKED_STATUS,
    ApiEngine,
)
from Scweet.config import ScweetConfig
from Scweet.cooldown import compute_cooldown

# The real error, as X sent it.
LOCKED_ERROR = [
    {
        "bounce": {"bounce_location": "https://twitter.com/account/access", "sub_error_code": 0},
        "code": 326,
        "extensions": {
            "bounce": {
                "bounce_location": "https://twitter.com/account/access",
                "sub_error_code": 0,
            },
            "code": 326,
            "kind": "Permissions",
            "name": "AuthorizationError",
            "source": "Client",
            "tracing": {"trace_id": "abc"},
        },
        "kind": "Permissions",
        "message": (
            "To protect our users from spam and other malicious activity, this account is "
            "temporarily locked. Please log in to https://twitter.com to unlock your account."
        ),
        "name": "AuthorizationError",
        "source": "Client",
    }
]


class TestALockedAccountIsNotAnEmptyPage:
    def test_the_answer_maps_to_the_locked_status(self):
        assert ApiEngine._map_graphql_errors_to_status(LOCKED_ERROR) == ACCOUNT_LOCKED_STATUS, (
            "a locked account answered 200; without a status the engine counts an empty page and keeps "
            "leasing the account"
        )

    def test_the_code_is_declared_with_its_evidence(self):
        assert 326 in ACCOUNT_LOCKED_CODES


class TestTheLockGetsItsOwnCooldown:
    def test_the_locked_status_rests_the_account_for_the_configured_time(self):
        config = ScweetConfig()
        status, until_ts, reason = compute_cooldown(423, {}, config)
        assert status == 423
        assert reason == "locked"
        import time

        rest_s = until_ts - time.time()
        assert config.locked_cooldown_s <= rest_s <= config.locked_cooldown_s + config.cooldown_jitter_s + 1

    def test_the_default_rest_is_one_hour_not_thirty_days(self):
        config = ScweetConfig()
        assert config.locked_cooldown_s == 3600.0
        assert config.locked_cooldown_s < config.auth_cooldown_s


class TestTheMappingStaysNarrow:
    """A wrong code costs an account its cooldown, so each branch must stay exact."""

    def test_an_error_about_one_tweet_is_not_a_lock(self):
        assert (
            ApiEngine._map_graphql_errors_to_status(
                [{"message": "Tweet author restricted who can reply"}]
            )
            is None
        )

    def test_a_protected_tweet_is_not_a_lock(self):
        assert ApiEngine._map_graphql_errors_to_status([{"message": "not authorized"}]) is None

    def test_a_dead_session_still_maps_to_401(self):
        assert (
            ApiEngine._map_graphql_errors_to_status(
                [{"code": 89, "message": "Invalid or expired token"}]
            )
            == 401
        )

    def test_a_rate_limit_still_maps_to_429(self):
        assert ApiEngine._map_graphql_errors_to_status([{"message": "Rate limit exceeded"}]) == 429

    def test_an_empty_list_maps_to_nothing(self):
        assert ApiEngine._map_graphql_errors_to_status([]) is None
