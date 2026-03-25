from __future__ import annotations

import json
import sys

import pytest

from Scweet.cli import build_parser, _print_results, _sanitize_query, _make_client, main


# ── Helpers ────────────────────────────────────────────────────────────────

def parse(*argv: str):
    """Parse a CLI argv list and return the Namespace."""
    return build_parser().parse_args(list(argv))


class _FakeClient:
    def __init__(self):
        self.search_calls = []
        self.profile_tweets_calls = []
        self.followers_calls = []
        self.following_calls = []
        self.user_info_calls = []

    def search(self, *args, **kwargs):
        self.search_calls.append((args, kwargs))
        return [{"id": "1"}]

    def get_profile_tweets(self, *args, **kwargs):
        self.profile_tweets_calls.append((args, kwargs))
        return [{"id": "2"}]

    def get_followers(self, *args, **kwargs):
        self.followers_calls.append((args, kwargs))
        return [{"id": "3"}]

    def get_following(self, *args, **kwargs):
        self.following_calls.append((args, kwargs))
        return [{"id": "4"}]

    def get_user_info(self, *args, **kwargs):
        self.user_info_calls.append((args, kwargs))
        return [{"screen_name": "elonmusk"}]


# ── Parser: global auth/config args ───────────────────────────────────────

def test_parser_auth_token():
    args = parse("--auth-token", "tok123", "search", "python")
    assert args.auth_token == "tok123"


def test_parser_cookies_file():
    args = parse("--cookies-file", "/tmp/c.json", "user-info", "elonmusk")
    assert args.cookies_file == "/tmp/c.json"


def test_parser_env_file():
    args = parse("--env-file", ".env", "user-info", "elonmusk")
    assert args.env_file == ".env"


def test_parser_db_path_default():
    args = parse("user-info", "elonmusk")
    assert args.db_path == "scweet_state.db"


def test_parser_db_path_custom():
    args = parse("--db-path", "/data/state.db", "user-info", "elonmusk")
    assert args.db_path == "/data/state.db"


def test_parser_proxy():
    args = parse("--proxy", "http://proxy:8080", "user-info", "elonmusk")
    assert args.proxy == "http://proxy:8080"


def test_parser_verbose_default_false():
    args = parse("user-info", "elonmusk")
    assert args.verbose is False


def test_parser_verbose_flag():
    args = parse("--verbose", "user-info", "elonmusk")
    assert args.verbose is True


def test_parser_verbose_short_flag():
    args = parse("-v", "user-info", "elonmusk")
    assert args.verbose is True


def test_parser_strict_not_a_flag():
    """strict is not user-facing; --strict should be unrecognised."""
    with pytest.raises(SystemExit):
        parse("--strict", "user-info", "elonmusk")


def test_parser_concurrency_default():
    args = parse("user-info", "elonmusk")
    assert args.concurrency == 5


def test_parser_concurrency_custom():
    args = parse("--concurrency", "10", "user-info", "elonmusk")
    assert args.concurrency == 10


# ── Parser: search subcommand ─────────────────────────────────────────────

def test_parser_search_positional_query():
    args = parse("search", "bitcoin")
    assert args.query == "bitcoin"


def test_parser_search_query_optional():
    args = parse("search", "--from", "elonmusk")
    assert args.query is None
    assert args.from_users == ["elonmusk"]


def test_parser_search_since_until():
    args = parse("search", "q", "--since", "2025-01-01", "--until", "2025-06-01")
    assert args.since == "2025-01-01"
    assert args.until == "2025-06-01"


def test_parser_search_lang():
    args = parse("search", "q", "--lang", "en")
    assert args.lang == "en"


def test_parser_search_display_type_default():
    args = parse("search", "q")
    assert args.display_type == "Top"


def test_parser_search_display_type_latest():
    args = parse("search", "q", "--display-type", "Latest")
    assert args.display_type == "Latest"


def test_parser_search_from_single():
    args = parse("search", "--from", "elonmusk")
    assert args.from_users == ["elonmusk"]


def test_parser_search_from_multiple():
    args = parse("search", "--from", "elonmusk", "naval")
    assert args.from_users == ["elonmusk", "naval"]


def test_parser_search_to():
    args = parse("search", "--to", "user1", "user2")
    assert args.to == ["user1", "user2"]


def test_parser_search_mention():
    args = parse("search", "--mention", "jack")
    assert args.mention == ["jack"]


def test_parser_search_all_words():
    args = parse("search", "--all-words", "python", "data")
    assert args.all_words == ["python", "data"]


def test_parser_search_any_words():
    args = parse("search", "--any-words", "ml", "ai")
    assert args.any_words == ["ml", "ai"]


def test_parser_search_exact_phrases():
    args = parse("search", "--exact-phrases", "machine learning", "deep learning")
    assert args.exact_phrases == ["machine learning", "deep learning"]


def test_parser_search_hashtags_any():
    args = parse("search", "--hashtags-any", "AI", "ML")
    assert args.hashtags_any == ["AI", "ML"]


def test_parser_search_hashtags_exclude():
    args = parse("search", "--hashtags-exclude", "ad", "sponsored")
    assert args.hashtags_exclude == ["ad", "sponsored"]


def test_parser_search_exclude_words():
    args = parse("search", "--exclude-words", "spam", "ads")
    assert args.exclude_words == ["spam", "ads"]


def test_parser_search_tweet_type():
    args = parse("search", "--tweet-type", "replies-only")
    assert args.tweet_type == "replies-only"


def test_parser_search_tweet_type_invalid():
    with pytest.raises(SystemExit):
        parse("search", "--tweet-type", "invalid")


def test_parser_search_min_likes():
    args = parse("search", "--min-likes", "100")
    assert args.min_likes == 100


def test_parser_search_min_replies():
    args = parse("search", "--min-replies", "5")
    assert args.min_replies == 5


def test_parser_search_min_retweets():
    args = parse("search", "--min-retweets", "10")
    assert args.min_retweets == 10


def test_parser_search_boolean_flags_default_false():
    args = parse("search", "q")
    assert args.has_images is False
    assert args.has_videos is False
    assert args.has_links is False
    assert args.verified_only is False
    assert args.blue_verified_only is False


def test_parser_search_has_images():
    args = parse("search", "--has-images")
    assert args.has_images is True


def test_parser_search_has_videos():
    args = parse("search", "--has-videos")
    assert args.has_videos is True


def test_parser_search_has_links():
    args = parse("search", "--has-links")
    assert args.has_links is True


def test_parser_search_has_mentions():
    args = parse("search", "--has-mentions")
    assert args.has_mentions is True


def test_parser_search_has_hashtags():
    args = parse("search", "--has-hashtags")
    assert args.has_hashtags is True


def test_parser_search_near():
    args = parse("search", "--near", "San Francisco")
    assert args.near == "San Francisco"


def test_parser_search_within():
    args = parse("search", "--within", "15km")
    assert args.within == "15km"


def test_parser_search_verified_only():
    args = parse("search", "--verified-only")
    assert args.verified_only is True


def test_parser_search_blue_verified_only():
    args = parse("search", "--blue-verified-only")
    assert args.blue_verified_only is True


def test_parser_search_place():
    args = parse("search", "--place", "New York")
    assert args.place == "New York"


def test_parser_search_geocode():
    args = parse("search", "--geocode", "40.7,-74.0,10km")
    assert args.geocode == "40.7,-74.0,10km"


def test_parser_search_limit():
    args = parse("search", "--limit", "50")
    assert args.limit == 50


def test_parser_search_max_empty_pages():
    args = parse("search", "--max-empty-pages", "3")
    assert args.max_empty_pages == 3


def test_parser_search_resume():
    args = parse("search", "--resume")
    assert args.resume is True


# ── Parser: output args ────────────────────────────────────────────────────

def test_parser_save_default_false():
    args = parse("search", "q")
    assert args.save is False


def test_parser_save_flag():
    args = parse("search", "--save", "q")
    assert args.save is True


def test_parser_save_format():
    args = parse("search", "--save-format", "json", "q")
    assert args.save_format == "json"


def test_parser_save_format_invalid():
    with pytest.raises(SystemExit):
        parse("search", "--save-format", "xml", "q")


def test_parser_save_dir():
    args = parse("search", "--save-dir", "/tmp/out", "q")
    assert args.save_dir == "/tmp/out"


def test_parser_save_name():
    args = parse("search", "--save-name", "my_results", "q")
    assert args.save_name == "my_results"


def test_parser_pretty_default_false():
    args = parse("search", "q")
    assert args.pretty is False


def test_parser_pretty_flag():
    args = parse("search", "--pretty", "q")
    assert args.pretty is True


# ── Parser: profile-tweets ────────────────────────────────────────────────

def test_parser_profile_tweets_single_user():
    args = parse("profile-tweets", "elonmusk")
    assert args.users == ["elonmusk"]


def test_parser_profile_tweets_multiple_users():
    args = parse("profile-tweets", "elonmusk", "naval")
    assert args.users == ["elonmusk", "naval"]


def test_parser_profile_tweets_limit():
    args = parse("profile-tweets", "elonmusk", "--limit", "20")
    assert args.limit == 20


def test_parser_profile_tweets_resume():
    args = parse("profile-tweets", "elonmusk", "--resume")
    assert args.resume is True


def test_parser_profile_tweets_requires_users():
    with pytest.raises(SystemExit):
        parse("profile-tweets")


# ── Parser: followers ─────────────────────────────────────────────────────

def test_parser_followers_users():
    args = parse("followers", "elonmusk", "naval")
    assert args.users == ["elonmusk", "naval"]


def test_parser_followers_raw_json():
    args = parse("followers", "elonmusk", "--raw-json")
    assert args.raw_json is True


def test_parser_followers_raw_json_default():
    args = parse("followers", "elonmusk")
    assert args.raw_json is False


# ── Parser: following ─────────────────────────────────────────────────────

def test_parser_following_users():
    args = parse("following", "elonmusk")
    assert args.users == ["elonmusk"]


def test_parser_following_raw_json():
    args = parse("following", "elonmusk", "--raw-json")
    assert args.raw_json is True


# ── Parser: user-info ─────────────────────────────────────────────────────

def test_parser_user_info_single():
    args = parse("user-info", "elonmusk")
    assert args.users == ["elonmusk"]


def test_parser_user_info_multiple():
    args = parse("user-info", "elonmusk", "naval", "sama")
    assert args.users == ["elonmusk", "naval", "sama"]


def test_parser_user_info_requires_users():
    with pytest.raises(SystemExit):
        parse("user-info")


# ── Parser: subcommand required ───────────────────────────────────────────

def test_parser_no_subcommand_exits():
    with pytest.raises(SystemExit):
        parse()


# ── _print_results ────────────────────────────────────────────────────────

def test_print_results_always_pretty(capsys):
    _print_results([{"a": 1}])
    out = capsys.readouterr().out
    assert "  " in out  # always indented
    assert json.loads(out) == [{"a": 1}]


def test_print_results_empty(capsys):
    _print_results([])
    out = capsys.readouterr().out.strip()
    assert json.loads(out) == []


def test_print_results_non_serializable(capsys):
    from datetime import date
    _print_results([{"d": date(2025, 1, 1)}])
    out = capsys.readouterr().out.strip()
    parsed = json.loads(out)
    assert parsed[0]["d"] == "2025-01-01"


# ── Command handlers (mocked client) ──────────────────────────────────────

def test_cmd_search_calls_client(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("search", "python", "--since", "2025-01-01", "--limit", "10")
    args.func(args)

    assert len(fake.search_calls) == 1
    _, kwargs = fake.search_calls[0]
    assert kwargs["since"] == "2025-01-01"
    assert kwargs["limit"] == 10
    assert capsys.readouterr().out == ""  # no stdout without --pretty


def test_cmd_search_pretty_prints_stdout(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("search", "--pretty", "python")
    args.func(args)

    out = json.loads(capsys.readouterr().out)
    assert out == [{"id": "1"}]


def test_cmd_search_filters_passed(monkeypatch):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse(
        "search",
        "--from", "elonmusk", "naval",
        "--hashtags-any", "AI",
        "--min-likes", "50",
        "--has-images",
        "--verified-only",
    )
    args.func(args)

    _, kwargs = fake.search_calls[0]
    assert kwargs["from_users"] == ["elonmusk", "naval"]
    assert kwargs["hashtags_any"] == ["AI"]
    assert kwargs["min_likes"] == 50
    assert kwargs["has_images"] is True
    assert kwargs["verified_only"] is True


def test_cmd_search_boolean_flags_false_become_none(monkeypatch):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("search", "q")
    args.func(args)

    _, kwargs = fake.search_calls[0]
    assert kwargs["has_images"] is None
    assert kwargs["has_videos"] is None
    assert kwargs["verified_only"] is None


def test_cmd_search_all_missing_filters_forwarded(monkeypatch):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse(
        "search",
        "--all-words", "python", "data",
        "--any-words", "ml", "ai",
        "--exact-phrases", "machine learning",
        "--hashtags-exclude", "ad",
        "--has-mentions",
        "--has-hashtags",
        "--near", "NYC",
        "--within", "10km",
    )
    args.func(args)

    _, kwargs = fake.search_calls[0]
    assert kwargs["all_words"] == ["python", "data"]
    assert kwargs["any_words"] == ["ml", "ai"]
    assert kwargs["exact_phrases"] == ["machine learning"]
    assert kwargs["hashtags_exclude"] == ["ad"]
    assert kwargs["has_mentions"] is True
    assert kwargs["has_hashtags"] is True
    assert kwargs["near"] == "NYC"
    assert kwargs["within"] == "10km"


def test_cmd_search_no_filter_lists_become_none(monkeypatch):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("search", "q")
    args.func(args)

    _, kwargs = fake.search_calls[0]
    assert kwargs["all_words"] is None
    assert kwargs["any_words"] is None
    assert kwargs["exact_phrases"] is None
    assert kwargs["from_users"] is None
    assert kwargs["to_users"] is None
    assert kwargs["mentioning_users"] is None
    assert kwargs["hashtags_any"] is None
    assert kwargs["hashtags_exclude"] is None
    assert kwargs["exclude_words"] is None
    assert kwargs["near"] is None
    assert kwargs["within"] is None


def test_cmd_profile_tweets_calls_client(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("profile-tweets", "elonmusk", "naval", "--limit", "30")
    args.func(args)

    assert len(fake.profile_tweets_calls) == 1
    positional, kwargs = fake.profile_tweets_calls[0]
    assert positional[0] == ["elonmusk", "naval"]
    assert kwargs["limit"] == 30
    assert capsys.readouterr().out == ""


def test_cmd_followers_calls_client(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("followers", "elonmusk", "--limit", "100", "--raw-json")
    args.func(args)

    assert len(fake.followers_calls) == 1
    positional, kwargs = fake.followers_calls[0]
    assert positional[0] == ["elonmusk"]
    assert kwargs["limit"] == 100
    assert kwargs["raw_json"] is True
    assert capsys.readouterr().out == ""


def test_cmd_following_calls_client(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("following", "elonmusk", "--resume")
    args.func(args)

    assert len(fake.following_calls) == 1
    _, kwargs = fake.following_calls[0]
    assert kwargs["resume"] is True


def test_cmd_user_info_calls_client(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("user-info", "elonmusk", "naval")
    args.func(args)

    assert len(fake.user_info_calls) == 1
    positional, _ = fake.user_info_calls[0]
    assert positional[0] == ["elonmusk", "naval"]
    assert capsys.readouterr().out == ""


def test_cmd_user_info_pretty_prints(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("user-info", "elonmusk", "--pretty")
    args.func(args)

    out = json.loads(capsys.readouterr().out)
    assert out == [{"screen_name": "elonmusk"}]


def test_cmd_save_args_forwarded(monkeypatch):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("user-info", "elonmusk", "--save", "--save-format", "json", "--save-name", "test_out")
    args.func(args)

    _, kwargs = fake.user_info_calls[0]
    assert kwargs["save"] is True
    assert kwargs["save_format"] == "json"
    assert kwargs["save_name"] == "test_out"


def test_cmd_pretty_output(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)

    args = parse("user-info", "elonmusk", "--pretty")
    args.func(args)

    out = capsys.readouterr().out
    assert "  " in out  # indented


# ── _sanitize_query ───────────────────────────────────────────────────────

def test_sanitize_query_passthrough():
    assert _sanitize_query("python") == "python"


def test_sanitize_query_strips_whitespace():
    assert _sanitize_query("  python  ") == "python"


def test_sanitize_query_none_returns_empty():
    assert _sanitize_query(None) == ""


def test_sanitize_query_empty_returns_empty():
    assert _sanitize_query("") == ""


def test_sanitize_query_balanced_quotes_no_warning(capsys):
    result = _sanitize_query('"machine learning"')
    assert result == '"machine learning"'
    assert capsys.readouterr().err == ""


def test_sanitize_query_unbalanced_quotes_warns(capsys):
    result = _sanitize_query('"machine learning')
    assert result == '"machine learning'  # string unchanged, warning only
    assert "odd number of quote" in capsys.readouterr().err


def test_sanitize_query_two_phrases_balanced_no_warning(capsys):
    _sanitize_query('"hello" "world"')
    assert capsys.readouterr().err == ""


# ── --quiet in command handlers ───────────────────────────────────────────

# ── main() integration ────────────────────────────────────────────────────

def test_main_success_no_stdout_without_pretty(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)
    monkeypatch.setattr(sys, "argv", ["scweet", "user-info", "elonmusk"])

    main()

    assert capsys.readouterr().out == ""


def test_main_success_pretty_prints(monkeypatch, capsys):
    import Scweet.cli as cli_mod
    fake = _FakeClient()
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: fake)
    monkeypatch.setattr(sys, "argv", ["scweet", "user-info", "elonmusk", "--pretty"])

    main()

    out = json.loads(capsys.readouterr().out)
    assert isinstance(out, list)


def test_main_exception_exits_1(monkeypatch, capsys):
    import Scweet.cli as cli_mod

    def _boom(args):
        raise RuntimeError("something broke")

    monkeypatch.setattr(cli_mod, "_make_client", lambda args: _FakeClient())
    monkeypatch.setattr(sys, "argv", ["scweet", "user-info", "elonmusk"])

    # patch the func on the parsed namespace
    original_parse = cli_mod.build_parser

    def patched_parser():
        p = original_parse()
        return p

    monkeypatch.setattr(cli_mod, "build_parser", patched_parser)

    def failing_client(args):
        raise RuntimeError("something broke")

    monkeypatch.setattr(cli_mod, "_make_client", failing_client)

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert "something broke" in capsys.readouterr().err


def test_main_keyboard_interrupt_exits_130(monkeypatch):
    import Scweet.cli as cli_mod

    monkeypatch.setattr(sys, "argv", ["scweet", "user-info", "elonmusk"])
    monkeypatch.setattr(cli_mod, "_make_client", lambda args: (_ for _ in ()).throw(KeyboardInterrupt()))

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 130


def test_main_no_subcommand_exits(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["scweet"])
    with pytest.raises(SystemExit):
        main()
