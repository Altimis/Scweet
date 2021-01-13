import utils
from time import sleep
import random


def get_user_information(users, driver=None, headless=True):
    """ get user information if the "from_account" argument is specified """

    driver = utils.init_driver(headless=headless)

    users_info = {}

    for user in users :

        log_user_page(user, driver)

        if user is not None:

            try:
                following = driver.find_element_by_xpath(
                    '//a[contains(@href,"/' + user + '/following")]/span[1]/span[1]').text
                followers = driver.find_element_by_xpath(
                    '//a[contains(@href,"/' + user + '/followers")]/span[1]/span[1]').text
            except Exception as e:
                #print(e)
                return

            try:
                span1 = driver.find_element_by_xpath(
                    '//div[contains(@data-testid,"UserProfileHeader_Items")]//span[1]').text
                span2 = driver.find_element_by_xpath(
                    '//div[contains(@data-testid,"UserProfileHeader_Items")]//span[2]').text
                join_date = span2
                location = span1

            except Exception as e:
                # print(e)
                join_date = driver.find_element_by_xpath(
                    '//div[contains(@data-testid,"UserProfileHeader_Items")]//span[1]').text
                location = ""

            try:
                element = driver.find_element_by_xpath('//div[contains(@data-testid,"UserProfileHeader_Items")]//a[1]')
                website = element.get_attribute("href")
            except Exception as e:
                #print(e)
                website = ""

            try:
                desc = driver.find_element_by_xpath('//div[contains(@data-testid,"UserDescription")]').text
            except Exception as e:
                #print(e)
                desc = ""

            users_info[user] = [following, followers, join_date, location, website, desc]

        else:
            print("You must specify the user")
            break
            
    return users_info


def log_user_page(user, driver, headless=True):
    driver.get('https://twitter.com/' + user)
    sleep(random.uniform(1.5, 2.5))


def get_users_followers(users, verbose=1, headless=True, wait=2):

    followers = utils.get_users_follow(users, headless, "followers", verbose, wait=wait)

    return followers


def get_users_following(users, verbose=1, headless=True, wait=2):

    following = utils.get_users_follow(users, headless, "following", verbose, wait=wait)

    return following