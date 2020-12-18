# A simple and effective tool for tweets scraping using Selenium

In the last days, Twitter banned every tweets scrapers. This repository represent an alternative legal tool (depending on how many seconds we wait between each scrolling) to scrap tweets between two given dates (start_date and max_date), for a given language and list of requests, and saves a csv file. 

In this script, it is possible to use both chromedrivee.exe and msedgedriver.exe, based on the "navig" argument. These two drivers are available in the navigator website (based on you navigator version).  
I also tried to maximize the srcraped tweets between each start_date and end_date (these two dates are being updated for each refrsh of the website page. for more details please look at the source code in [scweet.py](https://github.com/Altimis/Scweet/blob/master/scrap.py).), and also by hiding the selenium browser window. 

## Requierments : 

```pip install -r requirements.txt```

## results :

The CSV file contains the following features (for each tweet) :
- 'UserName' : username
- 'Handle' : handle 
- 'Timestamp' : timestamp of the tweet
- 'Text' : tweet text
- 'Emojis' : emojis existing in tweet
- 'Comments' : number of comments
- 'Likes' : number of likes
- 'Retweets' : number of retweets
- 'Is_Promoted' : check if this it's a promoted tweet, since it would have nothing to do with out query.

*As a good example of the efficienty of this script, I could extract more than 30k tweets in 20 days for the query : "Tesla".*

## Usage example :

```Scrap tweets.

optional arguments:
  -h, --help            show this help message and exit
  --queries QUERIES     queries. they should be devided by "//" : Cat//Dog.
  --max_date MAX_DATE   max date for search query. example : %Y-%m-%d.
  --start_date START_DATE
                        start date for search query. example : %Y-%m-%d.
  --days_between DAYS_BETWEEN
                        days between each start date and end date for search
                        queries. example : 5.
  --navig NAVIG         navigator to use : chrome or edge.
  --lang LANG           tweets language. example : "en" for english and "fr"
                        for french.```

### To execute the script : 
python scweet.py --queries "bubbaloo//alpaccino" --max_date 2020-01-05 --start_date 2020-01-01 --days_between 2 --navig edge --lang="en"

