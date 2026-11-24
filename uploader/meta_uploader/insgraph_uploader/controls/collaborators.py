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

真机 2026-11-24 补充：候选面板是**创建弹窗之外的兄弟 ``role="dialog"``**
（portal 定位在入口附近），不是 ``el.closest('[role="dialog"]')`` 的后代。
入口与资格提示锚定在**包含可见协作者入口的创建弹窗**；面板解析规则：创建
弹窗自身含可见的非 switch checkbox 行时用创建弹窗（既有受控 DOM 形态）；
否则在所有可见 ``role="dialog"`` 里取同样含可见非 switch checkbox 行或
可见按钮、且与协作者入口几何最近的兄弟弹窗。Done/完成、候选行与 Reels
checkbox 回读都限定在这个解析出的面板内。面板解析只检查 dialog/checkbox/
button 结构，不扫描全页文案，也不使用 hash 类名。
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from patchright.async_api import Locator

from utils.humanize import Humanizer

from ..options import (
    ACCOUNT_INELIGIBLE,
    CONTROL_DISABLED,
    ENTRY_MISSING,
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
# 的中英文回退。定位限定在包含可见入口的创建弹窗内；没有弹窗祖先的输入框
# 不参与解析，也不做全页 locator。
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
_PANEL_ATTR = 'data-instagram-collaborator-panel'
_ENTRY_SELECTOR_UNION = ', '.join(ENTRY_SELECTORS)
# 面板与 chip 的 JS 共用同一个空白归一化实现；只声明一次，避免两份漂移。
_JS_NORM_HELPER = (
    "  const norm = (value) => "
    "String(value || '').replace(/\\s+/g, ' ').trim();\n"
)

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

# 面板解析（真机 2026-11-24）：候选面板是创建弹窗之外的兄弟 role=dialog。
# 先认创建弹窗自身（既有受控 DOM 把结果列表嵌在弹窗内）；否则在所有可见
# role=dialog 中取“含可见非 switch checkbox 行或可见按钮”且与协作者入口
# 几何最近的弹窗。可见按钮让“查询无候选但面板仍有 Done”也能被识别。
_PANEL_HELPERS_JS = _JS_NORM_HELPER + """
  const visible = (node) => {
    if (!node || !node.getClientRects().length) return false;
    const style = getComputedStyle(node);
    return style.visibility !== 'hidden' && style.display !== 'none';
  };
  const composer = el.closest('[role="dialog"]');
  const rowForInput = (input, dialog) => {
    let row = input.closest('button, [role="button"], li, label');
    if (!row) row = input.parentElement;
    while (row && row !== dialog && !norm(row.innerText || row.textContent)) {
      row = row.parentElement;
    }
    return row && row !== dialog ? row : null;
  };
  const hasCandidateRows = (dialog) => {
    if (!dialog || !visible(dialog)) return false;
    for (const input of dialog.querySelectorAll('input[type="checkbox"]')) {
      if ((input.getAttribute('role') || '').toLowerCase() === 'switch') {
        continue;
      }
      if (!visible(input)) continue;
      const row = rowForInput(input, dialog);
      if (!row || !visible(row)) continue;
      if (!norm(row.innerText || row.textContent || '')) continue;
      return true;
    }
    return false;
  };
  const hasVisibleButton = (dialog) => {
    if (!dialog || !visible(dialog)) return false;
    for (const node of dialog.querySelectorAll('button, [role="button"]')) {
      if (!visible(node)) continue;
      if (norm(node.innerText || node.textContent || '')) return true;
    }
    return false;
  };
  const isPanelDialog = (dialog) =>
    hasCandidateRows(dialog) || hasVisibleButton(dialog);
  const entryRect = el.getBoundingClientRect();
  const distanceTo = (node) => {
    const rect = node.getBoundingClientRect();
    const dx = Math.max(
      0, Math.max(rect.left - entryRect.right, entryRect.left - rect.right));
    const dy = Math.max(
      0, Math.max(rect.top - entryRect.bottom, entryRect.top - rect.bottom));
    return Math.hypot(dx, dy);
  };
  const resolvePanel = () => {
    if (hasCandidateRows(composer)) return composer;
    let best = null;
    let bestDistance = Infinity;
    for (const dialog of document.querySelectorAll('[role="dialog"]')) {
      if (dialog === composer || !isPanelDialog(dialog)) continue;
      const distance = distanceTo(dialog);
      if (best === null || distance < bestDistance) {
        best = dialog;
        bestDistance = distance;
      }
    }
    return best;
  };
"""

# 候选行：从 checkbox 出发找最近的 role=button/button/li/label 行；只读取
# username 首 token。AI/评论开关是 role=switch，明确排除。
_ROWS_JS = """(el, action) => {""" + _PANEL_HELPERS_JS + """
  const panel = resolvePanel();
  if (!panel) return (action && action.action === 'list') ? [] : null;
  const seen = new Set();
  const rows = [];
  for (const input of panel.querySelectorAll('input[type="checkbox"]')) {
    if ((input.getAttribute('role') || '').toLowerCase() === 'switch') continue;
    if (!visible(input)) continue;
    const row = rowForInput(input, panel);
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

# 用一次性属性戳把解析出的面板交给 Playwright locator；Done/完成 必须落在
# 这个面板内（兄弟 portal 或创建弹窗），不能全页搜索。
_PANEL_JS = """(el, stamp) => {""" + _PANEL_HELPERS_JS + """
  const panel = resolvePanel();
  if (!panel) return false;
  panel.setAttribute('data-instagram-collaborator-panel', stamp);
  return true;
}"""

# 图文预览图 chip：带 Close/关闭 svg 的 role=button，最近的 span 祖先里
# 有一个 username span。只认这个结构，不读取输入框里的 “5 people” 摘要。
_CHIPS_JS = """(el) => {
  const dialog = el.closest('[role="dialog"]');
  if (!dialog) return [];
""" + _JS_NORM_HELPER + """
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

    def _timeout(self, default_ms: int) -> int:
        return clamp_wait(self._budget, default_ms)

    def _check_budget(self) -> None:
        if self._budget is not None:
            self._budget.check_pre_click()

    async def _visible_dialogs(self, selector: str) -> list[Locator]:
        """返回 ``selector`` 命中的可见 ``role=dialog``；异常时视为不可见。"""
        nodes = self._page.locator(selector)
        visible: list[Locator] = []
        try:
            count = await nodes.count()
        except Exception:
            return visible
        for index in range(count):
            node = nodes.nth(index)
            try:
                if await node.is_visible():
                    visible.append(node)
            except Exception:
                continue
        return visible

    async def _composer(self, entry: Locator | None = None) -> Locator | None:
        """包含协作者入口的可见创建弹窗。

        真机同一页面还有 Collaborators 面板这个兄弟 ``role=dialog``；资格
        提示只能读创建弹窗，不能读兄弟面板或全页文案。有入口时用其最近的
        ``role=dialog`` 祖先；入口缺失（例如账号不合格）时退回含配文编辑器
        的可见弹窗，再退回唯一可见弹窗。
        """
        if entry is not None:
            try:
                ancestor = entry.locator(
                    'xpath=ancestor::*[@role="dialog"][1]'
                )
                if await ancestor.count() and await ancestor.first.is_visible():
                    return ancestor.first
            except Exception:
                return None
            return None
        for dialog in await self._visible_dialogs(
            '[role="dialog"]:has([data-lexical-editor="true"])'
        ):
            return dialog
        for dialog in await self._visible_dialogs('[role="dialog"]'):
            for selector in ENTRY_SELECTORS:
                candidate = dialog.locator(selector).first
                try:
                    if await candidate.count() and await candidate.is_visible():
                        return dialog
                except Exception:
                    continue
        visible = await self._visible_dialogs('[role="dialog"]')
        return visible[0] if len(visible) == 1 else None

    async def _entry(self, timeout_ms: int) -> Locator | None:
        """返回创建弹窗内第一个可见入口；全部缺席返回 None。"""
        candidates = self._page.locator(
            f'[role="dialog"]:has({_ENTRY_SELECTOR_UNION})'
        )
        deadline = time.monotonic() + max(int(timeout_ms), 0) / 1000
        while True:
            try:
                count = await candidates.count()
            except Exception:
                count = 0
            for index in range(count):
                dialog = candidates.nth(index)
                try:
                    if not await dialog.is_visible():
                        continue
                except Exception:
                    continue
                for selector in ENTRY_SELECTORS:
                    candidate = dialog.locator(selector).first
                    try:
                        if (
                            await candidate.count()
                            and await candidate.is_visible()
                        ):
                            return candidate
                    except Exception:
                        continue
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(_POLL_SECONDS)

    async def _restriction(self, entry: Locator | None = None) -> str | None:
        composer = await self._composer(entry)
        if composer is None:
            return None
        try:
            notices = await composer.locator(
                '[role="alert"]:visible, '
                '[aria-live="assertive"]:visible, '
                '[aria-live="polite"]:visible'
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
        disabled = False
        if entry is not None:
            disabled = await entry.is_disabled()
            if not disabled:
                disabled = (
                    (await entry.get_attribute('aria-disabled') or '')
                    .strip()
                    .lower()
                    == 'true'
                )
        # 页面明确写出账号/地区不具备协作者资格时，即使入口仍可聚焦也要
        # 归因为 account_ineligible；单纯禁用且无说明才是 control_disabled。
        restriction = await self._restriction(entry)
        if restriction:
            self.last_detail = restriction
            return INELIGIBLE
        if entry is None:
            return MISSING
        if disabled:
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

    def _stop_with_prefix(
        self,
        confirmed: list[str],
        stage: str,
        error: BaseException,
        *,
        readable: bool = True,
    ) -> OptionMismatchError:
        """预算/面板等待在中途归零：保留已确认前缀，按普通 mismatch 停止。

        不新增 reason 值：这里只说明“协作者没能在点击前完成”，由聚合错误
        文案带上原始预算错误和已确认 username。面板尚未打开时无法读取已选
        状态，``applied=None``；已经逐个回读过的前缀按请求顺序保留。
        """
        names = '、'.join(f'「{name}」' for name in confirmed) or '无'
        return OptionMismatchError(
            f'Instagram 协作者在{stage}中止（可能发布预算耗尽）：{error}；'
            f'失败前已确认：{names}',
            applied=list(confirmed) if readable else None,
        )

    async def set(self, requested) -> None:
        """按请求顺序逐个选中；首个失败立即停止并保留已确认前缀。"""
        self.last_evidence = {}
        self.last_detail = None
        self._confirmed = None
        if isinstance(requested, str):
            requested = (requested,)
        names = [normalize_collaborator_name(value) for value in requested]
        try:
            entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        except RuntimeError as error:
            self._confirmed = None
            raise self._stop_with_prefix(
                [], '定位入口时', error, readable=False
            ) from error
        if entry is None:
            raise OptionMismatchError(
                'Instagram 协作者入口不可用',
                applied=[],
                reason=ENTRY_MISSING,
            )
        try:
            await self._open_panel(entry)
        except RuntimeError as error:
            self._confirmed = None
            raise self._stop_with_prefix(
                [], '打开面板时', error, readable=False
            ) from error
        confirmed: list[str] = []
        for name in names:
            try:
                self._check_budget()
            except RuntimeError as error:
                self._confirmed = list(confirmed)
                raise self._stop_with_prefix(
                    confirmed, f'添加「{name}」前', error
                ) from error
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
            except RuntimeError as error:
                # 单个 username 处理中预算被 clamp 收紧到零：同样停止列表，
                # 不能丢掉失败前已确认的前缀。
                self._confirmed = list(confirmed)
                raise self._stop_with_prefix(
                    confirmed, f'添加「{name}」时', error
                ) from error
            confirmed.append(name)
        try:
            collapsed = await self._close_panel(entry)
        except RuntimeError as error:
            self._confirmed = list(confirmed)
            raise self._stop_with_prefix(
                confirmed, '收起面板时', error
            ) from error
        if not collapsed:
            self._confirmed = list(confirmed)
            raise OptionMismatchError(
                'Instagram 协作者候选列表或面板未收起'
                '（Done/完成 后仍可见，或找不到 Done/完成）',
                applied=list(confirmed),
                reason=LIST_NOT_COLLAPSED,
            )
        self._confirmed = list(confirmed)

    # -- panel ------------------------------------------------------------
    async def _panel(self, entry: Locator) -> Locator | None:
        """解析当前活动的协作者面板并返回一次性定位器。

        真机面板是入口所在创建弹窗之外的兄弟 ``role="dialog"``；这里用入口
        元素做锚点，由 ``_PANEL_JS`` 按结构 + 几何选出面板，再用一次性属性
        戳定位刚选中的节点。面板不存在/已收起时返回 ``None``。
        """
        token = uuid4().hex
        try:
            stamped = await entry.evaluate(_PANEL_JS, token)
        except Exception:
            return None
        if not stamped:
            return None
        panel = self._page.locator(f'[{_PANEL_ATTR}="{token}"]')
        try:
            if await panel.count() != 1:
                return None
        except Exception:
            return None
        return panel

    async def _done(self, entry: Locator) -> Locator | None:
        """已解析面板内可见的 Done/完成；角色定位优先，兼容嵌套文本行。"""
        panel = await self._panel(entry)
        if panel is None:
            return None
        for label in DONE_LABELS:
            button = panel.get_by_role(
                'button', name=label, exact=True
            ).first
            try:
                if await button.count() and await button.is_visible():
                    return button
            except Exception:
                continue
        return await row_for(panel, DONE_LABELS)

    async def _open_panel(self, entry: Locator) -> None:
        """聚焦优先；只有面板仍未出现时才点击入口。"""
        if await self._done(entry) is not None:
            return
        await entry.focus()
        if await self._wait_panel(entry, open_=True):
            return
        await self._behavior().click(entry)
        await self._wait_panel(entry, open_=True)

    async def _close_panel(self, entry: Locator) -> bool:
        done = await self._done(entry)
        if done is None:
            return False
        self._check_budget()
        await self._behavior().click(done)
        return await self._wait_panel(entry, open_=False)

    async def _wait_panel(self, entry: Locator, *, open_: bool) -> bool:
        deadline = time.monotonic() + self._timeout(PANEL_TIMEOUT_MS) / 1000
        while True:
            is_open = await self._done(entry) is not None
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
        if reason == SELECTION_FAILED:
            return f'Instagram 协作者点击后未选中：请求「{requested}」{detail}'
        return (
            f'Instagram 协作者回读不一致或读不到：请求「{requested}」{detail}'
        )

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
        """立即回读当前 username；返回 ``(失败原因或 None, 是否可读)``。

        只使用 spec 表里的 ``selection_failed`` / ``final_mismatch``：
        checkbox 可读但未勾选是点击未生效；chip 已渲染却没有目标 chip，或
        回读通道不可读，是回读不一致。``final_empty`` 是地点控件的契约，
        协作者不新增该原因。
        """
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
            if checked is not None:
                if username not in checked:
                    return SELECTION_FAILED, readable
                # 面板 checkbox 已勾选，但预览 chip 仍未出现：回读证据不一致。
                return FINAL_MISMATCH, readable
            if chips:
                return FINAL_MISMATCH, readable
            # chip 可读但为空且面板读不到：按“点击后未选中”归类。
            return (FINAL_MISMATCH if chips is None else SELECTION_FAILED), readable
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
