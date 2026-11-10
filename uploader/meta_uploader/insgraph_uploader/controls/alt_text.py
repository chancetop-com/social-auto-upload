"""替代文字控件：Accessibility 是配文弹窗内的**行内折叠区**，不是嵌套模态框。

实测结构（real-dom-2026-11-10 / probe6）：``Accessibility`` 行本身是
``div[role="button"]``，展开后同层插入若干 ``input[aria-label="Alt text"]``
（每图一个、自上而下按 ``--images`` 顺序），没有缩略图切换、没有
``Done``/``Save`` 按钮；再次激活该行即折叠，输入框从 DOM 移除，但值保留在
前端状态里，重开后原样回填。因此控件只做三件事：展开、按顺序填写并 blur、
收起。``set()`` / ``read()`` 结束时**一律收起**（spec §4.3.2），使管线的下一次
``read()`` 是真正的关闭 → 重开回读，而不是同一会话里的就地读取。
"""
from __future__ import annotations

import asyncio
import contextlib
import time
from typing import TYPE_CHECKING

from ..options import INELIGIBLE, MISSING, PRESENT, OptionMismatchError, clamp_wait
from ._rows import activate, press_enter, row_for

if TYPE_CHECKING:  # 运行时只导入 options 与行助手，避免把 Page 绑定成硬依赖。
    from patchright.async_api import Locator, Page

    from uploader.publish_timeout import PublishTimeoutBudget

# 入口文案：英文实测，中文按 spec §4.3.2 回退。
_ENTRY_LABELS = ('Accessibility', '无障碍', '替代文字')
# 输入框族：实测主选择器优先；DOM 顺序即图片顺序，不重排。
_ALT_INPUT_SELECTOR = (
    'input[aria-label="Alt text"], input[placeholder="Alt text"], '
    'textarea[aria-label="Alt text"]'
)

_CLOSE_TIMEOUT_MS = 5_000
_POLL_SECONDS = 0.05


class AltTextControl:
    """按图片张数填写替代文字的控件（``resolve/read/set`` 三方法）。

    图片张数由调用方从 ``self.image_files`` 传入，不用 DOM 猜测。折叠区只在
    需要时展开；``read()`` / ``set()`` 结束时一律收起，``resolve()`` 只是探针，
    保持原状并容忍收起失败。
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

    def _dialog(self) -> 'Locator':
        return self.page.get_by_role('dialog')

    async def _entry(self) -> 'Locator | None':
        """在创建弹窗内找 Accessibility 折叠行；面板与它同层，没有嵌套 dialog。"""
        return await row_for(self._dialog(), _ENTRY_LABELS)

    async def _entry_is_disabled(self, entry: 'Locator') -> bool:
        """``role=button`` 行可能用 aria-disabled 表达不可用，需连同祖先一起看。"""
        try:
            if not await entry.is_enabled():
                return True
            return bool(await entry.evaluate(
                "element => element.closest('[aria-disabled=\"true\"], [disabled]') !== null"
            ))
        except Exception:
            return False

    async def _inputs(self) -> 'Locator':
        """当前已渲染的 Alt text 输入框；折叠时为空（DOM 一并移除）。"""
        return self._dialog().locator(_ALT_INPUT_SELECTOR)

    async def _count(self) -> int:
        try:
            return await (await self._inputs()).count()
        except Exception:
            return 0

    async def _values(self) -> list[str]:
        inputs = await self._inputs()
        return [
            await inputs.nth(index).input_value()
            for index in range(await inputs.count())
        ]

    async def _has_inputs(self) -> bool:
        return bool(await self._count())

    async def _ensure_open(self) -> 'tuple[bool, bool]':
        """确保折叠区展开；返回 ``(是否展开, 是否由本次调用展开)``。"""
        if await self._has_inputs():
            return True, False
        entry = await self._entry()
        if entry is None:
            return False, False
        opened = await activate(
            self.page, entry, is_open=self._has_inputs, budget=self.budget
        )
        # activate 已用输入框出现作为展开成功的判据。
        return (True, True) if opened else (False, False)

    async def _collapse(self) -> None:
        """再次激活折叠行直到输入框消失；收不起来抛 ``OptionMismatchError``。

        ``read()`` / ``set()`` 必须让折叠区回到收起状态，管线的下一次 ``read()``
        才是“关闭 → 重开”回读；展开着却收不起来时无法确认回读，按 mismatch 上报
        （退出 1），不再像旧实现那样静默放弃。
        """
        entry = await self._entry()
        if entry is None or not await self._has_inputs():
            return
        await press_enter(self.page, entry)
        deadline = time.monotonic() + self._timeout(_CLOSE_TIMEOUT_MS) / 1000
        while await self._has_inputs():
            if time.monotonic() >= deadline:
                raise OptionMismatchError(
                    'Instagram 无障碍折叠区未能收起：Alt text 输入框仍在 DOM 中，'
                    '无法完成关闭 → 重开回读',
                    applied=None,
                )
            await asyncio.sleep(_POLL_SECONDS)

    async def _collapse_ignoring_failure(self) -> None:
        """异常路径上的尽力收起：不覆盖已经在传递的原始错误。"""
        with contextlib.suppress(OptionMismatchError):
            await self._collapse()

    async def resolve(self) -> str:
        """入口缺失 / 不可用 / 展开后仍无输入框时按不可用归类。

        本方法只是探针：只收起自己展开的折叠区，收起失败也不改变结论。
        """
        entry = await self._entry()
        if entry is None:
            return MISSING
        if await self._entry_is_disabled(entry):
            return INELIGIBLE
        opened, by_us = await self._ensure_open()
        try:
            # 入口存在但展开后仍没有 Alt text 输入框：spec §5.2 归为 entry_missing。
            return PRESENT if await self._has_inputs() else MISSING
        finally:
            if by_us:
                await self._collapse_ignoring_failure()

    async def read(self) -> list[str]:
        """打开折叠区回读逐张输入值，然后一律收起。

        无论进入时是否已展开，结束时都收起：回读必须是“关闭 → 重开”，否则读到
        的是同一会话里的就地状态。收不起来即按 mismatch 上报。
        """
        opened, _ = await self._ensure_open()
        if not opened:
            return []
        try:
            values = await self._values()
        except BaseException:
            await self._collapse_ignoring_failure()
            raise
        await self._collapse()
        return values

    async def set(self, requested: object) -> None:
        """数量等于图片张数才逐张填写；数量不符不填写并报出已观察到的值。

        填写完成后一律收起折叠区，保证管线下一次 ``read()`` 是关闭 → 重开回读。
        """
        if isinstance(requested, str):
            texts = [requested]
        else:
            texts = [str(text) for text in requested]  # type: ignore[union-attr]
        opened, _ = await self._ensure_open()
        if not opened:
            raise OptionMismatchError(
                f'Instagram 无障碍折叠区未展开：Alt text 输入框 0 个，'
                f'图片 {self.image_count} 张',
                applied=[],
            )
        try:
            inputs = await self._inputs()
            count = await inputs.count()
            values = await self._values()
            if count == 0:
                raise OptionMismatchError(
                    f'Instagram Alt text 输入框 0 个，图片 {self.image_count} 张，'
                    '无法按图片顺序逐张填写替代文字',
                    applied=[],
                )
            if count != self.image_count:
                raise OptionMismatchError(
                    f'Instagram Alt text 输入框 {count} 个，图片 {self.image_count} 张，'
                    '无法按图片顺序逐张填写替代文字',
                    applied=values,
                )
            if len(texts) != count:
                raise OptionMismatchError(
                    f'Instagram 替代文字 {len(texts)} 条，Alt text 输入框 {count} 个，'
                    '数量不符',
                    applied=values,
                )
            # 长度已由 §3.3 静态校验保证在 1..1000，运行时绝不截断。
            for index, text in enumerate(texts):
                field = inputs.nth(index)
                await field.fill(text)
                # 实测必须失焦才写入页面状态；否则折叠后值会丢。
                await field.evaluate('el => el.blur()')
        except BaseException:
            await self._collapse_ignoring_failure()
            raise
        # 正常结束必须真的收起：否则管线的 read() 只是同一会话的就地读取。
        await self._collapse()
