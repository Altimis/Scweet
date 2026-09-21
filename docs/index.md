# Scweet

Scrape Twitter / X without the official API. Tweets, profiles, followers and trends, from Python or the
command line.

[Get started](#quickstart){ .md-button .md-button--primary }
[Full reference](documentation.md){ .md-button }

---

## Two ways to run it

### Hosted — nothing to manage

The same engine runs on Apify. You need no X accounts, no cookies and no proxies. Configure a job in your
browser, or call it from your code, and export the result. A free tier is included.

[Run Scweet on Apify](https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=docs){ .md-button }

### Self-hosted — full control

You bring your own X accounts and proxies, and you run the code inside your own infrastructure.

---

## Quickstart

**1. Install**

```bash
pip install -U Scweet
```

**2. Get your `auth_token`**

Log in to [x.com](https://x.com), open the developer tools with `F12`, then read
**Application → Cookies → `https://x.com`** and copy the value of `auth_token`.

That one value is all you need. Scweet builds the rest.

!!! warning "Use a dedicated account"
    Never use your personal account. X can lock an account that sends many requests.

**3. Scrape**

```python
from Scweet import Scweet

s = Scweet(auth_token="YOUR_AUTH_TOKEN")
tweets = s.search("bitcoin", limit=100)

for tweet in tweets:
    print(tweet["text"])
```

On the next run you need no credential, because Scweet keeps the account in a local state file:

```python
s = Scweet()
tweets = s.search("ethereum", limit=100, save=True)   # save=True writes a CSV
```

!!! tip "Always set `limit`"
    Without it, a run continues until the account reaches its daily cap.

---

## What you can read

| Operation | Method |
|---|---|
| Tweets from a search | `search()` |
| Tweets of a profile | `get_profile_tweets()` |
| Media of a profile | `get_profile_media()` |
| One tweet by its id | `get_tweet_info()` |
| The replies to a tweet | `get_tweet_replies()` |
| The accounts that reposted a tweet | `get_reposters()` |
| Followers, following, verified followers | `get_followers()`, `get_following()`, `get_verified_followers()` |
| The profile of a user | `get_user_info()` |
| A search for people | `search_users()` |
| The trends of now | `get_trending()` |

Each method has an async form with the prefix `a`, for example `asearch()`. Each one returns a
`list[dict]`.

Read [the full reference](documentation.md) for every parameter.

---

## Next steps

- [Add a proxy](documentation.md#account-setup) before you read a large volume.
- [Use several accounts](documentation.md#account-management-scweetdb) to read more in one day.
- [Read the configuration](documentation.md#configuration-reference) for every setting.
- [Read the errors](documentation.md#error-handling) that Scweet raises, and what each one means.
- [Use the command line](documentation.md#cli) instead of Python.

## Support

- The code and the issues: [github.com/Altimis/Scweet](https://github.com/Altimis/Scweet)
- The package: [pypi.org/project/scweet](https://pypi.org/project/scweet/)
- The changes of each version: [changelog](changelog.md)
