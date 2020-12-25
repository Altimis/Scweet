from distutils.core import setup

with open('requirements.txt') as requirements:
    required = requirements.read().splitlines()

setup(
  name = 'Scweet',
  packages = ['Scweet'],
  version = '0.1',
  license='MIT',
  description = 'Tool for scraping Tweets',
  author = 'Soufiane and Yassine',
  author_email = 'bokudakgainaimachi@gmail.com',
  url = 'https://github.com/Altimis/Scweet',
  download_url = 'https://github.com/Altimis/Scweet/archive/0.1.tar.gz', 
  keywords = ['twitter', 'scraper', 'python', "crawl"],
  install_requires=required,
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
