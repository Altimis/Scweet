from distutils.core import setup
import setuptools

setup(
  name = 'Scweet',
  packages = ['Scweet'],
  version = '0.2.1',
  license='MIT',
  description = 'Tool for scraping Tweets',
  author = 'Yassine AIT JEDDI and Soufiane Bengadi ',
  author_email = 'bokudakgainaimachi@gmail.com',
  url = 'https://github.com/Altimis/Scweet',
  download_url = 'https://github.com/Altimis/Scweet/archive/0.1.1.tar.gz',
  keywords = ['twitter', 'scraper', 'python', "crawl", "following", "followers", "twitter-scraper", "tweets"],
  install_requires=['selenium', 'pandas', 'python-dotenv', 'chromedriver-autoinstaller'],
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
