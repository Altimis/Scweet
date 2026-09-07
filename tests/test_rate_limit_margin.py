"""An account hands off a margin above the rate-limit window, so it does not hit 429.

X returns `x-rate-limit-remaining` on each page. The count can lag, so X can answer 429 one request before the
header reaches zero. A 429 loses the page and forces a retry. The run stops an account when the header falls to
`rate_limit_min_remaining` and rests it until its window resets, and the cursor continues on a fresh account. A
live 20,000-tweet order lost about 10% of the data to 429s that this margin prevents.
"""

import asyncio
from types import SimpleNamespace

from Scweet.config import ScweetConfig
from Scweet.models import SearchRequest, SearchResult, TweetRecord
from Scweet.runner import Runner

# X reports a countdown from this value, but it rejects the request at REJECT_AT, one earlier than the header
# reaching zero. So a run that waits for the header to reach zero meets a 429; a margin stops before it.
REPORTED_START = 5
REJECT_AT = 4  # the (per-account) request number at which X answers 429


class _AccountsRepo:
    def __init__(self, count):
        self.count = count

    def acquire_leases(self, count, run_id, worker_id_prefix):
        return [{"username": f"a{i}", "lease_id": f"L{i}"} for i in range(self.count)]

    def record_usage(self, lease_id, pages=0, tweets=0):
        pass

    def release(self, lease_id, fields_to_set, fields_to_inc=None):
        return True


class _WindowedEngine:
    """A corpus paged by a cursor. Each account has its own request budget and its own countdown."""

    def __init__(self, total, page):
        self.page = page
        self.total = total
        self.per_account = {}
        self.issued_429 = False
        self.min_remaining_on_200 = REPORTED_START

    async def search_tweets(self, request):
        acct = (request.get("_leased_account") or {}).get("username", "?")
        n = self.per_account.get(acct, 0) + 1
        self.per_account[acct] = n
        if n >= REJECT_AT:
            self.issued_429 = True
            return {
                "result": SearchResult(),
                "cursor": request.get("cursor"),
                "status_code": 429,
                "headers": {"x-rate-limit-remaining": "0", "x-rate-limit-reset": "1893456000"},
            }
        cur = request.get("cursor")
        off = int(cur.split(":")[1]) if isinstance(cur, str) and cur.startswith("off:") else 0
        page = [TweetRecord(tweet_id=f"t{off + i}", text="x") for i in range(self.page) if off + i < self.total]
        remaining = REPORTED_START - n
        self.min_remaining_on_200 = min(self.min_remaining_on_200, remaining)
        more = off + self.page < self.total
        return {
            "result": SearchResult(tweets=page),
            "cursor": f"off:{off + self.page}" if more else None,
            "continue_with_cursor": more,
            "status_code": 200,
            "headers": {"x-rate-limit-remaining": str(remaining), "x-rate-limit-reset": "1893456000"},
        }


def _run(margin, total=10, page=2, accounts=6):
    base = ScweetConfig(
        n_splits=1,
        concurrency=accounts,
        # A floor larger than the time range forces exactly one interval, so the cursor handoff between accounts
        # is the only parallelism. This isolates the margin from the one-interval-per-account rule.
        scheduler_min_interval_s=200000,
        min_delay_s=0.0,
        api_page_size=page,
        max_empty_pages=1,
        max_interval_depth=0,
        rate_limit_min_remaining=margin,
        daily_tweets_limit=10 ** 9,
        daily_requests_limit=10 ** 9,
    )
    engine = _WindowedEngine(total, page)
    runner = Runner(
        config=SimpleNamespace(**base.model_dump()),
        repos={"accounts_repo": _AccountsRepo(accounts)},
        engines={"api_engine": engine},
        outputs=None,
    )

    async def _go():
        return await asyncio.wait_for(
            runner.run_search(
                SearchRequest(
                    since="2026-06-01_00:00:00_UTC",
                    until="2026-06-02_00:00:00_UTC",
                    search_query="q",
                    display_type="Latest",
                    limit=total,
                )
            ),
            timeout=20,
        )

    return asyncio.run(_go()), engine


class TestTheMarginHandsOffBeforeA429:
    def test_the_margin_avoids_the_429_and_collects_the_corpus(self):
        result, engine = _run(margin=2)
        assert engine.issued_429 is False, "the margin must hand off before X answers 429"
        assert engine.min_remaining_on_200 >= 2, (
            f"the run pushed an account below the margin; min remaining {engine.min_remaining_on_200}"
        )
        assert result.stats.tweets_count == 10, (
            f"the cursor must continue on a fresh account and collect all tweets; got {result.stats.tweets_count}"
        )

    def test_without_the_margin_the_run_meets_a_429(self):
        """The mutation: a margin of 0 waits for the window to empty, so it meets the 429 the margin prevents."""
        _result, engine = _run(margin=0)
        assert engine.issued_429 is True, "with no margin the account runs into the 429"
