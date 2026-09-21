<p align="center">
  <img src="assets/scweet_banner.png" alt="Scweet" width="480" />
</p>

<p align="center">
  <strong>Scrape Twitter / X without the official API.</strong>
  <br>
  Tweets, profiles, followers, trends and more.
  <br>
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
  <a href="https://altimis.github.io/Scweet/">
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
  <a href="https://pypi.org/project/scweet/">
    <img alt="Python versions" src="https://img.shields.io/pypi/pyversions/scweet.svg">
  </a>
  <a href="https://pepy.tech/projects/scweet">
    <img alt="PyPI Downloads" src="https://static.pepy.tech/badge/scweet/month">
  </a>
  <a href="https://github.com/Altimis/Scweet/blob/master/LICENSE.txt">
    <img alt="License" src="https://img.shields.io/github/license/Altimis/scweet">
  </a>
  <a href="https://apify.com/altimis/scweet">
    <img alt="Scweet Actor Status" src="https://apify.com/actor-badge?actor=altimis/scweet">
  </a>
</p>


---

## Two ways to run it

### 1. Hosted : nothing to manage ⭐

Runs on Apify. **You do not need X accounts, cookies or proxies.**

- Configure and run **from your browser**, no code needed, or drive it from code with the [Python API](https://apify.com/altimis/scweet/api/python)
- **Search** tweets, profile timelines, follower / following lists
- **Export** in different formats (**JSON, CSV or XLSX**)
- **Free tier included**; pay-as-you-go pricing is on the Actor page

<p align="center">
  <a href="https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97">
    <img height="44" alt="Run Scweet on Apify - free tier" src="https://img.shields.io/badge/%20Run%20Scweet%20on%20Apify-Free%20tier-246DFF?style=for-the-badge&logoColor=white&logo=data:image/svg%2Bxml;base64,PHN2ZyB3aWR0aD0iMTA4MCIgaGVpZ2h0PSIxMDgwIiB2aWV3Qm94PSIwIDAgMTA4MCAxMDgwIiBmaWxsPSJub25lIiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPgo8cGF0aCBkPSJNNjA3Ljg1OSA3OC4yMjE4SDk4Ny43ODVDOTk1LjUxMyA3OC4yMjE4IDEwMDEuNzggODQuNDg2OCAxMDAxLjc4IDkyLjIxNTFWNjcyLjgzNEMxMDAxLjc4IDY4Ni43NDIgOTgzLjY5IDY5Mi4xMzQgOTc2LjA3NSA2ODAuNDk2TDU5Ni4xNSA5OS44NzdDNTkwLjA2IDkwLjU3MDMgNTk2LjczNyA3OC4yMjE4IDYwNy44NTkgNzguMjIxOFoiIGZpbGw9IiMyNDZERkYiLz4KPHBhdGggZD0iTTQ3Mi4xNDEgNzguMjIxOEg5Mi4yMTVDODQuNDg2NyA3OC4yMjE4IDc4LjIyMTcgODQuNDg2OCA3OC4yMjE3IDkyLjIxNTFWNjcyLjgzNEM3OC4yMjE3IDY4Ni43NDIgOTYuMzA5NCA2OTIuMTM0IDEwMy45MjQgNjgwLjQ5Nkw0ODMuODUgOTkuODc3QzQ4OS45NCA5MC41NzAzIDQ4My4yNjMgNzguMjIxOCA0NzIuMTQxIDc4LjIyMThaIiBmaWxsPSIjMjBBMzRFIi8+CjxwYXRoIGQ9Ik01MzMuNDkxIDU0My4wODZMMTAxLjg5NSA5NzcuOTI3QzkzLjEzMDIgOTg2Ljc1OCA5OS4zODQ5IDEwMDEuNzggMTExLjgyNiAxMDAxLjc4SDk2OC41MjlDOTgwLjkxOSAxMDAxLjc4IDk4Ny4xOTcgOTg2Ljg2MyA5NzguNTM1IDk3OC4wMDNMNTUzLjQyOSA1NDMuMTYxQzU0Ny45NjkgNTM3LjU3NiA1MzguOTkzIDUzNy41NDIgNTMzLjQ5MSA1NDMuMDg2WiIgZmlsbD0iI0Y4NjYwNiIvPgo8L3N2Zz4K">
  </a>
</p>

### 2. Self-hosted : full control

Bring your own X accounts and proxies. Run it from Python or the CLI, inside your own infrastructure.

```python
from Scweet import Scweet

s = Scweet(auth_token="YOUR_AUTH_TOKEN")
tweets = s.search("bitcoin", limit=100)
```

Both give you the same data. Self-hosted: you run the code, and you manage the accounts and the proxies. Hosted: you press a button and get the results.

---

## What you can scrape

- [**Tweets**](DOCUMENTATION.md#search-api) — by keyword, hashtag, user, date range, engagement filters, language, location
- [**Profile timelines**](DOCUMENTATION.md#profile-tweets) — a user's full tweet history, with replies and media tabs
- [**Tweets by id**](DOCUMENTATION.md#tweet-lookup--replies) — full data for known tweet ids, their replies, and who reposted them
- [**Followers / Following**](DOCUMENTATION.md#followers--following) — full account lists at scale, verified followers included
- [**User profiles**](DOCUMENTATION.md#user-info) — bio, follower count, verification status, by handle or by id
- [**People search & trends**](DOCUMENTATION.md#search-users) — find accounts by keyword, read what is trending now

---

## Python Quickstart

Three steps from nothing to tweets. One account, one call, one result.

**1. Install**

```bash
pip install -U Scweet
```

**2. Get your `auth_token`**

Log into [x.com](https://x.com) → DevTools `F12` → **Application** → **Cookies** → `https://x.com` → copy the `auth_token` value. That one value is all you need; Scweet builds the rest.

> Use a dedicated account, never your personal one.

**3. Scrape**

```python
from Scweet import Scweet

s = Scweet(auth_token="YOUR_AUTH_TOKEN")
tweets = s.search("bitcoin", limit=100)

for tweet in tweets:
    print(tweet["text"])
```

That is the whole first run. On the next run, reuse the same accounts with no credentials:

```python
s = Scweet()                       # reads the state file scweet_state.db
tweets = s.search("ethereum", limit=100, save=True)   # save=True writes a CSV
```

> Always set `limit`. Without it, a run continues until the daily cap of the account.

**Next:** [add a proxy](#proxies) for real volume, [use several accounts](#multiple-accounts--proxies), or read the [full documentation](DOCUMENTATION.md).

### Proxies

A proxy is optional for a small run and recommended for real volume, because many requests from one IP raise the risk to an account. Pass one URL for all accounts:

```python
s = Scweet(auth_token="YOUR_AUTH_TOKEN", proxy="http://user:pass@proxy.example.com:8000")
```

On a rotating provider, put `{session}` in the URL to give each account its own exit IP: `http://user,session-{session}:pass@proxy.example.com:8000`. For a proxy per account, see [Multiple accounts & proxies](#multiple-accounts--proxies).

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
verified  = s.get_verified_followers(["elonmusk"], limit=1000)
```

### User profiles

```python
profiles = s.get_user_info(["githubstatus", "elonmusk"])
profiles = s.get_user_info(user_ids=["44196397"])   # numeric ids work too
```

### Tweets by id, replies, reposters

```python
tweets    = s.get_tweet_info(["1866123456789", "1866123456790"])  # up to 50 per request
replies   = s.get_tweet_replies("1866123456789", limit=100)
reposters = s.get_reposters("1866123456789", limit=100)
```

### People search, trends, media

```python
people = s.search_users("python developer", limit=50)
trends = s.get_trending()
media  = s.get_profile_media(["nasa"], limit=100)
tweets = s.get_profile_tweets(["nasa"], limit=100, include_replies=True)
```

For the full list of supported search operators, see [twitter-advanced-search](https://github.com/igorbrigadir/twitter-advanced-search).

---

## CLI

```bash
# Search with proxy, save to CSV
scweet --auth-token YOUR_AUTH_TOKEN --proxy http://user:pass@host:port \
  search "bitcoin" --since 2026-01-01 --limit 500 --save

# Followers, saved as JSON
scweet --auth-token YOUR_AUTH_TOKEN \
  followers elonmusk --limit 1000 --save --save-format json
```

For multi-account runs, use `--cookies-file cookies.json`.

---

## Multiple accounts & proxies

For higher throughput and reduced ban risk, use multiple dedicated accounts with per-account proxies.

Running Scweet locally at any real volume usually means dedicated accounts and proxies. You can use a single proxy, a rotating proxy, or assign one per account. On a rotating provider, put `{session}` in the proxy URL to give each account its own session — see "Proxy modes" in DOCUMENTATION.md.

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

One page of X is easy to fetch. 10,000 tweets is not, because accounts get rate-limited, cookies expire, and X changes its API.

**Your run finishes**
- A wide date range is split into intervals that run in parallel. If X stops one interval early, the others still fill.
- If X ends a page chain early, Scweet continues from the oldest tweet it received.
- If a run stops, `resume=True` continues from the last saved point instead of starting again.

**Your accounts stay usable**
- Scweet reads the rate-limit headers of X and stops each account 2 requests before its limit, so X does not block it.
- Scweet identifies the cause of each error. A bad request, an old query id and a dead session are handled differently, so a small error does not cost you an account.
- Scweet records the state of each account (locked, suspended, rate-limited) and waits the needed time before it uses that account again.

**It keeps working when X changes**
- X changes the ids of its internal API without notice. Scweet reads the new ids from the JavaScript files of X, at startup or when you call `refresh_manifest()`.

**It is easy to work with**
- 12 read operations, one consistent row shape, sync **and** async, a real CLI, and CSV/JSON output built in.
- 25 fields per tweet, including view counts, quotes, bookmarks, language and the nested quoted or retweeted post.

**Or let us run it for you**
- The [hosted version](https://apify.com/altimis/scweet?fpr=a40q9) does all of the above on our accounts and proxies. Free tier included.

> Also on [twint](https://github.com/twintproject/twint) and [snscrape](https://github.com/JustAnotherArchivist/snscrape): both are unmaintained and no longer work against X's current backend. If you are migrating from either, Scweet covers the same ground and more.

---

## Limitations

- Only publicly visible content is accessible — private/protected accounts are not supported
- Relies on undocumented X web endpoints; breakage is always possible after platform changes. Scweet self-heals by scraping fresh query IDs and feature flags from X's own bundles — at startup with `manifest_scrape_on_init=True`, or on demand at any time:
  ```python
  s = Scweet(auth_token="...", manifest_scrape_on_init=True)
  changes = s.refresh_manifest()   # or: scweet refresh-manifest
  ```
- Cookies can expire and may need periodic refreshing
- A single account typically handles hundreds to a few thousand tweets per day before hitting rate limits; multi-account pooling scales proportionally
- Proxies and dedicated accounts are strongly recommended for anything beyond light testing
- Username/password login is not supported. X's anti-automation defenses make programmatic login unreliable and likely to trigger account locks. Scweet authenticates with browser cookies (`auth_token`) extracted from an active session instead

---

## Documentation

Full API reference, config options, structured search filters, async patterns, resume, proxies, and troubleshooting.

**Read it as a site: [altimis.github.io/Scweet](https://altimis.github.io/Scweet/)** — the same text, with search and a navigation menu.

- [Account setup](DOCUMENTATION.md#account-setup)
- [Search API](DOCUMENTATION.md#search-api)
- [Profile tweets](DOCUMENTATION.md#profile-tweets)
- [Tweet lookup & replies](DOCUMENTATION.md#tweet-lookup--replies)
- [Followers / Following](DOCUMENTATION.md#followers--following)
- [User info](DOCUMENTATION.md#user-info)
- [Search users & trends](DOCUMENTATION.md#search-users)
- [Manifest refresh](DOCUMENTATION.md#manifest-refresh)
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
Yes — last verified with the 5.8.0 release (2026-09-15) against X's current GraphQL API.

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
