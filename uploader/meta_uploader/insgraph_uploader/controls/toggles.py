"""Instagram 配文页开关控件：关闭评论（工单 11）与 AI 标识（工单 12）复用。

DOM 语义与业务语义不一定一致：关闭评论开关的 ``checked`` 表示“评论已关闭”，
而管线需要的是 ``comments_enabled``。``SwitchControl`` 统一负责弹窗内定位、
按需展开折叠面板、读取语义值以及点击后回读；调用方只声明文案与是否反转。
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Awaitable, Callable

from patchright.async_api import expect

from ..options import INELIGIBLE, MISSING, PRESENT, OptionMismatchError, normalize_text

if TYPE_CHECKING:  # 仅用于类型标注，纯逻辑测试不构造浏览器类型。
    from patchright.async_api import Locator, Page

# 开关优先取 input[role=switch]（实测结构），再回退 div[role=switch]/checkbox。
_SWITCH_SELECTORS = ('input[role="switch"]', '[role="switch"]', '[role="checkbox"]')
# 同行文案：开关自身或父行的 textContent（隐藏时也不依赖渲染）。
_ROW_TEXT_JS = (
    "el => [el.textContent, el.parentElement && el.parentElement.textContent]"
    ".filter(Boolean).join(' ')"
)

_READBACK_TIMEOUT_MS = 10_000
_READBACK_INTERVAL_S = 0.1


def _timeout_ms(budget: object | None, default_ms: int = _READBACK_TIMEOUT_MS) -> int:
    """有预算时把等待收紧到剩余总预算，否则用控件默认超时。"""
    clamp = getattr(budget, "clamp_ms", None)
    return int(clamp(default_ms)) if callable(clamp) else default_ms


async def _switch_checked(switch: 'Locator') -> bool | None:
    """读取开关状态：``aria-checked`` 优先，原生 checkbox 回退 ``is_checked()``。"""
    aria = await switch.get_attribute("aria-checked")
    if aria is not None:
        return str(aria).strip().lower() == "true"
    try:
        return bool(await switch.is_checked())
    except Exception:
        return None


def disclosure_panel(
    page: 'Page',
    labels: tuple[str, ...],
    *,
    budget: object | None = None,
) -> Callable[[], Awaitable[None]]:
    """构造展开折叠区块（如 ``Advanced settings``）的零参异步函数。

    已展开（``aria-expanded="true"``）时不再点击；找不到入口时保持页面原状，
    由 ``SwitchControl.resolve()`` 归为 ``entry_missing``。
    """

    async def expand() -> None:
        dialog = page.get_by_role("dialog")
        for label in labels:
            # 折叠入口自身携带 aria-expanded，按“属性 + 文案”定位最稳。
            control = dialog.locator("[aria-expanded]").filter(has_text=label)
            if not await control.count():
                fallback = dialog.get_by_text(label, exact=False)
                if not await fallback.count():
                    continue
                control = fallback
            target = control.first
            expanded = await target.get_attribute("aria-expanded")
            if str(expanded or "").lower() == "true":
                return
            await target.click()
            if expanded is None:
                # 入口不维护 aria-expanded，扩展是否生效交给开关可见性判断。
                return
            try:
                await expect(target).to_have_attribute(
                    "aria-expanded", "true", timeout=_timeout_ms(budget)
                )
            except Exception:
                # 只切换内容、不回写 aria-expanded 的实现同样继续往下走。
                return
            return

    return expand


class SwitchControl:
    """配文弹窗内的一个 ARIA 开关（duck typed 满足 ``InstagramOptionControl``）。

    ``labels`` 是英文优先、中文回退的可见文案元组；``panel`` 是可选的零参异步
    展开函数（如 Advanced settings），只在开关不可见时调用；``invert=True`` 时
    ``read()`` 返回取反后的语义值（checked = 评论已关闭）。
    """

    def __init__(
        self,
        page: 'Page',
        *,
        labels: tuple[str, ...],
        panel: Callable[[], Awaitable[None]] | None = None,
        invert: bool = False,
        budget: object | None = None,
    ) -> None:
        if not labels:
            raise ValueError("SwitchControl 至少需要一个文案回退")
        self._page = page
        self._labels = tuple(labels)
        self._panel = panel
        self._invert = invert
        self._budget = budget
        self._panel_open = False

    async def _locate(self) -> 'Locator | None':
        """在创建弹窗内按“行内文案”定位开关：input 优先，再回退其它结构。

        先枚举弹窗内的开关，再读其自身/父行文案；这样同一弹窗里存在多个开关
        （评论、AI 标识）时也不会误点。
        """
        dialog = self._page.get_by_role("dialog")
        for selector in _SWITCH_SELECTORS:
            switches = dialog.locator(selector)
            try:
                count = await switches.count()
            except Exception:
                continue
            for index in range(count):
                switch = switches.nth(index)
                if await self._row_matches(switch):
                    return switch
        return None

    async def _row_matches(self, switch: 'Locator') -> bool:
        try:
            text = await switch.evaluate(_ROW_TEXT_JS)
        except Exception:
            return False
        row = normalize_text(str(text or ""))
        return any(normalize_text(label) in row for label in self._labels)

    async def _ensure_panel(self) -> None:
        """按实例至多展开一次；开关已可见时不点击折叠入口。"""
        if self._panel is None or self._panel_open:
            return
        # 先置位再等待：即使展开后仍找不到开关，重复调用也不会再次点击。
        self._panel_open = True
        switch = await self._locate()
        if switch is not None and await switch.is_visible():
            return
        await self._panel()

    async def resolve(self) -> str:
        await self._ensure_panel()
        switch = await self._locate()
        if switch is None:
            return MISSING
        if await switch.is_disabled():
            return INELIGIBLE
        return PRESENT

    async def read(self) -> bool | None:
        """返回语义值；``invert=True`` 时把 checked 取反（comments_enabled）。"""
        await self._ensure_panel()
        switch = await self._locate()
        if switch is None:
            return None
        checked = await _switch_checked(switch)
        if checked is None:
            return None
        return not checked if self._invert else checked

    async def set(self, requested: bool) -> None:
        """已满足时不点击；否则点击一次并等待回读一致，超时或回读不符即报错。"""
        requested = bool(requested)
        if await self.read() == requested:
            return
        switch = await self._locate()
        if switch is None:
            raise RuntimeError(f"Instagram 开关入口缺失: {self._labels[0]}")
        await switch.click()
        await self._wait_readback(requested)

    async def _wait_readback(self, requested: bool) -> None:
        deadline = time.monotonic() + _timeout_ms(self._budget) / 1000
        applied: bool | None = None
        while True:
            try:
                applied = await self.read()
            except Exception:
                applied = None
            if applied == requested:
                return
            if time.monotonic() >= deadline:
                # 回读不一致按 mismatch 记录，并保留页面实际读到值（spec §5.2）。
                raise OptionMismatchError(
                    f"Instagram 开关回读不一致: {self._labels[0]} "
                    f"requested={requested} applied={applied}",
                    applied=applied,
                )
            await asyncio.sleep(_READBACK_INTERVAL_S)
