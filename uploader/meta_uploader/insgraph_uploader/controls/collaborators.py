"""Instagram 协作者控件：打开面板 → 精确匹配 username → 逐个回读 → Done。

实测结构（2026-11-24）：

- 创建弹窗内的入口是 ``input[name="creation-collaborator-input"]``；中文
  placeholder 为「添加合作者」，英文为 “Add collaborators”。
- 聚焦/点击入口打开 Collaborators 面板：勾选行（username + 显示名 + checkbox）
  和 ``Done`` / 「完成」。
- 图文/轮播在预览图上渲染 chip：``span`` 文本为 username，同一容器内有带
  ``svg[aria-label="Close"/"关闭"]`` 的 ``role="button"``。
- 请求 ``nike`` 时联想会同时出现 ``_nikeza5``；只能取候选行首 token 做精确
  username 比较，显示名与包含关系不参与。

本控件复用既有 ``resolve/read/set`` 协议：``set()`` 内部逐个确认并把已确认
列表缓存为 ``_confirmed``，管线的 ``read()`` 在设置后返回请求顺序的结果。
所有可见交互都走共享 ``Humanizer``；不新增测试接缝，也不使用 hash 类名。
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
    ACCOUNT_INELIGIBLE,
    CONTROL_DISABLED,
    ENTRY_MISSING,
    FINAL_EMPTY,
    FINAL_MISMATCH,
    INELIGIBLE,
    LIST_NOT_COLLAPSED,
    MISSING,
    NO_CANDIDATES,
    NO_SAME_USERNAME,
    PRESENT,
    SELECTION_FAILED,
    UNAVAILABLE,
    OptionMismatchError,
    clamp_wait,
    normalize_collaborator_name,
)
from ._rows import row_for

if TYPE_CHECKING:  # 运行时只需要 page 的鸭子类型，避免把 patchright 绑进注册表。
    from patchright.async_api import Page

    from uploader.publish_timeout import PublishTimeoutBudget

# 入口选择器：结构属性优先，然后英文/中文 placeholder 与 aria-label，最后更宽
# 的中英文回退。定位始终限定在创建弹窗内，绝不使用全页 locator。
ENTRY_SELECTORS = (
    'input[name="creation-collaborator-input"]',
    'input[placeholder="Add collaborators"]',
    'input[aria-label="Add collaborators"]',
    'input[placeholder="添加合作者"]',
    'input[aria-label="添加合作者"]',
    'input[placeholder*="collaborator" i]',
    'input[aria-label*="collaborator" i]',
    'input[placeholder*="合作者"]',
    'input[aria-label*="合作者"]',
)
DONE_LABELS = ("Done", "完成")

ENTRY_TIMEOUT_MS = 5_000
PANEL_TIMEOUT_MS = 5_000
SUGGESTION_TIMEOUT_MS = 10_000
# 联想列表可能分批挂载：出现后短暂静置再重扫，避免只看到第一条。
SUGGESTION_SETTLE_MS = 250
# 点击后立即回读该 username；chip/checkbox 通常是同步渲染，给一个小窗口。
READBACK_TIMEOUT_MS = 3_000
DONE_TIMEOUT_MS = 5_000
MAX_REPORTED_CANDIDATES = 10
_POLL_SECONDS = 0.1
_ROW_ATTR = 'data-instagram-collaborator-row'

# 只有页面明确说明账号/地区不具备协作者资格时才使用 account_ineligible；
# 单纯 disabled 记 control_disabled。
_COLLABORATOR_RESTRICTION_PATTERNS = (
    re.compile(
        r"(?:collaborator|合作者|协作者)[^.\n]{0,40}"
        r"(?:not\s+available|isn['’]t\s+available|unavailable|"
        r"not\s+supported|isn['’]t\s+supported|"
        r"不可用|不支持|不符合资格|无法使用|无法邀请|无法添加)"
        r"[^.\n]{0,40}"
        r"(?:account|账号|region|country|地区|国家)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:account|账号)[^.\n]{0,40}"
        r"(?:not\s+eligible|ineligible|不符合资格|无资格)"
        r"[^.\n]{0,40}(?:collaborator|合作者|协作者)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:can['’]?t|cannot|unable\s+to|无法|不能)"
        r"[^.\n]{0,20}"
        r"(?:add|invite|select|添加|邀请|选择)"
        r"[^.\n]{0,20}(?:collaborator|合作者|协作者)",
        re.IGNORECASE,
    ),
)

# 候选行：从 checkbox 出发找最近的 role=button/button/li/label 行；只读取
# username 首 token。AI/评论开关是 role=switch，明确排除。
_ROWS_JS = """(el, action) => {
  const dialog = el.closest('[role="dialog"]') || document;
  const norm = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const visible = (node) => {
    if (!node || !node.getClientRects().length) return false;
    const style = getComputedStyle(node);
    return style.visibility !== 'hidden' && style.display !== 'none';
  };
  const rowFor = (input) => {
    let row = input.closest('button, [role="button"], li, label');
    if (!row) row = input.parentElement;
    while (row && row !== dialog && !norm(row.innerText || row.textContent)) {
      row = row.parentElement;
    }
    return row && row !== dialog ? row : null;
  };
  const seen = new Set();
  const rows = [];
  for (const input of dialog.querySelectorAll('input[type="checkbox"]')) {
    if ((input.getAttribute('role') || '').toLowerCase() === 'switch') continue;
    if (!visible(input)) continue;
    const row = rowFor(input);
    if (!row || seen.has(row)) continue;
    seen.add(row);
    const text = norm(row.innerText || row.textContent || '');
    if (!text) continue;
    const username = text.split(/\\s+/)[0];
    if (!username) continue;
    rows.push({
      node: row,
      username: username,
      display: text.slice(username.length).trim(),
      checked: Boolean(input.checked) ||
        (input.getAttribute('aria-checked') || '').toLowerCase() === 'true',
    });
  }
  if (!action || action.action === 'list') {
    return rows.map((row, index) => ({
      index: index,
      username: row.username,
      display: row.display,
      checked: row.checked,
    }));
  }
  const target = rows[action.index];
  if (!target) return null;
  if (norm(target.username).toLowerCase() !==
      norm(action.username).toLowerCase()) return null;
  target.node.setAttribute('data-instagram-collaborator-row', action.stamp);
  return true;
}"""

# 图文预览图 chip：带 Close/关闭 svg 的 role=button，最近的 span 祖先里
# 有一个 username span。只认这个结构，不读取输入框里的 “5 people” 摘要。
_CHIPS_JS = """(el) => {
  const dialog = el.closest('[role="dialog"]') || document;
  const norm = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
  const labels = new Set(['close', '关闭']);
  const names = [];
  const seen = new Set();
  for (const svg of dialog.querySelectorAll('svg[aria-label]')) {
    const label = norm(svg.getAttribute('aria-label')).toLowerCase();
    if (!labels.has(label)) continue;
    const button = svg.closest('[role="button"], button');
    if (!button) continue;
    const chip = button.closest('span');
    if (!chip) continue;
    const name = chip.querySelector('span');
    if (!name) continue;
    const text = norm(name.innerText || name.textContent || '');
    if (!text) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    names.push(text);
  }
  return names;
}"""


def collaborator_restriction_message(body: str | None) -> str | None:
    """返回页面明确写出的协作者资格限制句；没有则返回 ``None``。"""
    if not body:
        return None
    text = ' '.join(str(body).split())
    for pattern in _COLLABORATOR_RESTRICTION_PATTERNS:
        match = pattern.search(text)
        if match:
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
class CollaboratorCandidate:
    """一条联想候选：首个 token 是 username，其余是显示名。"""

    index: int
    username: str
    display: str | None = None
    checked: bool = False


class CollaboratorsControl:
    """创建页协作者入口；``set()`` 逐个选中并立即回读。"""

    def __init__(
        self,
        page: 'Page',
        *,
        image_count: int,
        budget: 'PublishTimeoutBudget | None' = None,
        humanizer: Humanizer | None = None,
    ) -> None:
        self._page = page
        self._image_count = image_count
        self._budget = budget
        self._humanizer = humanizer
        # set() 成功后按请求顺序缓存；管线在 Done 之后调用 read() 时不需要
        # 重开面板（Reels 的已选 username 只在面板打开时可读）。
        self._confirmed: list[str] | None = None
        self.last_evidence: dict = {}
        self.last_detail: str | None = None

    def _behavior(self) -> Humanizer:
        if self._humanizer is None:
            self._humanizer = Humanizer(self._page)
        return self._humanizer

    def _dialog(self) -> Locator:
        return self._page.get_by_role('dialog')

    def _timeout(self, default_ms: int) -> int:
        return clamp_wait(self._budget, default_ms)

    def _check_budget(self) -> None:
        if self._budget is not None:
            self._budget.check_pre_click()

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
        if self._page is None:
            return None
        try:
            notices = await self._dialog().locator(
                '#collaborator-restriction:visible, '
                '[data-testid*="collaborator"] '
                ':is([role="alert"],[aria-live="assertive"]):visible'
            ).all_inner_texts()
        except Exception:
            return None
        for notice in notices:
            reason = collaborator_restriction_message(notice)
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
            disabled = (
                (await entry.get_attribute('aria-disabled') or '').strip().lower()
                == 'true'
            )
        if disabled:
            restriction = await self._restriction()
            if restriction:
                self.last_detail = restriction
                return INELIGIBLE
            return UNAVAILABLE
        return PRESENT

    async def read(self) -> list[str] | None:
        """已确认的 username（请求顺序），或页面当前可见的选中项。

        ``set()`` 成功后返回缓存；否则图文读预览 chip、Reels 读面板 checkbox。
        无法读取时返回 ``None``；页面可读但没有选中项时返回 ``[]``。
        """
        if self._confirmed is not None:
            return list(self._confirmed)
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            return None
        if self._image_count > 0:
            return await self._read_chips(entry)
        checked = await self._checked_usernames(entry)
        return checked

    async def set(self, requested) -> None:
        """按请求顺序逐个选中；首个失败立即停止并保留已确认前缀。"""
        self.last_evidence = {}
        self.last_detail = None
        self._confirmed = None
        if isinstance(requested, str):
            requested = (requested,)
        names = [normalize_collaborator_name(value) for value in requested]
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if entry is None:
            raise OptionMismatchError(
                'Instagram 协作者入口不可用',
                applied=[],
                reason=ENTRY_MISSING,
            )
        await self._open_panel(entry)
        confirmed: list[str] = []
        for name in names:
            self._check_budget()
            try:
                if await self._is_selected(entry, name):
                    # 已经是选中状态：再点一次会取消勾选，绝不能重复点击。
                    confirmed.append(name)
                    continue
                candidates = await self._type_and_wait(entry, name)
                if not candidates:
                    raise OptionMismatchError(
                        'Instagram 协作者搜索未出现任何候选：'
                        f'请求「{name}」',
                        applied=list(confirmed),
                        reason=NO_CANDIDATES,
                    )
                chosen = self._exact_candidate(name, candidates)
                if chosen is None:
                    raise OptionMismatchError(
                        self._mismatch_message(name, candidates),
                        applied=list(confirmed),
                        reason=NO_SAME_USERNAME,
                    )
                if not await self._click_candidate(entry, chosen):
                    raise OptionMismatchError(
                        'Instagram 协作者候选点击失败：'
                        f'请求「{name}」',
                        applied=list(confirmed),
                        reason=SELECTION_FAILED,
                    )
                failure, readable = await self._wait_selected(entry, name)
                if failure is not None:
                    applied = list(confirmed)
                    if not applied and not readable:
                        # 回读本身不可读：区分“确认了 0 个”与“读不到”。
                        applied = None
                    raise OptionMismatchError(
                        self._readback_message(name, failure, candidates),
                        applied=applied,
                        reason=failure,
                    )
            except OptionMismatchError:
                self._confirmed = list(confirmed)
                raise
            confirmed.append(name)
        if not await self._close_panel(entry):
            self._confirmed = list(confirmed)
            raise OptionMismatchError(
                'Instagram 协作者面板未收起（Done/完成 后仍可见）',
                applied=list(confirmed),
                reason=LIST_NOT_COLLAPSED,
            )
        self._confirmed = list(confirmed)

    # -- panel ------------------------------------------------------------
    async def _done(self) -> Locator | None:
        """可见的 Done/完成 按钮；角色定位优先，兼容嵌套文本行。"""
        dialog = self._dialog()
        for label in DONE_LABELS:
            button = dialog.get_by_role('button', name=label, exact=True).first
            try:
                if await button.count() and await button.is_visible():
                    return button
            except Exception:
                continue
        return await row_for(dialog, DONE_LABELS)

    async def _open_panel(self, entry: Locator) -> None:
        """聚焦优先；只有面板仍未出现时才点击入口。"""
        if await self._done() is not None:
            return
        await entry.focus()
        if await self._wait_panel(open_=True):
            return
        await self._behavior().click(entry)
        await self._wait_panel(open_=True)

    async def _close_panel(self, entry: Locator) -> bool:
        done = await self._done()
        if done is None:
            return False
        self._check_budget()
        await self._behavior().click(done)
        return await self._wait_panel(open_=False)

    async def _wait_panel(self, *, open_: bool) -> bool:
        deadline = time.monotonic() + self._timeout(PANEL_TIMEOUT_MS) / 1000
        while True:
            is_open = await self._done() is not None
            if is_open is open_:
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_POLL_SECONDS)

    # -- search -----------------------------------------------------------
    async def _type_and_wait(
        self, entry: Locator, username: str
    ) -> list[CollaboratorCandidate]:
        """清空输入框、逐字符输入并等待候选；空列表时清空重输一次。"""
        humanizer = self._behavior()
        await entry.focus()
        for _attempt in range(2):
            await humanizer.press('ControlOrMeta+A')
            await humanizer.press('Backspace')
            await humanizer.type_text(username)
            candidates = await self._wait_for_candidates(entry)
            if candidates:
                return candidates
        return []

    async def _wait_for_candidates(
        self, entry: Locator
    ) -> list[CollaboratorCandidate]:
        deadline = time.monotonic() + self._timeout(SUGGESTION_TIMEOUT_MS) / 1000
        while True:
            candidates = await self._candidates(entry)
            if candidates:
                await self._page.wait_for_timeout(
                    self._timeout(SUGGESTION_SETTLE_MS)
                )
                return await self._candidates(entry) or candidates
            if time.monotonic() >= deadline:
                return []
            await asyncio.sleep(_POLL_SECONDS)

    async def _candidates(
        self, entry: Locator
    ) -> list[CollaboratorCandidate]:
        try:
            rows = await entry.evaluate(_ROWS_JS)
        except Exception:
            return []
        candidates: list[CollaboratorCandidate] = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            username = str(row.get('username') or '').strip()
            if not username:
                continue
            display = str(row.get('display') or '').strip() or None
            candidates.append(
                CollaboratorCandidate(
                    int(row.get('index', len(candidates))),
                    username,
                    display,
                    bool(row.get('checked')),
                )
            )
        return candidates

    async def _click_candidate(
        self, entry: Locator, candidate: CollaboratorCandidate
    ) -> bool:
        """给命中的行打一次性属性戳，再由共享 Humanizer 坐标点击。"""
        token = uuid4().hex
        try:
            stamped = await entry.evaluate(
                _ROWS_JS,
                {
                    'action': 'stamp',
                    'index': candidate.index,
                    'username': candidate.username,
                    'stamp': token,
                },
            )
        except Exception:
            return False
        if not stamped:
            return False
        node = self._page.locator(f'[{_ROW_ATTR}="{token}"]')
        try:
            if await node.count() != 1:
                return False
        except Exception:
            return False
        await self._behavior().click(node)
        return True

    @staticmethod
    def _exact_candidate(
        requested: str, candidates: list[CollaboratorCandidate]
    ) -> CollaboratorCandidate | None:
        """首个 username 首 token 规范化后完全相等的候选；不比较显示名。"""
        wanted = normalize_collaborator_name(requested)
        for candidate in candidates:
            if normalize_collaborator_name(candidate.username) == wanted:
                return candidate
        return None

    @staticmethod
    def _mismatch_message(
        requested: str, candidates: list[CollaboratorCandidate]
    ) -> str:
        reported = candidates[:MAX_REPORTED_CANDIDATES]
        observed = '、'.join(
            f'「{candidate.username}」'
            + (f'（{candidate.display}）' if candidate.display else '')
            for candidate in reported
        )
        if not observed:
            observed = '（未出现任何候选）'
        elif len(candidates) > MAX_REPORTED_CANDIDATES:
            observed += (
                f'（共 {len(candidates)} 条，仅列前 '
                f'{MAX_REPORTED_CANDIDATES} 条）'
            )
        return (
            'Instagram 协作者没有同 username 候选：'
            f'请求「{requested}」；观察到的候选：{observed}'
        )

    @staticmethod
    def _readback_message(
        requested: str, reason: str, candidates: list[CollaboratorCandidate]
    ) -> str:
        selected = next(
            (
                candidate
                for candidate in candidates
                if normalize_collaborator_name(candidate.username)
                == normalize_collaborator_name(requested)
            ),
            None,
        )
        detail = f'；候选「{selected.username}」' if selected else ''
        if reason == FINAL_EMPTY:
            return f'Instagram 协作者回读为空：请求「{requested}」{detail}'
        if reason == SELECTION_FAILED:
            return f'Instagram 协作者点击后未选中：请求「{requested}」{detail}'
        return f'Instagram 协作者回读不一致：请求「{requested}」{detail}'

    # -- readback ---------------------------------------------------------
    async def _is_selected(self, entry: Locator, username: str) -> bool:
        if self._image_count > 0:
            chips = await self._read_chips(entry)
            if chips is not None and username in chips:
                return True
        checked = await self._checked_usernames(entry)
        return bool(checked and username in checked)

    async def _wait_selected(
        self, entry: Locator, username: str
    ) -> tuple[str | None, bool]:
        """立即回读当前 username；返回 ``(失败原因或 None, 是否可读)``。"""
        deadline = time.monotonic() + self._timeout(READBACK_TIMEOUT_MS) / 1000
        if self._image_count > 0:
            chips: list[str] | None = None
            while True:
                chips = await self._read_chips(entry)
                if chips is not None and username in chips:
                    return None, True
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(_POLL_SECONDS)
            checked = await self._checked_usernames(entry)
            readable = chips is not None or checked is not None
            if checked is not None and username not in checked:
                return SELECTION_FAILED, readable
            if chips is None:
                return FINAL_MISMATCH, readable
            if not chips:
                return FINAL_EMPTY, readable
            return FINAL_MISMATCH, readable
        checked = None
        while True:
            checked = await self._checked_usernames(entry)
            if checked is not None and username in checked:
                return None, True
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(_POLL_SECONDS)
        readable = checked is not None
        return (SELECTION_FAILED if readable else FINAL_MISMATCH), readable

    async def _read_chips(self, entry: Locator) -> list[str] | None:
        try:
            chips = await entry.evaluate(_CHIPS_JS)
        except Exception:
            return None
        if not isinstance(chips, list):
            return None
        names: list[str] = []
        for chip in chips:
            name = normalize_collaborator_name(str(chip or '').strip())
            if name and name not in names:
                names.append(name)
        return names

    async def _checked_usernames(self, entry: Locator) -> list[str] | None:
        try:
            rows = await entry.evaluate(_ROWS_JS)
        except Exception:
            return None
        if not isinstance(rows, list):
            return None
        names: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get('checked'):
                continue
            name = normalize_collaborator_name(
                str(row.get('username') or '').strip()
            )
            if name and name not in names:
                names.append(name)
        return names
