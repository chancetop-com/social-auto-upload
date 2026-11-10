"""替代文字控件：Accessibility 模态框内按图片顺序逐张填写，关闭后重开回读。

规格：spec §4.3.2。入口与输入框均已实测（research 06 §2.7）：英文
``Accessibility`` 打开模态框后是 ``input[placeholder="Alt text"]``，2 图轮播
观察到 2 个输入框。所有定位都限定在 ``page.get_by_role('dialog')`` 内：配文页
本身是创建弹窗，无障碍模态框是它之上新开的 dialog，因此按“最内层含输入框的
dialog”定位，避免嵌套 dialog 造成重复计数或全页兜底。
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from patchright.async_api import expect

from ..options import INELIGIBLE, MISSING, PRESENT, OptionMismatchError, clamp_wait

if TYPE_CHECKING:  # 运行时只导入 options 与 expect，避免把 Page 绑定成硬依赖。
    from patchright.async_api import Locator, Page

    from uploader.publish_timeout import PublishTimeoutBudget

# 入口文案：英文实测，中文按 spec §4.3.2 回退。
_ENTRY_LABELS = ('Accessibility', '无障碍', '替代文字')
# 输入框候选：实测主选择器优先，其余按 placeholder / aria-label 结构回退。
# 每次只采用第一个命中的族，保证同一族内按 DOM 顺序逐张对应 --images。
_ALT_INPUT_SELECTORS = (
    'input[placeholder="Alt text"]',
    'input[placeholder*="alt" i]',
    'textarea[placeholder*="alt" i]',
    'input[aria-label*="alt" i]',
)
# 模态框主按钮：英文候选 + 中文回退；找不到就报 mismatch，不猜文案（spec §11）。
_CLOSE_LABELS = ('Done', 'Save', '完成')

_MODAL_OPEN_TIMEOUT_MS = 30_000
_MODAL_CLOSE_TIMEOUT_MS = 30_000
# 模态框已挂载后给前端渲染输入框的宽限，避免把“还没渲染”误判成 0 个输入框。
_INPUT_GRACE_SECONDS = 2.0
_POLL_SECONDS = 0.05


class AltTextControl:
    """按图片张数填写替代文字的控件（``resolve/read/set`` 三方法）。

    图片张数由调用方从 ``self.image_files`` 传入，不用 DOM 猜测。``read()``
    每次都重新打开模态框读取真实值：关闭再打开的回读才算数，填进去时的输入框
    状态不能替代回读（spec §4.3.2）。
    """

    def __init__(
        self, page: 'Page', *, image_count: int, budget: 'PublishTimeoutBudget | None' = None
    ) -> None:
        self.page = page
        self.image_count = image_count
        self.budget = budget

    def _timeout(self, default_ms: int) -> int:
        """把等待收紧到剩余发布预算；无预算时用默认值。"""
        return clamp_wait(self.budget, default_ms)

    def _dialogs(self) -> 'Locator':
        return self.page.get_by_role('dialog')

    async def _entry(self) -> 'Locator | None':
        """在最外层创建弹窗内找 Accessibility 入口（按钮优先，再退可见文案）。"""
        dialogs = self._dialogs()
        if not await dialogs.count():
            return None
        scope = dialogs.first
        for label in _ENTRY_LABELS:
            for candidate in (
                scope.get_by_role('button', name=label, exact=True),
                scope.get_by_text(label, exact=True),
            ):
                if await candidate.count():
                    return candidate.first
        return None

    async def _entry_is_disabled(self, entry: 'Locator') -> bool:
        """``role=button`` 行可能用 aria-disabled 表达不可用，需连同祖先一起看。"""
        if not await entry.is_enabled():
            return True
        return bool(await entry.evaluate(
            "element => element.closest('[aria-disabled=\"true\"], [disabled]') !== null"
        ))

    async def _modal_with_inputs(self) -> 'Locator | None':
        """当前已打开的、含可见 Alt text 输入框的最内层 dialog；未打开返回 None。

        ``filter(has=...)`` 会命中藏起来的输入框（display:none 的模态框仍在 DOM
        中），所以内层定位必须显式要求可见，否则关闭后的弹窗会被当成“已打开”。
        """
        dialogs = self._dialogs()
        for selector in _ALT_INPUT_SELECTORS:
            holder = dialogs.filter(has=self.page.locator(f'{selector}:visible'))
            if await holder.count():
                return holder.last
        return None

    async def _input_locator(self, modal: 'Locator') -> 'Locator':
        """选定一个输入框族；命中 0 个时也返回该族，交给调用方按 0 个处理。"""
        for selector in _ALT_INPUT_SELECTORS:
            locator = modal.locator(selector)
            if await locator.count():
                return locator
        return modal.locator(_ALT_INPUT_SELECTORS[0])

    async def _values(self, inputs: 'Locator') -> list[str]:
        return [
            await inputs.nth(index).input_value()
            for index in range(await inputs.count())
        ]

    async def _open_modal(self) -> 'tuple[Locator | None, bool]':
        """确保无障碍模态框已打开；返回 ``(模态框, 是否由本次调用打开)``。"""
        modal = await self._modal_with_inputs()
        if modal is not None:
            return modal, False
        entry = await self._entry()
        if entry is None:
            return None, False
        before = await self._dialogs().count()
        await entry.click()
        return await self._wait_for_modal(before), True

    async def _wait_for_modal(self, before: int) -> 'Locator | None':
        """等模态框挂载并渲染输入框；只有确实没有输入框时才返回仅有的 dialog。"""
        deadline = time.monotonic() + self._timeout(_MODAL_OPEN_TIMEOUT_MS) / 1000
        mounted_at: float | None = None
        while True:
            modal = await self._modal_with_inputs()
            if modal is not None:
                return modal
            dialogs = self._dialogs()
            if await dialogs.count() > before:
                if mounted_at is None:
                    mounted_at = time.monotonic()
                elif time.monotonic() - mounted_at >= _INPUT_GRACE_SECONDS:
                    # 模态框已出现但没有任何 Alt text 输入框：按 0 个交给调用方。
                    return dialogs.last
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(_POLL_SECONDS)

    async def _close_modal(self, modal: 'Locator', *, applied: object = None) -> None:
        """点击模态框内主按钮并等待其消失；找不到按钮即报 mismatch，不猜文案。"""
        for label in _CLOSE_LABELS:
            for button in (
                modal.get_by_role('button', name=label, exact=True),
                modal.get_by_text(label, exact=True),
            ):
                if await button.count():
                    await button.first.click()
                    await expect(modal).to_have_count(
                        0, timeout=self._timeout(_MODAL_CLOSE_TIMEOUT_MS)
                    )
                    return
        raise OptionMismatchError(
            'Instagram 无障碍模态框未找到关闭按钮（Done / Save / 完成），'
            '无法确认替代文字已保存',
            applied=applied,
        )

    async def resolve(self) -> str:
        """入口缺失 / disabled / 或模态框没有任何输入框时按不可用归类。"""
        entry = await self._entry()
        if entry is None:
            return MISSING
        if await self._entry_is_disabled(entry):
            return INELIGIBLE
        modal, opened = await self._open_modal()
        if modal is None:
            return MISSING
        try:
            inputs = await self._input_locator(modal)
            # 入口存在但模态框没有 Alt text 输入框：spec §5.2 归为 entry_missing。
            return PRESENT if await inputs.count() else MISSING
        finally:
            if opened:
                await self._close_modal(modal)

    async def read(self) -> list[str]:
        """重新打开模态框回读逐张输入值（关闭后再开，不能读填进去的缓存）。"""
        modal, opened = await self._open_modal()
        if modal is None:
            return []
        inputs = await self._input_locator(modal)
        values = await self._values(inputs)
        if opened:
            await self._close_modal(modal, applied=values)
        return values

    async def set(self, requested: object) -> None:
        """数量等于图片张数才逐张填写；数量不符不填写并报出已观察到的值。"""
        if isinstance(requested, str):
            texts = [requested]
        else:
            texts = [str(text) for text in requested]  # type: ignore[union-attr]
        modal, opened = await self._open_modal()
        if modal is None:
            raise OptionMismatchError(
                f'Instagram 无障碍模态框未打开：Alt text 输入框 0 个，'
                f'图片 {self.image_count} 张',
                applied=[],
            )
        inputs = await self._input_locator(modal)
        try:
            count = await inputs.count()
            if count != self.image_count:
                raise OptionMismatchError(
                    f'Instagram Alt text 输入框 {count} 个，图片 {self.image_count} 张，'
                    '无法按图片顺序逐张填写替代文字',
                    applied=await self._values(inputs),
                )
            if len(texts) != count:
                raise OptionMismatchError(
                    f'Instagram 替代文字 {len(texts)} 条，Alt text 输入框 {count} 个，'
                    '数量不符',
                    applied=await self._values(inputs),
                )
            # 长度已由 §3.3 静态校验保证在 1..1000，运行时绝不截断。
            for index, text in enumerate(texts):
                await inputs.nth(index).fill(text)
            current = await self._values(inputs)
        except Exception:
            if opened:
                try:
                    await self._close_modal(modal)
                except Exception:
                    # 已判定失败，关闭失败不能覆盖原始失败原因。
                    pass
            raise
        await self._close_modal(modal, applied=current)
