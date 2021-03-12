# A simple and unlimited twitter scraper with python and without authentification. 

In the last days, Twitter banned almost every twitter scrapers. This repository represent an alternative legal tool (depending on how many seconds we wait between each scrolling) to scrap tweets between two given dates (start_date and max_date), for a given language and list of words or account name, and saves a csv file containing scraped data :  

``[UserScreenName,	UserName,	Timestamp,	Text, Embedded_text, Emojis,	Comments,	Likes,	Retweets,	Image link,	Tweet URL]``  

It is also possible to download and save the images from ``Image link`` by passing the argument ``save_images = True``, If you only want to scrape images, I recommand to set the argument ``display_type = image`` to show only tweets that contain images.  

You can scrape user profile information as well, including following and followers.  

Scweet uses only selenium to scrape data. Authentification is required in the case of followers/following scraping. It is recommended to log in with a new account (if the list of followers is very long, it is possible that your account will be banned). To log in to your account, you need to enter your ``username`` and ``password`` in [env](https://github.com/Altimis/Scweet/blob/master/.env) file. You can controle the ``wait`` parameter in the ``get_users_followers`` and ``get_users_following`` functions. 

The [user](https://github.com/Altimis/Scweet/blob/master/Scweet/user.py) code allows you to get all information of a list of users, including location, join date and lists of **followers and following**. Check [this example](https://github.com/Altimis/Scweet/blob/master/Scweet/Example.ipynb).

**Note that all these functionalities will be added in the final version of the library**.

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

The ``get_users_following`` and ``get_users_followers`` in [user](https://github.com/Altimis/Scweet/blob/master/Scweet/user.py) give a list of following and followers for a given list of users. Note that each user should start with an uppercase letter. 

**More features will be added soon, such as "all reaplies of each tweet for a specific twitter account"**

## Usage :

### Notebook example : 

**You can check the example [here](https://github.com/Altimis/Scweet/blob/master/Example.ipynb).**

### Terminal :

```Scrap tweets.

optional arguments:
  -h, --help            show this help message and exit
  --words WORDS         Words to search. they should be separated by "//" : Cat//Dog.
  --from_account FROM_ACCOUNT
                        Tweets posted by "from_account" account.
  --to_account TO_ACCOUNT
                        Tweets posted in response to "to_account" account.
  --hashtag HASHTAG
                        Tweets containing #hashtag
  --max_date MAX_DATE   max date for search query. example : %Y-%m-%d.
  --start_date START_DATE
                        Start date for search query. example : %Y-%m-%d.
  --interval INTERVAL   Interval days between each start date and end date for
                        search queries. example : 5.
  --lang LANG           tweets language. Example : "en" for english and "fr"
                        for french.
  --headless HEADLESS   Headless webdrives or not. True or False
  --limit LIMIT         Limit tweets per <interval>
  --display_type DISPLAY_TYPE
                        Display type of twitter page : Latest or Top tweets (
  --resume RESUME       Resume the last scraping work. You need to pass the same arguments (<words>, <start_date>, <max_date>...)```

### To execute the script : 
python scweet.py --words "excellente//car" --to_account "tesla"  --max_date 2020-01-05 --start_date 2020-01-01 --limit 10 --interval 1 --display_type Latest --lang="en" --headless True
```
