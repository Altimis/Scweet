import utils
from time import sleep


def get_user_information(user, driver=None):

    """ get user information if the "from_account" argument is specified """

    driver = utils.init_driver()

    log_user_page(user, driver)

    if user is not None:

    	try:
    		following = driver.find_element_by_xpath('//a[contains(@href,"/'+user+'/following")]/span[1]/span[1]').text
    		followers = driver.find_element_by_xpath('//a[contains(@href,"/'+user+'/followers")]/span[1]/span[1]').text
    	except Exception as e:
            print(e)
            return

    	try:
        	span1 = driver.find_element_by_xpath('//div[contains(@data-testid,"UserProfileHeader_Items")]//span[1]').text
        	span2 = driver.find_element_by_xpath('//div[contains(@data-testid,"UserProfileHeader_Items")]//span[2]').text
        	join_date = span2
        	location = span1

    	except Exception as e:
    		#print(e)
        	join_date = driver.find_element_by_xpath('//div[contains(@data-testid,"UserProfileHeader_Items")]//span[1]').text
        	location = ""

    	try :
    		element = driver.find_element_by_xpath('//div[contains(@data-testid,"UserProfileHeader_Items")]//a[1]')
    		website = element.get_attribute("href")
    	except Exception as e:
    		print(e)
    		website = ""

    	try :
    		desc = driver.find_element_by_xpath('//div[contains(@data-testid,"UserDescription")]').text
    	except Exception as e:
    		print(e)
    		desc = ""

    	return following, followers, join_date,location, website, desc

    else : 
        print("You should specify the user.")
        return

def log_user_page(user, driver):

    driver.get('https://twitter.com/'+user)
    sleep(2)

def get_followers(user, driver):

    utils.log_in(driver)
    log_user_page(user,driver)

    sleep(2)

    driver.find_element_by_xpath('//a[contains(@href,"/'+user+'/followers")]/span[1]/span[1]').click()

    cards = driver.find_elements_by_xpath('//div[contains(@data-testid,"UserCell")]')


    for card in cards:
        #follower = card.find_element_by_xpath('//a[contains(@href,"/")][1]').get_attribute('href')
        follower = card.find_element_by_class_name('css-901oao.css-16my406.r-1qd0xha.r-ad9z0x.r-bcqeeo.r-qvutc0').text
        print(follower)

if __name__ == '__main__':
	
	

	#following, followers, join_date, location, website, desc = get_user_information("Tesla", driver)

	#print('following:'+following+'\nfollowers: '+followers+'\njoin_date: '+join_date+ '\nlocation: ' +location + '\nwebsite: '+website + '\ndescription: '+desc)

	get_followers("Tesla", driver)

