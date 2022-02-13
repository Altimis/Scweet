

# A simple and unlimited Twitter scraper with python.

Recently, Twitter has banned almost every Twitter scraper. This repository presents an alternative tool to scrape Twitter based on 3 functions:  
- [scrape](https://github.com/Altimis/Scweet/blob/master/Scweet/scweet.py): Scrapes all the information regarding tweets between two given dates, for a given language and list of words or account name, in the form of a csv file containing retrieved data (more storage methods will be added). 
- [get_user_information](https://github.com/Altimis/Scweet/blob/master/Scweet/user.py): Scrapes users information, incluing number of following and followers, location and description.
- [get_users_followers and get_users_following](https://github.com/Altimis/Scweet/blob/master/Scweet/user.py): Scrapes followers and following accounts for a given list of users.  

It is also possible to download the images showed in tweets by passing the argument `save_images = True`. If you only want to scrape images, it is recommended to set the argument `display_type = image` to show only tweets that contain images. 

Authentication is required for scraping followers/following. It is recommended to log in with a new account, otherwise the account could be banned if the list of followers is very long. To log in to your account, you need to enter your username `SCWEET_USERNAME` and password `SCWEET_PASSWORD` in the [.env](https://github.com/Altimis/Scweet/blob/master/.env) file. You can control the `wait` parameter in the `get_users_followers` and `get_users_following` functions according to you internet speed. 

## Requirements : 

`pip install -r requirements.txt`

Note : You must have Chrome installed on your system. 

## Results :

### Tweets :

The CSV file contains the following features (for each tweet) :

- 'UserScreenName' : 
- 'UserName' : UserName 
- 'Timestamp' : timestamp of the tweet
- 'Text' : tweet text
- 'Embedded_text' : embedded text written above the tweet. This can be an image, a video or even another tweet if the tweet in question is a reply
- 'Emojis' : emojis in the tweet
- 'Comments' : number of comments
- 'Likes' : number of likes
- 'Retweets' : number of retweets
- 'Image link' : link of the image in the tweet
- 'Tweet URL' : tweet URL

### Following / Followers :

The `get_users_following` and `get_users_followers` in [user](https://github.com/Altimis/Scweet/blob/master/Scweet/user.py) file give a list of following and followers for a given list of users.

## Usage :

### Library :

The library is now available. To install the library, run :

`pip install Scweet==1.8`

After the installation, you can import and use the functions as follows:

```
from Scweet.scweet import scrape
from Scweet.user import get_user_information, get_users_following, get_users_followers
```

**Scrape top tweets with the words 'bitcoin', 'ethereum'  geolocated less than 200 km from Alicante (Spain) Lat=38.3452, Long=-0.481006 and without replies:**  
**The process is slower as the interval is smaller (choose an interval that can divide the period of time between, start and max date)**

```
data = scrape(words=['bitcoin','ethereum'], since="2021-10-01", until="2021-10-05", from_account = None,         interval=1, headless=False, display_type="Top", save_images=False, lang="en",
	resume=False, filter_replies=False, proximity=False, geocode="38.3452,-0.481006,200km")
```

**Scrape top tweets of with the hashtag #bitcoin, in proximity and without replies:**  
**The process is slower as the interval is smaller (choose an interval that can divide the period of time between, start and max date)**

```
data = scrape(hashtag="bitcoin", since="2021-08-05", until=None, from_account = None, interval=1, 
              headless=True, display_type="Top", save_images=False, 
              resume=False, filter_replies=True, proximity=True)
```

**Get the main information of a given list of users:**  
**These users follow me on Twitter**

```
users = ['nagouzil', '@yassineaitjeddi', 'TahaAlamIdrissi', 
         '@Nabila_Gl', 'geceeekusuu', '@pabu232', '@av_ahmet', '@x_born_to_die_x']
```

**This function will return a list that contains : **  
**["no. of following","no. of followers", "join date", "date of birth", "location", "website", "description"]**

```
users_info = get_user_information(users, headless=True)
```

**Get followers and following of a given list of users**
**Enter your username and password in .env file. I recommend you do not use your main account.**  
**Increase wait argument to avoid banning your account and maximize the crawling process if the internet is slow. I used 1 and it's safe.**  

**Set your .env file with `SCWEET_EMAIL` , `SCWEET_USERNAME`  and `SCWEET_PASSWORD` variables and provide its path**  

```
env_path = ".env"

following = get_users_following(users=users, env=env_path, verbose=0, headless=True, wait=2, limit=50, file_path=None)

followers = get_users_followers(users=users, env=env_path, verbose=0, headless=True, wait=2, limit=50, file_path=None)
```

### Terminal :

```
Scrape tweets.

optional arguments:
  -h, --help            show this help message and exit
  --words WORDS         Words to search for. they should be separated by "//" : Cat//Dog.
  --from_account FROM_ACCOUNT
                        Tweets posted by "from_account" account.
  --to_account TO_ACCOUNT
                        Tweets posted in response to "to_account" account.
  --mention_account MENTION_ACCOUNT
                        Tweets that mention "mention_account" account.         
  --hashtag HASHTAG
                        Tweets containing #hashtag
  --until UNTIL         End date for search query. example : %Y-%m-%d.
  --since SINCE
                        Start date for search query. example : %Y-%m-%d.
  --interval INTERVAL   Interval days between each start date and end date for
                        search queries. example : 5.
  --lang LANG           Tweets language. Example : "en" for english and "fr"
                        for french.
  --headless HEADLESS   Headless webdrives or not. True or False
  --limit LIMIT         Limit tweets to be scraped.
  --display_type DISPLAY_TYPE
                        Display type of Twitter page : Latest or Top tweets
  --resume RESUME       Resume the last scraping. specify the csv file path.
  --proxy PROXY         Proxy server
  --proximity PROXIMITY Proximity
  --geocode GEOCODE     Geographical location coordinates to center the
                        search (), radius. No compatible with proximity
  --minreplies MINREPLIES
                        Min. number of replies to the tweet
  --minlikes MINLIKES   Min. number of likes to the tweet
  --minretweets MINRETWEETS
                        Min. number of retweets to the tweet
```

### To run the script :
`python scweet.py --words "excellente//car" --to_account "tesla"  --until 2020-01-05 --since 2020-01-01 --limit 10 --interval 1 --display_type Latest --lang="en" --headless True`
