"""
Scweet - Twitter Scraping Tool
Author: Yassine Ait Jeddi (@altimis)
License: MIT
Repository: https://github.com/Altimis/scweet
"""

import requests


class Domain:
    def __init__(self, domainJson):
        self.domain = domainJson["domain"]
        self.id = domainJson["id"]


class Mail:
    def __init__(self, emailJson, token):
        self.fromAddress = emailJson["from"]["address"]
        self.toAddress = []
        for receiver in emailJson["to"]:
            self.toAddress.append(receiver["address"])
        self.session = requests.Session()
        self.token = token
        self.fromName = emailJson["from"]["name"]
        self.subject = emailJson["subject"]
        self.size = emailJson["size"]
        self.id = emailJson["id"]
        self.text = self.read()["text"]

    def read(self):
        r = self.session.get(
            "https://api.mail.tm/messages/" + self.id,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )

        return r.json()

    def delete(self):
        r = self.session.delete(
            "https://api.mail.tm/messages/" + self.id,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )

        if r.status_code == 204:
            return 0
        if r.status_code == 404:
            return 1


class MailTMClient:
    def getAvailableDomains(self):
        r = self.session.get("https://api.mail.tm/domains")
        domains = []
        for domainJson in r.json()["hydra:member"]:
            # Only fetch public & active domains for now.
            if domainJson["isActive"] == True and domainJson["isPrivate"] == False:
                domains.append(Domain(domainJson))
        return domains

    def register(self, address, password):
        r = self.session.post(
            "https://api.mail.tm/accounts",
            json={
                "address": address,
                "password": password,
            },
        )

        if r.status_code == 201 or r.status_code == 200:
            (responseCode, response) = self.login(address, password)
            if responseCode == 0:
                return (0, response)
        elif r.status_code == 400:
            return (1, r.json()["detail"])
        elif r.status_code == 422:
            return (2, r.json()["detail"])
        print(f'response {r.status_code}')
        return -1, None

    def login(self, address, password):
        r = self.session.post(
            "https://api.mail.tm/token",
            json={
                "address": address,
                "password": password,
            },
        )

        if r.status_code == 200:
            return (0, r.json()["token"])
        if r.status_code == 401:
            return (1, r.json()["message"])

    def getInbox(self):
        r = self.session.get(
            "https://api.mail.tm/messages",
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
            },
        )

        inbox = []
        for emailJson in r.json()["hydra:member"]:
            inbox.append(Mail(emailJson, self.token))
        return inbox

    def __init__(self, token=None):
        self.session = requests.Session()
        self.token = token if token is not None else token
