"""Pages opened by one command in an existing managed browser context."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from loguru import logger
from patchright.async_api import BrowserContext, Page


class ManagedPages:
    def __init__(self, context: BrowserContext):
        self._context = context
        self._owned: list[Page] = []

    @property
    def pages(self) -> list[Page]:
        return [page for page in self._owned if not page.is_closed()]

    @property
    def request(self):
        return self._context.request

    async def cookies(self, urls):
        return await self._context.cookies(urls)

    def _track(self, page: Page) -> None:
        self._owned.append(page)
        # This event identifies the opener even when several tabs have the same URL.
        page.on("popup", self._track)

    async def new_page(self) -> Page:
        page = await self._context.new_page()
        self._track(page)
        return page

    async def close(self) -> None:
        while self._owned:
            page = self._owned.pop()
            try:
                if not page.is_closed():
                    await page.close()
            except Exception:
                logger.warning("无法关闭本命令的托管标签页。")


@asynccontextmanager
async def managed_pages(context: BrowserContext) -> AsyncIterator[ManagedPages]:
    pages = ManagedPages(context)
    try:
        yield pages
    finally:
        await pages.close()
