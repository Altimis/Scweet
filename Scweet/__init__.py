import logging

from .client import Scweet
from .__version__ import __version__
from .config import ScweetConfig
from .db import ScweetDB
from .exceptions import (
    AccountPoolExhausted,
    AuthError,
    EngineError,
    NetworkError,
    ProxyError,
    RateLimitError,
    RunFailed,
    ScweetError,
)

logging.getLogger("Scweet").addHandler(logging.NullHandler())

__all__ = [
    "Scweet",
    "ScweetConfig",
    "ScweetDB",
    "ScweetError",
    "AccountPoolExhausted",
    "EngineError",
    "RunFailed",
    "NetworkError",
    "ProxyError",
    "RateLimitError",
    "AuthError",
]
