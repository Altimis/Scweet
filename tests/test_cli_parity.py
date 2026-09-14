"""The CLI reaches every public method of the client.

The failure mode: a release adds a method to the client and forgets the
subcommand. Each existing test covers one command, so no test fails, and a
user of the CLI never learns that the feature exists. This file fails instead.

A method that belongs to the library only goes in LIBRARY_ONLY with the reason.
"""

import inspect

from Scweet.cli import build_parser
from Scweet.client import Scweet

# A method here needs no subcommand. Give the reason for each entry.
LIBRARY_ONLY: dict[str, str] = {}

# The method of the client on the left, its subcommand on the right.
METHOD_TO_COMMAND = {
    "search": "search",
    "get_profile_tweets": "profile-tweets",
    "get_profile_media": "profile-media",
    "get_tweet_info": "tweet-info",
    "get_tweet_replies": "tweet-replies",
    "get_reposters": "reposters",
    "get_followers": "followers",
    "get_following": "following",
    "get_verified_followers": "verified-followers",
    "get_user_info": "user-info",
    "search_users": "search-users",
    "get_trending": "trending",
    "refresh_manifest": "refresh-manifest",
}

# A keyword that the CLI exposes under a shorter flag name.
FLAG_ALIASES = {
    "from_users": "from",
    "to_users": "to",
    "mentioning_users": "mention",
    "user_ids": "ids",
}

# A keyword of a method that the CLI leaves out on purpose.
CLI_OMITS = {
    # A shell cannot pass a Python object or a callback.
    "config",
    "on_tweets_batch",
    "on_tweets_page",
    "on_follows_page",
    "on_profiles_batch",
}


def _public_sync_methods() -> set:
    names = set()
    for name, member in inspect.getmembers(Scweet, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        # An async twin mirrors its sync method, so it needs no command.
        if name.startswith("a") and name[1:] in dict(
            inspect.getmembers(Scweet, predicate=inspect.isfunction)
        ):
            continue
        if isinstance(inspect.getattr_static(Scweet, name, None), property):
            continue
        names.add(name)
    return names


def _subcommands() -> dict:
    parser = build_parser()
    action = next(a for a in parser._actions if hasattr(a, "_name_parser_map"))
    return action.choices


def test_every_public_method_has_a_subcommand():
    methods = _public_sync_methods()
    mapped = set(METHOD_TO_COMMAND) | set(LIBRARY_ONLY)
    unmapped = sorted(methods - mapped)
    assert not unmapped, (
        f"these methods reach no CLI command: {unmapped}. Add the subcommand, "
        "or name the method in LIBRARY_ONLY with its reason."
    )


def test_every_mapped_command_exists_in_the_parser():
    commands = _subcommands()
    for method, command in METHOD_TO_COMMAND.items():
        assert command in commands, f"{method} maps to the missing command {command!r}"


def test_no_subcommand_exists_without_a_method():
    commands = set(_subcommands())
    extra = sorted(commands - set(METHOD_TO_COMMAND.values()))
    assert not extra, f"these commands reach no method of the client: {extra}"


def test_every_keyword_of_a_method_reaches_a_flag():
    commands = _subcommands()
    gaps: dict[str, list] = {}
    for method, command in METHOD_TO_COMMAND.items():
        signature = inspect.signature(getattr(Scweet, method))
        keywords = {
            name
            for name in signature.parameters
            if name not in ("self", "args", "kwargs") and name not in CLI_OMITS
        }
        flags = set()
        for action in commands[command]._actions:
            for option in action.option_strings:
                flags.add(option.lstrip("-").replace("-", "_"))
            if not action.option_strings and action.dest != "help":
                flags.add(action.dest)
        missing = sorted(
            name for name in keywords if name not in flags and FLAG_ALIASES.get(name) not in flags
        )
        if missing:
            gaps[f"{method} -> {command}"] = missing
    assert not gaps, (
        f"these keywords reach no CLI flag: {gaps}. Add the flag, or name the "
        "keyword in CLI_OMITS with its reason."
    )
