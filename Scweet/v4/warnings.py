from __future__ import annotations

import warnings
from typing import Optional


_emitted_messages: set[str] = set()


def warn_deprecated(message: str) -> None:
    if message in _emitted_messages:
        return
    _emitted_messages.add(message)
    warnings.warn(message, FutureWarning, stacklevel=2)


def warn_legacy_import_path() -> None:
    warn_deprecated(
        "Importing Scweet from `Scweet.scweet` is deprecated in v4.x; "
        "use `from Scweet import Scweet`. Planned removal in v5.0."
    )


def warn_legacy_arg(arg_name: str, replacement: Optional[str] = None) -> None:
    if replacement:
        message = (
            f"`{arg_name}` is deprecated in v4.x, planned removal in v5.0. "
            f"Use `{replacement}` instead."
        )
    else:
        message = f"`{arg_name}` is deprecated in v4.x, planned removal in v5.0."
    warn_deprecated(message)
