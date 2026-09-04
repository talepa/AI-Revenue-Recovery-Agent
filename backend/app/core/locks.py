"""Distributed locking / idempotency guard.

Prevents two concurrent triggers of the same operation — e.g. two
overlapping POST /recovery-cases/{id}/run calls for the same case, or two
overlapping detect-overdue sweeps — from racing and double-executing
actions. Falls back to an in-process lock when REDIS_URL isn't configured,
the same auto-fallback pattern as the LLM client and Kafka publisher. The
fallback only guards within this one process; it does not coordinate
across multiple app instances the way real Redis does.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from app.core.config import settings

_local_locks: dict[str, asyncio.Lock] = {}

DEFAULT_LOCK_TTL_SECONDS = 60


class LockAcquisitionError(Exception):
    """Raised when a lock is already held by another in-flight operation."""


@contextlib.asynccontextmanager
async def acquire_lock(key: str, ttl_seconds: int = DEFAULT_LOCK_TTL_SECONDS) -> AsyncIterator[None]:
    if settings.redis_url:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.redis_url)
        lock = client.lock(f"lock:{key}", timeout=ttl_seconds, blocking=False)
        try:
            if not await lock.acquire():
                raise LockAcquisitionError(f"Lock '{key}' is already held")
            try:
                yield
            finally:
                with contextlib.suppress(Exception):
                    await lock.release()
        finally:
            await client.aclose()
        return

    lock = _local_locks.setdefault(key, asyncio.Lock())
    if lock.locked():
        raise LockAcquisitionError(f"Lock '{key}' is already held")
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()
