import csv
import os
import datetime
import argparse
import pandas as pd

from utils import init_driver, get_last_date_from_csv, log_search_page, keep_scroling, dowload_images


# class Scweet():
def scrap(start_date, max_date, words=None, to_account=None, from_account=None, interval=5, lang=None,
          headless=True, limit=float("inf"), display_type="Top", resume=False, proxy=None, hashtag=None, show_images=False, save_images=False):
    """
    scrap data from twitter using requests, starting from start_date until max_date. The bot make a search between each start_date and end_date
    (days_between) until it reaches the max_date.

    return:
    data : df containing all tweets scraped with the associated features.
    save a csv file containing all tweets scraped with the associated features.
    """

    # initiate the driver
    if save_images == True:
        show_images = True
    driver = init_driver(headless, proxy, show_images)

    data = []
    tweet_ids = set()
    save_dir = "outputs"
    write_mode = 'w'
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)

    # start scraping from start_date until max_date
    init_date = start_date  # used for saving file
    # add interval to start_date to get end_date for te first search
    if words:
        if type(words) is str : 
            words = words.split("//")
            path = save_dir + "/" + words.split("//")[0] + '_' + str(init_date).split(' ')[0] + '_' + \
               str(max_date).split(' ')[0] + '.csv'
        else :
            path = save_dir + "/" + words[0] + '_' + str(init_date).split(' ')[0] + '_' + \
                   str(max_date).split(' ')[0] + '.csv'
    elif from_account:
        path = save_dir + "/" + from_account + '_' + str(init_date).split(' ')[0] + '_' + str(max_date).split(' ')[
            0] + '.csv'
    elif to_account:
        path = save_dir + "/" + to_account + '_' + str(init_date).split(' ')[0] + '_' + str(max_date).split(' ')[
            0] + '.csv'
    elif hashtag:
        path = save_dir + "/" + hashtag + '_' + str(init_date).split(' ')[0] + '_' + str(max_date).split(' ')[
            0] + '.csv'

    if resume:
        start_date = str(get_last_date_from_csv(path))[:10]
        write_mode = 'a'
    # start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d')
    end_date = datetime.datetime.strptime(start_date, '%Y-%m-%d') + datetime.timedelta(days=interval)

    refresh = 0
    # save_every = interval  #save every "interval" days

    # keep searching until max_date

    with open(path, write_mode, newline='', encoding='utf-8') as f:
        header = ['UserScreenName', 'UserName', 'Timestamp', 'Text', 'Emojis', 'Comments', 'Likes', 'Retweets',
                  'Image link', 'Tweet URL']
        writer = csv.writer(f)
        if write_mode == 'w':
            writer.writerow(header)
        while end_date <= datetime.datetime.strptime(max_date, '%Y-%m-%d'):
            # number of scrolls
            scroll = 0

            # log search page between start_date and end_date
            if type(start_date) != str:
                log_search_page(driver=driver, words=words,
                                start_date=datetime.datetime.strftime(start_date, '%Y-%m-%d'),
                                end_date=datetime.datetime.strftime(end_date, '%Y-%m-%d'), to_account=to_account,
                                from_account=from_account, lang=lang, display_type=display_type,
                                hashtag=hashtag)
            else:
                log_search_page(driver=driver, words=words, start_date=start_date,
                                end_date=datetime.datetime.strftime(end_date, '%Y-%m-%d'), to_account=to_account,
                                from_account=from_account, hashtag=hashtag, lang=lang, display_type=display_type)

            # number of logged pages (refresh each <between_days>)
            refresh += 1
            # number of days crossed
            days_passed = refresh * interval

            # last position of the page : the purpose for this is to know if we reached the end of the page of not so
            # that we refresh for another <start_date> and <end_date>
            last_position = driver.execute_script("return window.pageYOffset;")
            # should we keep scrolling ?
            scrolling = True

            print("looking for tweets between " + str(start_date) + " and " + str(end_date) + " ...")

            # start scrolling and get tweets
            tweet_parsed = 0

            driver, data, writer, tweet_ids, scrolling, tweet_parsed, scroll, last_position = \
                keep_scroling(driver, data, writer, tweet_ids, scrolling, tweet_parsed, limit, scroll, last_position)

            # keep updating <start date> and <end date> for every search
            if type(start_date) == str:
                start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d') + datetime.timedelta(days=interval)
            else:
                start_date = start_date + datetime.timedelta(days=interval)
            end_date = end_date + datetime.timedelta(days=interval)

    data = pd.DataFrame(data, columns = ['UserScreenName', 'UserName', 'Timestamp', 'Text', 'Emojis', 
                              'Comments', 'Likes', 'Retweets','Image link', 'Tweet URL'])

    # save images
    if save_images==True:
        print("Saving images ...")
        save_images_dir = "images"
        if not os.path.exists(save_images_dir):
            os.makedirs(save_images_dir)

        dowload_images(data["Image link"], save_images_dir)

    # close the web driver
    driver.close()

    return data

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Scrap tweets.')

    parser.add_argument('--words', type=str,
                        help='Queries. they should be devided by "//" : Cat//Dog.', default=None)
    parser.add_argument('--from_account', type=str,
                        help='Tweets from this account (axample : @Tesla).', default=None)
    parser.add_argument('--to_account', type=str,
                        help='Tweets replyed to this account (axample : @Tesla).', default=None)
    parser.add_argument('--max_date', type=str,
                        help='Max date for search query. example : %%Y-%%m-%%d.', required=True)
    parser.add_argument('--start_date', type=str,
                        help='Start date for search query. example : %%Y-%%m-%%d.', required=True)
    parser.add_argument('--interval', type=int,
                        help='Interval days between each start date and end date for search queries. example : 5.',
                        default=1)
    parser.add_argument('--lang', type=str,
                        help='Tweets language. example : "en" for english and "fr" for french.', default=None)
    parser.add_argument('--headless', type=bool,
                        help='Headless webdrives or not. True or False', default=False)
    parser.add_argument('--limit', type=int,
                        help='Limit tweets per <interval>', default=float("inf"))
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
    lang = args.lang
    headless = args.headless
    limit = args.limit
    display_type = args.display_type
    from_account = args.from_account
    to_account = args.to_account
    resume = args.resume
    proxy = args.proxy

    data = scrap(start_date, max_date, words, to_account, from_account, interval, lang, headless, limit,
                 display_type, resume, proxy)
