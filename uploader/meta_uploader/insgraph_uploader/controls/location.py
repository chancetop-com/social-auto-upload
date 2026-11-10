"""Instagram 地点控件：输入 → 等待联想 → 规范化精确匹配 → 回读（spec §4.3.1）。

实测结构（real-dom-2026-11-10）：地点联想列表挂在页面根、**没有任何 ARIA
role**，是一列普通 ``div`` 行。因此候选只能按几何 + 精确文本定位：位于输入框
下方 520px 内、高 40–80px、宽超过 200px、子元素不超过 2 个。点击用行元素的
``.click()`` 派发；模糊候选永不点击。回读值以页面输入框为准，比较对象始终是
“被点候选的标签”，而不是原始请求值。
"""
from __future__ import annotations

import asyncio
import time
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
    from patchright.async_api import ElementHandle, Page

    from uploader.publish_timeout import PublishTimeoutBudget

# 已实测入口（06 §2.4）：配文页创建弹窗内的 “Add location”。
# 回退顺序固定：结构/placeholder → 中文 placeholder → aria-label，禁止全页定位。
ENTRY_SELECTORS = (
    'input[placeholder="Add location"]',
    'input[placeholder*="location" i]',
    'input[placeholder*="地点"]',
    'input[aria-label*="location" i]',
)
# 等待联想列表的建议窗口（spec §4.3.1）；有预算时按剩余预算收紧。
ENTRY_TIMEOUT_MS = 5_000
SUGGESTION_TIMEOUT_MS = 10_000
CLICK_TIMEOUT_MS = 10_000
# 联想列表可能分批挂载：出现后短暂静置，避免只看到第一条就判“无精确匹配”。
SUGGESTION_SETTLE_MS = 250
# 逐字符输入更接近人工操作，实测 fill() 不会触发联想列表。
TYPE_DELAY_MS = 80
MAX_REPORTED_CANDIDATES = 10
_POLL_SECONDS = 0.1

# 几何 + 文本探针：默认返回下方候选行；传入 click 参数时点击指定行。
# 行结构是普通 div（无 role），所以不依赖类名，只看尺寸与位置。
_SUGGESTION_JS = """(el, action) => {
  const norm = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const rect = el.getBoundingClientRect();
  const mid = rect.left + rect.width / 2;
  // 联想列表是 portal：取输入框正下方最近的滚动容器（最内层），而不是全页同尺寸 div，
  // 否则侧栏 “Messages” / “Add collaborators” 等节点会混进候选甚至被误点。
  const containers = [...document.querySelectorAll('div')].filter(node => {
    const cs = getComputedStyle(node);
    if (cs.overflowY !== 'auto' && cs.overflowY !== 'scroll') return false;
    const box = node.getBoundingClientRect();
    if (box.height < 40 || box.width < 100) return false;
    if (box.top < rect.bottom - 12 || box.top > rect.bottom + 160) return false;
    if (Math.abs((box.left + box.width / 2) - mid) > 320) return false;
    return node.children.length >= 1;
  });
  const innermost = containers.filter(
    (node) => !containers.some((other) => other !== node && node.contains(other))
  );
  const list = innermost.sort((a, b) => b.children.length - a.children.length)[0];
  if (!list) return action && action.return_node ? null : [];
  const rows = [...list.children].filter((row) => norm(row.textContent));
  if (action && action.return_node) {
    const node = rows[action.index];
    if (!node) return null;
    if (norm(node.textContent).toLowerCase() !==
        String(action.label || '').toLowerCase()) return null;
    return node;
  }
  return rows
    .map((node, index) => ({index, label: norm(node.textContent)}))
    .filter((row) => row.label);
}"""


class LocationControl:
    """配文页地点输入框；``read()`` 返回输入框值或已选地点区块文本。"""

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
        """输入框值；为空时回读地点区块的文本（防御旧版 chip 结构）。"""
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            return None
        value = (await entry.input_value()).strip()
        if value:
            return value
        return await self._chip_text(entry)

    async def set(self, requested: str) -> None:
        """逐字符输入并点击规范化精确相等的第一个候选；否则列出候选并失败。"""
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            # resolve() 已断言入口存在；此处只防御竞态，避免误填其他输入框。
            raise RuntimeError('Instagram 地点入口不可用')
        entries = await self._type_and_wait(entry, requested)
        chosen = self._exact_entry(requested, entries)
        if chosen is None:
            raise OptionMismatchError(
                self._mismatch_message(requested, [label for _, label in entries]),
                applied=None,
            )
        index, label = chosen
        node = await self._click_entry(entry, index, label)
        if node is None:
            raise OptionMismatchError(
                self._mismatch_message(requested, [label for _, label in entries]),
                applied=None,
            )
        if not await self._wait_row_detached(node):
            # 被点节点仍在 DOM 里说明选择没生效：不把输入框里的输入当成已选地点。
            raise OptionMismatchError(
                'Instagram 地点候选在点击后仍未生效：'
                f'被选「{label}」',
                applied=await self.read(),
            )
        applied = await self.read()
        if not location_matches(label, applied):
            # 回读必须与被点候选规范化一致；不一致按实际回读值记 mismatch。
            raise OptionMismatchError(
                'Instagram 地点回读与被选候选不一致：'
                f'被选「{label}」，回读「{applied or ""}」',
                applied=applied,
            )

    async def _type_and_wait(
        self, entry: Locator, requested: str
    ) -> list[tuple[int, str]]:
        """逐字符输入并等待联想；列表始终为空时清空重输一次，规避 debounce 竞态。"""
        for attempt in range(2):
            if attempt:
                await entry.fill('')
            await entry.press_sequentially(requested, delay=TYPE_DELAY_MS)
            entries = await self._wait_for_suggestions(entry)
            if entries:
                return entries
        return []

    async def _suggestions(self, entry: Locator) -> list[tuple[int, str]]:
        """按几何 + 文本枚举输入框下方的联想行（保留原始下标）。"""
        try:
            rows = await entry.evaluate(_SUGGESTION_JS)
        except Exception:
            return []
        return [
            (int(row.get('index', -1)), str(row.get('label', '')))
            for row in rows or []
            if row.get('label')
        ]

    async def _wait_for_suggestions(
        self, entry: Locator
    ) -> list[tuple[int, str]]:
        """先等出现任意候选行，再短暂静置后重扫，避免只看到第一批。"""
        deadline = time.monotonic() + self._timeout(SUGGESTION_TIMEOUT_MS) / 1000
        while True:
            entries = await self._suggestions(entry)
            if entries:
                await self._page.wait_for_timeout(SUGGESTION_SETTLE_MS)
                return await self._suggestions(entry) or entries
            if time.monotonic() >= deadline:
                return []
            await asyncio.sleep(_POLL_SECONDS)

    async def _click_entry(
        self, entry: Locator, index: int, label: str
    ) -> 'ElementHandle | None':
        """返回被点候选的元素句柄并派发 ``.click()``；文本在点击前再核对一次。"""
        try:
            handle = await entry.evaluate_handle(
                _SUGGESTION_JS,
                {'index': index, 'label': label, 'return_node': True},
            )
        except Exception:
            return None
        node = handle.as_element()
        if node is None:
            return None
        # 实测：联想行只响应真实指针事件；``el.click()`` 不会触发选中，
        # 因此这里用 Playwright 的真实点击，失败即按未选中处理。
        try:
            await node.scroll_into_view_if_needed()
            await node.click(timeout=self._timeout(CLICK_TIMEOUT_MS))
        except Exception:
            return None
        return node

    async def _wait_row_detached(self, node: 'ElementHandle') -> bool:
        """选中后 Instagram 会卸载整个联想列表：以被点节点脱离 DOM 为准。

        实测（2026-11-10）：点击候选后列表节点 ``isConnected === false``，而
        输入框值保持不变；用“页面上是否还有类似尺寸的 div”判断会误判，因为
        配文栏滚动容器与页面其他节点也满足几何条件。
        """
        deadline = time.monotonic() + self._timeout(SUGGESTION_TIMEOUT_MS) / 1000
        while True:
            try:
                if await node.evaluate('el => !el.isConnected'):
                    return True
            except Exception:
                # 句柄已随旧文档销毁，同样视为消失。
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_POLL_SECONDS)

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
        """输入框为空时读地点区块文本，剔除清除按钮的图标文本。

        ``_abgh/_aw1v`` 是 Instagram 的旧版语义类名（非哈希类名），仅作防御性
        兜底：实测选中后输入框保留标签值，走不到这里；若结构再变则退到最近的
        祖先容器。
        """
        section = entry.locator(
            'xpath=ancestor::div'
            '[contains(concat(" ", normalize-space(@class), " "), " _abgh ")][1]'
        )
        if not await section.count():
            section = entry.locator('xpath=ancestor::div[1]')
        try:
            text = await section.first.evaluate(
                """(el) => {
                  const clone = el.cloneNode(true);
                  clone.querySelectorAll(
                    '[aria-haspopup="menu"], [aria-label="Close"], button'
                  ).forEach((node) => node.remove());
                  return String(clone.textContent || '')
                    .replace(/\\s+/g, ' ').trim();
                }"""
            )
        except Exception:
            return None
        return str(text or '').strip() or None
