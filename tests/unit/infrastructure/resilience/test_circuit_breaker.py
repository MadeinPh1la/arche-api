from __future__ import annotations

import asyncio

import pytest

from arche_api.infrastructure.resilience.circuit_breaker import CircuitBreaker


@pytest.mark.anyio
async def test_circuit_breaker_allows_success_in_closed_state() -> None:
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_s=1.0,
        half_open_max_calls=1,
    )

    async def ok() -> str:
        return "ok"

    async with breaker.guard("test-key"):
        result = await ok()

    assert result == "ok"
    assert breaker._state == "CLOSED"
    assert breaker._failures == 0


@pytest.mark.anyio
async def test_circuit_breaker_trips_open_after_failures() -> None:
    breaker = CircuitBreaker(
        failure_threshold=2,
        recovery_timeout_s=60.0,
        half_open_max_calls=1,
    )

    async def boom() -> None:
        raise RuntimeError("boom")

    # First failure: still CLOSED
    with pytest.raises(RuntimeError, match="boom"):
        async with breaker.guard("test-key"):
            await boom()
    assert breaker._state == "CLOSED"
    assert breaker._failures == 1

    # Second failure: threshold hit → OPEN
    with pytest.raises(RuntimeError, match="boom"):
        async with breaker.guard("test-key"):
            await boom()
    assert breaker._state == "OPEN"
    assert breaker._failures == 2

    # While OPEN and before recovery timeout, we should short-circuit
    called = False

    async def should_not_run() -> None:
        nonlocal called
        called = True

    with pytest.raises(RuntimeError, match="circuit_open"):
        async with breaker.guard("test-key"):
            await should_not_run()

    assert not called
    assert breaker._state == "OPEN"


@pytest.mark.anyio
async def test_circuit_breaker_recovers_via_half_open_and_closes_on_success() -> None:
    breaker = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout_s=0.05,
        half_open_max_calls=1,
    )

    async def boom() -> None:
        raise RuntimeError("boom")

    # Trip to OPEN with one failure
    with pytest.raises(RuntimeError, match="boom"):
        async with breaker.guard("svc"):
            await boom()
    assert breaker._state == "OPEN"

    # Wait for recovery timeout to elapse
    await asyncio.sleep(0.06)

    async def ok() -> str:
        return "ok"

    # First call after timeout: HALF_OPEN → success → CLOSED
    async with breaker.guard("svc"):
        result = await ok()

    assert result == "ok"
    assert breaker._state == "CLOSED"
    assert breaker._failures == 0


@pytest.mark.anyio
async def test_circuit_breaker_half_open_call_limit() -> None:
    """When HALF_OPEN, exceeding half_open_max_calls fails fast."""
    breaker = CircuitBreaker(
        failure_threshold=1,
        recovery_timeout_s=0.05,
        half_open_max_calls=1,
    )

    async def boom() -> None:
        raise RuntimeError("boom")

    # Trip to OPEN
    with pytest.raises(RuntimeError, match="boom"):
        async with breaker.guard("svc"):
            await boom()
    assert breaker._state == "OPEN"

    # Wait until HALF_OPEN allowed
    await asyncio.sleep(0.06)

    # First HALF_OPEN call runs; second should hit limit.
    async def slow_ok() -> None:
        await asyncio.sleep(0.05)

    async def guarded_call() -> None:
        async with breaker.guard("svc"):
            await slow_ok()

    async def guarded_call_second() -> None:
        async with breaker.guard("svc"):
            await slow_ok()

    # Run two calls concurrently; one should hit "circuit_half_open_limit".
    tasks = [guarded_call(), guarded_call_second()]
    results: list[BaseException | None] = []

    async def capture(coro):
        try:
            await coro
            results.append(None)
        except Exception as exc:  # noqa: BLE001
            results.append(exc)

    await asyncio.gather(*(capture(t) for t in tasks))

    # Exactly one should be RuntimeError("circuit_half_open_limit").
    assert any(isinstance(r, RuntimeError) and "circuit_half_open_limit" in str(r) for r in results)
