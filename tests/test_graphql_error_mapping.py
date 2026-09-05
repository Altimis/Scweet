"""Tests for ApiEngine._map_graphql_errors_to_status.

X answers HTTP 200 and adds an `errors` list. The engine maps a message to a status code, and `compute_cooldown`
gives a 401 the value of `auth_cooldown_s`, which defaults to 30 days. So a wrong map removes an account of the
user for a month.

Each message below comes from a real answer of X. The pair "Invalid or expired token" with code 89, and the pair
"Could not authenticate you" with code 32, were captured from the live API on 2026-09-04.
"""

import time

from Scweet.api_engine import ApiEngine
from Scweet.cooldown import compute_cooldown


def _map(message, code=None, extensions=None):
    err = {"message": message}
    if code is not None:
        err["code"] = code
    if extensions:
        err["extensions"] = extensions
    return ApiEngine._map_graphql_errors_to_status([err])


class TestAMessageAboutOneTweetDoesNotBlockAnAccount:
    """X sends these while the session is healthy. Each one describes a single tweet."""

    def test_a_restricted_reply_is_not_an_authentication_failure(self):
        """The word `author` contains `auth`, so a substring test maps this to 401.

        X sends this for a normal tweet whose author limits who can reply. It is a common condition and not an
        error, so it must not cost the account 30 days.
        """
        assert _map("Tweet author restricted who can reply to this Tweet") != 401

    def test_an_unavailable_author_field_is_not_an_authentication_failure(self):
        assert _map("Tweet.author_id is unavailable") != 401

    def test_a_blocked_author_is_not_an_authentication_failure(self):
        assert _map("You are blocked from viewing this author") != 401

    def test_a_denied_tweet_of_a_protected_account_is_not_an_authentication_failure(self):
        """X sends this for one tweet of a protected account. The phrase holds "authorization"."""
        assert _map("Authorization: Denied by access control") != 401

    def test_a_tweet_that_the_account_cannot_view_is_not_an_authentication_failure(self):
        assert _map("Not authorized to view this Tweet") != 401

    def test_a_routine_message_does_not_reach_the_cooldown_of_30_days(self):
        """The complete chain: the message of X, then the status, then the cooldown of the account."""
        status = _map("Tweet author restricted who can reply to this Tweet")
        _status, until_ts, reason = compute_cooldown(status, headers=None, config=None)
        assert reason != "auth_failed"
        assert (until_ts - time.time()) / 86400.0 < 1.0


class TestARealAuthenticationFailureStillBlocks:
    """The correction must not hide a credential that is really dead."""

    def test_an_invalid_token_maps_to_401(self):
        """Captured from the live API of X on 2026-09-04, with code 89."""
        assert _map("Invalid or expired token", code=89) == 401

    def test_a_failure_to_authenticate_maps_to_401(self):
        """Captured from the live API of X on 2026-09-04, with code 32."""
        assert _map("Could not authenticate you", code=32) == 401

    def test_the_code_alone_maps_to_401_when_x_changes_the_message(self):
        """The numeric code is the durable signal, because X can reword a message at any time."""
        assert _map("some new wording from X", code=89) == 401
        assert _map("some new wording from X", code=32) == 401

    def test_a_code_without_evidence_maps_to_nothing(self):
        """Only a code from a captured answer belongs in the set. A guess costs the account 30 days."""
        assert _map("something happened", code=144) is None
        assert _map("something happened", code=421) is None

    def test_an_unauthorized_message_maps_to_401(self):
        assert _map("Unauthorized") == 401

    def test_an_authorization_failure_maps_to_401(self):
        assert _map("Authorization failed") == 401

    def test_the_code_of_an_extension_maps_to_401(self):
        assert _map("something else", extensions={"code": "UNAUTHORIZED"}) == 401
        assert _map("something else", extensions={"errorType": "AUTHENTICATION_ERROR"}) == 401


class TestTheOtherStatusCodesStayCorrect:
    def test_a_rate_limit_maps_to_429(self):
        assert _map("Rate limit exceeded") == 429

    def test_too_many_requests_maps_to_429(self):
        assert _map("Too Many Requests") == 429

    def test_a_suspended_account_maps_to_403(self):
        assert _map("Your account is suspended") == 403

    def test_a_forbidden_message_maps_to_403(self):
        assert _map("Forbidden") == 403

    def test_a_validation_error_of_our_own_request_maps_to_nothing(self):
        """Captured from X on 2026-09-04. `code` is a string here, so the check of the numeric code must not
        raise and must not treat it as a failure of authentication."""
        assert (
            ApiEngine._map_graphql_errors_to_status(
                [
                    {
                        "code": "GRAPHQL_VALIDATION_FAILED",
                        "extensions": {"code": "GRAPHQL_VALIDATION_FAILED"},
                        "message": "must be defined",
                        "path": ["variable", "rawQuery"],
                    }
                ]
            )
            is None
        )

    def test_an_unknown_message_maps_to_nothing(self):
        assert _map("Some new message from X") is None

    def test_an_empty_list_maps_to_nothing(self):
        assert ApiEngine._map_graphql_errors_to_status([]) is None
        assert ApiEngine._map_graphql_errors_to_status(None) is None

    def test_a_rate_limit_wins_over_an_authentication_message(self):
        """X can send both. A rate limit is transient, so it must not retire the account."""
        errors = [{"message": "Rate limit exceeded"}, {"message": "Invalid or expired token", "code": 89}]
        assert ApiEngine._map_graphql_errors_to_status(errors) == 429
