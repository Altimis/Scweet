import re
import csv
import os
from time import sleep
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import datetime
import argparse
from msedge.selenium_tools import Edge, EdgeOptions
import pandas as pd


def get_data(card):
    """Extract data from tweet card"""
    try:
        username = card.find_element_by_xpath('.//span').text
    except :
        return
    try:
        handle = card.find_element_by_xpath('.//span[contains(text(), "@")]').text
    except :
        return
    
    try:
        postdate = card.find_element_by_xpath('.//time').get_attribute('datetime')
    except :
        return
    try:
        comment = card.find_element_by_xpath('.//div[2]/div[2]/div[1]').text
    except :
        comment = ""
    try:
        responding = card.find_element_by_xpath('.//div[2]/div[2]/div[2]').text
    except :
        responding = ""
    
    text = comment + responding
    
    try:
        reply_cnt = card.find_element_by_xpath('.//div[@data-testid="reply"]').text
    except :
        reply_cnt= 0
    try:
        retweet_cnt = card.find_element_by_xpath('.//div[@data-testid="retweet"]').text
    except :
        retweet_cnt = 0
    try:
        like_cnt = card.find_element_by_xpath('.//div[@data-testid="like"]').text
    except :
        like_cnt = 0
    #handle promoted tweets
    try:
    	image_link = card.find_element_by_xpath('.//img[@alt="Image"]')
    	image_link = image_link.get_attribute('innerHTML')
    except:
   		image_link = ""
    try:
        promoted = card.find_element_by_xpath('.//div[2]/div[2]/[last()]//span').text == "Promoted"
    except:
        promoted = False
    
    # get a string of all emojis contained in the tweet
    """Emojis are stored as images... so I convert the filename, which is stored as unicode, into 
    the emoji character."""
    try:
        emoji_tags = card.find_elements_by_xpath('.//img[contains(@src, "emoji")]')
    except : 
        return
    emoji_list = []
    for tag in emoji_tags:
        try:
            filename = tag.get_attribute('src') 
            emoji = chr(int(re.search(r'svg\/([a-z0-9]+)\.svg', filename).group(1), base=16))
        except AttributeError:
            continue
        if emoji:
            emoji_list.append(emoji)
    emojis = ' '.join(emoji_list)
    
    tweet = (username, handle, postdate, text, emojis, reply_cnt, retweet_cnt, like_cnt, image_link, promoted)
    return tweet    

def log_search_page(driver, start_date, end_date, lang, display_type, words, to_accounts, from_accounts):

    ''' Search for this query between start_date and end_date'''

    #req='%20OR%20'.join(words)
    if from_accounts!=None:
    	from_accounts = "(from%3A"+from_accounts+")%20"
    else :
    	from_accounts=""

    if to_accounts!=None:
    	to_accounts = "(to%3A"+to_accounts+")%20"
    else:
    	to_accounts=""

    if words!=None:
    	words = str(words).split("//")
    	words = "("+str('%20OR%20'.join(words))+")%20"
    else : 
    	words=""

    if lang!=None:
    	lang = 'lang%3A'+lang
    else : 
    	lang=""
    	
    end_date = "until%3A"+end_date+"%20"
    start_date = "since%3A"+start_date+"%20"

    #to_from = str('%20'.join([from_accounts,to_accounts]))+"%20"

    driver.get('https://twitter.com/search?q='+words+from_accounts+to_accounts+end_date+start_date+lang+'&src=typed_query')
    
    sleep(1)

    # navigate to historical 'Top' or 'Latest' tab
    try:
        driver.find_element_by_link_text(display_type).click()
    except:
        print("Latest Button doesnt exist.")
    

def init_driver(navig, headless,proxy):
    # create instance of web driver
    #path to the chromdrive.exe
    if navig == "chrome":
        browser_path = 'drivers/chromedriver.exe'
        options = Options()
        if headless==True:
        	options.headless=True
        else:
        	options.headless=False
        options.add_argument('--disable-gpu')
        options.add_argument('log-level=3')
        if proxy!=None:
        	options.add_argument('--proxy-server=%s' % proxy)
        prefs = {"profile.managed_default_content_settings.images": 2}
        options.add_experimental_option("prefs", prefs)
        driver = webdriver.Chrome(options=options,executable_path=browser_path)
        driver.set_page_load_timeout(100)
        return driver
    elif navig == "edge":
        browser_path = 'drivers/msedgedriver.exe'
        options = EdgeOptions()
        if proxy!=None:
        	options.add_argument('--proxy-server=%s' % proxy)
        if headless==True:
        	options.headless = True
        	options.use_chromium = False
        else:
        	options.headless = False
        	options.use_chromium = True
        options.add_argument('log-level=3')
        driver = Edge(options=options, executable_path=browser_path)
        return driver


def get_last_date_from_csv(path):

	df = pd.read_csv(path)
	return datetime.datetime.strftime(max(pd.to_datetime(df["Timestamp"])), '%Y-%m-%dT%H:%M:%S.000Z')


def keep_scroling(driver, data, writer, tweet_ids, scrolling, tweet_parsed, limit_search, scroll, last_position):

	""" scrolling function """

	while scrolling and tweet_parsed<limit_search:
		#get the card of tweets
		page_cards = driver.find_elements_by_xpath('//div[@data-testid="tweet"]')
		for card in page_cards:
			tweet = get_data(card)
			if tweet:
				#check if the tweet is unique
				tweet_id = ''.join(tweet[:-1])
				if tweet_id not in tweet_ids:
					tweet_ids.add(tweet_id)
					data.append(tweet)
					last_date=str(tweet[2])
					print("Tweet made at: " + str(last_date)+" is found.")
					writer.writerows([tweet])
					tweet_parsed+=1
					if tweet_parsed>=limit_search:
						break
		scroll_attempt = 0
		while True and tweet_parsed<limit_search:
			# check scroll position
			print("scroll", scroll)
			#sleep(1)
			driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
			scroll+=1
			sleep(1)
			curr_position = driver.execute_script("return window.pageYOffset;")
			if last_position == curr_position:
				scroll_attempt += 1

				# end of scroll region
				if scroll_attempt >= 2:
					scrolling = False
					break
				else:
					sleep(1) # attempt another scroll
			else:
				last_position = curr_position
				break
	return driver,data,writer, tweet_ids,scrolling, tweet_parsed, scroll, last_position

def scrap(start_date, max_date, words,to_accounts, from_accounts, days_between=5, navig="chrome", lang="en", headless=True, limit_search=1000, display_type="Top", resume=False, proxy=None):

    ''' 
    scrap data from twitter using requests, starting from start_date until max_date. The bot make a search between each start_date and end_date 
    (days_between) until it reaches the max_date.

    return:
    data : df containing all tweets scraped with the associated features.
    save a csv file containing all tweets scraped with the associated features.
    '''

    #initiate the driver
    driver=init_driver(navig, headless, proxy)

    data = []
    tweet_ids = set()
    save_dir = "outputs"
    write_mode = 'w'
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    #start scraping from start_date until max_date
    init_date=start_date #used for saving file
    #add days_between to start_date to get end_date for te first search
    if words:
    	path = save_dir+"/"+words.split("//")[0]+'_'+str(init_date).split(' ')[0]+'_'+str(max_date).split(' ')[0]+'.csv'
    elif from_accounts:
    	path = save_dir+"/"+from_accounts+'_'+str(init_date).split(' ')[0]+'_'+str(max_date).split(' ')[0]+'.csv'
    elif to_accounts:
    	path = save_dir+"/"+to_accounts+'_'+str(init_date).split(' ')[0]+'_'+str(max_date).split(' ')[0]+'.csv'

    if resume==True:
    	start_date = str(get_last_date_from_csv(path))[:10]
    	write_mode='a'
    	#start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.datetime.strptime(start_date, '%Y-%m-%d') + datetime.timedelta(days=days_between)

    refresh = 0
    #save_every = days_between  #save every "days_between" days

    #keep searching until max_date

    with open(path, write_mode, newline='', encoding='utf-8') as f:
    	header = ['UserName', 'Handle', 'Timestamp', 'Text', 'Emojis', 'Comments', 'Likes', 'Retweets', 'Image link', 'Is_Promoted']
    	writer = csv.writer(f)
    	if write_mode=='w':
    		writer.writerow(header)
    	while end_date<=datetime.datetime.strptime(max_date, '%Y-%m-%d'):
	        #number of scrolls
	        scroll=0

	        #log search page between start_date and end_date
	        if type(start_date)!=str:
	            log_search_page(driver=driver,words=words,start_date=datetime.datetime.strftime(start_date,'%Y-%m-%d'),end_date=datetime.datetime.strftime(end_date,'%Y-%m-%d'),to_accounts=to_accounts, from_accounts=from_accounts,lang=lang,display_type=display_type)
	        else : 
	            log_search_page(driver=driver,words=words,start_date=start_date,end_date=datetime.datetime.strftime(end_date,'%Y-%m-%d'),to_accounts=to_accounts, from_accounts=from_accounts,lang=lang,display_type=display_type)
	        
	        #number of logged pages (refresh each <between_days>)
	        refresh+=1
	        #number of days crossed
	        days_passed= refresh*days_between

	        #last position of the page : the purpose for this is to know if we reached the end of the page of not so that we refresh for another <start_date> and <end_date>
	        last_position = driver.execute_script("return window.pageYOffset;")
	        #should we keep scrolling ?
	        scrolling = True
	        
	        print("looking for tweets between "+str(start_date)+ " and " +str(end_date)+" ...")

	        #start scrolling and get tweets
	       	tweet_parsed=0

	       	driver,data,writer, tweet_ids,scrolling, tweet_parsed, scroll, last_position =\
	       	keep_scroling(driver, data, writer, tweet_ids, scrolling, tweet_parsed, limit_search, scroll, last_position)

	        #keep updating <start date> and <end date> for every search
	        if type(start_date)==str:
	            start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d') + datetime.timedelta(days=days_between)
	        else:
	            start_date = start_date + datetime.timedelta(days=days_between)
	        end_date = end_date + datetime.timedelta(days=days_between)

    # close the web driver
    driver.close()

    return data



if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Scrap tweets.')

    parser.add_argument('--words', type=str,
                    help='Queries. they should be devided by "//" : Cat//Dog.',default = None)
    parser.add_argument('--from_account', type=str,
                    help='Tweets from this account (axample : @Tesla).',default = None)
    parser.add_argument('--to_account', type=str,
                    help='Tweets replyed to this account (axample : @Tesla).',default = None)
    parser.add_argument('--max_date', type=str,
                    help='Max date for search query. example : %%Y-%%m-%%d.',required=True)
    parser.add_argument('--start_date', type=str,
                    help='Start date for search query. example : %%Y-%%m-%%d.',required=True)
    parser.add_argument('--interval', type=int,
                    help='Interval days between each start date and end date for search queries. example : 5.', default=1)
    parser.add_argument('--navig', type=str,
                    help='Navigator to use : chrome or edge.', default = "chrome")
    parser.add_argument('--lang', type=str,
                    help='Tweets language. example : "en" for english and "fr" for french.', default = None)
    parser.add_argument('--headless', type=bool,
                    help='Headless webdrives or not. True or False', default=False)
    parser.add_argument('--limit', type=int,
                    help='Limit tweets per <interval>', default=1000)
    parser.add_argument('--display_type', type=str,
                    help='Display type of twitter page : Latest or Top', default="Top")
    parser.add_argument('--resume', type=bool,
                    help='Resume the last scraping. specify the csv file path.', default=False)
    parser.add_argument('--proxy', type=str,
                    help='Proxy server', default=None)


    args = parser.parse_args()

    words = args.words
    max_date = args.max_date
    start_date = args.start_date
    interval = args.interval
    navig = args.navig
    lang = args.lang
    headless = args.headless
    limit= args.limit
    display_type=args.display_type
    from_account = args.from_account
    to_account = args.to_account
    resume=args.resume
    proxy = args.proxy

    data=scrap(start_date, max_date, words, to_account, from_account,interval,navig,lang, headless, limit,display_type,resume,proxy)