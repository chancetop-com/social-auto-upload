"""Instagram 地点控件：输入 → 等待联想 → 规范化精确匹配 → 回读（spec §4.3.1）。

实测结构（real-dom-2026-11-10）：地点联想列表以 portal 挂在页面根，**没有任何
ARIA role**，是一列普通 ``div`` 行。因此候选只能从输入框元素出发，按几何 + 精确
文本定位：取输入框正下方的滚动容器——``top`` 落在 ``bottom-12`` 到
``bottom+160`` 之间、``height >= 40``、``width >= 100``、水平中心相距不超过
320px，多个命中取最内层；候选行是该容器的直接子节点。定位到行之后，用一次性
属性戳把它变成 Playwright ``Locator``，点击统一走 ``Humanizer.click``（真实
指针事件）：实测 ``el.click()`` 与句柄点击都不能可靠触发选中。模糊候选永不
点击，同名候选取第一个。回读值以页面输入框为准，比较对象始终是“被点候选的
标签”，而不是原始请求值。
"""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from patchright.async_api import (
    Locator,
    TimeoutError as BrowserTimeoutError,
)

from utils.humanize import Humanizer

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
# 回退顺序固定：结构/name/placeholder → 中文 placeholder → aria-label，禁止全页定位。
ENTRY_SELECTORS = (
    'input[placeholder="Add location"]',
    'input[name="creation-location-input"]',
    'input[placeholder*="location" i]',
    'input[placeholder*="地点"]',
    'input[aria-label*="location" i]',
)
# 等待联想列表的建议窗口（spec §4.3.1）；有预算时按剩余预算收紧。
ENTRY_TIMEOUT_MS = 5_000
SUGGESTION_TIMEOUT_MS = 10_000
# 联想列表可能分批挂载：出现后短暂静置，避免只看到第一条就判“无精确匹配”。
SUGGESTION_SETTLE_MS = 250
# 逐字符输入更接近人工操作，实测 fill() 不会触发联想列表。Humanizer 的
# keystroke 采样均值 136ms、下界 30ms；本控件按“整段不短于 TYPE_DELAY_MS/字”
# 补齐缺口，保证不比旧的 press_sequentially(delay=80) 更快。
TYPE_DELAY_MS = 80
MAX_REPORTED_CANDIDATES = 10
_POLL_SECONDS = 0.1
# 候选行没有 role，只能由 JS 找到节点；一次性属性戳把它变成 Locator。
_SUGGESTION_ATTR = 'data-instagram-suggestion'

# 几何 + 文本探针：默认返回联想列表的候选行（保留原始下标）；传入
# ``{index, label, stamp}`` 时校验该下标行的精确文本，打上一次性属性戳并返回
# 是否命中，供调用方用 ``page.locator`` 取回 Locator 后走 Humanizer 点击。
# 行是普通 div（无 role），所以不依赖类名，只看尺寸与位置。
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
  if (!list) return action && action.stamp ? false : [];
  const rows = [...list.children].filter((row) => norm(row.textContent));
  if (action && action.stamp) {
    const node = rows[action.index];
    if (!node) return false;
    if (norm(node.textContent).toLowerCase() !==
        String(action.label || '').toLowerCase()) return false;
    node.setAttribute('data-instagram-suggestion', String(action.stamp));
    return true;
  }
  return rows
    .map((node, index) => ({index, label: norm(node.textContent)}))
    .filter((row) => row.label);
}"""


class LocationControl:
    """配文页地点输入框；``read()`` 返回输入框值或已选地点区块文本。"""

    def __init__(
        self,
        page: 'Page',
        *,
        budget: 'PublishTimeoutBudget | None' = None,
        humanizer: Humanizer | None = None,
    ) -> None:
        self._page = page
        self._budget = budget
        self._humanizer = humanizer

    def _behavior(self) -> Humanizer:
        """发布链路共享的 Humanizer；独立使用时按 page 自建（仍全部人类化）。"""
        if self._humanizer is None:
            self._humanizer = Humanizer(self._page)
        return self._humanizer

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
        """逐字符输入并等待联想；列表始终为空时清空重输一次，规避 debounce 竞态。

        首次输入前只聚焦（``T/none``）；重试时用全选 + Backspace 覆盖旧值，不再
        ``fill('')``。每次输入都由 ``Humanizer.type_text`` 逐字派发并自带一次
        ``after_type``；debounce 期间不重复输入。
        """
        humanizer = self._behavior()
        await entry.focus()
        for attempt in range(2):
            if attempt:
                await humanizer.press('ControlOrMeta+A')
                await humanizer.press('Backspace')
            started = time.monotonic()
            await humanizer.type_text(requested)
            await self._hold_cadence(started, len(requested))
            entries = await self._wait_for_suggestions(entry)
            if entries:
                return entries
        return []

    async def _hold_cadence(self, started: float, chars: int) -> None:
        """保证整段输入不比旧的 ``TYPE_DELAY_MS`` 更快。

        逐字节奏来自共享层（均值 136ms、下界 30ms）；这里只在采样偏快时补齐
        缺口，不复制第二份节奏表，也不在 ``HUMANIZE=0`` 的快速路径上加停顿。
        """
        if not self._behavior().enabled:
            return
        deficit = chars * TYPE_DELAY_MS / 1000.0 - (time.monotonic() - started)
        if deficit <= 0:
            return
        if self._budget is not None:
            deficit = min(deficit, max(0.0, self._budget.remaining_seconds()))
        if deficit > 0:
            await asyncio.sleep(deficit)

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
    ) -> Locator | None:
        """把被选候选变成 ``Locator`` 并走 Humanizer 点击；文本在点击前再核对一次。

        联想行没有 role、也不是输入框后代，唯一的桥是把 JS 找到的节点打上一次
        性属性戳，再由 ``page.locator`` 取回 Locator。点击必须是坐标点击：
        实测联想只响应真实指针事件，句柄/JS 点击都不会触发选中。
        """
        token = f's{index}-{uuid4().hex}'
        try:
            stamped = await entry.evaluate(
                _SUGGESTION_JS,
                {'index': index, 'label': label, 'stamp': token},
            )
        except Exception:
            return None
        if not stamped:
            return None
        candidate = self._page.locator(
            f'[{_SUGGESTION_ATTR}="{token}"]'
        )
        try:
            if await candidate.count() != 1:
                return None
        except Exception:
            return None
        humanizer = self._behavior()
        await humanizer.click(candidate)
        return candidate

    async def _wait_row_detached(self, node: Locator) -> bool:
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
                # Locator 已随旧文档销毁，同样视为消失。
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

    @staticmethod
    async def _container_text(section: Locator) -> str | None:
        """读取容器文本，剔除清除按钮等图标节点。"""
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

    async def _chip_text(self, entry: Locator) -> str | None:
        """输入框为空时读地点区块文本，剔除清除按钮的图标文本。

        只用最近祖先容器（结构），不使用任何 hash 类名。
        """
        section = entry.locator('xpath=ancestor::div[1]')
        return await self._container_text(section)
