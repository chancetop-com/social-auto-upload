"""Instagram 地点控件：输入 → 等待联想 → 规范化精确匹配 → 回读（spec §4.3.1）。

只做地点一项；所有定位限定在配文页的创建弹窗内，联想项按 ``role`` 匹配而
不按标签名，绝不点击模糊候选。回读值以页面为准（Instagram 可能规范化成
``Shanghai, China`` 之类的候选标签），因此比较对象始终是“被点候选的标签”，
而不是原始请求值。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from patchright.async_api import (
    Locator,
    TimeoutError as BrowserTimeoutError,
)

from ..options import (
    INELIGIBLE,
    MISSING,
    PRESENT,
    OptionMismatchError,
    clamp_wait,
    location_matches,
    normalize_text,
)

if TYPE_CHECKING:  # 运行时只需要 page 的鸭子类型，避免把 patchright 绑进注册表。
    from patchright.async_api import Page

    from uploader.publish_timeout import PublishTimeoutBudget

# 已实测入口（06 §2.4）：配文页创建弹窗内的 “Add location”。
# 回退顺序固定：结构/placeholder → 中文 placeholder → aria-label，禁止全页定位。
ENTRY_SELECTORS = (
    'input[placeholder="Add location"]',
    'input[placeholder*="location" i]',
    'input[placeholder*="地点"]',
    'input[aria-label*="location" i]',
)
# 联想列表可能是弹窗内的普通列表，也可能挂到 portal / 页面根：按 role 匹配。
SUGGESTION_SELECTOR = '[role="option"]:visible'
# 等待联想列表的建议窗口（spec §4.3.1）；有预算时按剩余预算收紧。
ENTRY_TIMEOUT_MS = 5_000
SUGGESTION_TIMEOUT_MS = 10_000
# 联想列表可能分批挂载：出现后短暂静置，避免只看到第一条就判“无精确匹配”。
SUGGESTION_SETTLE_MS = 250
MAX_REPORTED_CANDIDATES = 10
MAX_SCANNED_CANDIDATES = 50


class LocationControl:
    """配文页地点输入框；``read()`` 返回输入框值或已选地点 chip 文本。"""

    def __init__(
        self, page: 'Page', *, budget: 'PublishTimeoutBudget | None' = None
    ) -> None:
        self._page = page
        self._budget = budget

    def _dialog(self) -> Locator:
        """创建弹窗；四个选项共用同一个弹窗，绝不使用全页定位。"""
        return self._page.get_by_role('dialog')

    def _timeout(self, default_ms: int) -> int:
        """有预算时把单步等待收紧到剩余总预算。"""
        return clamp_wait(self._budget, default_ms)

    async def _entry(self, timeout_ms: int) -> Locator | None:
        """按回退顺序返回第一个可见入口；全部缺席返回 None。"""
        dialog = self._dialog()
        union = dialog.locator(', '.join(ENTRY_SELECTORS))
        try:
            await union.first.wait_for(state='visible', timeout=timeout_ms)
        except BrowserTimeoutError:
            return None
        for selector in ENTRY_SELECTORS:
            candidate = dialog.locator(selector).first
            if await candidate.count() and await candidate.is_visible():
                return candidate
        return None

    async def resolve(self) -> str:
        """``present`` / ``missing`` / ``ineligible``（存在但 disabled）。"""
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            return MISSING
        if await entry.is_disabled():
            return INELIGIBLE
        # 自定义控件只有 aria-disabled；两种禁用表达都算账号不合格。
        if (await entry.get_attribute('aria-disabled') or '').strip().lower() == 'true':
            return INELIGIBLE
        return PRESENT

    async def read(self) -> str | None:
        """输入框值；为空时回读同一行已选地点 chip 的文本。"""
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            return None
        value = (await entry.input_value()).strip()
        if value:
            return value
        return await self._chip_text(entry)

    async def set(self, requested: str) -> None:
        """填入地点并点击规范化精确相等的第一个候选；否则列出候选并失败。"""
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            # resolve() 已断言入口存在；此处只防御竞态，避免误填其他输入框。
            raise RuntimeError('Instagram 地点入口不可用')
        options = await self._type_and_wait(entry, requested)
        entries = await self._entries(options)
        chosen = self._exact_entry(requested, entries)
        if chosen is None:
            raise OptionMismatchError(
                self._mismatch_message(requested, [label for _, label in entries]),
                applied=None,
            )
        index, label = chosen
        await options.nth(index).click()
        applied = await self.read()
        if not location_matches(label, applied):
            # 回读必须与被点候选规范化一致；不一致按实际回读值记 mismatch。
            raise OptionMismatchError(
                'Instagram 地点回读与被选候选不一致：'
                f'被选「{label}」，回读「{applied or ""}」',
                applied=applied,
            )

    async def _type_and_wait(self, entry: Locator, requested: str) -> Locator | None:
        """填入地点并等待联想；列表始终为空时清空重输一次，规避 debounce 竞态。"""
        for attempt in range(2):
            if attempt:
                await entry.fill('')
            await entry.fill(requested)
            options = await self._wait_for_suggestions()
            if options is not None:
                return options
        return None

    async def _wait_for_suggestions(self) -> Locator | None:
        """先等页面（含弹窗）出现可见联想项，再优先返回弹窗内的那一份。"""
        page_options = self._page.locator(SUGGESTION_SELECTOR)
        try:
            await page_options.first.wait_for(
                state='visible', timeout=self._timeout(SUGGESTION_TIMEOUT_MS)
            )
        except BrowserTimeoutError:
            return None
        await self._page.wait_for_timeout(SUGGESTION_SETTLE_MS)
        dialog_options = self._dialog().locator(SUGGESTION_SELECTOR)
        if await dialog_options.count():
            return dialog_options
        return page_options

    async def _entries(self, options: Locator | None) -> list[tuple[int, str]]:
        """按 DOM 顺序返回 ``(原始下标, 空白折叠标签)``，空标签项不参与匹配。

        下标必须保留原始位置：``options.nth(i)`` 作用于未过滤的候选列表，若按
        压缩后的下标点击，空标签候选会让点击落到错误的地点（spec §4.3.1）。
        """
        if options is None:
            return []
        entries: list[tuple[int, str]] = []
        for index in range(min(await options.count(), MAX_SCANNED_CANDIDATES)):
            label = ' '.join((await options.nth(index).inner_text()).split())
            if label:
                entries.append((index, label))
        return entries

    @staticmethod
    def _exact_entry(
        requested: str, entries: list[tuple[int, str]]
    ) -> tuple[int, str] | None:
        """第一个规范化精确相等的候选；同名取第一个，模糊匹配永不命中。"""
        wanted = normalize_text(requested)
        for index, label in entries:
            if normalize_text(label) == wanted:
                return index, label
        return None

    @staticmethod
    def _mismatch_message(requested: str, labels: list[str]) -> str:
        """失败文案必须带请求值与观察到的候选（最多 10 条）。"""
        reported = labels[:MAX_REPORTED_CANDIDATES]
        observed = '、'.join(f'「{label}」' for label in reported)
        if not observed:
            observed = '（未出现任何候选）'
        elif len(labels) > MAX_REPORTED_CANDIDATES:
            observed += f'（共 {len(labels)} 条，仅列前 {MAX_REPORTED_CANDIDATES} 条）'
        return f'Instagram 地点没有精确匹配：请求「{requested}」；观察到的候选：{observed}'

    async def _chip_text(self, entry: Locator) -> str | None:
        """输入框为空时读同一行 chip 文本；候选结构由真实 DOM 用例固定。"""
        row = entry.locator('xpath=..')
        chips = row.locator('[role="button"]')
        for index in range(await chips.count()):
            text = ' '.join((await chips.nth(index).inner_text()).split())
            if text:
                return text
        return None
