"""Loss-tolerant wake-ups for one Gateway process. PostgreSQL arbitrates claims."""
import asyncio
from contextlib import asynccontextmanager, contextmanager, suppress
import math
import os

from redis.asyncio import Redis
from redis.exceptions import RedisError


class Wakeups:
    def __init__(self):
        url = os.environ.get("GATEWAY_REDIS_URL")
        self.channel = os.environ.get("GATEWAY_REDIS_CHANNEL")
        if url and not self.channel:
            raise ValueError("Set GATEWAY_REDIS_CHANNEL to an environment-specific service channel")
        self.redis = Redis.from_url(url, socket_connect_timeout=1) if url else None
        self.recheck = float(os.environ.get("GATEWAY_RECHECK_SECONDS", 5))
        if not math.isfinite(self.recheck) or not 0 < self.recheck <= 30:
            raise ValueError("GATEWAY_RECHECK_SECONDS must be positive and at most 30")
        self.waiters = set()

    @contextmanager
    def register(self):
        event = asyncio.Event()
        self.waiters.add(event)
        try:
            yield event
        finally:
            self.waiters.remove(event)

    def notify(self):
        for event in self.waiters:
            event.set()

    async def publish(self):
        # The caller has exited the write transaction. A failed notification has no effect on its outcome.
        self.notify()
        if self.redis:
            try:
                await asyncio.wait_for(self.redis.publish(self.channel, "ready"), timeout=1)
            except (RedisError, asyncio.TimeoutError, OSError):
                pass

    async def listen(self):
        while True:
            try:
                async with self.redis.pubsub() as subscription:
                    await subscription.subscribe(self.channel)
                    async for notice in subscription.listen():
                        if notice["type"] in ("subscribe", "message"):
                            self.notify()
            except (RedisError, OSError):
                await asyncio.sleep(1)

    @asynccontextmanager
    async def lifespan(self, app):
        listener = asyncio.create_task(self.listen()) if self.redis else None
        try:
            yield
        finally:
            if listener:
                listener.cancel()
                with suppress(asyncio.CancelledError):
                    await listener
                await self.redis.aclose()
