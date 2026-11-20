---
title: Scrape Twitter followers and following in Python
description: Export the followers, the following and the verified followers of any public X (Twitter) profile to CSV with Python. The fields of each profile, the limits, and a working example.
---

# Scrape Twitter followers and following in Python

Scweet reads three lists of a public X profile: its followers, the profiles that it follows, and its verified
followers. Each row is one profile, with its bio and its counts. This page exports the lists to CSV.

## Install and log in

```bash
pip install -U Scweet
```

Scweet needs the `auth_token` cookie of an X account that you own. The
[first guide](scrape-tweets-without-api.md#2-get-the-auth_token-of-an-x-account) shows how to copy it. Use a
dedicated account, never your personal one.

## Read the three lists

```python
from Scweet import Scweet

s = Scweet(auth_token="YOUR_AUTH_TOKEN")

followers = s.get_followers(["NASA"], limit=100)
following = s.get_following(["NASA"], limit=100)
verified = s.get_verified_followers(["NASA"], limit=100)

for profile in followers[:5]:
    print(profile["username"], profile["followers_count"], profile["description"][:60])
```

Each method also takes several profiles: `s.get_followers(["NASA", "SpaceX"], limit=200)`. The field `target` of
each row names the profile of the list, and the field `type` names the list.

## Save the lists to CSV

```python
followers = s.get_followers(["NASA"], limit=100, save=True, save_format="csv", save_name="nasa_followers")
```

Scweet writes `outputs/nasa_followers.csv`. Give each list its own `save_name`: a run adds its rows to the end of
a file with the same name. From the command line:

```bash
scweet --auth-token YOUR_AUTH_TOKEN followers NASA --limit 100 --save --save-name nasa_followers
scweet --auth-token YOUR_AUTH_TOKEN following NASA --limit 100 --save --save-name nasa_following
scweet --auth-token YOUR_AUTH_TOKEN verified-followers NASA --limit 100 --save --save-name nasa_verified
```

## The fields of a profile

| Field | Content |
|---|---|
| `username`, `name` | The handle and the display name |
| `description` | The bio |
| `location`, `url` | The location and the website of the bio |
| `created_at` | The date when the profile joined X |
| `followers_count`, `following_count`, `statuses_count` | The counts of followers, following and posts |
| `verified`, `blue_verified`, `identity_verified` | The marks of verification |
| `protected` | `True` for a private profile |
| `profile_image_url` | The profile photo |

The [reference](../documentation.md#user-record) gives every field.

## Limits

- **Set a limit.** A large profile has millions of followers. With no limit, a run continues until the account
  reaches its daily cap.
- **A list is slower than a search.** X allows fewer requests for followers than for tweets, so a large list takes
  longer. For more volume, add more accounts with a `cookies.json` file, as the
  [reference](../documentation.md#account-setup) shows.
- **Only public profiles.** X shows no list of a protected profile.

## Without your own accounts

The same engine also runs as a hosted service on Apify. You need no X account, no cookie and no proxy:
[run Scweet on Apify](https://apify.com/altimis/scweet).
