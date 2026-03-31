"""
Scweet v5 — sync example.

Demonstrates:
- Initializing Scweet with cookies
- Searching tweets (with and without structured filters)
- Profile tweets, followers, following, user info
- Saving results to disk
- Inspecting DB state via ScweetDB

Replace placeholders with your real cookies before running.
"""

from __future__ import annotations

import logging

from Scweet import Scweet, ScweetConfig, ScweetDB

# Optional: enable logging to see what Scweet is doing
logging.basicConfig(level=logging.INFO)


def main() -> None:
    # ── Initialize ───────────────────────────────────────────────────
    #
    # Pick one way to provide cookies:
    #   Scweet(cookies_file="cookies.json")
    #   Scweet(auth_token="YOUR_AUTH_TOKEN")
    #   Scweet(cookies={"auth_token": "...", "ct0": "..."})
    #   Scweet(db_path="scweet_state.db")  # reuse previously provisioned accounts
    #
    s = Scweet(
        cookies_file="examples/cookies.json",
        proxy="http://user:pass@host:port",       # recommended — use a dedicated proxy
        config=ScweetConfig(
            concurrency=3,
            daily_requests_limit=50,
            manifest_scrape_on_init=True,  # auto-fetch fresh GraphQL query IDs
        ),
    )

    # ── Search tweets ────────────────────────────────────────────────
    #
    # Always set `limit` — it controls the max items to collect.
    # Without it, scraping continues until results are exhausted
    # or your account's daily caps are hit.

    # Simple query (defaults to last 7 days)
    tweets = s.search("python programming", limit=50)
    print(f"Simple search: {len(tweets)} tweets")

    # With date range
    tweets = s.search("bitcoin", since="2025-01-01", until="2025-02-01", limit=100)
    print(f"Date range search: {len(tweets)} tweets")

    # Structured filters
    tweets = s.search(
        since="2025-01-01",
        from_users=["elonmusk"],
        min_likes=100,
        has_images=True,
        lang="en",
        display_type="Latest",
        limit=100,
    )
    print(f"Filtered search: {len(tweets)} tweets")

    # Combining query + filters
    tweets = s.search(
        "AI tools",
        since="2025-01-01",
        any_words=["chatgpt", "claude", "gemini"],
        exclude_words=["spam"],
        min_likes=50,
        limit=200,
    )
    print(f"Combined search: {len(tweets)} tweets")

    # Save results to disk
    tweets = s.search(
        "machine learning",
        since="2025-01-01",
        limit=100,
        save=True,                # write to disk
        save_format="both",       # csv + json
    )
    print(f"Saved search: {len(tweets)} tweets")

    # Resume an interrupted search
    tweets = s.search("bitcoin", since="2025-01-01", until="2025-06-01", limit=500, resume=True)
    print(f"Resumed search: {len(tweets)} tweets")

    # ── Profile tweets ───────────────────────────────────────────────

    tweets = s.get_profile_tweets(["elonmusk", "OpenAI"], limit=100)
    print(f"Profile tweets: {len(tweets)} tweets")

    # ── Followers / Following ────────────────────────────────────────

    followers = s.get_followers(["elonmusk"], limit=500)
    print(f"Followers: {len(followers)} users")

    following = s.get_following(["OpenAI"], limit=200)
    print(f"Following: {len(following)} users")

    # With raw JSON payload (full GraphQL user objects)
    followers = s.get_followers(["elonmusk"], limit=100, raw_json=True)
    if followers:
        print(f"Raw follower keys: {list(followers[0].keys())}")

    # ── User info (no limit needed — one API call per user) ────────

    profiles = s.get_user_info(["elonmusk", "OpenAI"])
    for p in profiles:
        print(f"  @{p.get('username')}: {p.get('followers_count')} followers")

    # ── DB inspection ────────────────────────────────────────────────

    db = ScweetDB("scweet_state.db")
    print("Accounts summary:", db.accounts_summary())
    print("Eligible accounts:", db.list_accounts(limit=5, eligible_only=True))

    # Maintenance helpers:
    # db.reset_daily_counters()
    # db.clear_leases(expired_only=True)
    # db.reset_account_cooldowns()
    # db.repair_account("my_account", force_refresh=True)


if __name__ == "__main__":
    main()
