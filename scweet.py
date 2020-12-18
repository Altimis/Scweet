import re
import csv
from getpass import getpass
from time import sleep
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException
from selenium import webdriver
import datetime
import argparse
from msedge.selenium_tools import Edge, EdgeOptions


def get_tweet_data(card):
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
        return
    try:
        responding = card.find_element_by_xpath('.//div[2]/div[2]/div[2]').text
    except :
        return
    try:
        text = comment + responding
    except :
        return
    try:
        reply_cnt = card.find_element_by_xpath('.//div[@data-testid="reply"]').text
    except :
        reply_cnt= float("nan")
    try:
        retweet_cnt = card.find_element_by_xpath('.//div[@data-testid="retweet"]').text
    except :
        retweet_cnt = float("nan")
    try:
        like_cnt = card.find_element_by_xpath('.//div[@data-testid="like"]').text
    except :
        like_cnt = float("nan")
    #handle promoted tweets
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
    
    tweet = (username, handle, postdate, text, emojis, reply_cnt, retweet_cnt, like_cnt, promoted)
    return tweet    



def log_search(driver, start_date, end_date,requests,lang):

    ''' Search for this query between start_date and end_date'''

    req='%20OR%20'.join(requests)
    driver.get('https://twitter.com/search?q=('+req+')%20until%3A'+end_date+'%20since%3A'+start_date+'%20lang%3A'+lang+'&src=typed_query')
    
    #https://twitter.com/search?q=(AIRbnb%20OR%20Amazon%20Web%20Services%20)%20until%3A'+end_date+'%20since%3A'+start_date+'&src=typed_query

    # find search input and search for term
    #search_input = driver.find_element_by_xpath('//input[@aria-label="Search query"]')
    #search_input.send_keys(search_term)
    #search_input.send_keys(Keys.RETURN)
    sleep(1)

    # navigate to historical 'Top' tab
    driver.find_element_by_link_text('Latest').click()
    

def init_driver(navig="chrome"):
    # create instance of web driver
    #path to the chromdrive.exe
    if navig == "chrome":
        browser_path = 'C:/Users/Yassine/Documents/GitHub/Predict-AXA-stocks-prices/drivers/chromedriver.exe'
        driver = webdriver.Chrome(executable_path=browser_path)
        driver.set_page_load_timeout(100)
        return driver
    elif navig == "edge":
        browser_path = 'C:/Users/Yassine/Documents/GitHub/Predict-AXA-stocks-prices/drivers/msedgedriver.exe'
        options = EdgeOptions()
        options.headless = True
        options.use_chromium = True
        driver = Edge(options=options, executable_path=browser_path)
        return driver


def scrap(requests, start_date, max_date, days_between, navig="chrome", lang="en"):

    ''' 
    scrap data from twitter using requests, starting from start_date until max_date. The bot make a search between each start_date and end_date 
    (days_between) until it reaches the max_date.

    return:
    data : df containing all tweets scraped with the associated features.
    save a csv file containing all tweets scraped with the associated features.
    '''

    #initiate the driver
    driver=init_driver(navig)
    data = []
    tweet_ids = set()

    #start scraping from start_date until max_date
    init_date=start_date #used for saving file
    #add days_between to start_date to get end_date for te first search
    end_date = datetime.datetime.strptime(start_date, '%Y-%m-%d') + datetime.timedelta(days=days_between)

    refresh = 0
    save_every = days_between  #save every "days_between" days
    #saved_header=False

    while end_date<=datetime.datetime.strptime(max_date, '%Y-%m-%d'):
        scroll=0
        if type(start_date)!=str:
            log_search(driver=driver,requests=requests,start_date=datetime.datetime.strftime(start_date,'%Y-%m-%d'),end_date=datetime.datetime.strftime(end_date,'%Y-%m-%d'),lang=lang)
        else : 
            log_search(driver=driver,requests=requests,start_date=start_date,end_date=datetime.datetime.strftime(end_date,'%Y-%m-%d'),lang=lang)
        
        refresh+=1
        days_passed= refresh*days_between

        last_position = driver.execute_script("return window.pageYOffset;")
        scrolling = True
        
        print("looking for tweets between "+str(start_date)+ " and " +str(end_date))

        while scrolling:
            page_cards = driver.find_elements_by_xpath('//div[@data-testid="tweet"]')
            for card in page_cards[-40:]:
                tweet = get_tweet_data(card)
                if tweet:
                    is_promoted= tweet[-1]
                    if is_promoted==True:
                        print("tis tweet is promoted : ", tweet[3])
                    tweet_id = ''.join(tweet[:-1])
                    if tweet_id not in tweet_ids and is_promoted==False:
                        tweet_ids.add(tweet_id)
                        data.append(tweet)
                        try:
                            last_date=datetime.datetime.strptime(data[-1][2],'%Y-%m-%dT%H:%M:%S.000Z')
                        except :
                            last_date=data[-1][2]
                        print(last_date)
                        

            scroll_attempt = 0
            while True:
                # check scroll position
                print("scroll", scroll)
                sleep(1)
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
                        sleep(2) # attempt another scroll
                else:
                    last_position = curr_position
                    break
        #keep updating start date and end date for every search
        if type(start_date)==str:
            start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d') + datetime.timedelta(days=days_between)
        else:
            start_date = start_date + datetime.timedelta(days=days_between)
        end_date = end_date + datetime.timedelta(days=days_between)

        if days_passed%save_every==0:

            with open(requests[0]+'_'+str(init_date).split(' ')[0]+'_'+str(max_date).split(' ')[0]+'.csv', 'a', newline='', encoding='utf-8') as f:
                header = ['UserName', 'Handle', 'Timestamp', 'Text', 'Emojis', 'Comments', 'Likes', 'Retweets', 'Is_Promoted']
                writer = csv.writer(f)
                #if saved_header==False:
                writer.writerow(header)
                saved_header=True
                writer.writerows(data)

    # close the web driver
    driver.close()

    return data



if __name__ == '__main__':

    parser = argparse.ArgumentParser(description='Scrap tweets.')

    parser.add_argument('--queries', type=str,
                    help='queries. they should be devided by "//" : Cat//Dog.')
    parser.add_argument('--max_date', type=str,
                    help='max date for search query. example : %%Y-%%m-%%d.')
    parser.add_argument('--start_date', type=str,
                    help='start date for search query. example : %%Y-%%m-%%d.')
    parser.add_argument('--days_between', type=int,
                    help='days between each start date and end date for search queries. example : 5.')
    parser.add_argument('--navig', type=str,
                    help='navigator to use : chrome or edge.')
    parser.add_argument('--lang', type=str,
                    help='tweets language. example : "en" for english and "fr" for french.')

    args = parser.parse_args()

    queries = args.queries
    requests = str(queries).split("//")
    max_date = args.max_date
    start_date = args.start_date
    days_between = args.days_between
    navig = args.navig
    lang = args.lang

    data=scrap(requests,start_date,max_date,days_between,navig,lang)

