from . import utils
from time import sleep
import random
import json
from selenium.webdriver.common.by import By


def get_user_information(users, driver=None, headless=True, with_extras: bool=False):
    """ get user information if the "from_account" argument is specified """

    driver = utils.init_driver(headless=headless)

    users_info = {}

    for i, user in enumerate(users):

        log_user_page(user, driver)

        if user is None:
            print('You must specify a user.')
            continue

        try:
            following = driver.find_element_by_xpath(
                '//a[contains(@href,"/following")]/span[1]/span[1]').text
            followers = driver.find_element_by_xpath(
                '//a[contains(@href,"/followers")]/span[1]/span[1]').text
        except Exception as e:
            following, followers = '', ''

        try:
            website_el = driver.find_element(By.XPATH, value="//a[contains(@data-testid,'UserUrl')]/span")
            website = website_el.text
        except Exception as e:
            website = ""

        try:
            desc = driver.find_element_by_xpath('//div[contains(@data-testid,"UserDescription")]').text
        except Exception as e:
            desc = ""
        a = 0
        try:
            join_date_el = driver.find_element(By.XPATH, value="//span[contains(@data-testid,'UserJoinDate')]/span[contains(.,'Joined ')]")
            join_date = join_date_el.text
        except Exception as e:
            join_date = ""
        try:
            birthday_el = driver.find_element(By.XPATH, value="//span[contains(@data-testid,'UserBirthdate') and contains(.,'Born ')]")
            birthday = birthday_el.text
        except Exception as e:
            birthday = ""
        try:
            location_el = driver.find_element(By.XPATH, value="//span[contains(@data-testid,'UserLocation')]/span/span")
            location = location_el.text
        except Exception as e:
            location = ""
        try:
            profile_photo_link = driver.find_element(By.XPATH, "//img[contains(@src, 'profile_images')]").get_attribute('src')
        except Exception as e:
            profile_photo_link = ''
        try:
            banner_photo_link = driver.find_element(By.XPATH, "//img[contains(@src, 'profile_banners')]").get_attribute('src')
        except Exception as e:
            banner_photo_link = ''


        prefixes = {
            'Joined ': 'join_date',
            'Born ': 'birthday',
        }
        fields = {
            'join_date': join_date, 'birthday': birthday, 'location': location,
            'desc': desc, 'website': website, 'profile_photo_link': profile_photo_link,
            'banner_photo_link': banner_photo_link,
        }
        swapped_fields = {}
        for field, val in fields.items():
            for prefix, true_field in prefixes.items():
                if val.startswith(prefix):
                    swapped_fields[field] = fields[true_field]
        for field, val in swapped_fields.items():
            #  old_val = fields[field]
            fields[field] = val

        join_date, birthday, location, desc, website = (
            fields['join_date'], fields['birthday'], fields['location'],
            fields['desc'], fields['website'],
        )


        print("--------------- " + user + " information : ---------------")
        print("Following : ", following)
        print("Followers : ", followers)
        print("Location : ", location)
        print("Join date : ", join_date)
        print("Birth date : ", birthday)
        print("Description : ", desc)
        print("Website : ", website)
        users_info[user] = [following, followers, join_date, birthday, location, website, desc]
        if with_extras:
            users_info[user] += [profile_photo_link, banner_photo_link]

        if i == len(users) - 1:
            driver.close()
            return users_info


def log_user_page(user, driver, headless=True):
    sleep(random.uniform(1, 2))
    driver.get('https://twitter.com/' + user)
    sleep(random.uniform(1, 2))


def get_users_followers(users, env, verbose=1, headless=True, wait=2, limit=float('inf'), file_path=None):
    followers = utils.get_users_follow(users, headless, env, "followers", verbose, wait=wait, limit=limit)

    if file_path == None:
        file_path = 'outputs/' + str(users[0]) + '_' + str(users[-1]) + '_' + 'followers.json'
    else:
        file_path = file_path + str(users[0]) + '_' + str(users[-1]) + '_' + 'followers.json'
    with open(file_path, 'w') as f:
        json.dump(followers, f)
        print(f"file saved in {file_path}")
    return followers


def get_users_following(users, env, verbose=1, headless=True, wait=2, limit=float('inf'), file_path=None):
    following = utils.get_users_follow(users, headless, env, "following", verbose, wait=wait, limit=limit)

    if file_path == None:
        file_path = 'outputs/' + str(users[0]) + '_' + str(users[-1]) + '_' + 'following.json'
    else:
        file_path = file_path + str(users[0]) + '_' + str(users[-1]) + '_' + 'following.json'
    with open(file_path, 'w') as f:
        json.dump(following, f)
        print(f"file saved in {file_path}")
    return following


def hasNumbers(inputString):
    return any(char.isdigit() for char in inputString)
