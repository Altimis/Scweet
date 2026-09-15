"""
Scweet — sync example.

The first path uses one value: the auth_token cookie of a logged-in account.
Copy it from your browser (DevTools > Application > Cookies > x.com), and Scweet
builds the rest. Replace the placeholder before you run.

It shows: search and its filters, tweets by id, replies and reposters, profile
tweets and media, followers and following, user info by handle and by id, a
people search, the trends, and the state of the pool.
"""

from __future__ import annotations

import logging

from Scweet import Scweet, ScweetDB

# Optional: see what Scweet does.
logging.basicConfig(level=logging.INFO)


def main() -> None:
    # ── The first path: one auth_token ───────────────────────────────
    s = Scweet(auth_token="YOUR_AUTH_TOKEN")

    # For several accounts, or a proxy per account, use a file instead:
    #   s = Scweet(cookies_file="examples/cookies.json")
    # A proxy is optional for a small run and recommended for volume:
    #   s = Scweet(auth_token="YOUR_AUTH_TOKEN", proxy="http://user:pass@proxy.example.com:8000")
    # On the next run, reuse the accounts with no credential:
    #   s = Scweet()   # reads scweet_state.db

    # ── Search ───────────────────────────────────────────────────────
    # Always set `limit`. Without it, a run continues until the daily cap.
    tweets = s.search("python programming", limit=50)
    print(f"Search: {len(tweets)} tweets")
    if tweets:
        t = tweets[0]
        print(f"  first: {t['views']} views, lang={t['lang']}, {t['likes']} likes")

    # A date range. display_type="Latest" (the default) is chronological and fills
    # a volume order; "Top" is a ranked selection and holds far fewer tweets.
    tweets = s.search(
        "bitcoin", since="2026-01-01", until="2026-02-01", display_type="Latest", limit=100
    )
    print(f"Date range: {len(tweets)} tweets")

    # A query with structured filters, saved to disk.
    tweets = s.search(
        "AI tools",
        since="2026-01-01",
        from_users=["OpenAI"],
        any_words=["chatgpt", "claude", "gemini"],
        min_likes=50,
        has_images=True,
        lang="en",
        limit=100,
        save=True,           # writes a file
        save_format="both",  # csv + json
    )
    print(f"Filtered search: {len(tweets)} tweets")

    # ── Tweets by id, replies, reposters ─────────────────────────────
    if tweets:
        ids = [t["tweet_id"] for t in tweets[:5]]
        by_id = s.get_tweet_info(ids)          # up to 50 ids in one request
        print(f"Tweets by id: {len(by_id)}")

        replies = s.get_tweet_replies(ids[0], limit=50)
        print(f"Replies: {len(replies)}")

        reposters = s.get_reposters(ids[0], limit=100)
        print(f"Reposters: {len(reposters)}")

    # ── Profile tweets and media ─────────────────────────────────────
    tweets = s.get_profile_tweets(["elonmusk"], limit=100)
    print(f"Profile tweets: {len(tweets)}")

    with_replies = s.get_profile_tweets(["elonmusk"], limit=100, include_replies=True)
    print(f"Profile tweets with replies: {len(with_replies)}")

    media = s.get_profile_media(["nasa"], limit=100)
    print(f"Profile media: {len(media)}")

    # ── Followers, following, verified followers ─────────────────────
    followers = s.get_followers(["elonmusk"], limit=500)
    print(f"Followers: {len(followers)}")

    following = s.get_following(["OpenAI"], limit=200)
    print(f"Following: {len(following)}")

    verified = s.get_verified_followers(["elonmusk"], limit=200)
    print(f"Verified followers: {len(verified)}")

    # ── User info: by handle, or by numeric id ───────────────────────
    profiles = s.get_user_info(["elonmusk", "OpenAI"])
    for p in profiles:
        print(f"  @{p['username']}: {p['followers_count']} followers")

    profiles = s.get_user_info(user_ids=["44196397"])  # up to 100 ids in one request
    print(f"By id: {len(profiles)}")

    # ── People search and trends ─────────────────────────────────────
    people = s.search_users("python developer", limit=50)
    print(f"People: {len(people)}")

    trends = s.get_trending()
    print(f"Trends: {len(trends)}")

    # ── Keep the query ids fresh ─────────────────────────────────────
    # X rotates its GraphQL ids, and a stale id answers 404. Call this on a
    # schedule, or when requests start to fail.
    changes = s.refresh_manifest()
    print(f"Manifest ids that rotated: {list(changes)}")

    # ── The state of the pool ────────────────────────────────────────
    db = ScweetDB("scweet_state.db")
    print("Accounts:", db.accounts_summary())
    # Maintenance:
    # db.reset_daily_counters()
    # db.clear_leases(expired_only=True)
    # db.repair_account("my_account", force_refresh=True)


if __name__ == "__main__":
    main()
