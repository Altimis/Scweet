#! /usr/bin/env python3
# -*- coding: utf-8 -*-
# vim:fenc=utf-8

"""
Get all of the replies to tweets.
"""

from typing import List, Dict, Any, Union
from .utils import init_driver
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
import time, random, re

def get_replies_from_tweets(
        urls: List[str],
        headless: bool=True,
        proxy=None,
        show_images: bool=False,
        option=None,
        firefox: bool=False,
        env=None,
    ) -> List[Dict[str, Any]]:
    driver = init_driver(
        headless=headless,
        proxy=proxy,
        show_images=show_images,
        option=option,
        firefox=firefox,
        env=env,
    )

    driver.get('https://twitter.com')
    replies = []
    for url in urls:
        replies += get_replies(url, driver)

    return replies



def close_tab(driver):
    try:
        if len(driver.window_handles) > 1:
            driver.close()
    except Exception as e:
        print("Cannot close tab!")
    try:
        driver.switch_to.window(driver.window_handles[0])
    except Exception as e:
        print("Cannot change focus!")


def open_tab(driver):
    driver.execute_script('window.open("");')
    driver.switch_to.window(driver.window_handles[1])


def get_replies(tweet_url: str, driver):
    print(tweet_url)
    open_tab(driver)
    driver.set_page_load_timeout(5)
    try:
        driver.get(tweet_url)
    except TimeoutException as te:
        print("Failed to get tweet")
        print(te)
        if len(driver.window_handles) > 1:
            driver.close()
        return []
    tweets_xpath = '//article[@data-testid="tweet"]'
    try:
        cards_el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, tweets_xpath))
        )
    except TimeoutException as te:
        close_tab(driver)
        return []
    except Exception as e:
        close_tab(driver)
        return []

    show_more_tries, show_more_max = 0, 20
    while show_more_tries < show_more_max:
        try:
            show_els = driver.find_elements(By.XPATH, "//span[contains(text(), 'Show')]")
            if not show_els:
                raise NoSuchElementException
            show_more_button = show_els[-1]
            driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
            time.sleep(random.uniform(0.5, 1.5))
            show_more_button.click()
            time.sleep(random.uniform(0.5, 1.5))
            show_more_tries += 1
            if show_more_tries >= show_more_max:
                raise NoSuchElementException
        except NoSuchElementException:
            print("Loaded all tweets.")
            break
        except Exception as e:
            close_tab(driver)
            return []


    cards = driver.find_elements(by=By.XPATH, value=tweets_xpath)
    if len(cards) == 0:
        return []
    print(f"Found {len(cards)} tweets.")
    infos = []
    for card in cards:
        info = parse_card(card, driver)
        infos.append(info)
    root_url = infos[0]['url']
    infos[0]['root_url'] = root_url
    infos[0]['thread_url'] = tweet_url
    infos[0]['prev_url'] = None
    for i, info in enumerate(infos[1:]):
        info['root_url'] = root_url
        info['thread_url'] = tweet_url
        info['prev_url'] = infos[i-1]['url']

    close_tab(driver)
    return [info for info in infos if info['timestamp'] is not None]


def parse_card(card, driver):
    image_links = []

    info = {}
    ### This is a hack, but the thread tweet doesn't have a timestamp, 
    ### so skip because we've already accounted for it.
    try:
        info['timestamp'] = card.find_element(by=By.XPATH, value='.//time').get_attribute('datetime')
    except:
        info['timestamp'] = None

    try:
        info['username'] = card.find_element(by=By.XPATH, value='.//span').text
    except:
        info['username'] = None

    try:
        info['handle'] = card.find_element(by=By.XPATH, value='.//span[contains(text(), "@")]').text
    except:
        info['handle'] = None


    try:
        info['text'] = card.find_element(by=By.XPATH, value='.//div[@data-testid="tweetText"]').text
    except:
        info['text'] = None

    try:
        info['embedded_text'] = card.find_element(by=By.XPATH, value='.//div[2]/div[2]/div[2]').text
    except:
        info['embedded_text'] = None

    # text = comment + embedded

    try:
        info['replies_str'] = card.find_element(by=By.XPATH, value='.//div[@data-testid="reply"]').text
    except:
        info['replies_str'] = '0'

    try:
        info['retweets_str'] = card.find_element(by=By.XPATH, value='.//div[@data-testid="retweet"]').text
    except:
        info['retweets_str'] = '0'

    try:
        info['likes_str'] = card.find_element(by=By.XPATH, value='.//div[@data-testid="like"]').text
    except:
        info['likes_str'] = '0'

    try:
        elements = card.find_elements(by=By.XPATH, value='.//div[2]/div[2]//img[contains(@src, "https://pbs.twimg.com/")]')
        for element in elements:
            image_links.append(element.get_attribute('src'))
    except:
        image_links = []
    info['image_links'] = image_links

    # if save_images == True:
    #	for image_url in image_links:
    #		save_image(image_url, image_url, save_dir)
    # handle promoted tweets

    try:
        promoted = card.find_element(by=By.XPATH, value='.//div[2]/div[2]/[last()]//span').text == "Promoted"
    except:
        promoted = False
    if promoted:
        info['promoted'] = promoted

    # get a string of all emojis contained in the tweet
    try:
        emoji_tags = card.find_elements(by=By.XPATH, value='.//img[contains(@src, "emoji")]')
    except:
        emoji_tags = []
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
    info['emojis'] = emojis

    # tweet url
    try:
        element = card.find_element(by=By.XPATH, value='.//a[contains(@href, "/status/")]')
        info['url'] = element.get_attribute('href')
    except:
        info['url'] = None

    agent_xpath = '//a[contains(@href, "help.twitter.com/using-twitter/how-to-tweet")]//span'
    try:
        agent_el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, agent_xpath))
        )
        info['agent'] = agent_el.text
    except TimeoutException as te:
        print("Timeout!")
        print(te)
        info['agent'] = None
    except Exception as e:
        print("Encountered exception!")
        print(e)
        info['agent'] = None
    return info

