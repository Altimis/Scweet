
# 🐦 Scweet: A Simple and Unlimited Twitter Scraper in Python

[![Scweet Actor Status](https://apify.com/actor-badge?actor=altimis/scweet)](https://apify.com/altimis/scweet)
[![PyPI Downloads](https://static.pepy.tech/badge/scweet/month)](https://pepy.tech/projects/scweet)
[![PyPI Version](https://img.shields.io/pypi/v/scweet.svg)](https://pypi.org/project/scweet/)
[![License](https://img.shields.io/github/license/Altimis/scweet)](https://github.com/Altimis/scweet/blob/main/LICENSE)

> **Note:** Scweet is **not affiliated with Twitter/X**. Use responsibly and lawfully.

---

## 🚀 Recent X Platform Changes & Scweet v3 Update

Scweet has recently encountered challenges due to major changes on **X (formerly Twitter)**. In response, we’re excited to announce the new **Scweet v3** release!

### ✨ What’s New in v3:
- ✅ Fully **asynchronous architecture** for faster, smoother scraping
- 🧠 **No more manual Chromedriver setup** – Scweet handles Chromium internally
- 🚀 Enhanced for **personal and research-level scraping**
- ⚠️ **Follower/following scraping temporarily disabled** (to return in future updates)

> 🔧 For heavy-duty scraping, we recommend using **[Scweet on Apify](https://apify.com/altimis/scweet)** – a cloud-based solution offering higher throughput and stability (up to **1000 tweets/minute**), no infrastructure setup needed.

⚠️ **Responsible Use Reminder**  
Whether running locally or in the cloud, **always scrape tweets ethically, lawfully, and respectfully**.

---

## 📌 What is Scweet?

Scweet is a Python-based scraping tool designed to fetch tweets and user data **without relying on traditional Twitter APIs**, which have become increasingly restricted.

With Scweet, you can:
- Scrape tweets by keywords, hashtags, mentions, accounts, or timeframes
- Get detailed user profile information
- (Coming soon) Retrieve followers/following lists again!

---

## 🔧 Key Features

### 🐤 `scrape()` – Tweet Scraper

Scrape tweets between two dates using keywords, hashtags, mentions, or specific accounts.

**✅ Available arguments include:**
```python
- since, until            # Date range (format: YYYY-MM-DD)
- words                   # Keywords (string or list, use "//" separator for strings)
- from_account            # Tweets from a user
- to_account              # Tweets to a user
- mention_account         # Tweets mentioning a user
- hashtag                 # Search by hashtag
- lang                    # Language code (e.g. "en")
- limit                   # Max number of tweets
- display_type            # "Top" or "Latest"
- resume                  # Resume from previous CSV
- filter_replies          # Include/exclude replies
- proximity               # Local tweet filtering
- geocode                 # Geolocation filtering
- minlikes                # Tweets with minimum likes count
- minretweets             # Tweets with minimum retweets count
- minreplies              # Tweets with minimum replies count
- save_dir                # Output directory
- custom_csv_name         # Output csv name 
```
---

### 👤 `get_user_information()` – User Info Scraper

Fetch profile details for a list of handles. Returns a dictionary with:
- `username` (display name)
- `following` (number of accounts they follow)
- `verified_followers` (number of verified followers)
- `location`, `website`, `join_date`, `description`

**🧩 Arguments:**
```python
- handles        # List of Twitter/X handles
- login (bool)   # Set True to login and access full data
```

---

### 🔒 `get_users_followers()` & `get_users_following()`  
⚠️ **Currently Disabled due to platform changes**  
These will be re-enabled in future versions as we work around new limitations.

---

## 🛠️ Class Initialization & Configuration

You can customize Scweet’s behavior during initialization:

```python
scweet = Scweet(
  proxy=None,                              # Dict or None {host, post, username, pasword}
  cookies=None,                            # Use saved cookies file
  cookies_path='cookies',                  # Folder path where cookies will be saved/loaded in future usage
  user_agent=None,                         # Custom user agent string
  env_path='.env',                         # Environment variables
  n_splits=-1,                             # Split date interval (-1 for daily)
  concurrency=5,                           # Concurrent tabs
  headless=True,                           # Run headlessly
  scroll_ratio=100,                        # Adjust scroll behavior
  code_callback=None                       # Optional custom login code handler. Scweet only handles MailTM emails to get the code if X asks for it.
)
```

---

## 🔐 Authentication

Scweet requires login to fetch tweets. Set up your `.env` file like this:

```env
EMAIL=your_email@example.com
EMAIL_PASSWORD=your_email_password
USERNAME=your_username
PASSWORD=your_password
```

Use the built-in helper to create disposable login emails:

```python
from Scweet.utils import create_mailtm_email
```

For custom email providers, pass your own `code_callback`.

---

## 🔧 Installation

```bash
pip install Scweet
```
Make sure your environment is set up with Python 3.7+, chrome browser and pip is available.

## 💡 Example Usage

### 🐍 Python Script

```python
from Scweet.scweet import Scweet
from Scweet.user import get_user_information

scweet = Scweet(proxy=None, cookies=None, cookies_path='cookies',
                user_agent=None, disable_images=True, env_path='.env',
                n_splits=-1, concurrency=5, headless=True, scroll_ratio=100)

# Get user profile info
handles = ['nagouzil', 'yassineaitjeddi', 'TahaAlamIdrissi']
infos = scweet.get_user_information(handles=handles, login=True)
print(infos)

# Scrape tweets with keywords
results = scweet.scrape(
  since="2022-10-01",
  until="2022-10-06",
  words=['bitcoin', 'ethereum'],
  lang="en",
  limit=20,
  display_type="Top",
  resume=False,
  filter_replies=False,
  minlikes=10,
  minretweets=10,
  save_dir='outputs',
  custom_csv_name='crypto.csv'
)
print(len(results))
scweet.close()
```

### 📝 Example Output 

When you scrape tweets using the scrape() function, the results will be written to a CSV file, with each row representing a tweet. Here’s an example of what the output might look like:


| tweetId            | UserScreenName | UserName  | Timestamp               | Text                                                                                     | Embedded_text            | Emojis | Comments | Likes | Retweets | Image link                                                                                     | Tweet URL                                         |
|--------------------|----------------|-----------|--------------------------|-------------------------------------------------------------------------------------------|--------------------------|--------|----------|-------|----------|--------------------------------------------------------------------------------------------------|--------------------------------------------------|
| 1577716440299442187 | @elonmusk      | Elon Musk | 2022-10-05T17:44:46.000Z | 10.69.3 will actually be a major upgrade. We’re keeping .69 just because haha.            | Replying to@WholeMarsBlog |        | 1256     | 18787 | 1000     | https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_bigger.jpg | /elonmusk/status/1577716440299442187             |
| 1577737664689848326 | @elonmusk      | Elon Musk | 2022-10-05T19:09:06.000Z | Twitter is an accelerant to fulfilling the original http://X.com vision                  | Replying to@TEDchris      |        | 967      | 10967 | 931      | https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_bigger.jpg | /elonmusk/status/1577737664689848326             |
| 1577747565533069312 | @elonmusk      | Elon Musk | 2022-10-05T19:48:27.000Z | That wouldn’t be hard to do                                                                | Replying to@ashleevance   |        | 1326     | 31734 | 1011     | https://pbs.twimg.com/profile_images/1683899100922511378/5lY42eHs_bigger.jpg | /elonmusk/status/1577747565533069312             |
| 1577732106784051214 | @elonmusk      | Elon Musk | 2022-10-05T18:47:01.000Z | *"I do not think it is simple at all, but I have yet to hear any realistic path to peace.* |                          |        | –        | –     | –        | –                                                                                                | /elonmusk/status/1577732106784051214             |


**Columns description**:

- **tweetId**: The unique identifier for the tweet.
- **UserScreenName**: The Twitter/X handle of the user who posted the tweet.
- **UserName**: The display name of the user.
- **Timestamp**: The date and time the tweet was posted.
- **Text**: The content of the tweet.
- **Embedded_text**: If the tweet is a reply, this will show the user being replied to.
- **Emojis**: Any emojis used in the tweet.
- **Comments**: Number of replies to the tweet.
- **Likes**: Number of likes the tweet received.
- **Retweets**: Number of retweets the tweet received.
- **Image link**: A link to the image(s) attached to the tweet, if any.
- **Tweet URL**: Direct URL to the tweet.

---

## ☁️ Scweet on Apify (Cloud)

Need powerful, scalable, high-volume scraping?  
Try [**Scweet on Apify**](https://apify.com/altimis/scweet) – a no-setup cloud solution:

- 🚀 Up to **1000 tweets/minute**
- 📦 Exports to datasets or files
- 🔒 Secure, isolated runs
- 🔁 Ideal for automation, long-term projects

---

## 🙏 Responsible Use

We care deeply about ethical scraping.

> **Please:** Use Scweet for research, archiving, and lawful purposes only.  

---

## 📎 Resources

- 📄 [Example Script](https://github.com/Altimis/Scweet/blob/master/example.py)
- 🐞 [Issues / Bugs](https://github.com/Altimis/Scweet/issues)
- 🌐 [Scweet on Apify](https://apify.com/altimis/scweet)

---

## ⭐ Star & Contribute

If you find Scweet useful, consider **starring** the repo ⭐  
We welcome **PRs**, bug reports, and ideas for new features!

---

MIT License • © 2020–2025 Altimis
