from distutils.core import setup
setup(
  name = 'Scweet',
  packages = ['Scweet'],
  version = '0.1',
  license='MIT',        # Chose a license from here: https://help.github.com/articles/licensing-a-repository
  description = 'TYPE YOUR DESCRIPTION HERE',
  author = 'Soufiane and Yassine',
  author_email = 'bengadisoufiane@gmail.com',
  url = 'https://github.com/Altimis/Scweet',
  download_url = 'https://github.com/user/reponame/archive/v_01.tar.gz',    # I explain this later on
  keywords = ['twitter', 'scraper', 'python', "crawl"],
  install_requires=[
          'msedge-selenium-tool',
          'selenium',
          'pandas',
      ],
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