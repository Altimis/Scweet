"""
Scweet v4 (async) example.

Use this pattern in:
- notebooks/Jupyter (use `await ...` directly)
- FastAPI/Starlette handlers
- any asyncio-based application

Important:
- In an async environment, do NOT call `scrape()` because it uses asyncio.run(...).
- Use `await ascrape(...)` instead.
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

    tweets = await scweet.ascrape(
        since="2026-02-01",
        until="2026-02-07",
        words=["bitcoin"],
        limit=50,
        resume=True,
        save_dir=str(outputs_dir),
        custom_csv_name="async_bitcoin.csv",
        display_type="Latest",
    )
    print("tweets:", len(tweets))

    # Optional: explicitly close the underlying HTTP engine/session pool.
    await scweet.aclose()


if __name__ == "__main__":
    asyncio.run(main())
