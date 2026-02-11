from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    since: str
    until: Optional[str] = None
    # Legacy query surface kept for compatibility.
    words: Optional[list[str]] = None
    to_account: Optional[str] = None
    from_account: Optional[str] = None
    mention_account: Optional[str] = None
    hashtag: Optional[str] = None
    # Canonical v4 search surface.
    search_query: Optional[str] = None
    all_words: Optional[list[str]] = None
    any_words: Optional[list[str]] = None
    exact_phrases: Optional[list[str]] = None
    exclude_words: Optional[list[str]] = None
    hashtags_any: Optional[list[str]] = None
    hashtags_exclude: Optional[list[str]] = None
    from_users: Optional[list[str]] = None
    to_users: Optional[list[str]] = None
    mentioning_users: Optional[list[str]] = None
    tweet_type: Optional[str] = None
    verified_only: Optional[bool] = None
    blue_verified_only: Optional[bool] = None
    has_images: Optional[bool] = None
    has_videos: Optional[bool] = None
    has_links: Optional[bool] = None
    has_mentions: Optional[bool] = None
    has_hashtags: Optional[bool] = None
    min_likes: Optional[int] = None
    min_replies: Optional[int] = None
    min_retweets: Optional[int] = None
    place: Optional[str] = None
    geocode: Optional[str] = None
    near: Optional[str] = None
    within: Optional[str] = None
    lang: Optional[str] = None
    limit: Optional[int] = None
    display_type: str = "Top"
    resume: bool = False
    save_dir: str = "outputs"
    custom_csv_name: Optional[str] = None
    cursor: Optional[str] = None
    initial_cursor: Optional[str] = None
    query_hash: Optional[str] = None


class ProfileRequest(BaseModel):
    handles: list[str] = Field(default_factory=list)
    login: bool = False


class FollowsRequest(BaseModel):
    handle: str
    type: Literal["followers", "verified_followers", "following"] = "following"
    login: bool = True
    stay_logged_in: bool = True
    sleep: float = 2


class TweetUser(BaseModel):
    screen_name: Optional[str] = None
    name: Optional[str] = None


class TweetMedia(BaseModel):
    image_links: list[str] = Field(default_factory=list)


class TweetRecord(BaseModel):
    tweet_id: str
    user: TweetUser = Field(default_factory=TweetUser)
    timestamp: Optional[str] = None
    text: Optional[str] = None
    embedded_text: Optional[str] = None
    emojis: Optional[str] = None
    comments: int = 0
    likes: int = 0
    retweets: int = 0
    media: TweetMedia = Field(default_factory=TweetMedia)
    tweet_url: Optional[str] = None
    raw: Optional[dict[str, Any]] = None


class RunStats(BaseModel):
    tweets_count: int = 0
    tasks_total: int = 0
    tasks_done: int = 0
    tasks_failed: int = 0
    retries: int = 0


class SearchResult(BaseModel):
    tweets: list[TweetRecord] = Field(default_factory=list)
    stats: RunStats = Field(default_factory=RunStats)


class ProfileResult(BaseModel):
    profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)
