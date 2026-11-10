"""配文页共用页面助手：折叠行定位、展开与控件点击。

实测结构（real-dom-2026-11-10）：折叠入口是 ``div[role="button"]``，里面只有
一个文案 span 和一个 chevron svg，**没有** ``aria-expanded``；展开与否靠内容
出现或 ``svg[aria-label="Up chevron icon"]`` 判断。配文列在视口边缘还有一层
覆盖 div 会拦截鼠标点击，但键盘激活始终可用，因此点击一律按“键盘优先、鼠标
兜底”的顺序执行。这里只依赖结构属性与可见文案，不使用任何哈希类名。
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING, Awaitable, Callable

from ..options import clamp_wait

if TYPE_CHECKING:  # 运行时只依赖 options，纯逻辑测试不构造浏览器类型。
    from patchright.async_api import Locator, Page

    from uploader.publish_timeout import PublishTimeoutBudget

# 键盘激活后的验证窗口；真实页面响应在数百毫秒内。
_ACTIVATE_TIMEOUT_MS = 3_000
# 鼠标 / JS 兜底的点击与验证窗口。
_FALLBACK_TIMEOUT_MS = 2_000
_POLL_SECONDS = 0.1


async def row_for(
    dialog: 'Locator', labels: tuple[str, ...]
) -> 'Locator | None':
    """按可见文案找到所在折叠行（``xpath=ancestor::*[@role="button"][1]``）。

    文案必须是精确节点文本：同一弹窗里还有描述段落，子串匹配会命中错误元素。
    找不到返回 ``None``，由调用方按 ``entry_missing`` 归类。
    """
    for label in labels:
        nodes = dialog.get_by_text(label, exact=True)
        try:
            count = await nodes.count()
        except Exception:
            continue
        for index in range(count):
            node = nodes.nth(index)
            try:
                if not await node.is_visible():
                    continue
                # 实测折叠行是 div[role=button]；原生 button 作为结构回退。
                row = node.locator(
                    'xpath=ancestor::*[@role="button" or self::button][1]'
                )
                if await row.count():
                    return row.first
            except Exception:
                continue
    return None


async def _wait_until(
    predicate: Callable[[], Awaitable[bool]], timeout_ms: int
) -> bool:
    """轮询谓词直到为真或超时；谓词异常视为“还没到状态”。"""
    deadline = time.monotonic() + max(int(timeout_ms), 0) / 1000
    while True:
        try:
            if await predicate():
                return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(_POLL_SECONDS)


async def press_enter(page: 'Page', row: 'Locator') -> None:
    """聚焦折叠行并按 Enter；鼠标点击在面板边缘会被覆盖层拦截，键盘才稳定。"""
    with contextlib.suppress(Exception):
        await row.scroll_into_view_if_needed()
    with contextlib.suppress(Exception):
        await row.focus()
        await page.keyboard.press("Enter")


async def activate(
    page: 'Page',
    row: 'Locator',
    *,
    is_open: Callable[[], Awaitable[bool]],
    budget: 'PublishTimeoutBudget | None' = None,
) -> bool:
    """展开折叠行并返回是否真的展开。

    顺序固定：``scroll_into_view_if_needed`` → ``focus`` + Enter → 点击兜底 →
    ``el.click()`` 兜底；每步都用 ``is_open`` 轮询验证，避免“点了但没展开”。
    """
    try:
        if await is_open():
            return True
    except Exception:
        pass
    await press_enter(page, row)
    if await _wait_until(is_open, clamp_wait(budget, _ACTIVATE_TIMEOUT_MS)):
        return True
    with contextlib.suppress(Exception):
        await row.click(timeout=clamp_wait(budget, _FALLBACK_TIMEOUT_MS))
    if await _wait_until(is_open, clamp_wait(budget, _FALLBACK_TIMEOUT_MS)):
        return True
    with contextlib.suppress(Exception):
        await row.evaluate("el => el.click()")
    return await _wait_until(is_open, clamp_wait(budget, _FALLBACK_TIMEOUT_MS))


async def click_control(
    page: 'Page', locator: 'Locator', *, budget: 'PublishTimeoutBudget | None' = None
) -> None:
    """点击开关等控件：滚动可见后点击，失败依次回退到键盘与 ``el.click()``。"""
    with contextlib.suppress(Exception):
        await locator.scroll_into_view_if_needed()
    try:
        await locator.click(timeout=clamp_wait(budget, _FALLBACK_TIMEOUT_MS))
        return
    except Exception:
        pass
    with contextlib.suppress(Exception):
        await locator.focus()
        await page.keyboard.press("Space")
        return
    with contextlib.suppress(Exception):
        await locator.evaluate("el => el.click()")
