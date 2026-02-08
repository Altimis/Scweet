from __future__ import annotations

from typing import Any, Protocol


class EngineProtocol(Protocol):
    async def search_tweets(self, request: Any): ...

    async def get_profiles(self, request: Any): ...

    async def get_follows(self, request: Any): ...


def select_engine(kind: str, api_engine, browser_engine):
    normalized = (kind or "auto").strip().lower()

    if normalized == "api":
        if api_engine is None:
            raise ValueError("API engine requested but not available")
        return api_engine

    if normalized == "browser":
        if browser_engine is None:
            raise ValueError("Browser engine requested but not available")
        return browser_engine

    if normalized == "auto":
        if api_engine is not None:
            return api_engine
        if browser_engine is not None:
            return browser_engine
        raise ValueError("No engine is available for auto selection")

    raise ValueError(f"Unknown engine kind: {kind}")
