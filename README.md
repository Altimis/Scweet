
# 🐦 Scweet: A Simple and Unlimited Twitter Scraper in Python

> **Note:** Scweet is **not affiliated with Twitter/X**. Use responsibly and lawfully.

---

## 🚀 Recent X Platform Changes & Scweet v3.0 Update

Scweet has recently encountered challenges due to major changes on **X (formerly Twitter)**. In response, we’re excited to announce the new **Scweet v3.0** release!

### ✨ What’s New in v3.0:
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
- minlikes, minretweets, minreplies
- save_dir, custom_csv_name
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
EMAIL_PASSWORD
USERNAME=your_username
PASSWORD=your_password
```

Use the built-in helper to create disposable login emails:

```python
from Scweet.utils import create_mailtm_email
```

For custom email providers, pass your own `code_callback`.

---

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

---

### 🖥️ Terminal Usage

```bash
python scweet.py --words "excellent//car" --to_account "tesla" \
  --until 2020-01-05 --since 2020-01-01 --limit 10 \
  --interval 1 --display_type Latest --lang "en" --headless True
```

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