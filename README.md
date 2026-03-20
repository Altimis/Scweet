[![Scweet Actor Status](https://apify.com/actor-badge?actor=altimis/scweet)](https://apify.com/altimis/scweet)
[![PyPI Downloads](https://static.pepy.tech/badge/scweet/month)](https://pepy.tech/projects/scweet)
[![PyPI Version](https://img.shields.io/pypi/v/scweet.svg)](https://pypi.org/project/scweet/)
[![License](https://img.shields.io/github/license/Altimis/scweet)](https://github.com/Altimis/scweet/blob/main/LICENSE)
[![Documentation](https://img.shields.io/badge/docs-DOCUMENTATION.md-blue)](DOCUMENTATION.md)

# Scweet

A Python library for scraping Twitter/X via its web GraphQL API. No official API access needed — just your browser cookies.

**What you can do:**

- **Search tweets** — by keyword, date range, user, hashtag, engagement filters, language, location. Supports raw [Twitter advanced search operators](https://github.com/igorbrigadir/twitter-advanced-search) as the query string
- **Profile tweets** — fetch a user's timeline
- **Followers / Following** — scrape follower and following lists
- **User info** — profile metadata (bio, follower count, verified status, etc.)
- **Multi-account pooling** — rotate across accounts with automatic rate limiting and cooldowns
- **Resume** — pick up interrupted scrapes from where they left off
- **Save to CSV / JSON** — built-in output persistence
- **Async support** — every method has a sync and async variant

## Installation

```bash
pip install -U Scweet
```

## Quick Start

**1. Get your cookies** — Log into Twitter/X, open DevTools (F12) → Application → Cookies → `https://x.com`, copy `auth_token` and `ct0`.

**2. Create `cookies.json`:**

```json
[{ "username": "your_account", "cookies": { "auth_token": "...", "ct0": "..." } }]
```

**3. Scrape:**

```python
from Scweet import Scweet

s = Scweet(cookies_file="cookies.json")

# Search tweets
tweets = s.search("python programming", limit=100)
tweets = s.search("AI", since="2024-01-01", until="2024-06-01", limit=500)

# Profile tweets
tweets = s.get_profile_tweets(["elonmusk", "OpenAI"], limit=200)

# Followers / Following
users = s.get_followers(["elonmusk"], limit=1000)
users = s.get_following(["OpenAI"], limit=500)

# User info
profiles = s.get_user_info(["elonmusk", "OpenAI"])
```

> **Tip:** Always set `limit` — without it, scraping continues until results are exhausted or daily account caps are hit.

> **Don't want to manage accounts and proxies?** Scweet is also available as a [hosted actor on Apify](https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97) — no setup, no cookies, free tier included.

## Structured Search Filters

```python
tweets = s.search(
    since="2024-01-01",
    from_users=["OpenAI"],
    min_likes=50,
    has_links=True,
    lang="en",
    limit=200,
)
```

Available filters: `all_words`, `any_words`, `exact_phrases`, `exclude_words`, `hashtags_any`, `from_users`, `to_users`, `mentioning_users`, `tweet_type`, `verified_only`, `has_images`, `has_videos`, `has_links`, `min_likes`, `min_replies`, `min_retweets`, `place`, `geocode`, and more. See [Full Documentation](DOCUMENTATION.md).

## Other Account Sources

```python
s = Scweet(cookies={"auth_token": "...", "ct0": "..."})           # Direct cookies
s = Scweet(auth_token="YOUR_AUTH_TOKEN")                           # Auth token only (ct0 bootstrapped)
s = Scweet(cookies=[{"auth_token": "t1", "ct0": "c1"}, ...])      # Multi-account pool
s = Scweet(db_path="scweet_state.db")                              # Reuse provisioned accounts
```

## Configuration

```python
from Scweet import Scweet, ScweetConfig

s = Scweet(
    cookies_file="cookies.json",
    config=ScweetConfig(
        concurrency=3,
        proxy="http://user:pass@host:port",
        daily_requests_limit=50,
        manifest_scrape_on_init=True,
    ),
)
```

| Field | Default | Description |
|-------|---------|-------------|
| `concurrency` | `5` | Parallel workers |
| `proxy` | `None` | HTTP proxy for API calls |
| `min_delay_s` | `2.0` | Minimum delay between requests |
| `daily_requests_limit` | `30` | Max API requests per account per day |
| `daily_tweets_limit` | `600` | Max tweets per account per day |
| `manifest_scrape_on_init` | `False` | Auto-fetch fresh GraphQL query IDs on startup |

For output formats, resume, async patterns, account management, and the full config reference — see [Full Documentation](DOCUMENTATION.md).

## Saving Results

```python
tweets = s.search("bitcoin", since="2024-01-01", limit=200, save=True)
# → outputs/bitcoin_2024-01-01_2024-03-20.csv

tweets = s.search("AI", limit=200, save=True, save_format="json")
# → outputs/AI_2024-03-13_2024-03-20.json

tweets = s.search("query", limit=200, save=True, save_name="my_results")
# → outputs/my_results.csv
```

Files are written to `outputs/` by default (configurable via `ScweetConfig(save_dir="my_dir")`). File names are auto-generated from the query and date range, or you can set `save_name` explicitly. Results append to existing files.

## Async Support

```python
import asyncio
from Scweet import Scweet

async def main():
    s = Scweet(cookies_file="cookies.json")
    tweets = await s.asearch("python", limit=100)
    users = await s.aget_followers(["elonmusk"], limit=500)

asyncio.run(main())
```

All methods: `asearch()`, `aget_profile_tweets()`, `aget_followers()`, `aget_following()`, `aget_user_info()`.

## Important Notes

- This is scraping (Twitter/X web GraphQL), not an official API. Behavior may change.
- You need X account cookies. Rate limits and anti-bot measures are enforced by X.
- Use responsibly and in compliance with applicable terms and laws.

## Contributing

PRs, bug reports, and feature suggestions are welcome!
If you find Scweet useful, consider starring the repo.

---
MIT License
