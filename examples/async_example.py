"""
Scweet — async example.

Use this pattern in a notebook, a FastAPI or Starlette handler, or any
asyncio application. In an async context, use the `a`-prefixed methods
(asearch, aget_followers, ...). The sync methods call asyncio.run internally
and fail inside a running event loop.

The first path uses one value: the auth_token cookie of a logged-in account.
Replace the placeholder before you run.
"""

from __future__ import annotations

import asyncio
import logging

from Scweet import Scweet, ScweetDB

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    # The first path: one auth_token. For several accounts or a proxy per
    # account, use Scweet(cookies_file="examples/cookies.json") instead.
    s = Scweet(auth_token="YOUR_AUTH_TOKEN")

    # ── Search ───────────────────────────────────────────────────────
    # Always set `limit`. Without it, a run continues until the daily cap.
    tweets = await s.asearch("python programming", limit=50)
    print(f"Search: {len(tweets)} tweets")

    tweets = await s.asearch(
        "AI tools",
        since="2026-01-01",
        from_users=["OpenAI"],
        min_likes=50,
        limit=100,
        save=True,
        save_format="json",
    )
    print(f"Filtered search: {len(tweets)} tweets")

    # ── Tweets by id, replies, reposters ─────────────────────────────
    if tweets:
        ids = [t["tweet_id"] for t in tweets[:5]]
        print(f"Tweets by id: {len(await s.aget_tweet_info(ids))}")
        print(f"Replies: {len(await s.aget_tweet_replies(ids[0], limit=50))}")
        print(f"Reposters: {len(await s.aget_reposters(ids[0], limit=100))}")

    # ── Profiles, media, the social graph ────────────────────────────
    print(f"Profile tweets: {len(await s.aget_profile_tweets(['elonmusk'], limit=100))}")
    print(f"Profile media: {len(await s.aget_profile_media(['nasa'], limit=100))}")
    print(f"Followers: {len(await s.aget_followers(['elonmusk'], limit=500))}")
    print(f"Following: {len(await s.aget_following(['OpenAI'], limit=200))}")
    print(f"Verified followers: {len(await s.aget_verified_followers(['elonmusk'], limit=200))}")

    # ── User info, people search, trends ─────────────────────────────
    profiles = await s.aget_user_info(["elonmusk", "OpenAI"])
    for p in profiles:
        print(f"  @{p['username']}: {p['followers_count']} followers")
    print(f"People: {len(await s.asearch_users('python developer', limit=50))}")
    print(f"Trends: {len(await s.aget_trending())}")

    # ── The state of the pool ────────────────────────────────────────
    db = ScweetDB("scweet_state.db")
    print("Accounts:", db.accounts_summary())


if __name__ == "__main__":
    asyncio.run(main())
