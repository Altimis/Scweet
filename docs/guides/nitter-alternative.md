---
title: Nitter alternative in Python, with an RSS feed
description: nitter.net and xcancel are offline. Read the latest posts of X accounts from Python, keep only the new ones, and write your own RSS feed of an account.
---

# A Nitter alternative in Python: read X accounts and make an RSS feed

Many people used Nitter to read X accounts without the X website, often through its RSS feeds. X sent
cease-and-desist letters to the project in August and September 2026
([TechCrunch, 2026-08-25](https://techcrunch.com/2026/08/25/x-sends-cease-and-desist-to-open-source-project-nitter-over-alleged-scraping/),
[TechCrunch, 2026-09-15](https://techcrunch.com/2026/09/15/nitter-and-xcancel-are-dead-again-after-xs-latest-legal-actions/)).
nitter.net and xcancel.com are offline, and GitHub shows the repository `zedeus/nitter` as archived.

This page reads the same data from Python: the latest posts of a list of accounts, only the posts that are new
since the last run, and an RSS file that a feed reader can open.

## Install and log in

```bash
pip install -U Scweet
```

Scweet needs the `auth_token` cookie of an X account that you own. The
[first guide](scrape-tweets-without-api.md#2-get-the-auth_token-of-an-x-account) shows how to copy it. Use a
dedicated account, never your personal one.

## Read the latest posts of several accounts

```python
from Scweet import Scweet

s = Scweet(auth_token="YOUR_AUTH_TOKEN")
posts = s.get_profile_tweets(["NASA", "SpaceX"], limit=40)

for post in posts:
    print(post["timestamp"], post["user"]["screen_name"], post["text"][:80])
```

To include the replies of the accounts, add `include_replies=True`.

## Keep only the posts that are new since the last run

The id of a post grows with time. So keep the highest id that you saw, and on the next run, keep only the posts
with a higher id:

```python
import json
from pathlib import Path

from Scweet import Scweet

seen_file = Path("last_seen.json")
last_seen = json.loads(seen_file.read_text()) if seen_file.exists() else {}

s = Scweet()  # the account from the state file of the first run
for account in ["NASA", "SpaceX"]:
    posts = s.get_profile_tweets([account], limit=20)
    new = [p for p in posts if int(p["tweet_id"]) > last_seen.get(account, 0)]
    for post in new:
        print(account, post["tweet_url"])
    if posts:
        last_seen[account] = max(int(p["tweet_id"]) for p in posts)

seen_file.write_text(json.dumps(last_seen))
```

Run the script on a schedule, for example with `cron` once an hour.

## Write an RSS feed of an account

This script writes `NASA.xml`, a standard RSS 2.0 file. Serve it from any web folder, or open it with a feed reader
that reads local files.

```python
from datetime import datetime
from email.utils import format_datetime
import xml.etree.ElementTree as ET

from Scweet import Scweet

account = "NASA"
s = Scweet()
posts = s.get_profile_tweets([account], limit=20)

rss = ET.Element("rss", version="2.0")
channel = ET.SubElement(rss, "channel")
ET.SubElement(channel, "title").text = f"@{account} on X"
ET.SubElement(channel, "link").text = f"https://x.com/{account}"
ET.SubElement(channel, "description").text = f"The latest posts of @{account}"

for post in posts:
    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = post["text"][:100]
    ET.SubElement(item, "link").text = post["tweet_url"]
    ET.SubElement(item, "guid").text = post["tweet_url"]
    ET.SubElement(item, "description").text = post["text"]
    when = datetime.strptime(post["timestamp"], "%a %b %d %H:%M:%S %z %Y")
    ET.SubElement(item, "pubDate").text = format_datetime(when)

ET.ElementTree(rss).write(f"{account}.xml", encoding="utf-8", xml_declaration=True)
```

## Read the mentions of an account

Nitter also showed the posts that mention an account. A search gives the same:

```python
mentions = s.search("@NASA -from:NASA", since="2026-11-01", limit=100)
```

## Without your own accounts

The same engine also runs as a hosted service on Apify. You need no X account, no cookie and no proxy:
[run Scweet on Apify](https://apify.com/altimis/scweet).
