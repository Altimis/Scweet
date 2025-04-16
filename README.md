# 🐦 Scweet: A Simple and Unlimited Twitter Scraper in Python

[![Scweet Actor Status](https://apify.com/actor-badge?actor=altimis/scweet)](https://apify.com/altimis/scweet)
[![PyPI Downloads](https://static.pepy.tech/badge/scweet/month)](https://pepy.tech/projects/scweet)
[![PyPI Version](https://img.shields.io/pypi/v/scweet.svg)](https://pypi.org/project/scweet/)
[![License](https://img.shields.io/github/license/Altimis/scweet)](https://github.com/Altimis/scweet/blob/main/LICENSE)

> **Note:** Scweet is **not affiliated with Twitter/X**. Use responsibly and lawfully.

---

## 🚀 Scweet on Apify: Cloud-Powered Scraping

For heavy-duty scraping, we recommend using [**Scweet on Apify**](https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97) – a cloud-based solution that offers:
- **Zero setup:** No need to install or maintain infrastructure.
- **Incredible Speed:** Up to **1000 tweets per minute**.
- **High Reliability:** Managed and isolated runs for consistent performance.
- **Free Usage Tier:** Get started for free with a generous quota—perfect for experiments, small projects, or learning how Scweet works. Once you exceed the free quota, you'll pay only **$0.30 per 1,000 tweets**.

[![Run on Apify](https://apify.com/static/run-on-apify-button.svg)](https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97)

---

## 🚀 Recent X Platform Changes & Scweet v3 Update

Scweet has recently encountered challenges due to major changes on **X (formerly Twitter)**. In response, we’re excited to announce the new **Scweet v3** release!

### ✨ What’s New in v3:
- ✅ Fully **asynchronous architecture** for faster, smoother scraping
- 🧠 **No more manual Chromedriver setup** – Scweet handles Chromium internally with **[Nodriver](https://github.com/ultrafunkamsterdam/nodriver)**
- 🚀 Enhanced for **personal and research-level scraping**
- 🧑‍🤝‍🧑 **Follower & following scraping is back!** (see below 👇)

---

## 📌 What is Scweet?

Scweet is a Python-based scraping tool designed to fetch tweets and user data **without relying on traditional Twitter APIs**, which have become increasingly restricted.

With Scweet, you can:
- Scrape tweets by keywords, hashtags, mentions, accounts, or timeframes
- Get detailed user profile information
- ✅ Retrieve followers, following, and verified followers!

---

## 🔧 Key Features

### 🐤 `scrape()` – Tweet Scraper

Scrape tweets between two dates using keywords, hashtags, mentions, or specific accounts.

**✅ Available arguments include:**
```python
- since, until
- words
- from_account, to_account, mention_account
- hashtag, lang
- limit, display_type, resume
- filter_replies, proximity, geocode
- minlikes, minretweets, minreplies
- save_dir, custom_csv_name
```

---

### 👤 `get_user_information()` – User Info Scraper

Fetch profile details for a list of handles. Returns a dictionary with:
- `username`, `verified_followers`
- `following`, `location`, `website`, `join_date`, `description`

**🧩 Arguments:**
```python
- handles        # List of Twitter/X handles
- login (bool)   # Required for complete data
```

---

### 🧑‍🤝‍🧑 `get_followers()`, `get_following()`, `get_verified_followers()` – NEW! 🎉

Scweet now supports scraping followers and followings again!

> ⚠️ **Important Note:** This functionality relies on browser rendering and may trigger rate-limiting or account lockouts. Use with caution and always stay logged in during scraping.

**🧩 Example Usage:**
```python
handle = "x_born_to_die_x"

# Get followers
followers = scweet.get_followers(handle=handle, login=True, stay_logged_in=True, sleep=1)

# Get following
following = scweet.get_following(handle=handle, login=True, stay_logged_in=True, sleep=1)

# Get only verified followers
verified = scweet.get_verified_followers(handle=handle, login=True, stay_logged_in=True, sleep=1)
```

---

## 🛠️ Class Initialization & Configuration

Customize Scweet’s behavior during setup:

```python
scweet = Scweet(
  proxy=None,                 # Dict or None
  cookies=None,               # Nodriver-based cookie handling
  cookies_path='cookies',     # Folder for saving/loading cookies
  user_agent=None,            # Optional custom user agent
  disable_images=True,        # Speeds up scraping
  env_path='.env',            # Path to your .env file
  n_splits=-1,                # Date range splitting
  concurrency=5,              # Number of concurrent tabs
  headless=True,              # Headless scraping
  scroll_ratio=100            # Adjust for scroll depth/speed
)
```

---

## 🔐 Authentication

Scweet requires login for tweets, user info, and followers/following.

Set up your `.env` file like this:

```env
EMAIL=your_email@example.com
EMAIL_PASSWORD=your_email_password
USERNAME=your_username
PASSWORD=your_password
```

Need a temp email? Use built-in MailTM integration:

```python
from Scweet.utils import create_mailtm_email
email, password = create_mailtm_email()
```

---

## 🔧 Installation

```bash
pip install Scweet
```
Requires **Python 3.7+** and a Chromium-based browser.

---

## 💡 Example Usage

### 🐍 Python Script

```python
from Scweet.scweet import Scweet
from Scweet.utils import create_mailtm_email

scweet = Scweet(proxy=None, cookies=None, cookies_path='cookies',
                user_agent=None, disable_images=True, env_path='.env',
                n_splits=-1, concurrency=5, headless=False, scroll_ratio=100)

# Get followers (⚠️ requires login)
followers = scweet.get_followers(handle="x_born_to_die_x", login=True, stay_logged_in=True, sleep=1)
print(followers)

# Get user profile data
infos = scweet.get_user_information(handles=["x_born_to_die_x", "Nabila_Gl"], login=True)
print(infos)

# Scrape tweets
results = scweet.scrape(
  since="2022-10-01",
  until="2022-10-06",
  words=["bitcoin", "ethereum"],
  lang="en",
  limit=20,
  minlikes=10,
  minretweets=10,
  save_dir='outputs',
  custom_csv_name='crypto.csv'
)
print(len(results))
```

---

## 📝 Example Output 

| tweetId | UserScreenName | Text | Likes | Retweets | Timestamp |
|--------|----------------|------|-------|----------|-----------|
| ...    | @elonmusk      | ...  | 18787 | 1000     | 2022-10-05T17:44:46.000Z |

> Full CSV output includes user info, tweet text, stats, embedded replies, media, and more.

---

## ☁️ Scweet on Apify (Cloud)

Need powerful, scalable, high-volume scraping?  
Try [**Scweet on Apify**](https://apify.com/altimis/scweet):

- 🚀 Up to **1000 tweets/minute**
- 📦 Export to datasets
- 🔒 Secure, isolated browser instances
- 🔁 Ideal for automation & research projects

---

## 🙏 Responsible Use

We care deeply about ethical scraping.

> **Please:** Use Scweet for research, education, and lawful purposes only. Respect platform terms and user privacy.

---

## 📎 Resources

- 📄 [Example Script](https://github.com/Altimis/Scweet/blob/master/example.py)
- 🐞 [Issues / Bugs](https://github.com/Altimis/Scweet/issues)
- 🌐 [Scweet on Apify](https://apify.com/altimis/scweet)

---

## ⭐ Star & Contribute

If you find Scweet useful, consider **starring** the repo ⭐  
We welcome **PRs**, bug reports, and feature suggestions!

---

MIT License • © 2020–2025 Altimis