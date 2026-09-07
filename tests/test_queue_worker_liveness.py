"""An idle worker waits while another worker still holds a task.

A worker that finds the queue empty must not exit while another worker processes a task, because that task can
enqueue a continuation or a split of an interval. If the idle worker exits too soon, the work of a truncated
interval falls to the few workers that survive, and each of those exhausts the request budget of its account.
The run ends only when the queue is empty, no delayed task waits, and no worker holds a task.
"""

import asyncio

from Scweet.queue import InMemoryTaskQueue


class TestAnIdleWorkerWaitsForWorkInFlight:
    def test_a_worker_does_not_exit_while_another_holds_a_task(self):
        async def _go():
            queue = InMemoryTaskQueue()
            await queue.enqueue([{"task_id": "1"}])

            first = await queue.lease("A")  # A now holds task 1
            assert first is not None

            # B asks for work. The queue is empty, but A still holds a task that may enqueue more, so B waits.
            b_lease = asyncio.ensure_future(queue.lease("B"))
            await asyncio.sleep(0.15)
            assert not b_lease.done(), "B exited while A still held a task"

            # A produces a continuation. B must pick it up, not exit.
            await queue.enqueue([{"task_id": "2"}])
            second = await asyncio.wait_for(b_lease, timeout=1.0)
            assert second["task_id"] == "2"

            return True

        assert asyncio.run(_go())

    def test_all_workers_exit_when_no_work_remains(self):
        async def _go():
            queue = InMemoryTaskQueue()
            await queue.enqueue([{"task_id": "1"}])

            a = await queue.lease("A")  # A holds the only task
            # B waits because A is active.
            b_lease = asyncio.ensure_future(queue.lease("B"))
            await asyncio.sleep(0.1)
            assert not b_lease.done()

            # A finishes and asks for more. The queue is empty and no other worker is active, so A exits.
            a_again = await queue.lease("A")
            assert a_again is None, "A must exit when the queue is empty and no worker holds a task"

            # With A gone, B must also exit instead of waiting for ever.
            b = await asyncio.wait_for(b_lease, timeout=1.0)
            assert b is None, "B must exit once no worker holds a task and the queue is empty"

            return True

        assert asyncio.run(_go())

    def test_release_worker_lets_the_others_exit(self):
        """A worker that leaves its loop on a break must release itself, or the others wait for ever."""

        async def _go():
            queue = InMemoryTaskQueue()
            await queue.enqueue([{"task_id": "1"}])
            await queue.lease("A")  # A holds a task and never calls lease again (it breaks its loop)

            b_lease = asyncio.ensure_future(queue.lease("B"))
            await asyncio.sleep(0.1)
            assert not b_lease.done(), "B waits while A is still counted as active"

            queue.release_worker("A")  # A leaves its loop
            b = await asyncio.wait_for(b_lease, timeout=1.0)
            assert b is None, "after A releases itself, B exits because no worker is active"

            return True

        assert asyncio.run(_go())
