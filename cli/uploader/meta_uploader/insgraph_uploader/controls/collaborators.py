"""Instagram 协作者控件：打开面板 → 精确匹配 username → 逐个回读 → Done。

实测结构（2026-11-24）：

- 创建弹窗内的入口是 ``input[name="creation-collaborator-input"]``；中文
  placeholder 为「添加合作者」，英文为 “Add collaborators”。
- 聚焦/点击入口后可先显示说明浮层；输入后出现勾选行与 ``Done`` / 「完成」。
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
否则取最近的兄弟面板。空查询时，入口旁的说明浮层内有与入口同名的可见图标。
Done/完成、候选行与 Reels checkbox 回读都限定在解析出的面板内。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

from patchright.async_api import Locator

from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.humanize import Humanizer

from ..options import (
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
    OptionUnsupportedError,
    clamp_wait,
)
from ._collaborator_dom import (
    DONE_LABELS,
    ENTRY_SELECTORS,
    _CHIPS_JS,
    _ENTRY_SELECTOR_UNION,
    _PANEL_ATTR,
    _PANEL_JS,
    _PANEL_OPEN_JS,
    _ROW_ATTR,
    _ROWS_JS,
    collaborator_count_summary,
    collaborator_limit_message,
    collaborator_restriction_message,
)
from ._rows import row_for

if TYPE_CHECKING:  # 运行时只需要 page 的鸭子类型，避免把 patchright 绑进注册表。
    from patchright.async_api import Page

    from uploader.publish_timeout import PublishTimeoutBudget

ENTRY_TIMEOUT_MS = 5_000
PANEL_TIMEOUT_MS = 5_000
SUGGESTION_TIMEOUT_MS = 10_000
# 点击后立即回读该 username；chip/checkbox 通常是同步渲染，给一个小窗口。
READBACK_TIMEOUT_MS = 3_000
_RENDER_STABLE_SECONDS = 0.2
MAX_REPORTED_CANDIDATES = 10
_POLL_SECONDS = 0.1


@dataclass(frozen=True, slots=True)
class CollaboratorCandidate:
    """一条联想候选：首个 token 是 username，其余是显示名。"""

    username: str
    display: str | None = None
    checked: bool = False


@dataclass(frozen=True, slots=True)
class _SelectionState:
    """某 username 在点击前对当前帖型证据的可见状态。"""

    confirmed: bool
    checked: bool


@dataclass(frozen=True, slots=True)
class _ReadbackResult:
    """单次逐个回读结果：``failure=None`` 表示确认选中。"""

    failure: str | None
    readable: bool


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
        self.last_detail: str | None = None

    def _behavior(self) -> Humanizer:
        if self._humanizer is None:
            self._humanizer = Humanizer(self._page)
        return self._humanizer

    @property
    def _uses_preview_chips(self) -> bool:
        """图文/轮播用预览 chip 回读；Reels 只能读面板 checkbox。"""
        return self._image_count > 0

    def _timeout(self, default_ms: int) -> int:
        return clamp_wait(self._budget, default_ms)

    def _probe_timeout(self, default_ms: int) -> int:
        """按剩余发布预算收紧单次探针超时；预算已耗尽时用短超时而不打断清理。"""
        try:
            return max(1, self._timeout(default_ms))
        except RuntimeError:
            return max(1, min(default_ms, 500))

    def _check_budget(self) -> None:
        if self._budget is not None:
            self._budget.check_pre_click()

    async def _eval(
        self,
        locator: Locator,
        script: str,
        arg: object = None,
        *,
        timeout_ms: int,
    ) -> object:
        """在已收紧的超时内执行 DOM 探针；已卸载节点立即失败不拖 30s。"""
        if await locator.count() == 0:
            raise LookupError('locator detached')
        wait_ms = max(1, int(timeout_ms))
        if arg is None:
            return await locator.evaluate(script, timeout=wait_ms)
        return await locator.evaluate(script, arg, timeout=wait_ms)

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

    @staticmethod
    async def _first_visible_entry(dialog: Locator) -> Locator | None:
        """返回 ``dialog`` 内第一个按优先级命中的可见协作者入口。"""
        for selector in ENTRY_SELECTORS:
            candidate = dialog.locator(selector).first
            try:
                if await candidate.count() and await candidate.is_visible():
                    return candidate
            except Exception:
                continue
        return None

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
        editors = await self._visible_dialogs(
            '[role="dialog"]:has([data-lexical-editor="true"])'
        )
        if editors:
            return editors[0]
        visible = await self._visible_dialogs('[role="dialog"]')
        for dialog in visible:
            if await self._first_visible_entry(dialog) is not None:
                return dialog
        return visible[0] if len(visible) == 1 else None

    async def _entry(self, timeout_ms: int) -> Locator | None:
        """返回创建弹窗内第一个可见入口；全部缺席返回 None。"""
        selector = f'[role="dialog"]:has({_ENTRY_SELECTOR_UNION})'
        deadline = time.monotonic() + max(int(timeout_ms), 0) / 1000
        while True:
            for dialog in await self._visible_dialogs(selector):
                candidate = await self._first_visible_entry(dialog)
                if candidate is not None:
                    return candidate
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(_POLL_SECONDS)

    async def _notice_texts(self, dialog: Locator) -> list[str]:
        """结构化读取弹窗内的可见提示（alert / aria-live），不扫全页文案。"""
        try:
            return await dialog.locator(
                '[role="alert"]:visible, '
                '[aria-live="assertive"]:visible, '
                '[aria-live="polite"]:visible'
            ).all_inner_texts()
        except Exception:
            return []

    async def _restriction(self, entry: Locator | None = None) -> str | None:
        composer = await self._composer(entry)
        if composer is None:
            return None
        for notice in await self._notice_texts(composer):
            reason = collaborator_restriction_message(notice)
            if reason:
                return reason
        return None

    async def _limit_refusal(
        self, entry: Locator, position: int, *, username: str | None = None
    ) -> str | None:
        """逐个回读失败时，判断页面是否明确以“上限”拒绝了第 N 个。

        只读创建弹窗/已解析面板内的结构化提示，以及入口上的 ``N people``
        摘要；没有明确拒绝信号时返回 ``None``，保留原回读原因
        （``selection_failed`` / ``final_mismatch``）。
        """
        bodies: list[str] = []
        composer = await self._composer(entry)
        if composer is not None:
            bodies.extend(await self._notice_texts(composer))
        panel = await self._panel(
            entry, timeout_ms=self._probe_timeout(READBACK_TIMEOUT_MS)
        )
        if panel is not None:
            bodies.extend(await self._notice_texts(panel))
        for body in dict.fromkeys(bodies):
            notice = collaborator_limit_message(body)
            if notice:
                return (
                    f'页面拒绝第 {position} 个协作者'
                    f'（可能达到该账号的协作者上限）：{notice}'
                )
        summary = ''
        try:
            if await entry.count():
                summary = str(
                    await entry.input_value(
                        timeout=self._probe_timeout(READBACK_TIMEOUT_MS)
                    )
                    or ''
                )
        except Exception:
            summary = ''
        shown = collaborator_count_summary(summary, query=username)
        if shown is not None and shown < position:
            return (
                f'页面显示已选 {shown} 人，第 {position} 个协作者未被接受'
                '（可能达到该账号的协作者上限）'
            )
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
        if self._uses_preview_chips:
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
        """中途失败：保留已确认前缀，按普通 mismatch 停止。

        不新增 reason 值：这里只说明“协作者没能在点击前完成”，由聚合错误
        文案带上原始错误和已确认 username。面板尚未打开时无法读取已选状态，
        ``applied=None``；已经逐个回读过的前缀按请求顺序保留。原始错误可能
        是发布预算耗尽、Playwright 定位/点击超时或面板动作失败，按原样附在
        文案里，不猜测未验证的原因。
        """
        names = '、'.join(f'「{name}」' for name in confirmed) or '无'
        return OptionMismatchError(
            f'Instagram 协作者在{stage}中止：{error}；'
            f'失败前已确认：{names}',
            applied=list(confirmed) if readable else None,
        )

    @staticmethod
    def _panel_not_open(
        error: BaseException | None = None,
    ) -> OptionMismatchError:
        """面板没能打开：统一按 ``list_not_collapsed`` 停止，尚未输入任何词。

        原始浏览器错误只写入异常文案（聚合错误/stderr），不写入结果 ``detail``。
        """
        if error is None:
            suffix = '（聚焦/点击入口后仍看不到协作者说明、候选列表或 Done/完成）'
        else:
            suffix = f'（聚焦/点击入口时失败：{error}）'
        return OptionMismatchError(
            f'Instagram 协作者面板未能打开{suffix}',
            applied=None,
            reason=LIST_NOT_COLLAPSED,
        )

    async def set(self, requested) -> None:
        """按请求顺序逐个选中；首个失败立即停止并保留已确认前缀。"""
        self.last_detail = None
        self._confirmed = None
        if isinstance(requested, str):
            requested = (requested,)
        # 入口前已由 options.py 完成一次去前导 @；此处只做大小写/空白统一，绝不再剥 @。
        names = [str(value).strip().lower() for value in requested]
        try:
            entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        except (LoginRequiredError, PublishResultUnknownError):
            raise
        except Exception as error:
            self._confirmed = None
            raise self._stop_with_prefix(
                [], '定位入口时', error, readable=False
            ) from error
        if entry is None:
            self._confirmed = None
            raise OptionUnsupportedError(
                'Instagram 协作者入口不可用',
                reason=ENTRY_MISSING,
            )
        try:
            opened = await self._open_panel(entry)
        except (LoginRequiredError, PublishResultUnknownError):
            raise
        except Exception as error:
            # 面板打开阶段的浏览器错误同样意味着“面板未打开”，按 spec 的
            # list_not_collapsed 记录；此时尚未输入任何 username。
            self._confirmed = None
            raise self._panel_not_open(error) from error
        if not opened:
            self._confirmed = None
            raise self._panel_not_open()
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
                state = await self._existing_selection_state(entry, name)
                if state.confirmed:
                    # 已有目标证据（图文 chip / Reels checkbox）：不再点击，避免取消勾选。
                    confirmed.append(name)
                    continue
                chosen: CollaboratorCandidate | None = None
                if not state.checked:
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
                    # 上一条搜索词可能把已预选行过滤掉了；搜出后若已勾选绝不反勾。
                    if not chosen.checked:
                        if not await self._click_candidate(entry, chosen):
                            raise OptionMismatchError(
                                'Instagram 协作者候选点击失败：'
                                f'请求「{name}」',
                                applied=list(confirmed),
                                reason=SELECTION_FAILED,
                            )
                readback = await self._wait_selected(entry, name)
                if readback.failure is not None:
                    failure = readback.failure
                    applied = list(confirmed)
                    if not applied and not readback.readable:
                        # 回读本身不可读：区分“确认了 0 个”与“读不到”。
                        applied = None
                    message = self._readback_message(name, failure, chosen)
                    # 不论回读判成 selection_failed 还是 final_mismatch，
                    # 页面明确写出上限/拒绝时都要带上 detail；只有
                    # selection_failed 才因“页面拒绝”升级为 final_mismatch。
                    detail = await self._limit_refusal(
                        entry, len(confirmed) + 1, username=name
                    )
                    if detail:
                        if failure == SELECTION_FAILED:
                            failure = FINAL_MISMATCH
                        message = f'{message}；{detail}'
                    raise OptionMismatchError(
                        message,
                        applied=applied,
                        reason=failure,
                        detail=detail,
                    )
            except OptionMismatchError:
                self._confirmed = list(confirmed)
                raise
            except (LoginRequiredError, PublishResultUnknownError):
                # 登录/结果未知必须按原类型上抛，不能折叠成普通 mismatch。
                raise
            except Exception as error:
                # 单个 username 处理中的任意浏览器错误（Playwright
                # Error/TimeoutError）或预算收紧都停止列表；不能丢掉失败前
                # 已确认的前缀，也不能让 generic 管线把 applied 记成 None。
                self._confirmed = list(confirmed)
                raise self._stop_with_prefix(
                    confirmed, f'添加「{name}」时', error
                ) from error
            confirmed.append(name)
        try:
            collapsed = await self._close_panel(entry)
        except (LoginRequiredError, PublishResultUnknownError):
            raise
        except Exception as error:
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
        if self._uses_preview_chips:
            await self._verify_preview(entry, confirmed, stable_seconds=0)
        self._confirmed = list(confirmed)

    # -- panel ------------------------------------------------------------
    async def _panel(
        self, entry: Locator, *, timeout_ms: int | None = None, stamp: str | None = None
    ) -> Locator | None:
        """解析当前活动的协作者面板并返回一次性定位器。

        真机面板是入口所在创建弹窗之外的兄弟 ``role="dialog"``；这里用入口
        元素做锚点，由 ``_PANEL_JS`` 按结构 + 几何选出面板，再用一次性属性
        戳定位刚选中的节点。面板不存在/已收起时返回 ``None``。
        """
        token = stamp or uuid4().hex
        wait_ms = (
            timeout_ms
            if timeout_ms is not None
            else self._probe_timeout(PANEL_TIMEOUT_MS)
        )
        try:
            stamped = await self._eval(
                entry, _PANEL_JS, token, timeout_ms=wait_ms
            )
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

    @staticmethod
    async def _done_in(panel: Locator) -> Locator | None:
        """在指定面板内定位可见的 Done/完成；角色定位优先，兼容嵌套文本行。"""
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

    async def _open_panel(self, entry: Locator) -> bool:
        """聚焦优先；只有面板仍未出现时才点击入口。返回是否确认打开。"""
        if await self._panel(entry) is not None:
            return True
        await entry.focus(timeout=max(1, self._timeout(PANEL_TIMEOUT_MS)))
        if await self._wait_panel_open(entry):
            return True
        humanizer = self._behavior()
        await humanizer.click(entry)
        return await self._wait_panel_open(entry)

    async def _close_panel(self, entry: Locator) -> bool:
        stamp = uuid4().hex
        panel = await self._panel(entry, stamp=stamp)
        if panel is None:
            return False
        done = await self._done_in(panel)
        if done is None:
            return False
        self._check_budget()
        humanizer = self._behavior()
        await humanizer.click(done)
        return await self._wait_panel_closed(entry, stamp)

    async def _wait_panel_open(self, entry: Locator) -> bool:
        window_ms = self._timeout(PANEL_TIMEOUT_MS)
        deadline = time.monotonic() + window_ms / 1000
        wait_ms = max(1, window_ms)
        while True:
            if await self._panel(entry, timeout_ms=wait_ms) is not None:
                return True
            if time.monotonic() >= deadline:
                return False
            await asyncio.sleep(_POLL_SECONDS)

    async def _wait_panel_closed(self, entry: Locator, stamp: str) -> bool:
        """等待已操作的面板收起，并检查入口旁是否又出现说明浮层。"""
        window_ms = self._timeout(PANEL_TIMEOUT_MS)
        deadline = time.monotonic() + window_ms / 1000
        closed_since = None
        while True:
            try:
                still_open = await self._eval(
                    entry, _PANEL_OPEN_JS, stamp,
                    timeout_ms=max(1, int((deadline - time.monotonic()) * 1000)),
                )
            except Exception:
                # 重绘期间可能暂时读不到入口，下一次探测再确认。
                still_open = True
            now = time.monotonic()
            if still_open:
                closed_since = None
            elif closed_since is None:
                closed_since = now
            elif now - closed_since >= _RENDER_STABLE_SECONDS:
                return True
            if now >= deadline:
                return False
            await asyncio.sleep(min(_POLL_SECONDS, deadline - now))

    # -- search -----------------------------------------------------------
    async def _type_and_wait(
        self, entry: Locator, username: str
    ) -> list[CollaboratorCandidate]:
        """清空输入框、逐字符输入并等待候选；空列表时清空重输一次。"""
        humanizer = self._behavior()
        await entry.focus(timeout=max(1, self._timeout(ENTRY_TIMEOUT_MS)))
        for _attempt in range(2):
            await humanizer.press('ControlOrMeta+A')
            await humanizer.press('Backspace')
            await humanizer.type_text(username)
            candidates = await self._wait_for_candidates(entry, username)
            if candidates:
                return candidates
        return []

    async def _wait_for_candidates(
        self, entry: Locator, username: str
    ) -> list[CollaboratorCandidate]:
        """结果更新期间可能保留上一批候选；只在精确命中时提前结束。"""
        deadline = time.monotonic() + self._timeout(SUGGESTION_TIMEOUT_MS) / 1000
        while True:
            candidates = await self._candidates(
                entry, timeout_ms=self._timeout(int(_POLL_SECONDS * 1000))
            )
            remaining = deadline - time.monotonic()
            if self._exact_candidate(username, candidates) is not None or remaining <= 0:
                return candidates
            await asyncio.sleep(min(_POLL_SECONDS, remaining))

    async def _candidates(
        self, entry: Locator, *, timeout_ms: int | None = None
    ) -> list[CollaboratorCandidate]:
        wait_ms = (
            timeout_ms
            if timeout_ms is not None
            else self._probe_timeout(SUGGESTION_TIMEOUT_MS)
        )
        try:
            rows = await self._eval(entry, _ROWS_JS, timeout_ms=wait_ms)
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
            stamped = await self._eval(
                entry,
                _ROWS_JS,
                {
                    'action': 'stamp',
                    'username': candidate.username,
                    'stamp': token,
                },
                timeout_ms=self._probe_timeout(SUGGESTION_TIMEOUT_MS),
            )
        except Exception:
            return False
        if stamped == 'already_checked':
            return True
        if not stamped:
            return False
        node = self._page.locator(f'[{_ROW_ATTR}="{token}"]')
        try:
            if await node.count() != 1:
                return False
        except Exception:
            return False
        humanizer = self._behavior()
        await humanizer.click(node)
        return True

    @staticmethod
    def _exact_candidate(
        requested: str, candidates: list[CollaboratorCandidate]
    ) -> CollaboratorCandidate | None:
        """首个 username 首 token 精确相等的候选；不再剥离 ``@``，也不比较显示名。"""
        wanted = str(requested).strip().lower()
        for candidate in candidates:
            if candidate.username.strip().lower() == wanted:
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
        requested: str,
        reason: str,
        chosen: CollaboratorCandidate | None,
    ) -> str:
        detail = f'；候选「{chosen.username}」' if chosen else ''
        if reason == SELECTION_FAILED:
            return f'Instagram 协作者点击后未选中：请求「{requested}」{detail}'
        return (
            f'Instagram 协作者回读不一致或读不到：请求「{requested}」{detail}'
        )

    # -- readback ---------------------------------------------------------
    async def verify_share_ready(self, requested: list[str]) -> None:
        """Share 就绪后核对图文标签，并确认入口旁没有重现说明浮层。"""
        entry = await self._entry(self._timeout(ENTRY_TIMEOUT_MS))
        if self._uses_preview_chips:
            await self._verify_preview(entry, requested, stable_seconds=_RENDER_STABLE_SECONDS)
        wait_ms = self._timeout(PANEL_TIMEOUT_MS)
        if entry is not None:
            try:
                if await self._eval(entry, _PANEL_OPEN_JS, timeout_ms=wait_ms) is False:
                    return
            except Exception:
                pass  # 无法从入口复核时，保留已逐个确认的用户名并停在 Share 前。
        raise OptionMismatchError(
            'Instagram 发布前未能确认协作者面板已收起',
            applied=list(requested), reason=LIST_NOT_COLLAPSED,
        )

    async def _verify_preview(
        self, entry: Locator | None, requested: list[str], *, stable_seconds: float
    ) -> None:
        deadline = time.monotonic() + self._timeout(READBACK_TIMEOUT_MS) / 1000
        expected = set(requested)
        matched_since = None
        while True:
            chips = await self._read_chips(
                entry, timeout_ms=self._timeout(int(_POLL_SECONDS * 1000))
            ) if entry is not None else None
            now = time.monotonic()
            if chips is not None and set(chips) == expected:
                if matched_since is None:
                    matched_since = now
                if now - matched_since >= stable_seconds:
                    return
            else:
                matched_since = None
            if entry is None or now >= deadline:
                break
            await asyncio.sleep(min(_POLL_SECONDS, deadline - now))
        raise OptionMismatchError(
            f'Instagram 协作者面板收起后预览标签不符：请求 {requested}，回读 {chips}',
            applied=None if chips is None else [name for name in requested if name in chips],
            reason=FINAL_MISMATCH,
        )

    async def _existing_selection_state(
        self, entry: Locator, username: str
    ) -> _SelectionState:
        """返回某 username 在当前帖型证据下是否已确认，以及面板是否已勾选。

        图文/轮播必须见到预览 chip 才算确认；若 checkbox 已勾选但无 chip，
        绝不再次点击（避免取消勾选），而是交由 ``_wait_selected`` 走 chip 回读。
        """
        if self._uses_preview_chips:
            chips = await self._read_chips(entry)
            if chips is not None and username in chips:
                return _SelectionState(confirmed=True, checked=True)
            checked = await self._checked_usernames(entry)
            return _SelectionState(
                confirmed=False, checked=bool(checked and username in checked)
            )
        checked = await self._checked_usernames(entry)
        is_checked = bool(checked and username in checked)
        return _SelectionState(confirmed=is_checked, checked=is_checked)

    async def _wait_selected(
        self, entry: Locator, username: str
    ) -> _ReadbackResult:
        """立即回读当前 username；返回失败原因（或 None）及通道是否可读。

        只使用 spec 表里的 ``selection_failed`` / ``final_mismatch``：
        checkbox 可读但未勾选是点击未生效；chip 已渲染却没有目标 chip，或
        回读通道不可读，是回读不一致。``final_empty`` 是地点控件的契约，
        协作者不新增该原因。
        """
        window_ms = self._timeout(READBACK_TIMEOUT_MS)
        deadline = time.monotonic() + window_ms / 1000
        wait_ms = max(1, window_ms)
        if self._uses_preview_chips:
            chips: list[str] | None = None
            while True:
                chips = await self._read_chips(entry, timeout_ms=wait_ms)
                if chips is not None and username in chips:
                    return _ReadbackResult(failure=None, readable=True)
                if time.monotonic() >= deadline:
                    break
                await asyncio.sleep(_POLL_SECONDS)
            checked = await self._checked_usernames(entry, timeout_ms=wait_ms)
            readable = chips is not None or checked is not None
            if checked is not None:
                if username not in checked:
                    return _ReadbackResult(SELECTION_FAILED, readable)
                # 面板 checkbox 已勾选，但预览 chip 仍未出现：回读证据不一致。
                return _ReadbackResult(FINAL_MISMATCH, readable)
            if chips:
                return _ReadbackResult(FINAL_MISMATCH, readable)
            # chip 可读但为空且面板读不到：按“点击后未选中”归类。
            return _ReadbackResult(
                FINAL_MISMATCH if chips is None else SELECTION_FAILED,
                readable,
            )
        checked = None
        while True:
            checked = await self._checked_usernames(entry, timeout_ms=wait_ms)
            if checked is not None and username in checked:
                return _ReadbackResult(failure=None, readable=True)
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(_POLL_SECONDS)
        readable = checked is not None
        return _ReadbackResult(
            SELECTION_FAILED if readable else FINAL_MISMATCH, readable
        )

    async def _read_chips(
        self, entry: Locator, *, timeout_ms: int | None = None
    ) -> list[str] | None:
        wait_ms = (
            timeout_ms
            if timeout_ms is not None
            else self._probe_timeout(READBACK_TIMEOUT_MS)
        )
        try:
            chips = await self._eval(entry, _CHIPS_JS, timeout_ms=wait_ms)
        except Exception:
            return None
        if not isinstance(chips, list):
            return None
        names: list[str] = []
        for chip in chips:
            name = str(chip or '').strip().lower()
            if name and name not in names:
                names.append(name)
        return names

    async def _checked_usernames(
        self, entry: Locator, *, timeout_ms: int | None = None
    ) -> list[str] | None:
        wait_ms = (
            timeout_ms
            if timeout_ms is not None
            else self._probe_timeout(READBACK_TIMEOUT_MS)
        )
        try:
            rows = await self._eval(entry, _ROWS_JS, timeout_ms=wait_ms)
        except Exception:
            return None
        if not isinstance(rows, list):
            return None
        names: list[str] = []
        for row in rows:
            if not isinstance(row, dict) or not row.get('checked'):
                continue
            name = str(row.get('username') or '').strip().lower()
            if name and name not in names:
                names.append(name)
        return names
