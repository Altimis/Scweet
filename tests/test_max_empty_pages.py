"""The default of `max_empty_pages` reads past a stray empty page.

X sends an empty page in the middle of a chain while results remain. A value of 1 ends the interval at the first
gap and loses the rest, and the run reports success. This measures the fill on a fixture where empty pages fall
singly between data pages, and it fixes the default from the measurement.
"""

import asyncio
from types import SimpleNamespace

from Scweet.config import ScweetConfig
from Scweet.models import SearchRequest, SearchResult, TweetRecord
from Scweet.runner import Runner


class _AccountsRepo:
    def acquire_leases(self, count, run_id, worker_id_prefix):
        return [{"username": "acct-a", "lease_id": "lease-a"}]

    def record_usage(self, lease_id, pages=0, tweets=0):
        pass

    def release(self, lease_id, fields_to_set, fields_to_inc=None):
        return True


class _CorpusEngine:
    """Yields a fixed corpus: data, empty, data, empty, data, then empty for ever.

    Six tweets exist, split across three data pages, with a single empty page between each. After the data the
    chain ends, which X shows as empty pages that never stop.
    """

    def __init__(self):
        self.pages = [2, 0, 2, 0, 2]  # tweet counts per page; then infinite 0
        self.calls = 0

    async def search_tweets(self, request):
        n = self.pages[self.calls] if self.calls < len(self.pages) else 0
        self.calls += 1
        tweets = [TweetRecord(tweet_id=f"t-{self.calls}-{i}", text="x") for i in range(n)]
        return {
            "result": SearchResult(tweets=tweets),
            "cursor": f"C-{self.calls}",
            "continue_with_cursor": True,
            "status_code": 200,
            "headers": {},
        }


def _config(max_empty_pages):
    base = ScweetConfig(n_splits=1, concurrency=1, scheduler_min_interval_s=300, min_delay_s=0.0)
    return SimpleNamespace(**{**base.model_dump(), "max_empty_pages": max_empty_pages})


def _measure(max_empty_pages):
    engine = _CorpusEngine()
    runner = Runner(
        config=_config(max_empty_pages),
        repos={"accounts_repo": _AccountsRepo()},
        engines={"api_engine": engine},
        outputs=None,
    )

    async def _go():
        return await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="q",
                max_empty_pages=max_empty_pages,
            )
        )

    result = asyncio.run(_go())
    return result.stats.tweets_count, engine.calls


class TestTheDefaultReadsPastAStrayEmptyPage:
    def test_value_one_loses_data_after_the_first_empty_page(self):
        tweets, _calls = _measure(1)
        assert tweets == 2, "a value of 1 stops at the first empty page and loses the rest"

    def test_the_default_reads_the_whole_corpus(self):
        tweets, _calls = _measure(3)
        assert tweets == 6, "the default must read past the single empty pages and collect all six tweets"

    def test_a_higher_value_collects_no_more_and_wastes_requests(self):
        """5 reads the same six tweets but confirms the end with two more empty requests than 3 does."""
        tweets_3, calls_3 = _measure(3)
        tweets_5, calls_5 = _measure(5)
        assert tweets_5 == tweets_3 == 6
        assert calls_5 == calls_3 + 2, "5 wastes two more requests at the true end than 3"

    def test_the_shipped_default_is_three(self):
        assert ScweetConfig().max_empty_pages == 3
