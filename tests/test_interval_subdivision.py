"""A cursor chain that ends while tweets remain triggers a split of the interval.

X stops a cursor chain at a depth limit while the time range still holds tweets. The chain ends on a full page
with no cursor, and the rest of the range is never fetched. The engine now splits the interval and re-queries
each half, down to a floor. The global set of seen tweet ids drops the overlap, so a narrower half that
re-fetches a tweet the parent already returned adds nothing twice.
"""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

from Scweet.config import ScweetConfig
from Scweet.models import SearchRequest, SearchResult, TweetRecord
from Scweet.runner import Runner
from Scweet.scheduler import subdivide_interval

_FMT = "%Y-%m-%d_%H:%M:%S_UTC"


class TestSubdivideInterval:
    def test_it_halves_a_wide_interval(self):
        halves = subdivide_interval("2026-06-01_00:00:00_UTC", "2026-06-02_00:00:00_UTC", 300)
        assert halves == [
            ("2026-06-01_00:00:00_UTC", "2026-06-01_12:00:00_UTC"),
            ("2026-06-01_12:00:00_UTC", "2026-06-02_00:00:00_UTC"),
        ]

    def test_it_refuses_to_split_below_the_floor(self):
        assert subdivide_interval("2026-06-01_00:00:00_UTC", "2026-06-01_00:06:40_UTC", 300) == []


class _AccountsRepo:
    def acquire_leases(self, count, run_id, worker_id_prefix):
        return [{"username": f"a{i}", "lease_id": f"L{i}"} for i in range(max(1, count))]

    def record_usage(self, lease_id, pages=0, tweets=0):
        pass

    def release(self, lease_id, fields_to_set, fields_to_inc=None):
        return True


class _CorpusEngine:
    """A realistic corpus. Tweets are spread across the day, and X truncates a dense range.

    For a range, the engine returns the tweets whose timestamp falls inside it, newest first, capped at one page.
    A range with more tweets than a page returns a full page and no cursor, which is the truncation signal. A
    range that fits inside a page returns a partial page, which does not trigger a split. So a wide range splits
    and a narrow range stops, exactly as a real chain converges.
    """

    def __init__(self, total_tweets: int, day_start: str, day_end: str, page: int):
        self.page = page
        self.calls = 0
        start = datetime.strptime(day_start, _FMT)
        end = datetime.strptime(day_end, _FMT)
        step = (end - start) / total_tweets
        # One tweet at the middle of each equal slice of the day.
        self.corpus = [
            (start + step * i + step / 2, f"tweet-{i}") for i in range(total_tweets)
        ]

    async def search_tweets(self, request):
        self.calls += 1
        since = datetime.strptime(request["since"], _FMT)
        until = datetime.strptime(request["until"], _FMT)
        in_range = [(ts, tid) for ts, tid in self.corpus if since <= ts < until]
        in_range.sort(reverse=True)  # newest first, as X returns
        page = in_range[: self.page]
        # Stamp each tweet with the real X time format, so the runner can continue from the oldest.
        tweets = [
            TweetRecord(tweet_id=tid, text="x", timestamp=ts.strftime("%a %b %d %H:%M:%S +0000 %Y"))
            for ts, tid in page
        ]
        return {
            "result": SearchResult(tweets=tweets),
            # A truncated range gives a full page and no cursor; a fitting range gives a partial page.
            "cursor": None,
            "continue_with_cursor": False,
            "status_code": 200,
            "headers": {},
        }


def _config(max_interval_depth, page=5):
    base = ScweetConfig(
        n_splits=1,
        # One account, so the run makes exactly one initial interval. This isolates the split of a truncated
        # interval from the rule that gives one interval per account. See TestOneIntervalPerAccount.
        concurrency=1,
        scheduler_min_interval_s=300,
        min_delay_s=0.0,
        api_page_size=page,
        max_empty_pages=1,
        max_interval_depth=max_interval_depth,
    )
    return SimpleNamespace(**base.model_dump())


DAY_START = "2026-06-01_00:00:00_UTC"
DAY_END = "2026-06-02_00:00:00_UTC"
TOTAL = 40
PAGE = 5


def _run(max_interval_depth, display_type="Latest"):
    engine = _CorpusEngine(TOTAL, DAY_START, DAY_END, PAGE)
    runner = Runner(
        config=_config(max_interval_depth, PAGE),
        repos={"accounts_repo": _AccountsRepo()},
        engines={"api_engine": engine},
        outputs=None,
    )

    async def _go():
        return await asyncio.wait_for(
            runner.run_search(
                SearchRequest(
                    since=DAY_START, until=DAY_END, search_query="q", display_type=display_type
                )
            ),
            timeout=30,
        )

    return asyncio.run(_go()), engine


class TestTheRunSplitsATruncatedInterval:
    def test_without_division_only_one_page_is_collected(self):
        result, _engine = _run(max_interval_depth=0)
        assert result.stats.tweets_count == PAGE, (
            "with division off, a truncated interval returns only one page and loses the rest"
        )

    def test_with_division_the_run_collects_the_whole_corpus(self):
        result, engine = _run(max_interval_depth=8)
        assert result.stats.tweets_count == TOTAL, (
            f"division must recover all {TOTAL} tweets; got {result.stats.tweets_count}"
        )
        assert engine.calls > 1

    def test_continuing_from_the_oldest_tweet_costs_few_requests(self):
        """The run narrows from the oldest tweet, not by halving, so it spends about one request per page.

        40 tweets at 5 per page need about 8 pages. Halving with overlap would cost far more. A tight bound
        proves the narrowing path runs, not the wasteful halving fallback.
        """
        result, engine = _run(max_interval_depth=8)
        assert result.stats.tweets_count == TOTAL
        assert engine.calls <= 12, (
            f"expected about 8 requests by narrowing from the oldest tweet; got {engine.calls}"
        )

    def test_a_deeper_cap_collects_at_least_as_much(self):
        shallow, _ = _run(max_interval_depth=1)
        deep, _ = _run(max_interval_depth=8)
        assert deep.stats.tweets_count > shallow.stats.tweets_count

    def test_a_genuine_end_does_not_split(self):
        """A range that fits inside one page ends genuinely, with a partial last page. It must not split.

        Splitting a range that already returned everything wastes requests. The trigger is a full last page, so
        a sparse range makes exactly one call.
        """
        engine = _CorpusEngine(total_tweets=3, day_start=DAY_START, day_end=DAY_END, page=PAGE)
        runner = Runner(
            config=_config(max_interval_depth=8, page=PAGE),
            repos={"accounts_repo": _AccountsRepo()},
            engines={"api_engine": engine},
            outputs=None,
        )

        async def _go():
            return await asyncio.wait_for(
                runner.run_search(SearchRequest(since=DAY_START, until=DAY_END, search_query="q")),
                timeout=20,
            )

        result = asyncio.run(_go())
        assert result.stats.tweets_count == 3
        assert engine.calls == 1, "a sparse range must not split; it made more than one call"


def _truncated_task(display_type):
    """A task whose interval ended on a full page, ready for a continuation decision."""
    return {
        "task_id": "t",
        "interval_depth": 0,
        "query": {
            "raw": {"search_query": "q", "display_type": display_type},
            "since": DAY_START,
            "until": DAY_END,
            "cursor": None,
        },
    }


class TestTheSortDecidesTheContinuation:
    """A `Latest` search continues a truncated interval. A `Top` search does not.

    A `Latest` search returns tweets newest first, so the run narrows from the oldest tweet and re-queries only
    the older part. A `Top` search ranks tweets by engagement, so the top tweets of a range and the top tweets
    of each half are mostly the same tweets. A live 20,000-tweet Top order that halved read 767 pages for 1,873
    unique tweets, which is 88% waste. So the run does not continue a Top interval.
    """

    def test_a_latest_interval_continues(self):
        tasks = Runner._build_subdivision_tasks(
            _truncated_task("Latest"),
            min_interval_s=300,
            max_depth=8,
            oldest_seen="Wed Jun 15 12:00:00 +0000 2026",
        )
        assert tasks, "a truncated Latest interval must produce a continuation"

    def test_a_top_interval_does_not_continue(self):
        tasks = Runner._build_subdivision_tasks(
            _truncated_task("Top"),
            min_interval_s=300,
            max_depth=8,
            oldest_seen="Wed Jun 15 12:00:00 +0000 2026",
        )
        assert tasks == [], (
            "a Top interval must not be continued, because halving a ranked result re-fetches the same tweets"
        )

    def test_the_default_sort_top_does_not_continue(self):
        # The default display_type is Top, so a caller who does not set the sort gets the Top behaviour.
        task = _truncated_task("Top")
        task["query"]["raw"].pop("display_type")
        tasks = Runner._build_subdivision_tasks(
            task, min_interval_s=300, max_depth=8, oldest_seen="Wed Jun 15 12:00:00 +0000 2026"
        )
        assert tasks == []


class _CountingAccountsRepo:
    """Records the number of accounts asked for, and hands out that many."""

    def __init__(self):
        self.requested = None

    def acquire_leases(self, count, run_id, worker_id_prefix):
        self.requested = count
        return [{"username": f"a{i}", "lease_id": f"L{i}"} for i in range(max(1, count))]

    def record_usage(self, lease_id, pages=0, tweets=0):
        pass

    def release(self, lease_id, fields_to_set, fields_to_inc=None):
        return True


class TestOneIntervalPerAccount:
    """The run splits the range into at least one interval per account, so no account stays idle.

    The narrowing of a truncated interval is serial, so the initial split is the only source of parallelism
    across accounts. If the run makes fewer intervals than accounts, the extra accounts do no work, and each
    active account exhausts its request budget on a dense interval.
    """

    def _count_initial_tasks(self, n_splits, concurrency):
        base = ScweetConfig(
            n_splits=n_splits,
            concurrency=concurrency,
            scheduler_min_interval_s=300,
            min_delay_s=0.0,
            api_page_size=5,
            max_empty_pages=1,
            max_interval_depth=0,  # off, so only the initial split makes tasks
        )
        engine = _CorpusEngine(TOTAL, DAY_START, DAY_END, PAGE)
        runner = Runner(
            config=SimpleNamespace(**base.model_dump()),
            repos={"accounts_repo": _CountingAccountsRepo()},
            engines={"api_engine": engine},
            outputs=None,
        )

        async def _go():
            return await asyncio.wait_for(
                runner.run_search(
                    SearchRequest(since=DAY_START, until=DAY_END, search_query="q", display_type="Latest")
                ),
                timeout=20,
            )

        return asyncio.run(_go())

    def test_more_accounts_than_splits_makes_one_interval_per_account(self):
        # n_splits=1 but 4 accounts: without the rule the run makes 1 interval and 3 accounts idle.
        result = self._count_initial_tasks(n_splits=1, concurrency=4)
        assert result.stats.tasks_total >= 4, (
            f"the run must make at least one interval per account; got {result.stats.tasks_total} for 4 accounts"
        )

    def test_more_splits_than_accounts_keeps_the_splits(self):
        # n_splits=6 with 2 accounts: the larger split count wins, so depth of coverage is not lost.
        result = self._count_initial_tasks(n_splits=6, concurrency=2)
        assert result.stats.tasks_total >= 6
