import re
import random
import datetime
import string
from .mailtm import *
import urllib


async def check_element_if_exists_by_text(tab, text, timeout=10):
    try:
        await tab.find(text, timeout=timeout)
        return True
    except:
        return False


async def check_element_if_exists_by_css(tab, css, timeout=20):
    try:
        await tab.select(css, timeout=timeout)
        return True
    except:
        return False


async def get_code_from_email(email_address, email_password):
    try:
        retries = 0
        while retries < 5:
            mailclient = MailTMClient()
            resp_code, token = mailclient.login(email_address, email_password)
            if 'Invalid' in token:
                return "code_not_found"
            r = requests.get(
                "https://api.mail.tm/messages",
                headers={
                    "Authorization": "Bearer " + token,
                    "Content-Type": "application/json",
                },
            )
            inbox = []
            for emailJson in r.json()["hydra:member"]:
                inbox.append(Mail(emailJson, token))
            # print(f"all emails : {[mss.read() for mss in inbox]}")
            ig_messages = [mss.read() for mss in inbox] # if mss.read()['from']['name'] == "Instagram"]
            message = ig_messages[0]
            created_at = datetime.strptime(message['createdAt'], "%Y-%m-%dT%H:%M:%S+00:00")
            now = datetime.now()
            # time_diff = (now - created_at).seconds + (now - created_at).days * 24 * 3600
            # if time_diff < 3900:
            text = message['subject']
            match = re.search(r'Your X confirmation code is (.+)\b', text)
            if match:
                verif_code = match.group(1)  # Access the first capturing group
                log = f"Verification code found: {verif_code}"
                return verif_code
            else:
                retries += 1
                continue

        return "code_not_found"
    except Exception as e:
        log = f"An error occurred while fetching email: {e}"
        return "code_not_found"


def extract_count_from_aria_label(element):
    if not element:
        return "0"
    aria_label = element.get('aria-label', '')
    match = re.search(r'(\d+)', aria_label)
    if match:
        return match.group(1)
    return "0"


def dowload_images(urls, save_dir):
    for i, url_v in enumerate(urls):
        for j, url in enumerate(url_v):
            urllib.request.urlretrieve(url, save_dir + '/' + str(i + 1) + '_' + str(j + 1) + ".jpg")


def generate_mail_prefix():
    """
    Generate a random, human-readable email prefix.

    Returns:
        str: A randomly generated email prefix.
    """
    # Define components for the email prefix
    words = [
        "jola", "needs", "abass", "smart", "xaax", "looool",
        "brav", "smih", "kond", "jit", "blaso", "sota", "kaw", "jlov"
    ]
    separators = ['.', '_', '-', '']
    random_word = random.choice(words)
    random_number = ''.join(random.choices(string.digits, k=4))  # 4-digit number
    random_letters = ''.join(random.choices(string.ascii_lowercase, k=3))  # 3 random letters
    separator = random.choice(separators)

    # Combine the components
    prefix = f"{random_word}{separator}{random_letters}{separator}{random_number}"

    return prefix

def generate_password(length=12):
    """
    Generate a strong password with the specified length.

    Parameters:
        length (int): Length of the password to be generated. Default is 12.

    Returns:
        str: A randomly generated password.
    """
    if length < 8:
        raise ValueError("Password length should be at least 8 characters.")

    # Define the character pools
    lower = string.ascii_lowercase
    upper = string.ascii_uppercase
    digits = string.digits
    special = string.punctuation

    # Ensure the password includes at least one of each type of character
    all_characters = lower + upper + digits + special
    password = [
        random.choice(lower),
        random.choice(upper),
        random.choice(digits),
        random.choice(special),
    ]

    # Fill the rest of the password length with random characters from all pools
    password += random.choices(all_characters, k=length - 4)

    # Shuffle the password to ensure randomness
    random.shuffle(password)

    return ''.join(password)

def create_mailtm_email(max_retries=10):
    """
    Synchronous method to create an email account via MailTMClient.
    Keeps trying until the email is successfully created or max_retries is reached.

    Returns a tuple (email, password) if successful; otherwise, returns (None, None).
    """
    retries = 0
    mailtm = MailTMClient()

    while retries < max_retries:
        try:
            print("Creating email ...")
            available_domains = mailtm.getAvailableDomains()
            if available_domains and len(available_domains) > 0:
                available_domain = available_domains[0].domain
            else:
                retries += 1
                continue

            # Assuming generate_mail_prefix and generate_password are now synchronous methods.
            email_prefix = generate_mail_prefix()
            password = generate_password()
            email = f"{email_prefix}@{available_domain}"
            resp, key = mailtm.register(email, password)
            if resp == 0:
                print(f"Email {email} created ")
                return email, password
            else:
                print("Registration failed; retrying...")
        except Exception as ex:
            print(f"Exception in create_email: {ex}")
        retries += 1

    print("Max retries reached; no email created.")
    return None, None

