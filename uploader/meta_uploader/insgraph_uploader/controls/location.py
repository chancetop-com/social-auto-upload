"""Instagram 地点控件：输入 → 等待联想 → 按名称精确匹配 → 收起回读（spec §4.3.1）。

实测结构（real-dom-2026-11-10）：地点联想列表以 portal 挂在页面根，**没有任何
ARIA role**，是一列普通 ``div`` 行。因此候选只能从输入框元素出发，按几何 + 精确
文本定位：取输入框正下方的滚动容器——``top`` 落在 ``bottom-12`` 到
``bottom+160`` 之间、``height >= 40``、``width >= 100``、水平中心相距不超过
320px，多个命中取最内层；候选行是该容器的直接子节点。定位到行之后，用一次性
属性戳把它变成 Playwright ``Locator``，点击统一走 ``Humanizer.click``（真实
指针事件）：实测 ``el.click()`` 与句柄点击都不能可靠触发选中。模糊候选永不
点击，同名候选取页面顺序第一个。

候选行可能把名称与地址分行显示（收入 2026-11-20 受控页证据）：第一行是名称，
其余可见行合并为地址。匹配只比较名称——去首尾空白、合并连续空白、忽略大小写；
地址只作为所点行的证据记录。成功必须同时满足候选行/列表已收起，以及控件读回
所选名称。
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from patchright.async_api import (
    Locator,
    TimeoutError as BrowserTimeoutError,
)

from utils.humanize import Humanizer

from ..options import (
    FINAL_EMPTY,
    FINAL_MISMATCH,
    INELIGIBLE,
    LIST_NOT_COLLAPSED,
    MISSING,
    NO_CANDIDATES,
    NO_SAME_NAME,
    PRESENT,
    SELECTION_FAILED,
    UNAVAILABLE,
    OptionMismatchError,
    clamp_wait,
    location_matches,
    normalize_text,
)
from ._rows import dismiss_suggestions

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

# 只有页面明确说明资格限制时才允许使用 account_ineligible 文案。缺失入口、
# 通用提示或无关的 “... aren't available” 都不能命中；每个模式都要求地点
# 主题与否定/资格词相邻，或显式带账号/地区限定。
_LOCATION_RESTRICTION_PATTERNS = (
    re.compile(
        r"(?:location|地点)[^.\n]{0,40}"
        r"(?:not\s+available|isn['’]t\s+available|unavailable|"
        r"not\s+supported|isn['’]t\s+supported|"
        r"不可用|不支持|不符合资格|无法使用|无法选择)"
        r"[^.\n]{0,40}"
        r"(?:account|账号|region|country|地区|国家|age|年龄)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:account|账号)[^.\n]{0,40}"
        r"(?:not\s+eligible|ineligible|不符合资格|无资格)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:can['’]?t|cannot|unable\s+to|无法|不能)"
        r"[^.\n]{0,20}"
        r"(?:add|select|use|choose|添加|选择|设置)"
        r"[^.\n]{0,20}(?:location|地点)",
        re.IGNORECASE,
    ),
)


def location_restriction_message(body: str | None) -> str | None:
    """返回页面里明确的地点资格限制句；没有则返回 ``None``。"""
    if not body:
        return None
    text = " ".join(str(body).split())
    for pattern in _LOCATION_RESTRICTION_PATTERNS:
        match = pattern.search(text)
        if match:
            # 保留匹配句的完整可见文案（含句号），并限制无标点页面的长度。
            endings = [
                index for index in (
                    text.find('.', match.end()),
                    text.find('。', match.end()),
                )
                if index != -1
            ]
            end = min(endings) if endings else min(
                len(text), match.end() + 120
            )
            return text[match.start():end + 1].strip()
    return None


@dataclass(frozen=True, slots=True)
class LocationCandidate:
    """一条联想候选：第一行名称，其余可见行地址（可能没有地址）。"""

    index: int
    name: str
    address: str | None = None


# 几何 + 文本探针：默认返回联想列表的候选行（保留原始下标）；传入
# ``{index, name, address, stamp}`` 时校验该下标行的名称/地址，打上一次性
# 属性戳并返回是否命中，供调用方用 ``page.locator`` 取回 Locator 后走
# Humanizer 点击。行是普通 div（无 role），所以不依赖类名，只看尺寸与位置。
_SUGGESTION_JS = """(el, action) => {
  const norm = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const rowLines = (node) => String(node.innerText || node.textContent || '')
    .split(/\\r?\\n+/)
    .map(norm)
    .filter(Boolean);
  const parseRow = (node) => {
    const lines = rowLines(node);
    return {
      name: lines.length ? lines[0] : '',
      address: lines.length > 1 ? lines.slice(1).join(' ') : null,
    };
  };
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
  const selectionKey = Symbol.for('sau.instagram.locationSelection');
  if (action && action.verifyCollapse) {
    const selected = el[selectionKey];
    if (!selected || selected.token !== action.verifyCollapse) return false;
    const replaced = selected.parent.children[selected.slot];
    return !containers.some(node => {
      const owned = node === selected.list || (
        !selected.existing.has(node) &&
        (node === replaced || (selected.list.id && node.id === selected.list.id) ||
         !selected.parent.isConnected)
      );
      return owned && [...node.children].some(row => row.getClientRects().length && parseRow(row).name);
    });
  }
  const innermost = containers.filter(
    (node) => !containers.some((other) => other !== node && node.contains(other))
  );
  const list = innermost.sort((a, b) => b.children.length - a.children.length)[0];
  if (!list) return action && action.stamp ? false : [];
  const rows = [...list.children].filter((row) => parseRow(row).name);
  if (action && action.stamp) {
    const node = rows[action.index];
    if (!node) return false;
    const parsed = parseRow(node);
    if (norm(parsed.name).toLowerCase() !==
        norm(action.name).toLowerCase()) return false;
    if (norm(parsed.address || '') !== norm(action.address || '')) return false;
    const parent = list.parentElement;
    el[selectionKey] = {token: action.stamp, list, parent,
      slot: [...parent.children].indexOf(list), existing: new WeakSet(document.querySelectorAll('div'))};
    node.setAttribute('data-instagram-suggestion', String(action.stamp));
    return true;
  }
  return rows.map((node, index) => {
    const parsed = parseRow(node);
    return {index, name: parsed.name, address: parsed.address};
  }).filter((row) => row.name);
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
        # 成功/失败时供结果管线追加所点行证据；没有点击时保持空字典。
        self.last_evidence: dict = {}
        # resolve 时读到的明确资格限制文案，供失败结果说明原因。
        self.last_detail: str | None = None

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

    async def _restriction(self) -> str | None:
        """读取页面明确写出的地点资格限制；探测失败不凭空判定。"""
        if self._page is None:
            return None
        try:
            dialog = self._dialog()
            notices = await dialog.locator(
                '#location-restriction:visible, [data-testid*="location"] '
                ':is([role="alert"],[aria-live="assertive"]):visible'
            ).all_inner_texts()
        except Exception:
            return None
        for notice in notices:
            reason = location_restriction_message(notice)
            if reason:
                return reason
        return None

    async def resolve(self) -> str:
        """``present`` / ``missing`` / ``ineligible`` / ``unavailable``。"""
        self.last_detail = None
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            restriction = await self._restriction()
            if restriction:
                self.last_detail = restriction
                return INELIGIBLE
            return MISSING
        disabled = await entry.is_disabled()
        if not disabled:
            # 自定义控件只有 aria-disabled；两种禁用表达都算入口不可用。
            disabled = (
                (await entry.get_attribute('aria-disabled') or '').strip().lower()
                == 'true'
            )
        if disabled:
            # 只有页面明确提示资格限制时才归因为账号不可用；单纯 disabled
            # 记 control_disabled，避免把页面状态误写成“账号不符合资格”。
            restriction = await self._restriction()
            if restriction:
                self.last_detail = restriction
                return INELIGIBLE
            return UNAVAILABLE
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
        """逐字符输入并按名称点击首个同名候选；随后要求收起且回读一致。"""
        self.last_evidence = {}
        self.last_detail = None
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            # resolve() 已断言入口存在；此处只防御竞态，避免误填其他输入框。
            raise RuntimeError('Instagram 地点入口不可用')
        entries = await self._type_and_wait(entry, requested)
        if not entries:
            raise OptionMismatchError(
                'Instagram 地点搜索未出现任何候选：'
                f'请求「{requested}」',
                applied=None,
                reason=NO_CANDIDATES,
            )
        chosen = self._exact_entry(requested, entries)
        if chosen is None:
            raise OptionMismatchError(
                self._mismatch_message(requested, entries),
                applied=None,
                reason=NO_SAME_NAME,
            )
        selection = await self._click_entry(entry, chosen)
        if selection is None:
            raise OptionMismatchError(
                self._mismatch_message(requested, entries),
                applied=None,
                reason=SELECTION_FAILED,
            )
        # 地址只记录所点行；同名异址时以这一行的可见地址为准。
        self.last_evidence = {
            'candidate_name': chosen.name,
            'candidate_index': chosen.index,
        }
        if chosen.address:
            self.last_evidence['candidate_address'] = chosen.address
        if not await self._wait_list_collapsed(entry, selection):
            # 被点节点仍在 DOM 里说明选择没生效：不把输入框里的输入当成已选地点。
            raise OptionMismatchError(
                'Instagram 地点候选在点击后仍未收起：'
                f'被选「{chosen.name}」{self._address_suffix(chosen)}',
                applied=await self.read(),
                reason=LIST_NOT_COLLAPSED,
            )
        # 真机 2026-11-13：地点联想浮层选中后仍挂在 DOM 上盖住右侧选项面板，
        # 下一次点击报 covered-by。点弹窗标题栏关闭浮层（不改写已选地点）。
        await dismiss_suggestions(self._dialog(), self._behavior())
        applied = await self.read()
        if not applied:
            raise OptionMismatchError(
                'Instagram 地点回读为空：'
                f'被选「{chosen.name}」{self._address_suffix(chosen)}',
                applied=None,
                reason=FINAL_EMPTY,
            )
        if not location_matches(chosen.name, applied):
            # 回读必须与被点候选的名称规范化一致；地址不参与比较。
            raise OptionMismatchError(
                'Instagram 地点回读与被选候选名称不一致：'
                f'被选「{chosen.name}」，回读「{applied}」',
                applied=applied,
                reason=FINAL_MISMATCH,
            )

    async def _type_and_wait(
        self, entry: Locator, requested: str
    ) -> list[LocationCandidate]:
        """逐字符输入并等待联想；列表始终为空时清空重输一次，规避 debounce 竞态。

        首次输入前只聚焦（``T/none``）；重试时用全选 + Backspace 覆盖旧值，不再
        ``fill('')``。每次输入都由 ``Humanizer.type_text`` 逐字派发并自带一次
        ``after_type``；debounce 期间不重复输入。
        """
        humanizer = self._behavior()
        await entry.focus()
        for attempt in range(2):
            if attempt or await entry.input_value():
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

    async def _suggestions(self, entry: Locator) -> list[LocationCandidate]:
        """按几何 + 文本枚举输入框下方的联想行（保留原始下标）。"""
        try:
            rows = await entry.evaluate(_SUGGESTION_JS)
        except Exception:
            return []
        candidates: list[LocationCandidate] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get('name') or row.get('label') or '').strip()
            if not name:
                continue
            address = str(row.get('address') or '').strip() or None
            candidates.append(
                LocationCandidate(
                    int(row.get('index', len(candidates))),
                    name,
                    address,
                )
            )
        return candidates

    async def _wait_for_suggestions(
        self, entry: Locator
    ) -> list[LocationCandidate]:
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
        self, entry: Locator, candidate: LocationCandidate
    ) -> str | None:
        """把被选候选变成 ``Locator`` 并走 Humanizer 点击；点击前再核对名称/地址。

        联想行没有 role、也不是输入框后代，唯一的桥是把 JS 找到的节点打上一次
        性属性戳，再由 ``page.locator`` 取回 Locator。点击必须是坐标点击：
        实测联想只响应真实指针事件，句柄/JS 点击都不会触发选中。
        """
        token = f's{candidate.index}-{uuid4().hex}'
        try:
            stamped = await entry.evaluate(
                _SUGGESTION_JS,
                {
                    'index': candidate.index,
                    'name': candidate.name,
                    'address': candidate.address,
                    'stamp': token,
                },
            )
        except Exception:
            return None
        if not stamped:
            return None
        node = self._page.locator(
            f'[{_SUGGESTION_ATTR}="{token}"]'
        )
        try:
            if await node.count() != 1:
                return None
        except Exception:
            return None
        humanizer = self._behavior()
        await humanizer.click(node)
        return token

    async def _wait_list_collapsed(self, entry: Locator, token: str) -> bool:
        """Wait out row replacement as well as the original list's collapse."""
        deadline = time.monotonic() + self._timeout(SUGGESTION_TIMEOUT_MS) / 1000
        while True:
            if await entry.evaluate(_SUGGESTION_JS, {"verifyCollapse": token}):
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_POLL_SECONDS)

    @staticmethod
    def _exact_entry(
        requested: str, entries: list[LocationCandidate]
    ) -> LocationCandidate | None:
        """第一个名称规范化相等的候选；同名取第一个，模糊匹配永不命中。"""
        wanted = normalize_text(requested)
        for candidate in entries:
            if normalize_text(candidate.name) == wanted:
                return candidate
        return None

    @staticmethod
    def _address_suffix(candidate: LocationCandidate) -> str:
        return f'（地址：{candidate.address}）' if candidate.address else ''

    @staticmethod
    def _mismatch_message(
        requested: str, entries: list[LocationCandidate]
    ) -> str:
        """失败文案必须带请求值与观察到的候选（最多 10 条，含可见地址）。"""
        reported = entries[:MAX_REPORTED_CANDIDATES]
        observed = '、'.join(
            f'「{candidate.name}」'
            + (f'（{candidate.address}）' if candidate.address else '')
            for candidate in reported
        )
        if not observed:
            observed = '（未出现任何候选）'
        elif len(entries) > MAX_REPORTED_CANDIDATES:
            observed += f'（共 {len(entries)} 条，仅列前 {MAX_REPORTED_CANDIDATES} 条）'
        return (
            'Instagram 地点没有同名候选：'
            f'请求「{requested}」；观察到的候选：{observed}'
        )

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
