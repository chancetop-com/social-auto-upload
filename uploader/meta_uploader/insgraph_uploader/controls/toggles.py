"""Instagram 配文页开关控件：关闭评论（工单 11）与 AI 标识（工单 12）复用。

DOM 语义与业务语义不一定一致：关闭评论开关的 ``checked`` 表示“评论已关闭”，
而管线需要的是 ``comments_enabled``。``SwitchControl`` 统一负责弹窗内定位、
按需展开折叠面板、读取语义值以及点击后回读；调用方只声明文案与是否反转。

实测结构（real-dom-2026-11-10）：开关是标签列的**兄弟列**里的
``input[role=switch]``，开关自身与父元素的 textContent 都是空；定位必须从
标签文本出发，向上找到包含开关的最近祖先，再取其中的开关。
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from ..options import (
    INELIGIBLE,
    MISSING,
    PRESENT,
    OptionMismatchError,
    clamp_wait,
)
from ._rows import activate, click_control, row_for

if TYPE_CHECKING:  # 仅用于类型标注，纯逻辑测试不构造浏览器类型。
    from patchright.async_api import Locator, Page

    from uploader.publish_timeout import PublishTimeoutBudget

# 开关候选：实测是 input[role=switch]，其余为结构回退。
_SWITCH_SELECTOR = '[role="switch"], [role="checkbox"]'
# 非精确文案的兜底：沿祖先链（含自身，向上 4 层）找包含标签文本的行。
_SWITCH_TEXT_JS = """(el, labels) => {
  const norm = (value) => String(value || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const wanted = labels.map(norm).filter(Boolean);
  let node = el;
  for (let depth = 0; depth < 5 && node; depth += 1, node = node.parentElement) {
    const text = norm(node.textContent);
    if (wanted.some((label) => text.includes(label))) return true;
  }
  return false;
}"""

# 折叠状态的真值主要看内容是否可见；chevron 只作辅助，文案允许英文变体与中文。
_UP_CHEVRON_SELECTOR = (
    '[aria-label="Up chevron icon"], '
    '[aria-label*="chevron" i][aria-label*="up" i], '
    '[aria-label*="向上"]'
)

_READBACK_TIMEOUT_MS = 10_000
_READBACK_INTERVAL_S = 0.1


async def _switch_checked(switch: 'Locator') -> bool | None:
    """读取开关状态：``aria-checked`` 优先，原生 checkbox 回退 ``is_checked()``。"""
    aria = await switch.get_attribute("aria-checked")
    if aria is not None:
        return str(aria).strip().lower() == "true"
    try:
        return bool(await switch.is_checked())
    except Exception:
        return None


class SwitchControl:
    """配文弹窗内的一个 ARIA 开关（duck typed 满足 ``InstagramOptionControl``）。

    ``labels`` 是英文优先、中文回退的可见文案元组；``panel_labels`` 是可选折叠
    入口文案（如 Advanced settings），只在开关缺席或只有隐藏节点时按实例至多
    激活一次；``invert=True`` 时 ``read()`` 返回取反后的语义值（checked = 评论已关闭）。
    """

    def __init__(
        self,
        page: 'Page',
        *,
        labels: tuple[str, ...],
        panel_labels: tuple[str, ...] | None = None,
        invert: bool = False,
        budget: 'PublishTimeoutBudget | None' = None,
    ) -> None:
        if not labels:
            raise ValueError("SwitchControl 至少需要一个文案回退")
        self._page = page
        self._labels = tuple(labels)
        self._panel_labels = tuple(panel_labels) if panel_labels else ()
        self._invert = invert
        self._budget = budget
        self._panel_open = False

    def _dialog(self) -> 'Locator':
        return self._page.get_by_role("dialog")

    async def _locate(self) -> 'Locator | None':
        """按标签文本定位开关：精确文本 → 最近的含开关祖先 → 开关本身。

        精确文本定位覆盖实测结构；再枚举开关、沿祖先链比对文案，兜住
        “标签是变体文案（如 ``AI label``）”但节点文本不完全相等的情况。
        """
        dialog = self._dialog()
        for label in self._labels:
            nodes = dialog.get_by_text(label, exact=True)
            try:
                count = await nodes.count()
            except Exception:
                continue
            for index in range(count):
                switch = await self._switch_under(nodes.nth(index))
                if switch is not None:
                    return switch
        switches = dialog.locator(_SWITCH_SELECTOR)
        try:
            count = await switches.count()
        except Exception:
            return None
        for index in range(count):
            switch = switches.nth(index)
            try:
                if await switch.evaluate(_SWITCH_TEXT_JS, list(self._labels)):
                    return switch
            except Exception:
                continue
        return None

    @staticmethod
    async def _switch_under(node: 'Locator') -> 'Locator | None':
        """从标签节点向上找最近的含开关祖先，再取其中的开关。"""
        try:
            holder = node.locator(
                'xpath=ancestor-or-self::*'
                '[descendant-or-self::*[@role="switch"] or '
                'descendant-or-self::*[@role="checkbox"]][1]'
            )
            if not await holder.count():
                return None
            switch = holder.locator(_SWITCH_SELECTOR)
            if await switch.count():
                return switch.first
        except Exception:
            return None
        return None

    @staticmethod
    async def _visible(switch: 'Locator') -> bool:
        """开关是否真的可见；折叠面板收起时保留的隐藏节点不算可用。"""
        try:
            return bool(await switch.is_visible())
        except Exception:
            return False

    async def _panel_open_in_dom(self) -> bool:
        """折叠面板是否已展开：开关**可见**，或 chevron 已朝上。

        实测收起的面板仍会在 DOM 里保留 switch 节点：只按“存在”判断会把未展开
        误认为已展开，跳过激活后开关永远点不到，因此存在之外还必须可见。
        """
        switch = await self._locate()
        if switch is not None and await self._visible(switch):
            return True
        row = await row_for(self._dialog(), self._panel_labels)
        if row is None:
            return False
        try:
            return bool(await row.locator(_UP_CHEVRON_SELECTOR).count())
        except Exception:
            return False

    async def _expand_panel(self) -> None:
        """按实例至多激活一次折叠入口；失败也不重复点击。"""
        if self._panel_open or not self._panel_labels:
            return
        # 先置位再等待：即使展开后仍找不到开关，重复调用也不会再次点击。
        self._panel_open = True
        row = await row_for(self._dialog(), self._panel_labels)
        if row is None:
            return
        await activate(
            self._page, row, is_open=self._panel_open_in_dom, budget=self._budget
        )

    async def _ensure(self) -> 'Locator | None':
        """返回开关；缺席或只有隐藏节点且声明了折叠入口时展开一次再找。"""
        switch = await self._locate()
        if switch is not None and await self._visible(switch):
            return switch
        if self._panel_labels:
            await self._expand_panel()
        return await self._locate()

    async def resolve(self) -> str:
        switch = await self._ensure()
        if switch is None:
            return MISSING
        if await switch.is_disabled():
            return INELIGIBLE
        try:
            if (await switch.get_attribute("aria-disabled") or "").lower() == "true":
                return INELIGIBLE
        except Exception:
            pass
        return PRESENT

    async def read(self) -> bool | None:
        """返回语义值；``invert=True`` 时把 checked 取反（comments_enabled）。"""
        switch = await self._ensure()
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
        switch = await self._ensure()
        if switch is None:
            raise RuntimeError(
                f"Instagram 开关入口缺失: {self._labels[0]}"
                f"{_panel_hint(self._panel_labels)}"
            )
        await click_control(self._page, switch, budget=self._budget)
        await self._wait_readback(requested)

    async def _wait_readback(self, requested: bool) -> None:
        deadline = time.monotonic() + clamp_wait(
            self._budget, _READBACK_TIMEOUT_MS
        ) / 1000
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


def _panel_hint(panel_labels: tuple[str, ...]) -> str:
    """入口缺失时附带折叠面板文案，便于定位是面板没展开还是账号不支持。"""
    return f"（折叠入口: {panel_labels[0]}）" if panel_labels else ""
