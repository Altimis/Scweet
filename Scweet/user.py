import utils
from time import sleep
import random


def get_user_information(user, driver=None, headless=True):
    """ get user information if the "from_account" argument is specified """

    driver = utils.init_driver(headless=headless)

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

        return following, followers, join_date, location, website, desc

    else:
        print("You should specify the user.")
        return


def log_user_page(user, driver, headless=True):
    driver.get('https://twitter.com/' + user)
    sleep(random.uniform(1.5, 2.5))


def get_followers(user, verbose=1, headless=True, wait=3):
    followers = {
        "Following": utils.get_follow(user, headless, "followers", verbose, wait=wait)
    }

    return followers


def get_following(user, verbose=1, headless=True, wait=2):
    following = {
        "Followers": utils.get_follow(user, headless, "following", verbose, wait=wait)
    }

    return following
