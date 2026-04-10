<h1 align="center">Scweet</h1>

<p align="center">
  <strong>Scrape Twitter / X without the official API.</strong>
  <br>
  Hosted on Apify, or run locally with Python and CLI.
</p>

<p align="center">
  <a href="https://apify.com/altimis/scweet?fpr=a40q9">
    <img alt="Run on Apify" src="https://img.shields.io/badge/Run%20on-Apify-246DFF?logo=apify&logoColor=white">
  </a>
  <a href="#python-quickstart">
    <img alt="Python Quickstart" src="https://img.shields.io/badge/Python-Quickstart-3776AB?logo=python&logoColor=white">
  </a>
  <a href="#cli">
    <img alt="CLI Quickstart" src="https://img.shields.io/badge/CLI-Quickstart-111111?logo=gnu-bash&logoColor=white">
  </a>
  <a href="#documentation">
    <img alt="Documentation" src="https://img.shields.io/badge/Docs-Full%20Reference-0A66C2">
  </a>
</p>

<p align="center">
  <a href="https://github.com/Altimis/Scweet/actions/workflows/tests.yml">
    <img alt="Tests" src="https://github.com/Altimis/Scweet/actions/workflows/tests.yml/badge.svg">
  </a>
  <a href="https://pypi.org/project/scweet/">
    <img alt="PyPI Version" src="https://img.shields.io/pypi/v/scweet.svg">
  </a>
  <a href="https://pepy.tech/projects/scweet">
    <img alt="PyPI Downloads" src="https://static.pepy.tech/badge/scweet/month">
  </a>
  <a href="https://github.com/Altimis/scweet/blob/main/LICENSE">
    <img alt="License" src="https://img.shields.io/github/license/Altimis/scweet">
  </a>
  <a href="https://apify.com/altimis/scweet">
    <img alt="Scweet Actor Status" src="https://apify.com/actor-badge?actor=altimis/scweet">
  </a>
</p>

<p align="center">
  <a href="https://apify.com/altimis/scweet?fpr=a40q9">
    <img
      alt="Scweet logo"
      src="apify_in_out/scweet_logo.png"
      width="140"
    >
  </a>
</p>


---
<p align="center">
<strong>Scrape tweets, profiles, followers and more from Twitter/X. Uses X's own web GraphQL API, authenticated with your browser cookies. No official API key or developer account needed.<strong>
</p>

**What you can scrape:**
- **Tweets** — by keyword, hashtag, user, date range, engagement filters, language, location
- **Profile timelines** — a user's full tweet history
- **Followers / Following** — full account lists at scale
- **User profiles** — bio, follower count, verification status, and more

---

## Hosted — no setup needed

Run on Apify with no code, no cookies, and no account management. Free tier included.

[![Run on Apify](https://apify.com/static/run-on-apify-button.svg)](https://apify.com/altimis/scweet?fpr=a40q9)

> Running Scweet locally at any real volume usually means dedicated accounts and proxies. You can use a single proxy, a rotating proxy, or assign one per account. If you need a provider, [Webshare](https://www.webshare.io/?referral_code=kdgjcc09945q) works well. Disclosure: affiliate link.

---

## Python quickstart

**1. Install**

```bash
pip install -U Scweet
```

**2. Get your `auth_token`**

Log into [x.com](https://x.com) → DevTools `F12` → **Application** → **Cookies** → `https://x.com` → copy the `auth_token` value.

Scweet auto-bootstraps the `ct0` CSRF token from `auth_token` alone — or use the [`cookies.json` format](#multiple-accounts--proxies) for multiple accounts at once.

**3. Scrape**

```python
from Scweet import Scweet

# Credentials are stored in scweet_state.db automatically on first run
s = Scweet(auth_token="YOUR_AUTH_TOKEN", proxy="http://user:pass@host:port")

# Search tweets — save to CSV (save_format="json" or "both" also works)
tweets = s.search("bitcoin", since="2025-01-01", limit=500, save=True)

# Reuse provisioned accounts on subsequent runs — no credentials needed
s = Scweet(db_path="scweet_state.db")
tweets = s.search("ethereum", limit=500, save=True)
```

> Always set `limit` — without it, scraping continues until your account's daily cap is hit.

> All methods have async variants: `asearch()`, `aget_profile_tweets()`, `aget_followers()`, etc.

---

## Common tasks

### Search tweets

```python
tweets = s.search(
    "AI agents",
    since="2026-01-01",
    from_users=["elonmusk"],
    min_likes=50,
    limit=200,
    save=True,
)
```

### Profile timeline

```python
tweets = s.get_profile_tweets(["elonmusk"], limit=200)
```

### Followers / Following

```python
followers = s.get_followers(["elonmusk"], limit=1000)
following = s.get_following(["elonmusk"], limit=1000)
```

### User profiles

```python
profiles = s.get_user_info(["githubstatus", "elonmusk"])
```

For the full list of supported search operators, see [twitter-advanced-search](https://github.com/igorbrigadir/twitter-advanced-search).

---

## CLI

```bash
# Search with proxy, save to CSV
scweet --auth-token YOUR_AUTH_TOKEN --proxy http://user:pass@host:port \
  search "bitcoin" --since 2025-01-01 --limit 500 --save

# Followers, saved as JSON
scweet --auth-token YOUR_AUTH_TOKEN \
  followers elonmusk --limit 1000 --save --save-format json
```

For multi-account runs, use `--cookies-file cookies.json`.

---

## Multiple accounts & proxies

For higher throughput and reduced ban risk, use multiple dedicated accounts with per-account proxies.

**`cookies.json` format:**

```json
[
  { "username": "acct1", "cookies": { "auth_token": "..." }, "proxy": "http://user1:pass1@host1:port1" },
  { "username": "acct2", "cookies": { "auth_token": "..." }, "proxy": "http://user2:pass2@host2:port2" }
]
```

```python
s = Scweet(cookies_file="cookies.json")  # proxies are read from the file, one per account
```

> **Never use your personal Twitter/X account for scraping.** Use dedicated accounts only.

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

## Limitations

- Only publicly visible content is accessible — private/protected accounts are not supported
- Relies on undocumented X web endpoints; breakage is always possible after platform changes. Scweet can self-heal by scraping fresh query IDs and feature flags from X's `main.js` bundle at startup — pass `manifest_scrape_on_init=True` to enable:
  ```python
  s = Scweet(auth_token="...", manifest_scrape_on_init=True)
  ```
- Cookies can expire and may need periodic refreshing
- A single account typically handles hundreds to a few thousand tweets per day before hitting rate limits; multi-account pooling scales proportionally
- Proxies and dedicated accounts are strongly recommended for anything beyond light testing
- Username/password login is not supported. X's anti-automation defenses make programmatic login unreliable and likely to trigger account locks. Scweet authenticates with browser cookies (`auth_token`) extracted from an active session instead

---

## Documentation

Full API reference, config options, structured search filters, async patterns, resume, proxies, and troubleshooting:

- [Account setup](DOCUMENTATION.md#account-setup)
- [Search API](DOCUMENTATION.md#search-api)
- [Profile tweets](DOCUMENTATION.md#profile-tweets)
- [Followers / Following](DOCUMENTATION.md#followers--following)
- [User info](DOCUMENTATION.md#user-info)
- [Saving results](DOCUMENTATION.md#saving-results)
- [Resume interrupted searches](DOCUMENTATION.md#resume-interrupted-searches)
- [Controlling limits](DOCUMENTATION.md#controlling-limits)
- [Configuration reference](DOCUMENTATION.md#configuration-reference)
- [Account management (ScweetDB)](DOCUMENTATION.md#account-management-scweetdb)
- [Async usage](DOCUMENTATION.md#async-usage)
- [Error handling](DOCUMENTATION.md#error-handling)
- [CLI reference](DOCUMENTATION.md#cli)

For advanced Twitter search operators, see [twitter-advanced-search](https://github.com/igorbrigadir/twitter-advanced-search).

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
Never use your personal account — use dedicated accounts only. To reduce risk further: use **multiple accounts** (distributes load) and pair each with a **proxy** (prevents all requests from one IP).

**Does it work for private accounts?**
No. Only publicly visible content is accessible.

**Does it still work in 2025 / 2026?**
Yes — last verified working in March 2026 against X's current GraphQL API.

</details>

---

## Community

Have a question or want to share what you built with Scweet?
Open a thread in [**GitHub Discussions**](https://github.com/Altimis/Scweet/discussions).

**Found it useful? [Star the repo](https://github.com/Altimis/Scweet/stargazers)**

---

## Contributing

Bug reports, feature suggestions, and PRs are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

---

*MIT License*
