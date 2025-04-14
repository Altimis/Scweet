#!/usr/bin/python3
from distutils.core import setup
import setuptools
import io
import os

VERSION = None

here = os.path.abspath(os.path.dirname(__file__))

with io.open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = '\n' + f.read()

about = {}
if not VERSION:
    with open(os.path.join(here, 'Scweet', '__version__.py')) as f:
        exec(f.read(), about)
else:
    about['__version__'] = VERSION

setup(
  name='Scweet',
  packages=['Scweet'],
  version=about['__version__'],
  license='MIT',
  description='Tool for scraping Tweets',
  long_description=long_description,
  long_description_content_type="text/markdown",
  author='Yassine AIT JEDDI',
  author_email='aitjeddiyassine@gmail.com',
  url='https://github.com/Altimis/Scweet',
  download_url='https://github.com/Altimis/Scweet/archive/v3.0.tar.gz',
  keywords=['twitter', 'scraper', 'python', "crawl", "following", "followers", "twitter-scraper", "tweets"],
  install_requires=[
      'certifi',
      'python-dotenv',
      'urllib3',
      'PyVirtualDisplay',
      'beautifulsoup4==4.12.3',
      'nodriver==0.38.post1',
      'requests'
  ],
  classifiers=[
    'Development Status :: 4 - Beta',
    'Intended Audience :: Developers',
    'Topic :: Software Development :: Build Tools',
    'License :: OSI Approved :: MIT License',
    'Programming Language :: Python :: 3.9',
    'Programming Language :: Python :: 3.10',
    'Programming Language :: Python :: 3.11',
  ],
)
