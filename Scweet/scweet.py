import asyncio
import logging
import argparse
import csv
import json
import re
import os
import math
from datetime import datetime, timedelta, date
from typing import Awaitable, Callable, Optional, Union, List

import nodriver as uc
from requests.cookies import create_cookie
from bs4 import BeautifulSoup
from pyvirtualdisplay import Display

from .const import get_username, get_password, get_email, get_email_password
from .utils import (check_element_if_exists_by_text, check_element_if_exists_by_css,
                    get_code_from_email, extract_count_from_aria_label)

logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('seleniumwire').setLevel(logging.ERROR)
logging.getLogger('selenium').setLevel(logging.ERROR)
logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(message)s')

display = Display(visible=0, size=(1024, 768))


def parse_followers(text):
    text = text.split(' ')[0]
    if 'K' in text:
        followers = int(float(text.replace('K', '')) * 1000)
    elif 'M' in text:
        followers = int(float(text.replace('M', '')) * 1000000)
    else:
        text = text.replace(',', '')
        followers = int(text)
    return followers


class Scweet:
    main_tab: uc.Tab
    def __init__(self, proxy=None, cookies=None, cookies_path=None, user_agent=None,
                 disable_images=False, env_path=None, n_splits=5, concurrency=5, headless=True, scroll_ratio=30,
                 code_callback: Optional[Callable[[str, str], Awaitable[str]]] = None):
        self.driver = None
        self.proxy = proxy
        self.cookies = cookies
        self.user_agent = user_agent
        self.cookies_path = cookies_path
        self.disable_images = disable_images
        self.env_path = env_path
        self.n_splits = n_splits
        self.concurrency = concurrency
        self.headless = headless
        self.scroll_ratio = scroll_ratio
        # If no custom code callback is provided, use the default get_code_from_email for mailtm
        self.code_callback = code_callback or get_code_from_email
        if self.headless:
            display.start()

    async def init_nodriver(self):
        config = uc.Config()
        config.lang = "en-US"
        if self.proxy:
            logging.info(f"setting proxy : {self.proxy['host']}:{self.proxy['port']}")
            config.add_argument(f"--proxy-server={self.proxy['host']}:{self.proxy['port']}")
        if self.user_agent:
            config.add_argument(f'--user-agent={self.user_agent}')
        if self.disable_images:
            config.add_argument(f'--blink-settings=imagesEnabled=false')
        self.driver = await uc.start(config)
        self.main_tab = await self.driver.get("draft:,")
        if self.proxy:
            self.main_tab.add_handler(uc.cdp.fetch.RequestPaused, self.req_paused)
            self.main_tab.add_handler(
                uc.cdp.fetch.AuthRequired, self.auth_challenge_handler
             )

            await self.main_tab.send(uc.cdp.fetch.enable(handle_auth_requests=True))
            page = await self.driver.get("https://www.whatismyip.com/")
            await asyncio.sleep(5)

    async def auth_challenge_handler(self, event: uc.cdp.fetch.AuthRequired):
        # Split the credentials
        # Respond to the authentication challenge
        asyncio.create_task(
            self.main_tab.send(
                uc.cdp.fetch.continue_with_auth(
                    request_id=event.request_id,
                    auth_challenge_response=uc.cdp.fetch.AuthChallengeResponse(
                        response="ProvideCredentials",
                        username=self.proxy['username'],
                        password=self.proxy['password'],
                    ),
                )
            )
        )

    async def req_paused(self, event: uc.cdp.fetch.RequestPaused):
        asyncio.create_task(
            self.main_tab.send(
                uc.cdp.fetch.continue_request(request_id=event.request_id)
            )
        )

    async def enter_code(self, code):
        try:
            code_el = await self.main_tab.select("input[data-testid=ocfEnterTextTextInput]")
            await self.main_tab.sleep(15)
            if not code:
                return False
            await code_el.send_keys(code)
            await self.main_tab.sleep(2)
            try:
                next = await self.main_tab.find("Suivant", best_match=True)
            except Exception as e:
                next = await self.main_tab.find("Next", best_match=True)
            except Exception as err:
                next = await self.main_tab.find("Se Connecter", best_match=True)
            except Exception as eerr:
                next = await self.main_tab.find("Login", best_match=True)

            await next.click()
            await self.main_tab.sleep(2)
            return True

        except Exception as e:
            print(f"couldn't enter code : {e}")
            return False

    async def enter_username(self, username):
        try:
            username_el = await self.main_tab.select("input[data-testid=ocfEnterTextTextInput]")
            await username_el.send_keys(username)
            await self.main_tab.sleep(1)
            try:
                next = await self.main_tab.find("Suivant", best_match=True)
            except Exception as e:
                next = await self.main_tab.find("Next", best_match=True)
            except Exception as err:
                next = await self.main_tab.find("Se Connecter", best_match=True)
            except Exception as eerr:
                next = await self.main_tab.find("Login", best_match=True)

            await next.click()
            await self.main_tab.sleep(1)
        except Exception as e:
            print(f"Error entering username : {e}")
            pass

    async def normal_login(self, account):
        # enter username
        email_el = await self.main_tab.select("input[autocomplete=username]")
        await email_el.send_keys(account['email_address'])
        await self.main_tab.sleep(1)
        logging.info('Entered email')

        # click next
        try:
            next = await self.main_tab.find("Suivant", best_match=True)
        except:
            next = await self.main_tab.find("Next", best_match=True)
        await next.click()
        await self.main_tab.sleep(1)

        # check if username is required and enter
        try:
            await self.main_tab.sleep(1)
            await self.main_tab.find(
                "Entrez votre adresse email ou votre nom d'utilisateur.")  # Enter your phone number or username
            await self.enter_username(account['username'])
            logging.info('entered username')
        except:
            pass

        try:
            await self.main_tab.sleep(1)
            await self.main_tab.find(
                "Enter your phone number or username")  # Enter your phone number or username
            await self.enter_username(account['username'])
            logging.info('Entered username')
        except:
            pass

        # enter password
        password_el = await self.main_tab.select("input[autocomplete=current-password]")
        await password_el.send_keys(account['password'])
        await self.main_tab.sleep(2)
        logging.info('Entered password')

        # click login
        try:
            next = await self.main_tab.find("Se Connecter", best_match=True)
        except Exception as e:
            next = await self.main_tab.find("Login", best_match=True)
        except Exception as err:
            pass

        await self.main_tab.sleep(1)
        await next.click()

        if await self._is_logged_in():
            logging.info("Logged in successfully.")
            self.cookies = await self.driver.cookies.get_all(requests_cookie_format=True)
            if self.cookies_path:
                await self.driver.cookies.save(f"{self.cookies_path}/{account['username']}_cookies.dat")
            return self.main_tab, True, "", self.cookies

        # wait for code to be sent if required
        if (await check_element_if_exists_by_text(self.main_tab, "Code de confirmation") or
                await check_element_if_exists_by_text(self.main_tab, "Confirmation code")):
            # code = input("Enter the code you received in your email : ")
            await self.main_tab.sleep(10)
            code = await self.code_callback(account.get('email_address'), account.get('email_password'))
            code_status = await self.enter_code(code)
            if not code_status:
                return self.main_tab, False, "code_not_found", None
            logging.info('Entered Confirmation code')


        if (await check_element_if_exists_by_text(self.main_tab,
                                                 "Please verify your email address.", timeout=20) or
                await check_element_if_exists_by_text(self.main_tab,
                                                      'Your account has been locked.', timeout=20)):
            return self.main_tab, False, "Account locked.", None

        # check if login is successful
        if await self._is_logged_in():
            logging.info("Logged in successfully.")
            self.cookies = await self.driver.cookies.get_all(requests_cookie_format=True)
            if self.cookies_path:
                await self.driver.cookies.save(f"{self.cookies_path}/{account['username']}_cookies.dat")
            return self.main_tab, True, "", self.cookies
        else:
            return None, False, "Locked", None

    async def login(self):
        # await self.init_nodriver()
        account = {
            "email_address": get_email(self.env_path),
            "password": get_password(self.env_path),
            "username": get_username(self.env_path),
            "email_password": get_email_password(self.env_path)
        }
        self.main_tab = await self.driver.get("https://x.com/login")
        await self.main_tab.sleep(2)
        if os.path.exists(f"{self.cookies_path}/{account['username']}_cookies.dat"):
            logging.info(f"Loading cookies from path {self.cookies_path} ...")
            await self.driver.cookies.load(f"{self.cookies_path}/{account['username']}_cookies.dat")
            self.main_tab = await self.driver.get("https://x.com/login")
            await self.main_tab.sleep(3)
        elif self.cookies:
            logging.info(f"Loading cookies from file ...")
            await self.load_cookies(self.cookies)
            self.main_tab = await self.driver.get("https://x.com/login")
            await self.main_tab.sleep(3)

        if await self._is_logged_in():
            logging.info(f"Logged in successfully to {account.get('username')}")
            return self.main_tab, True, "", self.cookies

        if await check_element_if_exists_by_css(self.main_tab, "input[autocomplete=username]"):
            logging.info(f"Login in from scratch to {account.get('username')}")
            return await self.normal_login(account)
        else:
            logging.info("Something unexpected happened. Aborting.")
            return self.main_tab, False, "Other", None

    async def _is_logged_in(self):
        try:
            home = await self.main_tab.select("a[href='/home']")
            return True
        except Exception as e:
            return False

    async def load_cookies(self, cookie_dicts):
        for cdict in cookie_dicts:
            # Recreate the cookie using requests' create_cookie function
            c = create_cookie(
                name=cdict["name"],
                value=cdict["value"],
                domain=cdict["domain"],
                path=cdict["path"],
                expires=cdict["expires"],
                secure=cdict["secure"]
            )
            self.driver.cookies.set_cookie(c)

    async def get_data(self, post_soup):
        # username
        username_tag = post_soup.find('span')
        username = username_tag.get_text(strip=True) if username_tag else ""

        # handle: a span with '@'
        handle_tag = post_soup.find('span', text=lambda t: t and '@' in t)
        handle = handle_tag.get_text(strip=True) if handle_tag else ""

        # postdate: <time datetime="...">
        time_tag = post_soup.find('time')
        postdate = time_tag['datetime'] if time_tag and time_tag.has_attr('datetime') else ""

        # Full tweet text from div[data-testid=tweetText]
        tweet_text_div = post_soup.select_one('div[data-testid="tweetText"]')
        text = tweet_text_div.get_text(strip=True) if tweet_text_div else ""

        # embedded text (as previously handled)
        embedded_div = post_soup.select_one('div:nth-of-type(2) > div:nth-of-type(2) > div:nth-of-type(2)')
        embedded = embedded_div.get_text(strip=True) if embedded_div else ""

        # Counts from aria-label
        reply_div = post_soup.find('button', {'data-testid': 'reply'})
        retweet_div = post_soup.find('button', {'data-testid': 'retweet'})
        like_div = post_soup.find('button', {'data-testid': 'like'})

        reply_cnt = extract_count_from_aria_label(reply_div)
        retweet_cnt = extract_count_from_aria_label(retweet_div)
        like_cnt = extract_count_from_aria_label(like_div)

        # image links
        image_links = []
        image_tags = post_soup.select('div:nth-of-type(2) > div:nth-of-type(2) img')
        for img in image_tags:
            src = img.get('src', '')
            if 'https://pbs.twimg.com/' in src:
                image_links.append(src)

        # Check if promoted
        promoted_tag = post_soup.find('span', text='Promoted')
        if promoted_tag:
            return None  # Ignore promoted tweets

        # Emojis
        emoji_tags = post_soup.find_all('img', src=lambda s: s and 'emoji' in s)
        emoji_list = []
        for tag in emoji_tags:
            filename = tag.get('src', '')
            match = re.search(r'svg/([a-z0-9]+)\.svg', filename)
            if match:
                try:
                    emoji_cp = int(match.group(1), 16)
                    emoji = chr(emoji_cp)
                    emoji_list.append(emoji)
                except ValueError:
                    continue
        emojis = ' '.join(emoji_list)

        # tweet URL: <a href="/.../status/...">
        url_tag = post_soup.find('a', href=lambda h: h and '/status/' in h)
        tweet_url = url_tag['href'] if url_tag else ""

        tweet = {
            "username": username,
            "handle": handle,
            "postdate": postdate,
            "text": text,
            "embedded": embedded,  # reverted to embedded logic
            "emojis": emojis,
            "reply_cnt": reply_cnt,
            "retweet_cnt": retweet_cnt,
            "like_cnt": like_cnt,
            "image_links": image_links,
            "tweet_url": tweet_url
        }

        return tweet

    async def get_follows(self, username, type="following"):
        assert type in ["followers", "verified_followers", "following"]
        tab = await self.driver.get(f"https://x.com/{username}/{type}")
        await tab.sleep(3)

        num_scrolls = 0
        follow_ids = set()
        follow_urls = set()
        previous_len = 0
        while True:
            await tab.scroll_down(150)
            await tab.sleep(2)
            # count the number of li elements if they keep increase
            html_el = await tab.get_content()
            # Parse the entire HTML of the page with BeautifulSoup
            soup = BeautifulSoup(html_el, 'html.parser')
            # Find all tweet posts
            page_cards = soup.select('button[data-testid*="UserCell"]')
            for card in page_cards:
                # Get all text within the card
                card_text = card.get_text(separator=' ', strip=True)
                # print(card_text)
                # Find the first occurrence of @username using regex
                match = re.search(r'(@\w+)', card_text)
                if match:
                    username = match.group(1)
                    if username not in follow_ids:
                        follow_ids.add("@"+username)
                        follow_urls.add("/"+username)
                        print(f"got username {username}")
            if len(follow_ids) == previous_len:
                break
            previous_len = len(follow_ids)
            num_scrolls += 1
            print(f"num scrolls : {num_scrolls}")
            print(f"num usernames : {len(follow_ids)}")

    async def consume_html(self, html_queue, index, all_posts_data):
        """
        This coroutine runs concurrently with the main fetch loop.
        It consumes HTML from the queue and updates all_posts_data.
        """
        while True:
            html_el = await html_queue.get()
            await self.aget_data(html_el, index, all_posts_data)
            html_queue.task_done()

    async def aget_data(self, html_content, index, all_posts_data):
        data_file_name = f"data_{index}.json"
        soup = BeautifulSoup(html_content, 'html.parser')
        posts = soup.select('article[data-testid=tweet]')
        for post_soup in posts:
            data = await self.get_data(post_soup)
            if data:
                # Use the tweet_url as key
                tweet_id = data['tweet_url'].split("/")[-1]
                if tweet_id not in all_posts_data:
                    all_posts_data[tweet_id] = data
                    # Instead of continually reading and writing data.json, we write a separate file per task:
                    with open(data_file_name, "w") as f:
                        json.dump(all_posts_data, f)
        logging.info(f"[tab {index}] Extracted {len(all_posts_data)} tweets in total")
        return all_posts_data

    async def fetch_tweets(self, url, index, limit):
        tab = await self.driver.get(url, new_tab=True)
        if await check_element_if_exists_by_text(tab, "Retry"):
            retry = await tab.find('Retry')
            await retry.click()
            await tab.sleep(3)

        await tab.scroll_down(self.scroll_ratio//2)
        await tab.sleep(2)

        num_scrolls = 0
        all_posts_data = {}
        last_len = 0
        html_queue = asyncio.Queue()
        consumer_task = asyncio.create_task(self.consume_html(html_queue, index, all_posts_data))

        while True:
            await tab.activate()
            await tab.scroll_down(self.scroll_ratio)
            await tab.sleep(0.5)
            html_el = await tab.get_content()
            # Put the HTML in the queue for processing by the consumer
            await html_queue.put(html_el)
            num_scrolls += 1

            if await check_element_if_exists_by_text(tab, "Something went wrong. Try reloading."):
                logging.info(f"Something went wrong (rate limit) for tab index {index}")
                break
            elif num_scrolls%5 == 0:
                current_len = len(all_posts_data)
                if current_len == last_len:
                    logging.info(f"No more tweets for tab index {index}")
                    break
                last_len = current_len
            elif len(all_posts_data)>limit:
                logging.info("Reached desired tweets count.")
                break

        # Done producing, now wait for the consumer to finish processing all queued HTML
        await html_queue.join()
        # Cancel the consumer task if it's still running
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        await tab.sleep(1)
        await tab.close()

        logging.info(f"Scrolling ended after {num_scrolls} scrolls")
        logging.info(f"{len(all_posts_data)} unique tweets found after scrolling")

        return all_posts_data

    def scrape(self, **scrape_kwargs):
        """
        Synchronously execute the asynchronous scrape method.
        Users can call this method without handling asyncio themselves.
        """
        return asyncio.run(self.ascrape(**scrape_kwargs))

    async def ascrape(
            self,
            since: str,
            until: str = None,
            words: Union[str, list] = None,
            to_account: str = None,
            from_account: str = None,
            mention_account: str = None,
            lang: str = None,
            limit: float = float("inf"),
            display_type: str = "Top",
            resume: bool = False,
            hashtag: str = None,
            save_dir: str = "outputs",
            filter_replies: bool = False,
            proximity: bool = False,
            geocode: str = None,
            minreplies=None,
            minlikes=None,
            minretweets=None,
            custom_csv_name=None
    ):
        """
        Scrape tweets between [since, until] using concurrency, writing incrementally to CSV.
        If resume=True and a CSV file with the same name exists, we read its max 'Timestamp'
        and override `since` if it is more recent.
        """
        if not self.driver:
            await self.init_nodriver()

        if not until:
            until = date.today().strftime("%Y-%m-%d")

        # 1) Possibly override 'since' if resuming
        # -----------------------------------------
        # Build the default CSV path (we'll do this early so we know the file name)
        if words and isinstance(words, str):
            words = words.split("//")

        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        if words:
            fname_part = '_'.join(words)
        elif from_account:
            fname_part = from_account
        elif to_account:
            fname_part = to_account
        elif mention_account:
            fname_part = mention_account
        elif hashtag:
            fname_part = hashtag
        else:
            fname_part = "tweets"

        if not custom_csv_name:
            csv_filename = f"{save_dir}/{fname_part}_{since}_{until}.csv"
        else:
            csv_filename = f'{save_dir}/{custom_csv_name}'

        # If resume is True and the CSV already exists, read the last date
        if resume and os.path.exists(csv_filename):
            last_date_str = self.get_last_date_from_csv(csv_filename)
            if last_date_str:
                try:
                    # parse the CSV's last date (which we store as ISO8601 w/ 'T' but might have .000Z)
                    last_date_dt = datetime.fromisoformat(last_date_str.replace('Z', ''))
                    # Compare with the user-provided 'since' date
                    user_since_dt = datetime.strptime(since, "%Y-%m-%d")

                    # If the CSV's last timestamp is more recent, override
                    if last_date_dt.date() >= user_since_dt.date():
                        # new since = that CSV date
                        new_since_str = last_date_dt.strftime("%Y-%m-%d")
                        logging.info(f"[resume=True] Overriding since={since} -> {new_since_str}")
                        since = new_since_str
                except Exception as e:
                    logging.info(f"Could not parse last date from CSV: {e}")
                    # keep the original since

        # 2) Prepare the CSV header
        # -----------------------------------------
        header = [
            "tweetId", "UserScreenName", "UserName", "Timestamp", "Text",
            "Embedded_text", "Emojis", "Comments", "Likes",
            "Retweets", "Image link", "Tweet URL"
        ]

        # 3) Build all URLs (using your own build_search_url)
        # -----------------------------------------
        urls = self.build_search_url(
            since=since,
            until=until,
            lang=lang,
            display_type=display_type,
            words=words,
            to_account=to_account,
            from_account=from_account,
            mention_account=mention_account,
            hashtag=hashtag,
            filter_replies=filter_replies,
            proximity=proximity,
            geocode=geocode,
            minreplies=minreplies,
            minlikes=minlikes,
            minretweets=minretweets,
            n=self.n_splits
        )

        logging.info(f"{len(urls)} urls generated")

        # 4) Figure out write mode for CSV
        # -----------------------------------------
        write_mode = "a" if (resume and os.path.exists(csv_filename)) else "w"
        total_tweets = 0
        all_data = {}

        # 5) Open the CSV file
        # -----------------------------------------
        with open(csv_filename, write_mode, newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_mode == "w":
                writer.writerow(header)

            # 6) Initialize driver + optional login
            # -----------------------------------------
            main_tab, logged_in, reason, new_cookies = await self.login()
            if not logged_in:
                logging.info(f"Couldn't login due to {reason}")
                return

            # 7) Concurrency loop: fetch each chunk
            # -----------------------------------------
            for i in range(0, len(urls), self.concurrency):
                chunk = urls[i: i + self.concurrency]
                logging.info(f"Processing chunk with {len(chunk)} urls")
                tasks = [
                    asyncio.create_task(self.fetch_tweets(url, index=i + j, limit=limit))
                    for j, url in enumerate(chunk)
                ]
                results_list = await asyncio.gather(*tasks)

                # Write each tweet row to CSV
                for result_dict in results_list:
                    all_data.update(result_dict)
                    for tweet_id, tweet_data in result_dict.items():
                        row = [
                            tweet_id,
                            tweet_data.get("handle", ""),  # "UserScreenName"
                            tweet_data.get("username", ""),  # "UserName"
                            tweet_data.get("postdate", ""),  # "Timestamp"
                            tweet_data.get("text", ""),  # "Text"
                            tweet_data.get("embedded", ""),  # "Embedded_text"
                            tweet_data.get("emojis", ""),  # "Emojis"
                            tweet_data.get("reply_cnt", "0"),  # "Comments"
                            tweet_data.get("like_cnt", "0"),  # "Likes"
                            tweet_data.get("retweet_cnt", "0"),  # "Retweets"
                            " ".join(tweet_data.get("image_links", [])),  # "Image link"
                            tweet_data.get("tweet_url", ""),  # "Tweet URL"
                        ]
                        writer.writerow(row)
                        total_tweets += 1

                        if total_tweets >= limit:
                            logging.info(f"Reached limit of {limit} tweets. Stopping early.")
                            break
                    if total_tweets >= limit:
                        break
                if total_tweets >= limit:
                    break

            # 8) Done scraping
            # -----------------------------------------
            logging.info(f"Scraping completed. Total tweets written: {total_tweets}")

            # Cancel any lingering tasks before shutting down.
            pending_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in pending_tasks:
                task.cancel()
            await asyncio.gather(*pending_tasks, return_exceptions=True)

            # close driver if needed
            await self.close()

        return all_data

    def get_last_date_from_csv(self, path):
        """
        Reads the CSV file line-by-line to find the max 'Timestamp'.
        Returns the max date as a string in '%Y-%m-%dT%H:%M:%S.000Z' format or None.
        """
        max_dt = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.reader(f)
                # First row: header
                header = next(reader, None)
                if not header or "Timestamp" not in header:
                    return None
                ts_idx = header.index("Timestamp")

                # Read each row
                for row in reader:
                    if len(row) <= ts_idx:
                        continue
                    timestamp_str = row[ts_idx].strip()
                    if not timestamp_str:
                        continue

                    # Attempt to parse. If your CSV uses an exact known format,
                    # call datetime.strptime(timestamp_str, "<your_format>")
                    # For example, if you store it as 2025-01-21T18:34:59.000Z:
                    try:
                        # remove trailing 'Z' to parse with fromisoformat in Python 3.11+
                        dt = datetime.fromisoformat(timestamp_str.replace('Z', ''))
                    except:
                        # fallback formats, or skip
                        dt = None

                    if dt and (max_dt is None or dt > max_dt):
                        max_dt = dt
        except:
            return None

        if max_dt:
            return max_dt.strftime('%Y-%m-%dT%H:%M:%S.000Z')
        return None

    def build_search_url(self,
                         since: str,
                         until: str,
                         lang: str = None,
                         display_type: str = "Top",
                         words: Union[str, list] = None,
                         to_account: str = None,
                         from_account: str = None,
                         mention_account: str = None,
                         hashtag: str = None,
                         filter_replies: bool = False,
                         proximity: bool = False,
                         geocode: str = None,
                         minreplies: int = None,
                         minlikes: int = None,
                         minretweets: int = None,
                         n: int = 10
                         ) -> List[str]:

        display_type_allowed = {"Top", "Recent", "latest", "image"}
        if display_type not in display_type_allowed:
            raise ValueError(f"display_type must be one of {display_type_allowed}")

        # Convert `since` and `until` to datetime
        since_dt = datetime.strptime(since, "%Y-%m-%d")
        until_dt = datetime.strptime(until, "%Y-%m-%d")

        # Edge case: if since_dt >= until_dt, just return one interval
        total_days = (until_dt - since_dt).days
        if total_days < 1:
            total_days = 1

        # Set interval based on n.
        # If n == -1, split by day so that n becomes the number of days.
        if n == -1:
            n = total_days
            interval = 1  # interval in days
        else:
            interval = total_days / n

        # Prepare account/hashtag strings
        from_str = f"(from%3A{from_account})%20" if from_account else ""
        to_str = f"(to%3A{to_account})%20" if to_account else ""
        mention_str = f"(%40{mention_account})%20" if mention_account else ""
        hashtag_str = f"(%23{hashtag})%20" if hashtag else ""

        # Prepare words string
        if words:
            if isinstance(words, list) and len(words) > 1:
                # e.g. (python OR selenium)
                words_str = "(" + "%20OR%20".join(w.strip() for w in words) + ")%20"
            else:
                # single word or single-element list
                if isinstance(words, list):
                    single_word = words[0]
                else:
                    single_word = words
                words_str = f"({single_word})%20"
        else:
            words_str = ""

        # Language
        lang_str = f"lang%3A{lang}" if lang else ""

        # Display type -> &f=live or &f=image, etc.
        if display_type.lower() == "latest":
            display_type_str = "&f=live"
        elif display_type.lower() == "image":
            display_type_str = "&f=image"
        else:
            display_type_str = ""

        # Filter replies
        filter_replies_str = "%20-filter%3Areplies" if filter_replies else ""

        # Proximity
        proximity_str = "&lf=on" if proximity else ""

        # geocode
        geocode_str = f"%20geocode%3A{geocode}" if geocode else ""

        # min number of replies, likes, retweets
        minreplies_str = f"%20min_replies%3A{minreplies}" if minreplies is not None else ""
        minlikes_str = f"%20min_faves%3A{minlikes}" if minlikes is not None else ""
        minretweets_str = f"%20min_retweets%3A{minretweets}" if minretweets is not None else ""

        # Build intervals
        urls = []
        for i in range(n):
            current_since = since_dt + timedelta(days=i * interval)
            current_until = since_dt + timedelta(days=(i + 1) * interval)

            # Cap current_until at the final date
            if current_until > until_dt:
                current_until = until_dt

            since_part = f"since%3A{current_since.strftime('%Y-%m-%d')}%20"
            until_part = f"until%3A{current_until.strftime('%Y-%m-%d')}%20"

            # Build final path
            path = (
                    "https://x.com/search?q="
                    + words_str
                    + from_str
                    + to_str
                    + mention_str
                    + hashtag_str
                    + until_part
                    + since_part
                    + lang_str
                    + filter_replies_str
                    + geocode_str
                    + minreplies_str
                    + minlikes_str
                    + minretweets_str
                    + "&src=typed_query"
                    + display_type_str
                    + proximity_str
            )

            urls.append(path)

            # If we've reached or passed the final date, stop early
            if current_until >= until_dt:
                break

        return urls

    async def consume_profile(self, html_queue, all_infos):
        while True:
            handle, html_el = await html_queue.get()
            await self.aget_profile(html_el, handle, all_infos)
            html_queue.task_done()

    async def aget_profile(self, html, handle, all_infos):
        """
        Extract user profile information from the provided HTML and update all_infos.

        Expected fields:
          - username (display name)
          - following
          - verified_followers
          - location
          - website
          - join_date
          - description
        """
        soup = BeautifulSoup(html, 'html.parser')

        # Extract following using the element that shows following count.
        try:
            # This selector finds an <a> whose href contains "/following", then finds a nested span with text.
            following_elem = soup.select_one('a[href*="/following"] span span')
            following = following_elem.get_text(strip=True) if following_elem else None
            if following:
                following = parse_followers(following)
        except Exception:
            following = None

        # Extract verified followers from the corresponding element.
        try:
            verified_elem = soup.select_one('a[href*="/verified_followers"] span span')
            verified_followers = verified_elem.get_text(strip=True) if verified_elem else None
            if verified_followers:
                verified_followers = parse_followers(verified_followers)
        except Exception:
            verified_followers = None

        # Extract username (display name) from the element with data-testid="UserName".
        try:
            username_elem = soup.select_one('div[data-testid="UserName"] span')
            username = username_elem.get_text(strip=True) if username_elem else None
        except Exception:
            username = None

        # Extract location using the element with data-testid "UserLocation".
        try:
            location_elem = soup.select_one('span[data-testid="UserLocation"] span')
            location = location_elem.get_text(strip=True) if location_elem else ""
        except Exception:
            location = ""

        # Extract website using the element with data-testid "UserUrl"; we use the href attribute.
        try:
            website_elem = soup.select_one('a[data-testid="UserUrl"]')
            website = website_elem.get("href", "") if website_elem else ""
        except Exception:
            website = ""

        # Extract join date using the element with data-testid "UserJoinDate".
        try:
            join_date_elem = soup.select_one('span[data-testid="UserJoinDate"] span')
            join_date = join_date_elem.get_text(strip=True) if join_date_elem else ""
        except Exception:
            join_date = ""

        # Extract profile description from the element with data-testid "UserDescription".
        try:
            desc_elem = soup.select_one('div[data-testid="UserDescription"]')
            desc = desc_elem.get_text(strip=True) if desc_elem else ""
        except Exception:
            desc = ""

        # Build the profile dictionary.
        profile = {
            "username": username,
            "following": following,
            "verified_followers": verified_followers,
            "location": location,
            "website": website,
            "join_date": join_date,
            "description": desc
        }
        all_infos[handle] = profile
        return all_infos

    async def process_handles_chunk(self, handles_chunk):
        tab = await self.driver.get("https://x.com", new_tab=True)
        all_infos = {}
        profiles_queue = asyncio.Queue()
        consumer_task = asyncio.create_task(self.consume_profile(profiles_queue, all_infos))
        for handle in handles_chunk:
            try:
                await tab.activate()
                await tab.get(f"https://x.com/{handle}")
                await tab.sleep(4)
                await tab.activate()
                html_el = await tab.get_content()
                # Put the HTML in the queue for processing by the consumer
                await profiles_queue.put((handle, html_el))
            except Exception as e:
                pass

        await profiles_queue.join()
        consumer_task.cancel()
        try:
            await consumer_task
        except asyncio.CancelledError:
            pass

        await tab.close()
        return all_infos

    def get_user_information(self, **profiles_kwargs):
        return asyncio.run(self.aget_user_information(**profiles_kwargs))

    async def aget_user_information(self, handles, login=False):
        if not self.driver:
            await self.init_nodriver()

        if login:
            await self.login()
        chunk_size = math.ceil(len(handles) / self.concurrency)
        tasks = []

        for i in range(0, len(handles), chunk_size):
            chunk = handles[i: i + chunk_size]
            tasks.append(asyncio.create_task(self.process_handles_chunk(chunk)))

        results_list = await asyncio.gather(*tasks)

        consolidated_results = {}
        for result in results_list:
            consolidated_results.update(result)

        # Cancel any lingering tasks before shutting down.
        pending_tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in pending_tasks:
            task.cancel()
        await asyncio.gather(*pending_tasks, return_exceptions=True)

        await self.close()

        return consolidated_results

    async def close(self):
        if self.driver:
            self.driver.stop()
            self.driver = None

    async def __aenter__(self):
        await self.init_nodriver()

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Scrape tweets.')

    parser.add_argument('--words', type=str,
                        help='Queries. they should be devided by "//" : Cat//Dog.', default=None)
    parser.add_argument('--from_account', type=str,
                        help='Tweets from this account (example : @Tesla).', default=None)
    parser.add_argument('--to_account', type=str,
                        help='Tweets replyed to this account (example : @Tesla).', default=None)
    parser.add_argument('--mention_account', type=str,
                        help='Tweets mention a account (example : @Tesla).', default=None)
    parser.add_argument('--hashtag', type=str,
                        help='Hashtag', default=None)
    parser.add_argument('--until', type=str,
                        help='Max date for search query. example : %%Y-%%m-%%d.', required=True)
    parser.add_argument('--since', type=str,
                        help='Start date for search query. example : %%Y-%%m-%%d.', required=True)
    parser.add_argument('--n_splits', type=int,
                        help='Number of splits which will be performed on the since/until interval.',
                        default=5)
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
    parser.add_argument('--proximity', type=bool,
                        help='Proximity', default=False)
    parser.add_argument('--geocode', type=str,
                        help='Geographical location coordinates to center the search, radius. No compatible with proximity',
                        default=None)
    parser.add_argument('--minreplies', type=int,
                        help='Min. number of replies to the tweet', default=None)
    parser.add_argument('--minlikes', type=int,
                        help='Min. number of likes to the tweet', default=None)
    parser.add_argument('--minretweets', type=int,
                        help='Min. number of retweets to the tweet', default=None)
    parser.add_argument('--cookies_path', type=str,
                        help='Cookies path for login', default=None)
    parser.add_argument('--user_agent', type=str,
                        help='User agent', default=None)
    parser.add_argument('--disable_images', type=bool,
                        help='Display images while crawling', default=False)
    parser.add_argument('--env_path', type=str,
                        help='.env file holding account credentials', default=".env")
    parser.add_argument('--concurrency', type=int,
                        help='Number of concurrent crawling in the same n_split', default=5)

    args = parser.parse_args()

    words = args.words
    until = args.until
    since = args.since
    n_splits = args.interval
    lang = args.lang
    headless = args.headless
    limit = args.limit
    display_type = args.display_type
    from_account = args.from_account
    to_account = args.to_account
    mention_account = args.mention_account
    hashtag = args.hashtag
    resume = args.resume
    proxy = args.proxy
    proximity = args.proximity
    geocode = args.geocode
    minreplies = args.minreplies
    minlikes = args.minlikes
    minretweets = args.minlikes
    cookies_path = args.cookies_path
    user_agent = args.user_agent
    disable_images = args.disable_images
    env_path = args.env_path
    concurrency = args.concurrency



    scweet = Scweet(None, None, cookies_path, user_agent, disable_images, env_path, n_splits, concurrency, headless)

    scweet.scrape(since=since, until=until, words=words, to_account=to_account, from_account=from_account,
                     mention_account=mention_account,
                     hashtag=hashtag, lang=lang, limit=limit,
                     display_type=display_type, resume=resume, filter_replies=False, proximity=proximity,
                     geocode=geocode, minreplies=minreplies, minlikes=minlikes, minretweets=minretweets)
