# -*- coding: utf-8 -*-
"""Virtual clock for the XHS publish-chain tests (ticket 28).

Production code must not grow ``clock=`` / ``sleep=`` parameters just to be
testable, so this fixture patches the *module namespace* instead:

* the module's ``time`` binding is replaced with a proxy whose ``monotonic``
  returns :meth:`FakeClock.monotonic`;
* the module's ``asyncio`` binding is replaced with a proxy whose ``sleep``
  advances the same clock (everything else delegates to the real module).

Usage::

    clock = FakeClock(start=100.0)
    with clock.patch(uploader.xiaohongshu_uploader.main):
        await chain(...)
        clock.advance(15)

A module that does not import ``asyncio`` only gets the ``time`` patch; the
fixture records whether the ``asyncio`` patch was applied in
``patched_asyncio``.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack, contextmanager
from typing import Any, Iterator

from unittest.mock import patch


class _FakeTime:
    """``time`` proxy: only ``monotonic`` is virtual, everything else is real."""

    def __init__(self, clock: "FakeClock") -> None:
        self._clock = clock

    def monotonic(self) -> float:
        return self._clock.monotonic()

    def __getattr__(self, name: str) -> Any:
        return getattr(time, name)


class _FakeAsyncio:
    """``asyncio`` proxy: only ``sleep`` is virtual, everything else is real."""

    def __init__(self, clock: "FakeClock") -> None:
        self._clock = clock

    async def sleep(self, delay: float, result: Any = None) -> Any:
        await self._clock.sleep(delay)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)


class FakeClock:
    """Manually advanced monotonic clock plus an async ``sleep``.

    ``sleep`` records every requested duration and advances the clock by the
    same amount, so tests can assert the retry cadence (1s ARM polling, 500ms
    OBSERVE polling, ...) without spending wall-clock time.
    """

    def __init__(
        self,
        start: float = 0.0,
        *,
        module: Any | None = None,
    ) -> None:
        self._now = float(start)
        self._module = module
        self.sleep_calls: list[float] = []
        self.patched_asyncio = False
        self._active: contextmanager | None = None

    @property
    def now(self) -> float:
        return self._now

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        """Move the clock forward and return the new value."""
        self._now += float(seconds)
        return self._now

    async def sleep(self, seconds: float, result: Any = None) -> Any:
        """Record a sleep request and advance the clock by that duration."""
        delay = float(seconds)
        self.sleep_calls.append(delay)
        self._now += delay
        return result

    @contextmanager
    def patch(self, *modules: Any) -> Iterator["FakeClock"]:
        """Patch each module's ``time`` (and ``asyncio`` when present).

        Yields the clock so callers can chain ``clock.advance(...)`` inside the
        ``with`` block.  A module must expose a ``time`` attribute; missing
        ``asyncio`` is allowed (time-only modules such as
        ``uploader.publish_timeout``).
        """
        if not modules:
            raise AssertionError("FakeClock.patch() needs at least one module")

        stack = ExitStack()
        try:
            for module in modules:
                if not hasattr(module, "time"):
                    raise AssertionError(
                        f"{module!r} has no module-level 'time' name to patch"
                    )
                stack.enter_context(
                    patch.object(module, "time", _FakeTime(self))
                )
                if hasattr(module, "asyncio"):
                    stack.enter_context(
                        patch.object(module, "asyncio", _FakeAsyncio(self))
                    )
                    self.patched_asyncio = True
            yield self
        finally:
            stack.close()

    def __enter__(self) -> "FakeClock":
        if self._module is None:
            raise RuntimeError(
                "FakeClock needs module=... for the context-manager form; "
                "otherwise use clock.patch(module)"
            )
        self._active = self.patch(self._module)
        self._active.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        assert self._active is not None
        try:
            return bool(self._active.__exit__(exc_type, exc, tb))
        finally:
            self._active = None
