"""大鱼号人类化接线共用件：单实例缓存、预算裁剪停顿、选择器收窄。

`Humanizer` 的公开面由 ``utils.humanize`` 唯一定义；本模块只负责把平台对象
接到它上面，不复制任何参数表，也不提供第二条点击路径。
"""
from __future__ import annotations

import asyncio
from typing import Any

from utils.dom import ElementMissingError, ElementUnusableError
from utils.humanize import Humanizer
from utils.log import dayu_logger

#: 收窄轮询：多义立即失败，缺席按统一期限报 ElementMissingError。
_UNIQUE_TIMEOUT_MS = 30_000
_UNIQUE_POLL_SECONDS = 0.1


async def unique(locator: Any, what: str, *, timeout_ms: int = _UNIQUE_TIMEOUT_MS):
    """把 ``locator`` 收窄到唯一匹配；多义硬错 ``ambiguous:N``，不取 .first。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_ms / 1000
    while True:
        count = await locator.count()
        if count > 1:
            raise ElementUnusableError(
                what,
                role="interactive",
                reason=f"ambiguous:{count}",
                publish_clicked=False,
            )
        if count == 1:
            return locator
        if loop.time() >= deadline:
            raise ElementMissingError(what, role="interactive", publish_clicked=False)
        await asyncio.sleep(_UNIQUE_POLL_SECONDS)


class DayuHumanizeMixin:
    """一个 page 一个 ``Humanizer``；停顿只吃发布预算的剩余秒数。"""

    def _humanizer(self, page: Any) -> Humanizer:
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        budget = getattr(self, "_publish_budget", None)
        if budget is None:
            # 直接调用表单方法（离线测试/诊断）没有预算对象，不做裁剪。
            await asyncio.sleep(seconds)
            return
        remaining = max(0.0, budget.remaining_seconds())
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            dayu_logger.warning(
                "人类化停顿被预算裁剪: {}s > {}s",
                round(seconds, 2),
                round(remaining, 2),
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))


__all__ = ["DayuHumanizeMixin", "unique"]
