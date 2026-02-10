from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, TypeVar


T = TypeVar("T")


async def call_in_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a sync callable in a dedicated daemon thread and await its result.

    Avoids relying on asyncio's default executor, which can be constrained in some
    environments (notebooks/sandboxes).
    """

    loop = asyncio.get_running_loop()
    done: asyncio.Future[T] = loop.create_future()

    def _resolve_result(value: T) -> None:
        if not done.done():
            done.set_result(value)

    def _resolve_error(exc: BaseException) -> None:
        if not done.done():
            done.set_exception(exc)

    def _runner() -> None:
        try:
            value = func(*args, **kwargs)
        except BaseException as exc:
            loop.call_soon_threadsafe(_resolve_error, exc)
            return
        loop.call_soon_threadsafe(_resolve_result, value)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return await done

