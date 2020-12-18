# A simple and effective tool for tweets scraping using Selenium

In the last days, Twitter banned every tweets scrapers. This repository represent an alternative legal tool (depending on how many seconds we wait between each scrolling) to scrap tweets between two given dates (start_date and max_date), for a given language and list of requests, and saves a csv file containing (for each tweet) : 

- 'UserName' : username
- 'Handle' : handle 
- 'Timestamp' : timestamp of the tweet
- 'Text' : tweet text
- 'Emojis' : emojis existing in tweet
- 'Comments' : number of comments
- 'Likes' : number of likes
- 'Retweets' : number of retweets
- 'Is_Promoted' : check if this it's a promoted tweet, since it would have nothing to do with out query.

In this script, it is possible to use both chromedrivee.exe and msedgedriver.exe, based on the "navig" argument. These two drivers are available in the navigator website (based on you navigator version).  
I also tried to maximize the srcraped tweets between each start_date and end_date (these two dates are being updated for each refrsh of the website page. for more details please look at the source code in [scweet.py](https://github.com/Altimis/Scweet/blob/master/scrap.py).), and also by hiding the selenium browser window. 


## Requierments : 

```pip install -r requirements.txt```
## Usage example :

![](images/usage.PNG?raw=true)

### To execute the script : 
```python scweet.py --queries "bubbaloo//alpaccino" --max_date 2020-01-05 --start_date 2020-01-01 --days_between 2 --navig edge --lang="en"```

### results :
 
![](images/csv1.PNG?raw=true)
![](images/csv2.PNG?raw=true)

## Licence : 
