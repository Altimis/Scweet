[![Tests](https://github.com/Altimis/Scweet/actions/workflows/tests.yml/badge.svg)](https://github.com/Altimis/Scweet/actions/workflows/tests.yml)
[![PyPI Version](https://img.shields.io/pypi/v/scweet.svg)](https://pypi.org/project/scweet/)
[![PyPI Downloads](https://static.pepy.tech/badge/scweet/month)](https://pepy.tech/projects/scweet)
[![Stars](https://img.shields.io/github/stars/Altimis/Scweet)](https://github.com/Altimis/Scweet/stargazers)
[![License](https://img.shields.io/github/license/Altimis/scweet)](https://github.com/Altimis/scweet/blob/main/LICENSE)
[![Scweet Actor Status](https://apify.com/actor-badge?actor=altimis/scweet)](https://apify.com/altimis/scweet)

# Scweet — Twitter / X Scraper

Scrape tweets, profiles, followers and more from Twitter/X. **No official API key needed** — uses X's own web GraphQL API, authenticated with your browser cookies.

*Last verified working: March 2026*

**What you can scrape:**
- **Tweets** — by keyword, hashtag, user, date range, engagement filters, language, location
- **Profile timelines** — a user's full tweet history
- **Followers / Following** — full account lists at scale
- **User profiles** — bio, follower count, verification status, and more

---

## Get started

### Hosted — no setup needed

The quickest way to get Twitter/X data: run on Apify with no code, no cookies, and no account management. Free tier included.

[![Run on Apify](https://apify.com/static/run-on-apify-button.svg)](https://apify.com/altimis/scweet?fpr=a40q9)

---

### Python library

**1. Install**

```bash
pip install -U Scweet
```

**2. Get your `auth_token`**

Log into [x.com](https://x.com) → DevTools `F12` → **Application** → **Cookies** → `https://x.com` → copy the `auth_token` value.

Paste the `auth_token` alone and Scweet auto-bootstraps the `ct0` CSRF token — or use the `cookies.json` format below for multiple accounts at once.

**3. Scrape**

```python
from Scweet import Scweet

# First run: credentials are stored in scweet_state.db automatically
# Use a proxy to avoid rate limits and bans
# All methods have async variants: asearch(), aget_profile_tweets(), aget_followers(), ...
s = Scweet(auth_token="YOUR_AUTH_TOKEN", proxy="http://user:pass@host:port")

# Search and save to CSV  (save_format="json" or "both" also works; use save_dir= and save_name= to control the output path)
tweets = s.search("bitcoin", since="2025-01-01", limit=500, save=True)

# Profile timeline
tweets = s.get_profile_tweets(["elonmusk"], limit=200)

# Followers
users = s.get_followers(["elonmusk"], limit=1000)

# Next run: reuse provisioned accounts — no credentials needed again
s = Scweet(db_path="scweet_state.db")
tweets = s.search("ethereum", limit=500, save=True)
```

**Multiple accounts with per-account proxies** — for higher throughput and reduced ban risk:

```json
[
  { "username": "acct1", "cookies": { "auth_token": "..." }, "proxy": "http://user1:pass1@host1:port1" },
  { "username": "acct2", "cookies": { "auth_token": "..." }, "proxy": "http://user2:pass2@host2:port2" }
]
```

```python
s = Scweet(cookies_file="cookies.json")  # proxies are read from the file, one per account
```

> Always set `limit` — without it, scraping continues until your account's daily cap is hit.

> For the full list of supported search operators, see [twitter-advanced-search](https://github.com/igorbrigadir/twitter-advanced-search).

**From the CLI — no Python code needed:**

```bash
# Search with proxy, save to CSV
scweet --auth-token YOUR_AUTH_TOKEN --proxy http://user:pass@host:port search "bitcoin" --since 2025-01-01 --limit 500 --save

# Followers, saved as JSON
scweet --auth-token YOUR_AUTH_TOKEN followers elonmusk --limit 1000 --save --save-format json
```

For structured search filters, async patterns, resume, multiple accounts, and the full API reference — see [**Full Documentation**](DOCUMENTATION.md).

---

## Why Scweet?

| | twint | snscrape | twscrape | **Scweet** |
|---|---|---|---|---|
| **Works in 2026** | ❌ unmaintained | ❌ broken | ✅ | ✅ |
| Cookie / token auth | ❌ | ❌ | ✅ | ✅ |
| Multi-account pooling | ❌ | ❌ | ✅ | ✅ |
| Proxy support | ❌ | ❌ | ✅ | ✅ |
| Resume interrupted scrapes | ❌ | ❌ | ❌ | ✅ |
| Built-in CSV / JSON output | ✅ | ✅ | ❌ | ✅ |
| Sync + async API | ❌ | ❌ | Async only | ✅ both |
| Hosted, no-setup option | ❌ | ❌ | ❌ | ✅ Apify |
| Active maintenance | ❌ | ❌ | ⚠️ | ✅ |

[twint](https://github.com/twintproject/twint) has been unmaintained since 2023. [snscrape](https://github.com/JustAnotherArchivist/snscrape) broke after X's backend changes. [twscrape](https://github.com/vladkens/twscrape) is the closest active alternative — worth knowing, but async-only, no built-in file output, and no resume support.

---

<details>
<summary><strong>FAQ</strong></summary>

<br>

**Does it work without an official Twitter API key?**
Yes. Scweet calls X's internal GraphQL API — the same one the web app uses. No developer account or API key required.

**Is it a replacement for twint or snscrape?**
Yes. Both are broken as of 2024–2025. Scweet uses a different, currently-working approach: cookies + GraphQL instead of legacy unauthenticated endpoints.

**How many tweets can I scrape?**
A single account typically handles hundreds to a few thousand tweets per day before hitting rate limits. Multi-account pooling scales this proportionally. The hosted Apify actor manages accounts and rate limits automatically.

**Will my account get banned?**
Never use your personal account — use dedicated accounts only. To further reduce risk: use **multiple accounts** (distributes the load across them) and pair each with a **proxy** (prevents all requests coming from a single IP). The Apify actor handles both automatically — managed accounts and proxies are included.

**Does it work for private accounts?**
No. Only publicly visible content is accessible.

**Does it still work in 2025 / 2026?**
Yes — last verified working in March 2026 against X's current GraphQL API.

</details>

---

## Documentation

Full API reference, all config options, structured search filters, async patterns, resume, proxies, and troubleshooting:

→ [**DOCUMENTATION.md**](DOCUMENTATION.md)

---

## Community

Have a question or want to share what you built with Scweet?
Open a thread in [**GitHub Discussions**](https://github.com/Altimis/Scweet/discussions).

**Found it useful? [Star the repo ⭐](https://github.com/Altimis/Scweet/stargazers)**

---

## Contributing

Bug reports, feature suggestions, and PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

*MIT License*
