from __future__ import annotations

"""
Import shim for source checkouts.

This repository vendors the installable Python package under `Scweet/Scweet/`.
When running from the repo root (so that the outer `Scweet/` directory is on
`sys.path`), Python would otherwise treat `Scweet` as a namespace package and
`from Scweet import Scweet` would resolve to the nested module `Scweet.Scweet`.

By making the outer directory a package and extending `__path__` to include the
inner package directory, we preserve the expected public import surface:

  from Scweet import Scweet, ScweetConfig
  from Scweet.client import Scweet
  from Scweet.config import ScweetConfig
"""

from pathlib import Path

# Make inner package modules importable as submodules of this outer package
# when running from a source checkout.
_INNER_PACKAGE_DIR = Path(__file__).resolve().parent / "Scweet"
if _INNER_PACKAGE_DIR.is_dir():
    __path__.append(str(_INNER_PACKAGE_DIR))  # type: ignore[name-defined]

from .client import Scweet  # noqa: E402
from .__version__ import __version__  # noqa: E402
from .config import ScweetConfig  # noqa: E402
from .db import ScweetDB  # noqa: E402
from .exceptions import (  # noqa: E402
    AccountPoolExhausted,
    EngineError,
    NetworkError,
    ProxyError,
    RunFailed,
    ScweetError,
)
from .logging_config import configure_logging  # noqa: E402

__all__ = [
    "Scweet",
    "ScweetConfig",
    "ScweetDB",
    "configure_logging",
    "ScweetError",
    "AccountPoolExhausted",
    "EngineError",
    "RunFailed",
    "NetworkError",
    "ProxyError",
    "__version__",
]
