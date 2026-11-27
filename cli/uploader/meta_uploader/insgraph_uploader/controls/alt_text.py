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

from utils.dom import ElementUnusableError
from utils.humanize import Humanizer

from ..options import INELIGIBLE, MISSING, PRESENT, OptionMismatchError, alt_texts_match, clamp_wait
from ._rows import _wait_until, activate, press_enter, row_for

if TYPE_CHECKING:  # 运行时只导入 options 与行助手，避免把 Page 绑定成硬依赖。
    from patchright.async_api import Locator, Page

    from uploader.publish_timeout import PublishTimeoutBudget

# 入口文案：英文实测，中文按 spec §4.3.2 回退。
_ENTRY_LABELS = ('Accessibility', '无障碍', '替代文字')
# 输入框族：实测精确文案优先；精确文案缺失时才用大小写不敏感子串 + 中文回退。
# DOM 顺序即图片顺序，两个选择器内部都不重排。
_ALT_INPUT_EXACT = (
    'input[aria-label="Alt text"], input[placeholder="Alt text"], '
    'textarea[aria-label="Alt text"], textarea[placeholder="Alt text"]'
)
_ALT_INPUT_FALLBACK = (
    'input[aria-label*="alt" i], input[placeholder*="alt" i], '
    'textarea[aria-label*="alt" i], textarea[placeholder*="alt" i], '
    'input[aria-label*="替代文字"], input[placeholder*="替代文字"]'
)

_CLOSE_TIMEOUT_MS = 5_000
_INPUTS_TIMEOUT_MS = 2_000
_POLL_SECONDS = 0.05

_PANEL_STATE_JS = r"""() => {
    let hiddenPanelId;
    const linkedPanelState = (row, id) => {
        if (!id || /\s/.test(id)) return null;
        const dialog = row.closest('dialog, [role="dialog"]');
        const panel = row.ownerDocument.getElementById(id);
        if (panel && !dialog?.contains(panel)) return null;
        if (!panel || panel.closest('[hidden], [aria-hidden="true"]') ||
            !panel.checkVisibility({visibilityProperty: true})) {
            hiddenPanelId = id;
            return false;
        }
        // 常驻的空容器本身不能证明面板展开。
        if (hiddenPanelId === id || panel.getAttribute('aria-hidden') === 'false') return true;
        return null;
    };
    return row => {
        const expanded = row.getAttribute('aria-expanded');
        const aria = expanded === 'true' || expanded === 'false' ? expanded === 'true' : null;
        const visibleIcon = selector => [...row.querySelectorAll(selector)].some(
            icon => icon.checkVisibility({visibilityProperty: true})
        );
        const up = visibleIcon('[aria-label*="chevron" i][aria-label*="up" i], [aria-label*="向上"]');
        const down = visibleIcon('[aria-label*="chevron" i][aria-label*="down" i], [aria-label*="向下"]');
        const chevron = up === down ? null : up;
        const id = (row.getAttribute('aria-controls') || '').trim();
        const panel = linkedPanelState(row, id);
        const open = aria ?? chevron ?? panel;
        const coherent = [aria, chevron, panel].every(value => value === null || value === open);
        let visualCue = null;
        if (coherent && chevron !== null) visualCue = 'chevron';
        else if (coherent && panel !== null) visualCue = 'panel:' + id;
        return {open, visualCue};
    };
}"""

# 校验原生激活引起的展开；页面延迟切换时核对同一箭头或关联面板。
_WATCH_OPEN_JS = """(row, {selector, labels, verify}) => {
    const dialogSelector = 'dialog, [role="dialog"]';
    const dialog = row.closest(dialogSelector);
    const doc = row.ownerDocument;
    const state = (PANEL_STATE)();
    const visible = node => node.checkVisibility({visibilityProperty: true});
    const hasFields = current => [...current.closest(dialogSelector).querySelectorAll(selector)].some(visible);
    const isOpen = current => state(current).open ?? hasFields(current);
    if (!verify) return {isOpen, stop() {}};
    const currentRow = () => {
        if (row.isConnected && row.closest(dialogSelector)) return row;
        const scope = dialog.isConnected ? dialog : doc.getElementById(dialog.id);
        const dialogs = scope?.matches(dialogSelector) ? [scope] :
            [...doc.querySelectorAll(dialogSelector)].filter(visible);
        if (dialogs.length !== 1) return null;
        const buttons = [...dialogs[0].querySelectorAll('button, [role="button"]')].filter(visible);
        for (const attr of ['id', 'aria-controls']) {
            const value = row.getAttribute(attr);
            const matches = value ? buttons.filter(button => button.getAttribute(attr) === value) : [];
            if (matches.length === 1) return matches[0];
        }
        const matches = buttons.filter(button => [button, ...button.querySelectorAll('*')].some(
            node => visible(node) && labels.includes(node.innerText?.trim())
        ));
        return matches.length === 1 ? matches[0] : null;
    };
    let activation, frameRequest, frameTime, closedCue, reopened = false;
    const check = () => {
        const current = currentRow();
        if (current && isOpen(current)) reopened = true;
    };
    // 在页面的 rAF 处理前确认仍收起，在同一帧布局后检查结果。
    // 两次取样之间不运行 timer，帧前或帧后恢复的草稿不能确认保存。
    const afterLayout = new ResizeObserver(() => {
        afterLayout.disconnect();
        if (doc.timeline.currentTime === frameTime) check();
    });
    const observer = new MutationObserver(() => {
        if (activation.eventPhase !== Event.NONE && !reopened) check();
    });
    const before = event => {
        if (!event.isTrusted || (event.type !== 'click' && event.key !== 'Enter')) return;
        const current = currentRow();
        if (!current?.contains(event.target) || reopened) return;
        const {open, visualCue} = state(current);
        if (open || hasFields(current)) return;
        closedCue = visualCue;
        activation = event;
        // 弹窗自身也可能被替换，观察只在目标行收到原生激活后开始。
        observer.observe(doc, {subtree: true, childList: true, attributes: true});
        if (frameRequest == null) frameRequest = requestAnimationFrame(time => {
            frameRequest = null;
            const current = currentRow();
            if (reopened || !current || isOpen(current)) return;
            frameTime = time;
            afterLayout.observe(doc.documentElement);
        });
    };
    const events = ['keydown', 'keyup', 'click'];
    for (const type of events) doc.addEventListener(type, before, true);
    return {
        isOpen,
        verified() {
            if (reopened) return true;
            const current = currentRow();
            if (!closedCue || !current) return false;
            const {open, visualCue} = state(current);
            return open === true && visualCue === closedCue;
        },
        stop() {
            observer.disconnect();
            afterLayout.disconnect();
            if (frameRequest != null) cancelAnimationFrame(frameRequest);
            for (const type of events) doc.removeEventListener(type, before, true);
        }
    };
}""".replace("PANEL_STATE", _PANEL_STATE_JS)


class AltTextControl:
    """按图片顺序读写替代文字。发布时用 apply() 在同一次展开中检查并编辑。"""

    def __init__(
        self,
        page: 'Page',
        *,
        image_count: int,
        budget: 'PublishTimeoutBudget | None' = None,
        humanizer: Humanizer | None = None,
    ) -> None:
        self.page = page
        self.image_count = image_count
        self.budget = budget
        self._humanizer = humanizer

    def _behavior(self) -> Humanizer:
        """发布链路共享的 Humanizer；独立使用时按 page 自建（仍全部人类化）。"""
        if self._humanizer is None:
            self._humanizer = Humanizer(self.page)
        return self._humanizer

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
        """当前已渲染的 Alt text 输入框；折叠时为空（DOM 一并移除）。

        先认实测精确文案；精确文案完全缺席时才使用宽松子串回退，避免宽松
        选择器覆盖实测哨兵。
        """
        dialog = self._dialog()
        exact = dialog.locator(_ALT_INPUT_EXACT).filter(visible=True)
        if await exact.count():
            return exact
        return dialog.locator(_ALT_INPUT_FALLBACK).filter(visible=True)

    async def _has_inputs(self) -> bool:
        return bool(await (await self._inputs()).count())

    async def _ready_inputs(
        self, *, requested: object = None, readback: bool = False,
    ) -> 'tuple[Locator, list[str]]':
        """字段可能分批挂载，也可能先显示缓存值；最终比较取加载窗口末尾的快照。"""
        deadline = time.monotonic() + self._timeout(_INPUTS_TIMEOUT_MS) / 1000
        while True:
            inputs = await self._inputs()
            values = await inputs.evaluate_all('fields => fields.map(field => field.value)')
            remaining = deadline - time.monotonic()
            complete = len(values) >= self.image_count
            if complete and remaining > 0 and (readback or (
                requested is not None and alt_texts_match(requested, values)
            )):
                # 本次快照可能直接决定是否发布。保留当前展开状态，等保存值回填。
                await asyncio.sleep(remaining)
                continue
            if complete or remaining <= 0:
                if self.budget is not None:
                    self.budget.check_pre_click()
                return inputs, values
            await asyncio.sleep(min(_POLL_SECONDS, remaining))

    async def _expanded(self, entry: 'Locator') -> bool | None:
        return await entry.evaluate(f'row => ({_PANEL_STATE_JS})()(row).open', timeout=self._timeout(_CLOSE_TIMEOUT_MS))

    async def _ensure_open(
        self, entry: 'Locator | None' = None, *, require_activation: bool = False,
    ) -> tuple[bool, bool]:
        """确保折叠区展开；返回 ``(是否展开, 是否由本次调用展开)``。"""
        if entry is None:
            entry = await self._entry()
        if entry is None:
            return False, False

        watch = await entry.evaluate_handle(
            _WATCH_OPEN_JS,
            {'selector': f'{_ALT_INPUT_EXACT}, {_ALT_INPUT_FALLBACK}', 'labels': _ENTRY_LABELS,
             'verify': require_activation},
            timeout=self._timeout(_CLOSE_TIMEOUT_MS),
        )

        async def is_open():
            return await entry.evaluate(
                '(row, watch) => watch.isOpen(row)', watch, timeout=self._timeout(_CLOSE_TIMEOUT_MS)
            )

        try:
            if await is_open():
                return not require_activation, False
            opened = await activate(
                self.page, entry, is_open=is_open, humanizer=self._behavior(), budget=self.budget,
            )
            if opened and require_activation:
                # 内容与箭头可能分次更新。只等待同一次激活的确认，别再次切换折叠行。
                opened = await _wait_until(
                    lambda: watch.evaluate('watch => watch.verified()'),
                    self._timeout(_INPUTS_TIMEOUT_MS),
                )
            return opened, opened
        finally:
            try:
                await watch.evaluate('watch => watch.stop()')
            finally:
                await watch.dispose()

    async def _collapse(self) -> None:
        """再次激活折叠行直到输入框消失；收不起来抛 ``OptionMismatchError``。

        ``read()`` / ``set()`` 必须让折叠区回到收起状态，管线的下一次 ``read()``
        才是“关闭 → 重开”回读；展开着却收不起来时无法确认回读，按 mismatch 上报
        （退出 1），不再像旧实现那样静默放弃。
        """
        entry = await self._entry()
        if entry is None:
            raise OptionMismatchError('Instagram 无障碍折叠入口缺失，无法收起并核对替代文字')
        deadline = time.monotonic() + self._timeout(_CLOSE_TIMEOUT_MS) / 1000
        expanded = await self._expanded(entry)
        while expanded is None and not await self._has_inputs():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OptionMismatchError('Instagram 无法确认无障碍折叠区状态')
            await asyncio.sleep(min(_POLL_SECONDS, remaining))
            expanded = await self._expanded(entry)
        if expanded is not False and not await press_enter(self.page, entry):
            raise OptionMismatchError('Instagram 未能激活无障碍折叠行，无法核对替代文字')
        while True:
            state = await self._expanded(entry)
            if (state is False or (expanded is None and state is None)) and not await self._has_inputs():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise OptionMismatchError('Instagram 无障碍折叠区未能收起，无法核对替代文字')
            await asyncio.sleep(min(_POLL_SECONDS, remaining))

    async def _collapse_ignoring_failure(self) -> None:
        """异常路径上的尽力收起：不覆盖已经在传递的原始错误。"""
        with contextlib.suppress(Exception):
            await self._collapse()

    async def _open_available(self) -> tuple[str, bool]:
        entry = await self._entry()
        if entry is None:
            return MISSING, False
        if await self._entry_is_disabled(entry):
            return INELIGIBLE, False
        opened, by_us = await self._ensure_open(entry)
        return (PRESENT if opened else MISSING), by_us

    async def resolve(self) -> str:
        """单独探测时恢复折叠区原状。"""
        presence, by_us = await self._open_available()
        try:
            if presence == PRESENT:
                _, values = await self._ready_inputs()
                return PRESENT if values else MISSING
            return presence
        finally:
            if by_us:
                await self._collapse_ignoring_failure()

    @contextlib.asynccontextmanager
    async def _close_on_exit(self):
        try:
            yield
        except BaseException:
            await self._collapse_ignoring_failure()
            raise
        await self._collapse()

    async def apply(self, requested: object) -> tuple[str, list[str] | None]:
        """一次展开完成检查和填写，写入后重新展开核对保存的值。"""
        presence, _ = await self._open_available()
        if presence != PRESENT:
            return presence, None
        async with self._close_on_exit():
            inputs, current = await self._ready_inputs(requested=requested)
            if not current:
                return MISSING, None
            if alt_texts_match(requested, current):
                return PRESENT, current
            if self.budget is not None:
                self.budget.check_pre_click()
            await self._fill(requested, inputs, current)
        return PRESENT, await self.read(require_reopen=True)

    async def read(self, *, require_reopen: bool = False) -> list[str]:
        """打开折叠区回读逐张输入值，然后一律收起。

        无论进入时是否已展开，结束时都收起：回读必须是“关闭 → 重开”，否则读到
        的是同一会话里的就地状态。收不起来即按 mismatch 上报。
        """
        if require_reopen:
            opened, _ = await self._ensure_open(require_activation=True)
            if not opened:
                await self._collapse_ignoring_failure()
                raise OptionMismatchError('Instagram 未能确认无障碍折叠区重新展开')
        else:
            opened, _ = await self._ensure_open()
        if not opened:
            return []
        async with self._close_on_exit():
            _, values = await self._ready_inputs(readback=require_reopen)
            return values

    async def set(self, requested: object) -> None:
        """数量等于图片张数才逐张填写；数量不符不填写并报出已观察到的值。

        填写完成后一律收起折叠区，保证管线下一次 ``read()`` 是关闭 → 重开回读。
        """
        opened, _ = await self._ensure_open()
        if not opened:
            raise OptionMismatchError(
                f'Instagram 无障碍折叠区未展开：Alt text 输入框 0 个，'
                f'图片 {self.image_count} 张',
                applied=[],
            )
        async with self._close_on_exit():
            inputs, current = await self._ready_inputs()
            await self._fill(requested, inputs, current)

    async def _fill(self, requested: object, inputs: 'Locator', current: list[str]) -> None:
        if isinstance(requested, str):
            texts = [requested]
        else:
            texts = [str(text) for text in requested]  # type: ignore[union-attr]
        count = len(current)
        if count != self.image_count or count == 0:
            raise OptionMismatchError(
                f'Instagram Alt text 输入框 {count} 个，图片 {self.image_count} 张，'
                '无法按图片顺序逐张填写替代文字',
                applied=current,
            )
        if len(texts) != count:
            raise OptionMismatchError(
                f'Instagram 替代文字 {len(texts)} 条，Alt text 输入框 {count} 个，数量不符',
                applied=current,
            )
        behavior = self._behavior()
        for index, text in enumerate(texts):
            field = inputs.nth(index)
            await self._require_unique(field, index=index)
            await field.focus()
            await behavior.press('ControlOrMeta+A')
            await behavior.press('Delete')
            await behavior.type_text(text)
            # 输入框失焦才会把值写入页面状态。
            await field.evaluate('el => el.blur()')

    async def _require_unique(self, field: 'Locator', *, index: int) -> None:
        """每个文本点先收窄到 ``count() == 1``；多义直接硬错，不自动取首个。"""
        try:
            count = await field.count()
        except Exception as error:
            raise ElementUnusableError(
                what=f'Instagram 替代文字第 {index + 1} 张',
                role='editable',
                reason='probe-failed',
            ) from error
        if count != 1:
            raise ElementUnusableError(
                what=f'Instagram 替代文字第 {index + 1} 张',
                role='editable',
                reason=f'ambiguous:{count}',
            )
