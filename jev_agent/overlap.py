from __future__ import annotations

"""Small async primitives for overlapping helper work with tool I/O.

The functions in this module intentionally do not own an event loop or a model
runtime.  A caller can start a helper prefetch while a Jev request or an
external tool is in flight, then discard stale work using a revision number.
"""

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Generic, TypeVar


T = TypeVar("T")
U = TypeVar("U")


@dataclass(frozen=True)
class OverlapResult(Generic[T, U]):
    """Results of two independent operations started at the same time."""

    prefetch: T
    tool: U
    revision: int


async def run_prefetch_and_tool(
    *,
    prefetch: Callable[[], Awaitable[T]],
    tool_call: Callable[[], Awaitable[U]],
    revision: int,
) -> OverlapResult[T, U]:
    """Run helper prefetch and tool I/O concurrently.

    The caller owns model/network cancellation policy.  If either operation
    raises, ``asyncio.gather`` propagates that exception and the other task is
    cancelled by the caller or enclosing task group.
    """

    prefetched, tool_result = await asyncio.gather(prefetch(), tool_call())
    return OverlapResult(prefetched, tool_result, revision)


class RevisionPrefetch(Generic[T]):
    """Keep one speculative result and reject it after state changes.

    This is deliberately a tiny cache rather than a general scheduler.  A
    result is usable only when its revision equals the current task revision;
    this prevents a slow tool response from being paired with a stale token
    proposal.
    """

    def __init__(self) -> None:
        self._task: asyncio.Task[T] | None = None
        self._revision: int | None = None

    def start(self, factory: Callable[[], Awaitable[T]], *, revision: int) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = asyncio.create_task(factory())
        self._revision = revision

    async def take(self, *, revision: int) -> T | None:
        task, task_revision = self._task, self._revision
        self._task = None
        self._revision = None
        if task is None or task_revision != revision:
            if task is not None and not task.done():
                task.cancel()
            return None
        return await task

    async def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._revision = None
