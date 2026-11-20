---
title: snscrape and twint alternative that works in 2026
description: snscrape fails to import on Python 3.12 and twint stops at start. Scweet replaces both, with the same searches, profiles and followers. A command map and a code map.
---

# An snscrape and twint alternative that works in 2026

snscrape and twint were the usual tools to scrape X (Twitter) without the API. On a current Python, neither of
them runs. This page shows what happens, and how to move each command and each script to Scweet.

## What happens today

Tested on 2026-11-20, in a new virtual environment with Python 3.12.

**snscrape 0.7.0.20230622**, the last release (2023-06-22), installs and then fails at import:

```text
$ pip install snscrape
$ snscrape --max-results 5 twitter-search "bitcoin"
AttributeError: 'FileFinder' object has no attribute 'find_module'
```

**twint 2.1.20**, the last release (2020-04-29), installs and then stops at start:

```text
$ pip install twint
$ twint -s bitcoin --limit 5
ModuleNotFoundError: No module named 'async_timeout'
```

After a manual `pip install async_timeout`, it stops at its own check of the Python version:

```text
$ twint -s bitcoin --limit 5
[-] TWINT requires Python version 3.6+.
```

GitHub shows the twint repository as archived, so it is read-only. The last change to the snscrape repository is
from 2023-11-15.

## Install Scweet

```bash
pip install -U Scweet
```

Scweet needs the `auth_token` cookie of an X account that you own. The
[first guide](scrape-tweets-without-api.md#2-get-the-auth_token-of-an-x-account) shows how to copy it.

## The command map

| Task | snscrape | twint | Scweet |
|---|---|---|---|
| Search | `snscrape twitter-search "bitcoin since:2026-11-01"` | `twint -s bitcoin --since 2026-11-01` | `scweet search "bitcoin" --since 2026-11-01 --limit 100 --save` |
| Tweets of a profile | `snscrape twitter-user NASA` | `twint -u NASA` | `scweet profile-tweets NASA --limit 100 --save --save-name nasa_tweets` |
| Followers | — | `twint -u NASA --followers` | `scweet followers NASA --limit 100 --save --save-name nasa_followers` |
| Following | — | `twint -u NASA --following` | `scweet following NASA --limit 100 --save --save-name nasa_following` |
| One tweet | `snscrape twitter-tweet 2090227249551483321` | — | `scweet tweet-info 2090227249551483321 --pretty` |
| Save to a file | `--jsonl > tweets.jsonl` | `-o tweets.csv --csv` | `--save`, with `--save-format csv`, `json` or `both` |

Each Scweet command starts with `scweet --auth-token YOUR_AUTH_TOKEN`. After the first run, Scweet keeps the
account in its state file, and the option is no longer necessary.

The command prints nothing by default. `--save` writes the rows to the folder `outputs/`, and `--pretty` prints
them as JSON. Give each command its own `--save-name`: a run adds its rows to the end of a file with the same name,
and the default name of a profile command is the handle only.

## The code map

A script that used the Python module of snscrape:

```python
import snscrape.modules.twitter as sntwitter

for tweet in sntwitter.TwitterSearchScraper("bitcoin since:2026-11-01").get_items():
    print(tweet.date, tweet.user.username, tweet.rawContent)
```

becomes:

```python
from Scweet import Scweet

s = Scweet(auth_token="YOUR_AUTH_TOKEN")
for tweet in s.search("bitcoin", since="2026-11-01", limit=100):
    print(tweet["timestamp"], tweet["user"]["screen_name"], tweet["text"])
```

Each Scweet tweet is a `dict`. The names of the fields change as follows:

| snscrape | Scweet |
|---|---|
| `tweet.id` | `tweet["tweet_id"]` (a string) |
| `tweet.date` (a `datetime`) | `tweet["timestamp"]` (a string, for example `Wed Nov 18 23:59:45 +0000 2026`) |
| `tweet.rawContent` | `tweet["text"]` |
| `tweet.user.username` | `tweet["user"]["screen_name"]` |
| `tweet.likeCount` | `tweet["likes"]` |
| `tweet.retweetCount` | `tweet["retweets"]` |
| `tweet.replyCount` | `tweet["comments"]` |
| `tweet.quoteCount` | `tweet["quotes"]` |
| `tweet.viewCount` | `tweet["views"]` |
| `tweet.url` | `tweet["tweet_url"]` |

To get a `datetime` again:

```python
from datetime import datetime

when = datetime.strptime(tweet["timestamp"], "%a %b %d %H:%M:%S %z %Y")
```

## Two differences to know

- **Set a limit.** snscrape stopped when the results ended. Scweet also stops there, but a broad search can
  continue for a long time, so give `limit` or `--limit`.
- **An account is necessary.** X shows search results only to a logged-in user, so Scweet sends each request with
  the cookie of your account. Use a dedicated account, never your personal one.

## Without your own accounts

The same engine also runs as a hosted service on Apify. You need no X account, no cookie and no proxy:
[run Scweet on Apify](https://apify.com/altimis/scweet).
