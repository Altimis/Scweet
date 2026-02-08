from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    since: str
    until: Optional[str] = None
    words: Optional[list[str]] = None
    to_account: Optional[str] = None
    from_account: Optional[str] = None
    mention_account: Optional[str] = None
    hashtag: Optional[str] = None
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
