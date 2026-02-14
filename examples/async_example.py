"""
Scweet v4 (async) example.

Use this pattern in:
- notebooks/Jupyter (use `await ...` directly)
- FastAPI/Starlette handlers
- any asyncio-based application

Important:
- In an async environment, do NOT call `scrape()` because it uses asyncio.run(...).
- Use `await asearch(...)` (or `await ascrape(...)` for legacy code) instead.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from Scweet import Scweet, ScweetConfig, ScweetDB


async def main() -> None:
    root = Path(__file__).resolve().parents[1]
    examples_dir = root / "examples"
    db_path = root / "scweet_state.db"
    outputs_dir = root / "outputs"

    cfg = ScweetConfig.from_sources(
        db_path=str(db_path),
        cookies_file=str(examples_dir / "cookies.json"),
        # cookies={"auth_token": "...", "ct0": "..."},
        # cookies="YOUR_AUTH_TOKEN",
        provision_on_init=True,
        output_format="both",
        overrides={
            "pool": {"concurrency": 4},
            "operations": {"account_requests_per_min": 30},
            "output": {"dedupe_on_resume_by_tweet_id": True},
        },
    )

    scweet = Scweet(config=cfg)

    # Optional: set/override a per-account proxy in the DB (applies to API calls for that account).
    # ScweetDB(str(db_path)).set_account_proxy("acct-a", {"host": "127.0.0.1", "port": 8080})

    # Calls are in-memory by default (`save=False`).
    # To write files, set save=True (and optionally save_format).

    tweets = await scweet.asearch(
        since="2026-02-01",
        until="2026-02-07",
        search_query="bitcoin",
        any_words=["btc", "bitcoin"],
        min_likes=20,
        has_images=True,
        limit=50,
        resume=True,
        save_dir=str(outputs_dir),
        custom_csv_name="async_bitcoin.csv",
        save=True,
        save_format="both",
        display_type="Latest",
    )
    print("tweets:", len(tweets))

    profile_result = await scweet.aget_user_information(
        usernames=["elonmusk"],
        profile_urls=["https://x.com/OpenAI"],
        include_meta=True,
        save_dir=str(outputs_dir),
        custom_csv_name="async_profiles_info.csv",
        save=True,
        save_format="both",
    )
    print("user_info.items:", len(profile_result.get("items") or []))
    print("user_info.resolved:", (profile_result.get("meta") or {}).get("resolved"))

    profile_tweets = await scweet.aprofile_tweets(
        usernames=["OpenAI", "elonmusk"],
        profile_urls=["https://x.com/OpenAI"],
        limit=200,
        per_profile_limit=100,
        max_pages_per_profile=20,
        resume=True,
        # offline=True,  # optional: scrape without accounts (best-effort, usually limited pages)
        cursor_handoff=True,
        max_account_switches=2,
        save_dir=str(outputs_dir),
        custom_csv_name="async_profiles_timeline.csv",
        save=True,
        save_format="both",
    )
    print("profile_tweets:", len(profile_tweets))

    followers = await scweet.aget_followers(
        usernames=["OpenAI", "elonmusk"],
        profile_urls=["https://x.com/OpenAI"],
        user_ids=["44196397"],  # optional: target by id directly
        limit=200,
        per_profile_limit=100,
        max_pages_per_profile=20,
        resume=True,
        cursor_handoff=True,
        max_account_switches=2,
        save_dir=str(outputs_dir),
        custom_csv_name="async_followers.csv",
        save=True,
        save_format="csv",
        # raw_json=True,   # when save_format includes json, emit full payload rows under `raw`
    )
    print("followers:", len(followers))

    following = await scweet.aget_following(
        usernames=["OpenAI"],
        profile_urls=["https://x.com/elonmusk"],
        limit=100,
        per_profile_limit=100,
        max_pages_per_profile=20,
        resume=True,
        cursor_handoff=True,
        max_account_switches=2,
        save_dir=str(outputs_dir),
        custom_csv_name="async_following.csv",
        save=True,
        save_format="csv",
        # raw_json=True,
    )
    print("following:", len(following))

    # Optional: explicitly close the underlying HTTP engine/session pool.
    await scweet.aclose()


if __name__ == "__main__":
    asyncio.run(main())
