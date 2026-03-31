"""
Scweet v5 — async example.

Use this pattern in:
- Notebooks / Jupyter (use `await` directly)
- FastAPI / Starlette handlers
- Any asyncio-based application

Important: In an async context, use the async variants (asearch, aget_followers, etc.).
The sync methods use asyncio.run() internally and will fail inside a running event loop.
"""

from __future__ import annotations

import asyncio
import logging

from Scweet import Scweet, ScweetConfig, ScweetDB

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    s = Scweet(
        cookies_file="examples/cookies.json",
        proxy="http://user:pass@host:port",       # recommended — use a dedicated proxy
        config=ScweetConfig(
            concurrency=3,
            manifest_scrape_on_init=True,
        ),
    )

    # ── Search ───────────────────────────────────────────────────────
    #
    # Always set `limit` — without it, scraping continues until
    # results are exhausted or account daily caps are hit.

    tweets = await s.asearch("python programming", limit=50)
    print(f"Search: {len(tweets)} tweets")

    # With structured filters
    tweets = await s.asearch(
        since="2025-01-01",
        from_users=["OpenAI"],
        min_likes=50,
        has_links=True,
        limit=100,
        save=True,
        save_format="json",
    )
    print(f"Filtered search: {len(tweets)} tweets")

    # ── Profile tweets ───────────────────────────────────────────────

    tweets = await s.aget_profile_tweets(["elonmusk", "OpenAI"], limit=200)
    print(f"Profile tweets: {len(tweets)} tweets")

    # ── Followers / Following ────────────────────────────────────────

    followers = await s.aget_followers(["elonmusk"], limit=500)
    print(f"Followers: {len(followers)} users")

    following = await s.aget_following(["OpenAI"], limit=200)
    print(f"Following: {len(following)} users")

    # ── User info ────────────────────────────────────────────────────

    profiles = await s.aget_user_info(["elonmusk", "OpenAI"])
    for p in profiles:
        print(f"  @{p.get('username')}: {p.get('followers_count')} followers")

    # ── DB inspection ────────────────────────────────────────────────

    db = ScweetDB("scweet_state.db")
    print("Summary:", db.accounts_summary())


if __name__ == "__main__":
    asyncio.run(main())
