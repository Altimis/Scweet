"""
Scweet v4 (sync) example.

What it demonstrates:
- Build a ScweetConfig (recommended) and initialize Scweet
- Provision accounts into the local SQLite DB
- Scrape tweets and write outputs (CSV/JSON) with resume
- Inspect DB state via ScweetDB

Notes:
- Replace placeholders (cookies/auth) with your real values.
- v4 tweet search scraping is API-only; no browser scraping engine.
"""

from __future__ import annotations

from pathlib import Path

from Scweet import Scweet, ScweetConfig, ScweetDB


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    examples_dir = root / "examples"
    db_path = root / "scweet_state.db"
    outputs_dir = root / "outputs"

    # 1- Configure Scweet
    #
    # Pick one (or combine sources):
    # - accounts_file="accounts.txt" ex: username:password:email:email_password:2fa:auth_token
    # - cookies_file="cookies.json" (or "cookies.txt" Netscape export)
    # - cookies={"auth_token": "...", "ct0": "..."}  (direct cookie dict)
    # - currently the most reliable way of provisioning is providing the auth_token directly in the config, or in accounts.txt or in cookies.json
    # - login in with username/password is still not reliable. Login using API is coming soon in future release
    cfg = ScweetConfig.from_sources(
        db_path=str(db_path),
        accounts_file=str(examples_dir / "accounts.txt"),
        cookies_file=str(examples_dir / "cookies.json"),
        # cookies={"auth_token": "...", "ct0": "..."},
        # cookies="YOUR_AUTH_TOKEN",  # convenience (Scweet will bootstrap ct0 if allowed)
        bootstrap_strategy="auto",  # auto|token_only|nodriver_only|none
        provision_on_init=False,  # show explicit provisioning step below
        output_format="both",  # csv|json|both|none
        resume_mode="hybrid_safe",  # legacy_csv|db_cursor|hybrid_safe
        strict=False,
        proxy=None,  # "http://user:pass@host:port" or {"host": "...", "port": 8080, "username": "...", "password": "..."}
        overrides={
            # If you have fewer eligible accounts than concurrency, Scweet will effectively be limited by accounts.
            "pool": {"concurrency": 4},
            "operations": {
                "account_lease_ttl_s": 300,  # max seconds an account stays leased
                "account_requests_per_min": 30,
            },
            "output": {"dedupe_on_resume_by_tweet_id": True},
        },
    )

    scweet = Scweet(config=cfg)

    # 2) Provision accounts into the DB (optional if provision_on_init=True).
    provision_result = scweet.provision_accounts(
        accounts_file=str(examples_dir / "accounts.txt"),
        cookies_file=str(examples_dir / "cookies.json"),
        # env_path=str(examples_dir / ".env"),
        # cookies={"auth_token": "...", "ct0": "..."},
    )
    print("provision:", provision_result)

    # 3) Scrape tweets (sync)
    tweets = scweet.scrape(
        since="2026-02-01",
        until="2026-02-07",
        words=["bitcoin"],
        limit=200,  # per-run target
        resume=True,  # appends to existing outputs and continues based on resume mode
        save_dir=str(outputs_dir),
        custom_csv_name="sync_bitcoin.csv",
        display_type="Latest",
        # Optional search args:
        # from_account="elonmusk",
        # mention_account="elonmusk",
        # hashtag="btc",
        # lang="en",
    )
    print("tweets:", len(tweets))
    if tweets and isinstance(tweets[0], dict):
        print("first_tweet_id:", tweets[0].get("rest_id") or (tweets[0].get("tweet") or {}).get("rest_id"))

    # 4) Inspect DB state / maintenance helpers
    db = ScweetDB(str(db_path))
    print("db.accounts_summary:", db.accounts_summary())
    print("db.list_accounts:", db.list_accounts(limit=5, eligible_only=True))
    # Optional: set/override a per-account proxy in the DB (applies to API calls for that account).
    # db.set_account_proxy("acct-a", {"host": "127.0.0.1", "port": 8080})


if __name__ == "__main__":
    main()
