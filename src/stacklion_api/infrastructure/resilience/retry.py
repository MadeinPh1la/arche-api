# Copyright (c)
# SPDX-License-Identifier: MIT
"""Retry utilities (async) with jittered exponential backoff."""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry attempts."""

    total: int  # number of retries (not counting the first attempt)
    base: float  # base backoff seconds
    cap: float  # max backoff seconds
    jitter: bool = True  # add full jitter if True


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    retry_on: Callable[[Exception | T], bool],
) -> T:
    """Retry an async function with backoff until success or budget exhausted.

    Args:
        fn: Zero-arg async function to execute.
        policy: RetryPolicy defining count/backoff.
        retry_on: Predicate that returns True when we should retry.

    Returns:
        The return value of ``fn`` if successful.

    Raises:
        The last exception if retries are exhausted.
    """
    attempt = 0
    while True:
        try:
            result = await fn()
            if attempt == 0 or not retry_on(result):
                return result
        except Exception as exc:  # noqa: BLE001
            if attempt >= policy.total or not retry_on(exc):
                raise
        # compute sleep
        backoff = min(policy.cap, policy.base * (2**attempt))
        if policy.jitter:
            backoff = random.uniform(0, backoff)  # noqa: S311
        await asyncio.sleep(backoff)
        attempt += 1
