from Scweet.config import ScweetConfig


def test_daily_caps_defaults():
    config = ScweetConfig()
    assert config.daily_requests_limit == 300
    assert config.daily_tweets_limit == 6000


def test_daily_caps_stay_coherent_with_page_size():
    config = ScweetConfig()
    assert config.daily_requests_limit * config.api_page_size == config.daily_tweets_limit


def test_impersonation_follows_the_installed_curl_cffi():
    config = ScweetConfig()
    assert config.api_http_impersonate == "chrome"


def test_a_burst_keeps_a_floor_between_two_requests():
    config = ScweetConfig()
    assert config.min_delay_s == 1.0
