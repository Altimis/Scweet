#!/usr/bin/python3
from distutils.core import setup
import setuptools
import io
import os

VERSION = None

# Long description
here = os.path.abspath(os.path.dirname(__file__))

with io.open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = '\n' + f.read()

# Load the package's __version__.py
about = {}
if not VERSION:
    with open(os.path.join(here, 'Scweet', '__version__.py')) as f:
        exec(f.read(), about)
else:
    about['__version__'] = VERSION

setup(
  name = 'Scweet',
  packages = ['Scweet'],
  version = about['__version__'],
  license='MIT',
  description = 'Tool for scraping Tweets',
  long_description = long_description,
  long_description_content_type="text/markdown",
  author = 'Yassine AIT JEDDI and Soufiane Bengadi',
  author_email = 'aitjeddiyassine@gmail.com',
  url = 'https://github.com/Altimis/Scweet',
  download_url = 'https://github.com/Altimis/Scweet/archive/v0.3.0.tar.gz',
  keywords = ['twitter', 'scraper', 'python', "crawl", "following", "followers", "twitter-scraper", "tweets"],
  install_requires=['selenium', 'pandas', 'python-dotenv', 'chromedriver-autoinstaller', 'urllib3'],
  classifiers=[
    'Development Status :: 4 - Beta',
    'Intended Audience :: Developers',
    'Topic :: Software Development :: Build Tools',
    'License :: OSI Approved :: MIT License',
    'Programming Language :: Python :: 3',
    'Programming Language :: Python :: 3.4',
    'Programming Language :: Python :: 3.5',
    'Programming Language :: Python :: 3.6',
    'Programming Language :: Python :: 3.7',
    'Programming Language :: Python :: 3.8',
  ],
)
