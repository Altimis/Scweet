# A simple and unlimited twitter scraper with python.

In the last days, Twitter banned almost every twitter scrapers. This repository represent an alternative tool to scrap tweets between two given dates (since and until), for a given language and list of words or account name, and saves a csv file containing retrieved data :  

``[UserScreenName,	UserName,	Timestamp,	Text, Embedded_text, Emojis,	Comments,	Likes,	Retweets,	Image link,	Tweet URL]``  

It is also possible to download and save the images from ``Image link`` by passing the argument ``save_images = True``, If you only want to scrape images, I recommand to set the argument ``display_type = image`` to show only tweets that contain images.  

You can scrape user profile information as well, including following and followers.  

Authentification is required in the case of followers/following scraping. It is recommended to log in with a new account (if the list of followers is very long, it is possible that your account will be banned). To log in to your account, you need to enter your username ``SCWEET_USERNAME`` and password ``SCWEET_PASSWORD`` in [env](https://github.com/Altimis/Scweet/blob/master/.env) file. You can controle the ``wait`` parameter in the ``get_users_followers`` and ``get_users_following`` functions. 

The [user](https://github.com/Altimis/Scweet/blob/master/Scweet/user.py) code allows you to get all information of a list of users, including location, join date and lists of **followers and following**. Check [this example](https://github.com/Altimis/Scweet/blob/master/Scweet/Example.py).

## Requierments : 

```pip install -r requirements.txt```

Note : You need to have Chrome installed in your system

## Results :

### Tweets :

The CSV file contains the following features (for each tweet) :

- 'UserScreenName' : 
- 'UserName' : UserName 
- 'Timestamp' : timestamp of the tweet
- 'Text' : tweet text
- 'Embedded_text' : embedded text written above the tweet. It could be an image, video or even another tweet if the tweet in question is a reply. 
- 'Emojis' : emojis existing in tweet
- 'Comments' : number of comments
- 'Likes' : number of likes
- 'Retweets' : number of retweets
- 'Image link' : Link of the image in the tweet
- 'Tweet URL' : Tweet URL.

### Following / Followers :

The ``get_users_following`` and ``get_users_followers`` in [user](https://github.com/Altimis/Scweet/blob/master/Scweet/user.py) give a list of following and followers for a given list of users.

**More features will be added soon, such as "all reaplies of each tweet for a specific twitter account"**

## Usage :

### Library :

The library is now available. To install the library, run :

``pip install Scweet==1.6``

After installing, you can use it as follow : 

```
from Scweet.scweet import scrape
from Scweet.user import get_user_information, get_users_following, get_users_followers``
```

**scrape top tweets with the words 'covid','covid19' in proximity and without replies.**  
**the process is slower as the interval is smaller (choose an interval that can divide the period of time betwee, start and max date)**

```
data = scrape(words=['bitcoin','ethereum'], since="2015-04-01", until="2015-04-15", from_account = None, interval=1, 
              headless=True, display_type="Top", save_images=False, 
              resume=False, filter_replies=False, proximity=False)
```

**scrape top tweets of with the hashtag #covid19, in proximity and without replies.**  
**the process is slower as the interval is smaller (choose an interval that can divide the period of time betwee, start and max date)**

```
data = scrape(hashtag="bitcoin", since="2021-08-05", until=None, from_account = None, interval=1, 
              headless=True, display_type="Top", save_images=False, 
              resume=False, filter_replies=True, proximity=True)
```

**Get the main information of a given list of users**  
**These users belongs to my following.**

```
users = ['nagouzil', '@yassineaitjeddi', 'TahaAlamIdrissi', 
         '@Nabila_Gl', 'geceeekusuu', '@pabu232', '@av_ahmet', '@x_born_to_die_x']
```

**this function return a list that contains : **  
**["nb of following","nb of followers", "join date", "birthdate", "location", "website", "description"]**

```
users_info = get_user_information(users, headless=True)
```

**Get followers and following of a given list of users**
**Enter your username and password in .env file. I recommande you dont use your main account.**  
**Increase wait argument to avoid banning your account and maximise the crawling process if the internet is slow. I used 1 and it's safe.**  

**set your .env file with SCWEET_USERNAME and SCWEET_PASSWORD variables and provide its path**  

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
  --words WORDS         Words to search. they should be separated by "//" : Cat//Dog.
  --from_account FROM_ACCOUNT
                        Tweets posted by "from_account" account.
  --to_account TO_ACCOUNT
                        Tweets posted in response to "to_account" account.
  --mention_account MENTION_ACCOUNT
                        Tweets mention "mention_account" account.         
  --hashtag HASHTAG
                        Tweets containing #hashtag
  --until UNTIL   max date for search query. example : %Y-%m-%d.
  --since SINCE
                        Start date for search query. example : %Y-%m-%d.
  --interval INTERVAL   Interval days between each start date and end date for
                        search queries. example : 5.
  --lang LANG           tweets language. Example : "en" for english and "fr"
                        for french.
  --headless HEADLESS   Headless webdrives or not. True or False
  --limit LIMIT         Limit tweets per <interval>
  --display_type DISPLAY_TYPE
                        Display type of twitter page : Latest or Top tweets (
  --resume RESUME       Resume the last scraping work. You need to pass the same arguments (<words>, <since>, <until>...)```

### To execute the script : 
python scweet.py --words "excellente//car" --to_account "tesla"  --until 2020-01-05 --since 2020-01-01 --limit 10 --interval 1 --display_type Latest --lang="en" --headless True
```
