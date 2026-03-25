from __future__ import annotations

import argparse
import json
import sys


def _add_auth_args(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("auth")
    g.add_argument("--auth-token", metavar="TOKEN", help="auth_token cookie value")
    g.add_argument("--cookies-file", metavar="FILE", help="path to cookies JSON file")
    g.add_argument("--env-file", metavar="FILE", help="path to .env file")
    g.add_argument("--db-path", metavar="PATH", default="scweet_state.db",
                   help="SQLite state file (default: scweet_state.db)")

    g2 = parser.add_argument_group("config")
    g2.add_argument("--proxy", metavar="PROXY", help="proxy URL or JSON string")
    g2.add_argument("--concurrency", metavar="N", type=int, default=5,
                    help="worker concurrency (default: 5)")
    g2.add_argument("-v", "--verbose", action="store_true",
                    help="enable debug-level logging (default: INFO)")


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    g = parser.add_argument_group("output")
    g.add_argument("--save", action="store_true", help="save results to file")
    g.add_argument("--save-format", choices=["csv", "json", "both"], default="csv",
                   metavar="{csv,json,both}", help="file format when --save is set (default: csv)")
    g.add_argument("--save-dir", metavar="DIR", default="outputs",
                   help="directory for saved files (default: outputs)")
    g.add_argument("--save-name", metavar="NAME", help="base filename for saved output")
    g.add_argument("--pretty", action="store_true", help="print results as indented JSON to stdout")


def _make_client(args: argparse.Namespace):
    from .client import Scweet
    from .config import ScweetConfig

    cfg = ScweetConfig(
        proxy=args.proxy or None,
        concurrency=args.concurrency,
        save_dir=getattr(args, "save_dir", "outputs"),
    )
    return Scweet(
        auth_token=args.auth_token or None,
        cookies_file=args.cookies_file or None,
        env_path=args.env_file or None,
        db_path=args.db_path,
        config=cfg,
    )


def _print_results(results: list) -> None:
    print(json.dumps(results, indent=2, default=str))


def _sanitize_query(query: str | None) -> str:
    """Strip whitespace and warn on unbalanced quotes."""
    if not query:
        return ""
    q = query.strip()
    if q.count('"') % 2 != 0:
        print(
            'warning: query has an odd number of quote characters (") '
            "— this may produce unexpected search results",
            file=sys.stderr,
        )
    return q


# ── Subcommand handlers ────────────────────────────────────────────────────

def cmd_search(args: argparse.Namespace) -> None:
    client = _make_client(args)
    results = client.search(
        _sanitize_query(args.query),
        since=args.since,
        until=args.until,
        lang=args.lang,
        display_type=args.display_type,
        limit=args.limit,
        max_empty_pages=args.max_empty_pages,
        resume=args.resume,
        all_words=args.all_words or None,
        any_words=args.any_words or None,
        exact_phrases=args.exact_phrases or None,
        from_users=args.from_users or None,
        to_users=args.to or None,
        mentioning_users=args.mention or None,
        hashtags_any=args.hashtag or None,
        hashtags_exclude=args.hashtags_exclude or None,
        exclude_words=args.exclude or None,
        tweet_type=args.tweet_type.replace("-", "_") if args.tweet_type else None,
        min_likes=args.min_likes,
        min_replies=args.min_replies,
        min_retweets=args.min_retweets,
        has_images=True if args.has_images else None,
        has_videos=True if args.has_videos else None,
        has_links=True if args.has_links else None,
        has_mentions=True if args.has_mentions else None,
        has_hashtags=True if args.has_hashtags else None,
        verified_only=True if args.verified_only else None,
        blue_verified_only=True if args.blue_verified_only else None,
        place=args.place,
        geocode=args.geocode,
        near=args.near,
        within=args.within,
        save=args.save,
        save_format=args.save_format,
        save_name=args.save_name,
    )
    if args.pretty:
        _print_results(results)


def cmd_profile_tweets(args: argparse.Namespace) -> None:
    client = _make_client(args)
    results = client.get_profile_tweets(
        args.users,
        limit=args.limit,
        max_empty_pages=args.max_empty_pages,
        resume=args.resume,
        save=args.save,
        save_format=args.save_format,
        save_name=args.save_name,
    )
    if args.pretty:
        _print_results(results)


def cmd_followers(args: argparse.Namespace) -> None:
    client = _make_client(args)
    results = client.get_followers(
        args.users,
        limit=args.limit,
        max_empty_pages=args.max_empty_pages,
        resume=args.resume,
        raw_json=args.raw_json,
        save=args.save,
        save_format=args.save_format,
        save_name=args.save_name,
    )
    if args.pretty:
        _print_results(results)


def cmd_following(args: argparse.Namespace) -> None:
    client = _make_client(args)
    results = client.get_following(
        args.users,
        limit=args.limit,
        max_empty_pages=args.max_empty_pages,
        resume=args.resume,
        raw_json=args.raw_json,
        save=args.save,
        save_format=args.save_format,
        save_name=args.save_name,
    )
    if args.pretty:
        _print_results(results)


def cmd_user_info(args: argparse.Namespace) -> None:
    client = _make_client(args)
    results = client.get_user_info(
        args.users,
        save=args.save,
        save_format=args.save_format,
        save_name=args.save_name,
    )
    if args.pretty:
        _print_results(results)


# ── Parser ─────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scweet",
        description="Scweet — Twitter/X scraper CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  scweet --auth-token TOKEN search \"python\" --since 2025-01-01 --limit 50 --pretty\n"
            "  scweet --auth-token TOKEN search --from elonmusk naval --hashtag AI --has-images\n"
            "  scweet --auth-token TOKEN followers elonmusk --limit 200 --save --save-format json\n"
            "  scweet --cookies-file cookies.json user-info elonmusk naval --pretty\n"
        ),
    )

    _add_auth_args(parser)

    sub = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")
    sub.required = True

    # ── search ──────────────────────────────────────────────────────────
    p_search = sub.add_parser("search", help="search tweets",
                              formatter_class=argparse.RawDescriptionHelpFormatter)
    p_search.add_argument("query", nargs="?", metavar="QUERY",
                          help="search query string (optional — use filters alone if omitted)")

    f = p_search.add_argument_group("filters")
    f.add_argument("--since", metavar="DATE", help="start date YYYY-MM-DD")
    f.add_argument("--until", metavar="DATE", help="end date YYYY-MM-DD")
    f.add_argument("--lang", metavar="CODE", help="language code, e.g. en")
    f.add_argument("--display-type", choices=["Top", "Latest"], default="Top",
                   metavar="{Top,Latest}", help="Top or Latest (default: Top)")
    f.add_argument("--from", dest="from_users", nargs="+", metavar="USER",
                   help="tweets from these users")
    f.add_argument("--to", nargs="+", metavar="USER",
                   help="tweets sent to these users")
    f.add_argument("--mention", nargs="+", metavar="USER",
                   help="tweets mentioning these users")
    f.add_argument("--all-words", nargs="+", metavar="WORD",
                   help="tweets containing ALL of these words (AND)")
    f.add_argument("--any-words", nargs="+", metavar="WORD",
                   help="tweets containing ANY of these words (OR)")
    f.add_argument("--exact-phrases", nargs="+", metavar="PHRASE",
                   help="tweets containing these exact phrases")
    f.add_argument("--hashtag", nargs="+", metavar="TAG",
                   help="tweets containing any of these hashtags")
    f.add_argument("--hashtags-exclude", nargs="+", metavar="TAG",
                   help="exclude tweets containing these hashtags")
    f.add_argument("--exclude", nargs="+", metavar="WORD",
                   help="exclude tweets containing these words")
    f.add_argument("--tweet-type",
                   choices=["originals-only", "replies-only", "retweets-only", "exclude-replies", "exclude-retweets"],
                   metavar="{originals-only,replies-only,retweets-only,exclude-replies,exclude-retweets}",
                   help="filter by tweet type")
    f.add_argument("--min-likes", type=int, metavar="N")
    f.add_argument("--min-replies", type=int, metavar="N")
    f.add_argument("--min-retweets", type=int, metavar="N")
    f.add_argument("--has-images", action="store_true")
    f.add_argument("--has-videos", action="store_true")
    f.add_argument("--has-links", action="store_true")
    f.add_argument("--has-mentions", action="store_true")
    f.add_argument("--has-hashtags", action="store_true")
    f.add_argument("--verified-only", action="store_true")
    f.add_argument("--blue-verified-only", action="store_true")
    f.add_argument("--place", metavar="PLACE")
    f.add_argument("--geocode", metavar="GEOCODE")
    f.add_argument("--near", metavar="PLACE")
    f.add_argument("--within", metavar="RADIUS", help="radius for --near, e.g. 15km or 10mi")

    p = p_search.add_argument_group("pagination")
    p.add_argument("--limit", type=int, metavar="N", help="max tweets to return")
    p.add_argument("--max-empty-pages", type=int, metavar="N")
    p.add_argument("--resume", action="store_true", help="resume from last checkpoint")

    _add_output_args(p_search)
    p_search.set_defaults(func=cmd_search)

    # ── profile-tweets ──────────────────────────────────────────────────
    p_pt = sub.add_parser("profile-tweets", help="get tweets from user timelines",
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    p_pt.add_argument("users", nargs="+", metavar="USER",
                      help="one or more @handles")
    p_pt.add_argument("--limit", type=int, metavar="N", help="max tweets to return")
    p_pt.add_argument("--max-empty-pages", type=int, metavar="N")
    p_pt.add_argument("--resume", action="store_true")
    _add_output_args(p_pt)
    p_pt.set_defaults(func=cmd_profile_tweets)

    # ── followers ───────────────────────────────────────────────────────
    p_fol = sub.add_parser("followers", help="get followers of users",
                           formatter_class=argparse.RawDescriptionHelpFormatter)
    p_fol.add_argument("users", nargs="+", metavar="USER",
                       help="one or more @handles")
    p_fol.add_argument("--limit", type=int, metavar="N")
    p_fol.add_argument("--max-empty-pages", type=int, metavar="N")
    p_fol.add_argument("--resume", action="store_true")
    p_fol.add_argument("--raw-json", action="store_true",
                       help="return raw API JSON instead of normalized dicts")
    _add_output_args(p_fol)
    p_fol.set_defaults(func=cmd_followers)

    # ── following ───────────────────────────────────────────────────────
    p_fng = sub.add_parser("following", help="get accounts a user follows",
                           formatter_class=argparse.RawDescriptionHelpFormatter)
    p_fng.add_argument("users", nargs="+", metavar="USER",
                       help="one or more @handles")
    p_fng.add_argument("--limit", type=int, metavar="N")
    p_fng.add_argument("--max-empty-pages", type=int, metavar="N")
    p_fng.add_argument("--resume", action="store_true")
    p_fng.add_argument("--raw-json", action="store_true",
                       help="return raw API JSON instead of normalized dicts")
    _add_output_args(p_fng)
    p_fng.set_defaults(func=cmd_following)

    # ── user-info ───────────────────────────────────────────────────────
    p_ui = sub.add_parser("user-info", help="get user profile info",
                          formatter_class=argparse.RawDescriptionHelpFormatter)
    p_ui.add_argument("users", nargs="+", metavar="USER",
                      help="one or more @handles")
    _add_output_args(p_ui)
    p_ui.set_defaults(func=cmd_user_info)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    from .logging_config import configure_logging
    configure_logging(
        profile="detailed" if args.verbose else "simple",
        level="DEBUG" if args.verbose else "INFO",
        stream=sys.stderr,
        force=True,
    )

    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
