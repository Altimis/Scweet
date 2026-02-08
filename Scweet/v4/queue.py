from __future__ import annotations

import asyncio
from typing import Any, Optional
import uuid


class InMemoryTaskQueue:
    """Actor-style in-memory queue with delayed retry support."""

    def __init__(self, *, stop_event: Optional[asyncio.Event] = None):
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._pending_delays = 0
        self._pending_tasks: set[asyncio.Task] = set()
        self._stop_event = stop_event

    async def enqueue(self, tasks: list[dict]) -> None:
        for task in tasks:
            task.setdefault("fallback_attempts", 0)
            task.setdefault("account_switches", 0)
            task.setdefault("attempt", 0)
            await self._queue.put(task)

    async def lease(self, worker_id: str) -> Optional[dict]:
        while True:
            if self._stop_event and self._stop_event.is_set():
                return None
            try:
                task = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                if self._queue.empty() and self._pending_delays == 0:
                    return None
                await asyncio.sleep(0.05)
                continue
            task["lease_id"] = task.get("lease_id") or str(uuid.uuid4())
            task["lease_worker_id"] = worker_id
            return task

    async def ack(self, task: dict, stats: Optional[dict] = None) -> bool:
        if stats:
            current = task.get("stats") or {}
            current["pages"] = current.get("pages", 0) + stats.get("pages", 0)
            current["tweets"] = current.get("tweets", 0) + stats.get("tweets", 0)
            task["stats"] = current
        return True

    async def retry(
        self,
        task: dict,
        delay_s: int,
        reason: str,
        cursor: Optional[str] = None,
        last_error_code: Optional[int] = None,
        fallback_inc: int = 0,
        account_switch_inc: int = 0,
    ) -> bool:
        task["attempt"] = task.get("attempt", 0) + 1
        task["fallback_attempts"] = task.get("fallback_attempts", 0) + fallback_inc
        task["account_switches"] = task.get("account_switches", 0) + account_switch_inc
        task["last_error_code"] = last_error_code
        task["last_error_reason"] = reason
        query = task.get("query") or {}
        if cursor is not None:
            query["cursor"] = cursor
        task["query"] = query
        self._schedule_delayed_put(task, max(0, int(delay_s)))
        return True

    async def fail(self, task: dict, reason: str, last_error_code: Optional[int] = None) -> bool:
        task["last_error_code"] = last_error_code
        task["last_error_reason"] = reason
        return True

    def cancel_pending(self) -> None:
        for pending_task in list(self._pending_tasks):
            pending_task.cancel()
        self._pending_tasks.clear()
        self._pending_delays = 0

    def _schedule_delayed_put(self, task: dict[str, Any], delay_s: int) -> None:
        self._pending_delays += 1
        pending = asyncio.create_task(self._delayed_put(task, delay_s))
        self._pending_tasks.add(pending)
        pending.add_done_callback(self._pending_tasks.discard)

    async def _delayed_put(self, task: dict[str, Any], delay_s: int) -> None:
        try:
            await asyncio.sleep(delay_s)
            if self._stop_event and self._stop_event.is_set():
                return
            await self._queue.put(task)
        finally:
            self._pending_delays = max(0, self._pending_delays - 1)
