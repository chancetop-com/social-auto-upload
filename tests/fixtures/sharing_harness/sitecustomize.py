"""Deterministic clock and cleanup failure injection for installed CLI tests.

The production sharing layer keeps its hard 5-second minimum.  This module only
replaces the module-level clock/sleep seam inside a child interpreter so the
recovery suite can advance across that interval without spending wall-clock
time.  The same interpreter can raise from page/CDP cleanup to prove that a
warning cannot replace the command's primary result.
"""

from __future__ import annotations

import os
from pathlib import Path

_clock = os.environ.get("SAU_TEST_MANAGED_CLOCK")
if _clock:
    from utils import managed_sharing

    clock_path = Path(_clock)

    def _read() -> float:
        try:
            return float(clock_path.read_text())
        except FileNotFoundError:
            return 0.0

    def _write(value: float) -> None:
        # A successor and the departing command can briefly overlap. Replace
        # atomically so neither reader observes a truncated float.
        temporary = clock_path.with_name(
            f"{clock_path.name}.{os.getpid()}.tmp"
        )
        temporary.write_text(repr(value))
        os.replace(temporary, clock_path)

    def monotonic() -> float:
        return _read()

    def sleep(seconds: float) -> None:
        _write(_read() + max(0.0, float(seconds)))

    managed_sharing.monotonic = monotonic
    managed_sharing.sleep = sleep

if os.environ.get("SAU_TEST_PAGE_CLOSE_FAILURE"):
    from patchright.async_api import Page

    _page_close = Page.close

    async def _failing_page_close(page, **kwargs):
        try:
            url = page.url or ""
        except Exception:
            url = ""
        if ".com" in url:
            raise RuntimeError("offline page cleanup failure")
        return await _page_close(page, **kwargs)

    Page.close = _failing_page_close

if os.environ.get("SAU_TEST_BROWSER_CLOSE_FAILURE"):
    from patchright.async_api import Browser

    async def _failing_browser_close(browser, **kwargs):
        raise RuntimeError("offline CDP disconnect failure")

    Browser.close = _failing_browser_close
