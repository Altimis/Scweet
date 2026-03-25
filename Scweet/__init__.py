import logging

from .client import Scweet
from .__version__ import __version__
from .config import ScweetConfig
from .db import ScweetDB
from .exceptions import (
    AccountPoolExhausted,
    EngineError,
    NetworkError,
    ProxyError,
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
]
