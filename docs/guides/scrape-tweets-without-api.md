---
title: Scrape tweets in Python without the X API
description: Scrape tweets from X (Twitter) in Python with no API key and no developer account. Search by keyword, hashtag, user and date, then export CSV or JSON.
---

# Scrape tweets in Python without the X API

Scweet reads the tweets that the X website shows, with the cookie of an X account that you own. You need no API
key and no developer account. This page takes you from the install to a CSV file of tweets.

## 1. Install

```bash
pip install -U Scweet
```

Scweet runs on Python 3.9 to 3.14.

## 2. Get the auth_token of an X account

1. Log in to [x.com](https://x.com) in your browser.
2. Open the developer tools with `F12`.
3. Go to **Application → Cookies → `https://x.com`** and copy the value of `auth_token`.

!!! warning "Use a dedicated account"
    Never use your personal account. X can lock an account that sends many requests.

## 3. Search tweets

```python
from Scweet import Scweet

s = Scweet(auth_token="YOUR_AUTH_TOKEN")
tweets = s.search("bitcoin", since="2026-11-01", limit=100)

for tweet in tweets[:5]:
    print(tweet["timestamp"], tweet["user"]["screen_name"], tweet["text"][:80])
```

Replace `YOUR_AUTH_TOKEN` with the value from step 2. Keep the quotes.

Scweet keeps the account in a local state file, `scweet_state.db`. On the next run, `Scweet()` with no argument
uses the same account.

## 4. Filter the search

Each filter of the advanced search of X is a keyword argument:

```python
tweets = s.search(
    "AI agents",
    lang="en",
    min_likes=100,
    tweet_type="originals_only",
    since="2026-10-01",
    limit=100,
)
```

The operators of X also work inside the query, as you type them on x.com:

```python
tweets = s.search("from:NASA -filter:replies", since="2026-10-01", limit=100)
```

The [reference](../documentation.md#search-api) lists every filter.

## 5. Save the tweets to CSV or JSON

```python
tweets = s.search("bitcoin", since="2026-11-01", limit=100, save=True, save_format="both")
```

Scweet writes two files to the folder `outputs/`, for example `bitcoin_2026-11-01_2026-11-20.csv` and `.json`. The
name holds the query, the start date and the end date, which is today by default. A second run with the same name
adds its rows to the end of the files. Give `save_name="my_file"` for a name of your choice.

## 6. The same search from the command line

```bash
scweet --auth-token YOUR_AUTH_TOKEN search "bitcoin" --since 2026-11-01 --limit 100 --save
```

## The fields of a tweet

| Field | Content |
|---|---|
| `tweet_id` | The id of the tweet |
| `timestamp` | The time of the post, for example `Wed Nov 18 23:59:45 +0000 2026` |
| `text` | The full text |
| `user` | The author: `screen_name`, `name`, `followers_count` |
| `likes`, `retweets`, `comments`, `quotes`, `views` | The counts of engagement |
| `tweet_url` | The link to the tweet |
| `media` | The links of the images and the videos |

The [reference](../documentation.md#tweet-record) gives every field.

## Limits

- Always set `limit`. With no limit, a run continues until the account reaches its daily cap.
- One account reads a limited number of pages in each period. For more volume, add more accounts with a
  `cookies.json` file. The [reference](../documentation.md#account-setup) shows how.

## Without your own accounts

The same engine also runs as a hosted service on Apify. You need no X account, no cookie and no proxy:
[run Scweet on Apify](https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=guidetweets).
