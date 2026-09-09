"""The followers paths hold their own window budget.

X allows 50 requests in a window at the graph endpoint and restricts an account there more easily than at
a search (measured 2026-09-07). A follows run that spends the whole search budget of 50 leaves no margin,
and the graph endpoint locks an account silently.
"""

from Scweet.api_engine import ApiEngine
from Scweet.config import ScweetConfig


def _engine(config):
    return ApiEngine(config=config, accounts_repo=None, manifest_provider=None, session_factory=lambda: object())


def test_the_default_budget_keeps_a_margin_of_five():
    assert ScweetConfig().relationship_window_request_limit == 45


def test_follows_read_their_own_key():
    engine = _engine({"window_request_limit": 50, "relationship_window_request_limit": 7})
    assert engine._relationship_window_limit() == 7


def test_follows_never_fall_back_to_the_search_budget():
    engine = _engine({"window_request_limit": 50})
    assert engine._relationship_window_limit() == 45
