from Scweet.config import ScweetConfig


def test_daily_caps_defaults():
    config = ScweetConfig()
    assert config.daily_requests_limit == 300
    assert config.daily_tweets_limit == 6000


def test_daily_caps_stay_coherent_with_page_size():
    config = ScweetConfig()
    assert config.daily_requests_limit * config.api_page_size == config.daily_tweets_limit
