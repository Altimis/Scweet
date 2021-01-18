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
                    '//a[contains(@href,"/following")]/span[1]/span[1]').text
                followers = driver.find_element_by_xpath(
                    '//a[contains(@href,"/followers")]/span[1]/span[1]').text
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
                #print(e)
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


# Function to compare two strings 
# ignoring their cases 
def equalIgnoreCase(str1, str2): 
    i = 0

    # length of first string 
    len1 = len(str1) 

    # length of second string 
    len2 = len(str2) 

    # if length is not same 
    # simply return false since both string 
    # can not be same if length is not equal 
    if (len1 != len2): 
        return False

    # loop to match one by one 
    # all characters of both string 
    while (i < len1): 
        
        # if current characters of both string are same, 
        # increase value of i to compare next character 
        if (str1[i] == str2[i]): 
            i += 1

        # if any character of first string 
        # is some special character 
        # or numeric character and 
        # not same as corresponding character 
        # of second string then return false 
        elif (((str1[i] >= 'a' and str1[i] <= 'z') or
            (str1[i] >= 'A' and str1[i] <= 'Z')) == False): 
            return False

        # do the same for second string 
        elif (((str2[i] >= 'a' and str2[i] <= 'z') or
            (str2[i] >= 'A' and str2[i] <= 'Z')) == False): 
            return False

        # this block of code will be executed 
        # if characters of both strings 
        # are of different cases 
        else: 
            
            # compare characters by ASCII value 
            if (str1[i] >= 'a' and str1[i] <= 'z'): 
                if (ord(str1[i]) - 32 != ord(str2[i])): 
                    return False

            elif (str1[i] >= 'A' and str1[i] <= 'Z'): 
                if (ord(str1[i]) + 32 != ord(str2[i])): 
                    return False

            # if characters matched, 
            # increase the value of i 
            # to compare next char 
            i += 1

        # end of outer else block 

    # end of while loop 

    # if all characters of the first string 
    # are matched with corresponding 
    # characters of the second string, 
    # then return true 
    return True

