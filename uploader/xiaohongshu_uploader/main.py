# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import inspect
import os
import re
import time
from datetime import datetime
from pathlib import Path

from patchright.async_api import BrowserContext
from patchright.async_api import Page
from patchright.async_api import Playwright
from patchright.async_api import async_playwright

from conf import LOCAL_CHROME_HEADLESS, LOCAL_CHROME_PATH
from uploader.base_video import BaseVideoUploader
from uploader.publish_timeout import PublishTimeoutBudget
from utils.base_social_media import set_init_script
from utils.blocked import BlockedKind
from utils.blocked import BlockedRules
from utils.blocked import classify as classify_block
from utils.browser_session import BrowserSession
from utils.browser_session import provider_label
from utils.dom import Candidate
from utils.dom import ElementMissingError
from utils.dom import Resolved
from utils.dom import wait_resolved
from utils.errors import LoginRequiredError
from utils.humanize import Humanizer
from utils.login_qrcode import build_login_qrcode_path
from utils.login_qrcode import decode_qrcode_from_path
from utils.login_qrcode import print_terminal_qrcode
from utils.login_qrcode import remove_qrcode_file
from utils.login_qrcode import save_data_url_image
from utils.log import xiaohongshu_logger

XHS_DEFAULT_CREATOR_BASE_URL = "https://creator.xiaohongshu.com"
XHS_CREATOR_BASE_URL_ENV = "SAU_XHS_CREATOR_BASE_URL"
XHS_LOGIN_BOX_SELECTOR = "div[class*='login-box']"
XHS_LOGIN_SWITCH_SELECTOR = "img.css-wemwzq"
# 登录态正向锚点：零文本、零中文（空状态实机）。发布按钮不是登录证据。
XHS_LOGIN_POSITIVE_SELECTORS = (
    "input.upload-input",
    'div.progress-div [class^="upload-btn-input"]',
    "div[class*='upload-content'] input",
)
XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE = "immediate"
XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED = "scheduled"
_XHS_PRE_PUBLISH_TIMEOUT_MESSAGE = (
    "小红书发布超时（15 分钟）：尚未点击发布，未发布任何内容。"
)
_XHS_PUBLISH_RESULT_UNKNOWN_MESSAGE = (
    "小红书发布结果未知：发布点击已发出，但未观察到成功页，"
    "也未命中登录/验证码跳转；帖子可能已经发布。\n"
    "禁止自动重发。请先到小红书创作服务平台 → 笔记管理，"
    "按标题与发布时间核对；已存在则不要重发，不存在才可人工重试。"
)

# 「操作频繁」「请稍后再试」属于可恢复的限流提示，保留原有重试逻辑，
# 由 15 分钟总预算兜底。


# 「添加内容类型声明」下拉里的选项。来源声明是二级菜单，其余是顶层选项。
XHS_CONTENT_TYPE_LABELS = {
    "fiction": "虚构演绎，仅供娱乐",
    "ai": "笔记含AI合成内容",
    "marketing": "内容包含营销广告",
}
XHS_SOURCE_DECLARATION_LABELS = {
    "self-shot": "自主拍摄",
    "repost": "来源转载",
}
XHS_CONTENT_TYPES = tuple(XHS_CONTENT_TYPE_LABELS) + tuple(
    XHS_SOURCE_DECLARATION_LABELS
)

XHS_LOGIN_CHECK_TIMEOUT_MS = 20_000
XHS_LOGIN_CHECK_SETTLE_MS = 3_000

# ---------------------------------------------------------------------------
# 发布链路的等待上限（毫秒）。这些常量只是「上限」：真正传给 Playwright 的
# timeout 一律经 PublishTimeoutBudget.clamp_ms() 收缩到 15 分钟 deadline 内，
# 因此本模块不允许出现裸的 timeout=<数字> 字面量（见 tests/test_xhs_budget.py）。
# ---------------------------------------------------------------------------
XHS_NAVIGATION_TIMEOUT_MS = 30_000
XHS_URL_GUARD_TIMEOUT_MS = 30_000
XHS_VIDEO_UPLOAD_INPUT_TIMEOUT_MS = 3_000
XHS_NOTE_UPLOAD_INPUT_TIMEOUT_MS = 30_000
XHS_NOTE_UPLOAD_READY_TIMEOUT_MS = 3_000
XHS_PUBLISH_OBSERVE_WINDOW_MS = 3_000
XHS_LOCATION_INPUT_TIMEOUT_MS = 30_000
XHS_LOCATION_DROPDOWN_TIMEOUT_MS = 3_000
XHS_LOCATION_OPTION_TIMEOUT_MS = 3_000
XHS_LOCATION_FALLBACK_TIMEOUT_MS = 2_000
XHS_TOPIC_MENU_TIMEOUT_MS = 6_000
XHS_TOPIC_ITEM_TIMEOUT_MS = 4_000
XHS_DECLARATION_SCROLL_TIMEOUT_MS = 5_000
XHS_DECLARATION_MODAL_TIMEOUT_MS = 8_000
XHS_DECLARATION_SUGGESTION_TIMEOUT_MS = 10_000
XHS_DECLARATION_CONFIRM_TIMEOUT_MS = 5_000
XHS_COVER_SCROLL_TIMEOUT_MS = 5_000
XHS_COVER_TAB_TIMEOUT_MS = 10_000
XHS_COVER_CONFIRM_TIMEOUT_MS = 10_000
XHS_COVER_MODAL_CLOSE_TIMEOUT_MS = 15_000

# 登录二维码流程的固定上限（不属于 15 分钟发布预算）。
XHS_LOGIN_PANEL_TIMEOUT_MS = 30_000
XHS_LOGIN_SWITCH_TIMEOUT_MS = 10_000
XHS_LOGIN_QRCODE_TIMEOUT_MS = 30_000

# ---------------------------------------------------------------------------
# 固定 UI 静置/轮询间隔。它们不是超时判据：只覆盖点击/输入后的界面动画与
# 网络往返，因此保留固定值，但必须是具名常量（不允许裸数字 sleep）。
# ---------------------------------------------------------------------------
XHS_SCHEDULE_SETTLE_MS = 1_000
XHS_LOCATION_INPUT_SETTLE_MS = 1_000
XHS_LOCATION_SUGGEST_SETTLE_MS = 2_000
XHS_LOCATION_OPTIONS_SETTLE_MS = 3_000
XHS_DECLARATION_SETTLE_MS = 800
XHS_DECLARATION_DATE_SETTLE_MS = 300
XHS_DECLARATION_FILL_SETTLE_MS = 500
XHS_DECLARATION_CONFIRM_SETTLE_MS = 1_000
XHS_COVER_OPEN_SETTLE_MS = 2_000
XHS_COVER_MODAL_SETTLE_MS = 3_000
XHS_COVER_RENDER_SETTLE_MS = 4_000
XHS_ESCAPE_SETTLE_MS = 500
XHS_LOGIN_SETTLE_MS = 3_000

# 轮询/重试间隔（秒）：全部经 PublishTimeoutBudget.clamp_seconds() 收缩。
XHS_VIDEO_UPLOAD_POLL_SECONDS = 2.0
XHS_NOTE_UPLOAD_POLL_SECONDS = 1.0
XHS_PUBLISH_RETRY_SECONDS = 0.5
XHS_PUBLISH_OBSERVE_POLL_SECONDS = 0.3
XHS_LOGIN_SUCCESS_SETTLE_SECONDS = 2.0

# ---------------------------------------------------------------------------
# 选择器基线（spec §3 U4，ticket 33）。每个环节一组候选，顺序固定：
#
#     structure（结构） → upstream（上游同款结构） → text-zh（中文文本，最后手段）
#
# 解析统一走 utils.dom 的 resolve / wait_resolved：每次命中打一条日志，
# 结构分支 debug，任何非结构分支额外 info（同一行，含环节/种类/选择器/URL）。
# 主链路零中文依赖：结构候选里不允许出现中文文案。
# ---------------------------------------------------------------------------
XHS_ANCHOR_TIMEOUT_MS = 5_000
XHS_PUBLISH_BUTTON_POINT = (0.65, 0.5)


def _zh_css(selector: str, factory=None) -> Candidate:
    """中文兜底候选：CSS 里含中文文案（placeholder / has-text / get_by_text）。"""
    return Candidate(
        selector,
        kind="text-zh",
        factory=factory or (lambda scope: scope.locator(selector)),
    )


# 1. 发布按钮（即时/定时共用同一元素）。只有新版 xhs-publish-btn；
#    ``is-publish`` / ``submit-disabled`` 的就绪谓词归 ticket 36（ARM），
#    这里只定义选择器与落点。
XHS_PUBLISH_BUTTON_SELECTOR = "xhs-publish-btn"
XHS_PUBLISH_BUTTON_CANDIDATES = (Candidate(XHS_PUBLISH_BUTTON_SELECTOR),)

# 2. 标题：div.d-input input 与旧 placeholder 选择器是同一个节点，中文只兜底。
XHS_TITLE_CANDIDATES = (
    Candidate("div.d-input input"),
    _zh_css('input[placeholder*="填写标题"]'),
)

# 3. 正文：tiptap 编辑区 → ProseMirror → 中文 placeholder 上溯 contenteditable。
XHS_BODY_CANDIDATES = (
    Candidate('div.tiptap[role="textbox"][contenteditable="true"]'),
    Candidate('div.ProseMirror[contenteditable="true"]', kind="upstream"),
    _zh_css(
        'p[data-placeholder*="输入正文描述"] ↑ [contenteditable="true"]',
        factory=lambda scope: scope.locator(
            'p[data-placeholder*="输入正文描述"]'
        ).locator("xpath=ancestor-or-self::*[@contenteditable='true'][1]"),
    ),
)

# 4/5. 文件输入：命中数必须为 1；多义且无法用容器收窄 → ElementUnusableError。
#      禁止 .first / .last 猜测（图文首张与视频共用同一个 upload-input）。
XHS_UPLOAD_INPUT_SELECTOR = "div.upload-content input.upload-input"
XHS_VIDEO_FILE_CANDIDATES = (
    Candidate(XHS_UPLOAD_INPUT_SELECTOR),
    Candidate('input[type="file"][accept*=".mp4"]', kind="upstream"),
    Candidate('input[type="file"][accept*="video"]', kind="upstream"),
)
XHS_NOTE_IMAGE_CANDIDATES = (
    Candidate(XHS_UPLOAD_INPUT_SELECTOR),
    Candidate('.img-list .top input[type="file"][multiple]', kind="upstream"),
)

# 6/7. 话题候选与回读：候选项本身是多义列表（一次 50 项），话题逻辑归 ticket 39；
#      回读必须限定编辑区（整页会多数一个）。
XHS_TOPIC_MENU_SELECTOR = "#creator-editor-topic-container"
XHS_TOPIC_ITEM_SELECTOR = "#creator-editor-topic-container .item"
XHS_TOPIC_ITEM_NAME_SELECTOR = "#creator-editor-topic-container .item .name"
XHS_TOPIC_READBACK_CANDIDATES = (
    Candidate('div.tiptap[role="textbox"] a[data-topic]'),
)

# 8. 定时开关：中文卡片过滤已删除，两个结构容器都是无文本锚点。
XHS_SCHEDULE_SWITCH_CANDIDATES = (
    Candidate(".post-time-wrapper .d-switch"),
    Candidate(".post-time-switch-container .d-switch", kind="upstream"),
)

# 9. 定时时间输入：双结构兜底，不设删除期限（两者各 1 实机样本）。
XHS_SCHEDULE_TIME_CANDIDATES = (
    Candidate(".d-datepicker-input-filter input.d-text"),
    Candidate(".date-picker-container input", kind="upstream"),
)

# 10. 原创开关：结构主候选 → 中文卡片（容器限定 + 精确）。
XHS_ORIGINAL_SWITCH_CANDIDATES = (
    Candidate(".original-wrapper .d-switch"),
    _zh_css(
        '.custom-switch-card:has-text("原创声明") .d-switch',
        factory=lambda scope: scope.locator(".custom-switch-card")
        .filter(has_text="原创声明")
        .locator(".d-switch"),
    ),
)

# 11. 原创确认弹窗：creator 弹窗 → role=dialog（两个账号各出现一次后再删）。
XHS_ORIGINAL_MODAL_CANDIDATES = (
    Candidate("div.d-modal.creator-modal-style"),
    _zh_css(
        "role=dialog:has-text('声明原创')",
        factory=lambda scope: scope.get_by_role("dialog").filter(
            has_text="声明原创"
        ),
    ),
)
XHS_ORIGINAL_CONFIRM_CANDIDATES = (
    Candidate("button.custom-button"),
    Candidate("声明原创", kind="text-zh", exact=True),
)

# 12. 内容类型声明：容器是 class 不是 id（旧 id 写法恒为 0 命中）。
#     触发器限定 .publish-container 内 text 的 [tabindex="1"]；选项限定下拉 + 精确文案。
XHS_DECLARATION_CONTAINER_SELECTOR = ".publish-container"
XHS_DECLARATION_TRIGGER_CANDIDATES = (
    _zh_css(
        '.publish-container [tabindex="1"]:has-text("添加内容类型声明")',
        factory=lambda scope: scope.locator(
            '.publish-container [tabindex="1"]'
        ).filter(has_text="添加内容类型声明"),
    ),
    Candidate("添加内容类型声明", kind="text-zh", exact=True),
)
XHS_DECLARATION_OPTION_SELECTOR = ".declaration-drop-down .d-option"
# 声明弹窗的「确认」按钮：结构 button.custom-button → 中文精确文案。
# 这里同时是转载声明里原先 JS 文本点击兜底的替代路径（禁止注入脚本点击）。
XHS_DECLARATION_CONFIRM_CANDIDATES = (
    Candidate("button.custom-button"),
    Candidate("确认", kind="text-zh", exact=True),
)


def _declaration_option_candidates(label: str) -> tuple[Candidate, ...]:
    """声明下拉选项：结构下拉 + 精确文案 → 裸文案点击。"""
    pattern = re.compile(rf"^{re.escape(label)}$")
    return (
        _zh_css(
            f'.declaration-drop-down .d-option:text-is("{label}")',
            factory=lambda scope: scope.locator(
                XHS_DECLARATION_OPTION_SELECTOR
            ).filter(has_text=pattern),
        ),
        Candidate(label, kind="text-zh", exact=True),
    )


# 13. 封面：入口 .cover-edit-entry（容器 .cover-edit-stack）→ 弹窗；
#     两个零命中的旧入口（upload-cover / cover-plugin-preview）已删。
XHS_COVER_ENTRY_SELECTOR = ".cover-edit-stack .cover-edit-entry"
XHS_COVER_MODAL_SELECTOR = (
    ".d-modal.cover-modal.creator-modal-style.main-cover-editor-modal"
)
XHS_COVER_ENTRY_CANDIDATES = (
    Candidate(XHS_COVER_ENTRY_SELECTOR),
    Candidate("编辑封面", kind="text-zh"),
    Candidate("设置封面", kind="text-zh"),
)
XHS_COVER_MODAL_CANDIDATES = (Candidate(XHS_COVER_MODAL_SELECTOR),)
XHS_COVER_TAB_CANDIDATES = (
    Candidate("上传封面", kind="text-zh", exact=True),
    Candidate("上传", kind="text-zh", exact=True),
)
XHS_COVER_FILE_INPUT_CANDIDATES = (
    Candidate('div.upload-wrapper input[type="file"][accept*="image"]'),
    Candidate('input[type="file"][accept*="image"]', kind="upstream"),
)
XHS_COVER_CONFIRM_CANDIDATES = (
    _zh_css(
        "div.d-modal-footer 确定",
        factory=lambda scope: scope.locator(
            "div.d-modal-footer"
        ).get_by_text("确定", exact=True),
    ),
    Candidate("完成", kind="text-zh", exact=True),
)

# 14. 登录二维码：切换图标沿用 XHS_LOGIN_SWITCH_SELECTOR，
#     二维码结构主候选 img.css-1lhmg90 → 文本容器内 img 兜底。
XHS_LOGIN_QRCODE_CANDIDATES = (
    Candidate("img.css-1lhmg90"),
    _zh_css(
        "APP扫一扫登录 → following-sibling img",
        factory=lambda scope: scope.locator(".login-box-container")
        .get_by_text("APP扫一扫登录")
        .filter(visible=True)
        .locator("xpath=..//following-sibling::div//img"),
    ),
)

# 17. 添加图片瓦片（第 2 张起）：存在性锚点先行；批量分发语义保持不变，
#     瓦片/file chooser 的上传接线归 ticket 38。
XHS_NOTE_ADD_IMAGE_TILE_SELECTOR = ".img-preview-area .entry"
XHS_NOTE_ADD_IMAGE_INPUT_CANDIDATES = (
    Candidate('.img-list .top input[type="file"][multiple]'),
)

# Golden local-mode browser options.  ``sau_commands/xiaohongshu.py`` passes the
# same values to ``browser_session`` in Multilogin mode, so the two paths cannot
# drift.  Geolocation is a local-only context option: the Multilogin branch must
# never call ``grant_permissions`` (spec §8).
XHS_LAUNCH_KWARGS = {"channel": "chromium"}
# 本地模式固定中文：创作后台的按钮/弹窗/placeholder 都是中文选择器。
# 托管模式不会应用 context_kwargs，Profile 界面必须由人工保持中文。
XHS_CONTEXT_KWARGS = {
    "permissions": ["geolocation"],
    "locale": "zh-CN",
    "extra_http_headers": {"Accept-Language": "zh-CN,zh;q=0.9"},
}
XHS_INIT_SCRIPT = True

# ---------------------------------------------------------------------------
# 登录页 / 人机验证页：唯一判据 + 退出 10 文案（spec §3 U9 B / §3 U10）。
#
# 判定器与模式无关；模式只决定文案。文案在 raise 点拼（不做模板体系），
# ``{App}`` 取公开的 ``provider_label``，不带 profile id。
# ---------------------------------------------------------------------------
XHS_BLOCKED_RULES = BlockedRules(
    login_paths=("/website-login", "/login"),
    verification_paths=("/website-login/captcha",),
    login_box_selector=XHS_LOGIN_BOX_SELECTOR,
)

_XHS_PUBLISH_ATTEMPTED_SUFFIX = "发布可能已发出：重跑前请先确认该笔记是否存在。"


async def classify_blocked(page: Page) -> BlockedKind | None:
    """小红书唯一的登录/人机验证判据（只读，C1/C2 共用）。"""
    return await classify_block(page, XHS_BLOCKED_RULES)


def _blocked_message(
    kind: BlockedKind, mode: str, *, publish_attempted: bool
) -> str:
    """四句文案之一；``publish_attempted`` 只在派发后追加提示。"""
    if kind == "verification":
        if mode == "local":
            message = "小红书要求人机验证：请在浏览器中完成验证后重试。"
        else:
            message = (
                f"小红书要求人机验证：请在 {provider_label(mode)} 中"
                "完成该 Profile 的验证后重试。"
            )
    elif mode == "local":
        message = (
            "小红书登录态无效：请运行 sau xiaohongshu login --account <账号名> "
            "重新扫码后重试。"
        )
    else:
        message = (
            f"小红书登录态无效：请在 {provider_label(mode)} 中登录该 Profile 后重试。"
        )

    if publish_attempted:
        message += _XHS_PUBLISH_ATTEMPTED_SUFFIX
    return message


async def _check_blocked(
    page: Page, mode: str, *, publish_attempted: bool
) -> None:
    """检查点：命中即 ``LoginRequiredError``（退出 10）。

    ``publish_attempted`` 由调用点现取 ``publish_clicked`` 变量，禁止硬编码。
    """
    kind = await classify_blocked(page)
    if kind is None:
        return
    raise LoginRequiredError(
        _blocked_message(kind, mode, publish_attempted=publish_attempted),
        reason=kind,
        publish_attempted=publish_attempted,
    )


def _build_xhs_creator_url(path: str) -> str:
    base_url = os.getenv(
        XHS_CREATOR_BASE_URL_ENV,
        XHS_DEFAULT_CREATOR_BASE_URL,
    ).strip().rstrip("/")
    if not base_url:
        base_url = XHS_DEFAULT_CREATOR_BASE_URL
    return f"{base_url}/{path.lstrip('/')}"


XHS_LOGIN_CHECK_URL = _build_xhs_creator_url(
    "/publish/publish?from=homepage&target=video"
)


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


async def _xhs_user_agent(browser) -> str:
    """返回不带 ``HeadlessChrome`` 标记的浏览器 UA。

    小红书创作者中心的 SSO 会直接拒绝无头 Chromium 默认 UA：即使 cookie
    完全有效，所有请求也会被重定向到 ``/login``（``service-ticket`` 返回
    704 您已登出）。这里读取浏览器真实 UA 并把 ``HeadlessChrome`` 换成
    ``Chrome``，让无头模式与有头模式使用同一套 UA。
    """
    probe_context = await browser.new_context()
    try:
        probe_page = await probe_context.new_page()
        user_agent = await probe_page.evaluate("() => navigator.userAgent")
    finally:
        await probe_context.close()
    return user_agent.replace("HeadlessChrome", "Chrome")


def _anchor_hit_line(step: str, resolved: Resolved, page: Page) -> str:
    """命中日志的唯一格式：环节 / 候选种类 / 选择器 / URL。"""
    url = str(getattr(page, "url", "") or "")
    return (
        f"锚点命中｜环节={step}｜种类={resolved.kind}"
        f"｜选择器={resolved.selector}｜URL={url}"
    )


async def _resolve_anchor(
    page: Page,
    step: str,
    candidates: tuple[Candidate, ...],
    *,
    role: str = "attached",
    timeout_ms: int = XHS_ANCHOR_TIMEOUT_MS,
    scope=None,
    budget: PublishTimeoutBudget | None = None,
    point: tuple[float, float] | None = None,
    publish_clicked: bool = False,
) -> Resolved:
    """按矩阵候选解析一个锚点，并打一条命中日志。

    ``scope`` 默认整页；弹窗内的锚点传弹窗 locator，保证选择器被容器限定。
    结构分支只打 ``debug``；非结构分支（upstream / text-zh）额外打一条
    ``info``，让真机日志一眼看出是否走了兜底。
    """
    target = page if scope is None else scope
    resolved = await wait_resolved(
        target,
        candidates,
        role=role,
        timeout_ms=timeout_ms,
        budget=budget,
        point=point,
        publish_clicked=publish_clicked,
    )

    line = _anchor_hit_line(step, resolved, page)
    xiaohongshu_logger.debug(_msg("🎯", line))
    if resolved.kind != "structure":
        xiaohongshu_logger.info(_msg("🎯", line))
    return resolved


async def _emit_qrcode_callback(qrcode_callback, payload: dict):
    if not qrcode_callback:
        return

    callback_result = qrcode_callback(payload)
    if inspect.isawaitable(callback_result):
        await callback_result


def _build_login_result(
    success: bool,
    status: str,
    message: str,
    account_file: str,
    qrcode: dict | None = None,
    current_url: str = "",
) -> dict:
    return {
        "success": success,
        "status": status,
        "message": message,
        "account_file": str(account_file),
        "qrcode": qrcode,
        "current_url": current_url,
    }


async def _open_xhs_qrcode_panel(
    page: Page, *, humanizer: Humanizer | None = None
) -> None:
    login_box = page.locator(XHS_LOGIN_BOX_SELECTOR).first
    await login_box.wait_for(state="visible", timeout=XHS_LOGIN_PANEL_TIMEOUT_MS)

    scan_text = login_box.locator("div:has-text('扫一扫')").first
    if await scan_text.count():
        return

    switch_img = login_box.locator(XHS_LOGIN_SWITCH_SELECTOR).first
    await switch_img.wait_for(state="visible", timeout=XHS_LOGIN_SWITCH_TIMEOUT_MS)
    if humanizer is None:
        humanizer = Humanizer(page)
    await humanizer.click(switch_img)
    await login_box.locator("div:has-text('扫一扫')").first.wait_for(
        state="visible", timeout=XHS_LOGIN_SWITCH_TIMEOUT_MS
    )


async def _find_xhs_qrcode_locator(page: Page, *, humanizer: Humanizer | None = None):
    await _open_xhs_qrcode_panel(page, humanizer=humanizer)

    resolved = await _resolve_anchor(
        page,
        "登录二维码",
        XHS_LOGIN_QRCODE_CANDIDATES,
        role="visible",
        timeout_ms=XHS_LOGIN_QRCODE_TIMEOUT_MS,
    )
    return resolved.locator


async def _extract_xhs_qrcode_src(
    page: Page, *, humanizer: Humanizer | None = None
) -> str:
    qrcode_img = await _find_xhs_qrcode_locator(page, humanizer=humanizer)
    await qrcode_img.wait_for(state="visible", timeout=XHS_LOGIN_QRCODE_TIMEOUT_MS)
    qrcode_src = await qrcode_img.get_attribute("src")
    if not qrcode_src:
        raise RuntimeError("未获取到小红书登录二维码地址")
    return qrcode_src


async def _save_xhs_qrcode(
    page: Page,
    account_file: str,
    previous_qrcode_path: Path | None = None,
    qrcode_callback=None,
) -> dict:
    humanizer = Humanizer(page)
    qrcode_src = await _extract_xhs_qrcode_src(page, humanizer=humanizer)
    qrcode_path = build_login_qrcode_path(account_file, suffix="xhs_login_qrcode")
    qrcode_img = await _find_xhs_qrcode_locator(page, humanizer=humanizer)

    if qrcode_src.startswith("data:image/"):
        save_data_url_image(qrcode_src, qrcode_path)
    else:
        qrcode_path.parent.mkdir(parents=True, exist_ok=True)
        await qrcode_img.screenshot(path=str(qrcode_path))

    if previous_qrcode_path and previous_qrcode_path != qrcode_path:
        if remove_qrcode_file(previous_qrcode_path):
            xiaohongshu_logger.info(_msg("🧹", f"临时二维码文件已清理: {previous_qrcode_path}"))

    xiaohongshu_logger.info(_msg("🖼️", f"二维码已经准备好啦，已保存到: {qrcode_path}"))
    qrcode_content = decode_qrcode_from_path(qrcode_path)
    if qrcode_content:
        print_terminal_qrcode(qrcode_content, qrcode_path, "小红书APP")
    else:
        xiaohongshu_logger.warning(_msg("😵", f"终端没法完整显示二维码，请打开 {qrcode_path} 扫码"))

    qrcode_info = {
        "image_path": str(qrcode_path),
        "image_data_url": qrcode_src,
    }
    await _emit_qrcode_callback(qrcode_callback, qrcode_info)
    return qrcode_info


async def _is_xhs_login_completed(page: Page) -> bool:
    if page.url.startswith(_build_xhs_creator_url("/login")):
        return False

    login_box = page.locator(XHS_LOGIN_BOX_SELECTOR).first
    if not await login_box.count():
        return True

    try:
        return not await login_box.is_visible()
    except Exception:
        return True


async def is_logged_in(context: BrowserContext) -> bool:
    """Return whether the Multilogin Profile is logged in to Xiaohongshu.

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.  A clear login
    page or visible login form returns ``False``; a missing login form alone is
    not positive proof, so the publish-page upload anchor must also exist.
    Network failures, 5xx responses, timeouts, unexpected redirects and an
    ambiguous page structure raise so the CLI can exit 1 instead of silently
    treating an outage as "logged out".

    Worst-case budget: 20s navigation + 3s settle, inside the 15-30s spec.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            XHS_LOGIN_CHECK_URL,
            wait_until="domcontentloaded",
            timeout=XHS_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"小红书登录状态检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(XHS_LOGIN_CHECK_SETTLE_MS)

        current_url = str(getattr(page, "url", "") or "")
        creator_base = _build_xhs_creator_url("/")
        if not current_url.startswith(creator_base):
            raise RuntimeError(
                "小红书登录状态检查失败：页面未停留在小红书创作者中心"
                f"（url={current_url or '<empty>'}）"
            )

        if not await _is_xhs_login_completed(page):
            return False

        for selector in XHS_LOGIN_POSITIVE_SELECTORS:
            if await page.locator(selector).count():
                return True

        raise RuntimeError(
            "小红书登录状态检查失败：未找到发布页上传入口（页面结构异常）"
        )
    finally:
        await page.close()


async def cookie_auth(account_file):
    if not os.path.exists(account_file):
        return False

    async with async_playwright() as playwright:
        if LOCAL_CHROME_PATH:
            browser = await playwright.chromium.launch(headless=True, executable_path=LOCAL_CHROME_PATH)
        else:
            browser = await playwright.chromium.launch(headless=True, channel="chromium")
        try:
            context = await browser.new_context(
                storage_state=account_file,
                user_agent=await _xhs_user_agent(browser),
                **XHS_CONTEXT_KWARGS,
            )
            context = await set_init_script(context)
            page = await context.new_page()
            await page.goto(
                _build_xhs_creator_url(
                    "/publish/publish?from=homepage&target=video"
                )
            )
            await Humanizer(page).after_navigate()
            await page.wait_for_timeout(XHS_LOGIN_SETTLE_MS)

            if page.url.startswith(_build_xhs_creator_url("/login")):
                xiaohongshu_logger.info(_msg("🥹", "cookie 已失效，得重新登录一下"))
                return False

            login_box = page.locator(XHS_LOGIN_BOX_SELECTOR).first
            if await login_box.count():
                try:
                    if await login_box.is_visible():
                        xiaohongshu_logger.info(_msg("🥹", "页面仍然停留在登录二维码页，按 cookie 失效处理"))
                        return False
                except Exception:
                    return False

            xiaohongshu_logger.success(_msg("🥳", "cookie 有效"))
            return True
        except Exception as exc:
            xiaohongshu_logger.warning(_msg("😵", f"cookie 校验时出错，按失效处理: {exc}"))
            return False
        finally:
            await browser.close()


async def xiaohongshu_setup(
    account_file,
    handle=False,
    return_detail=False,
    qrcode_callback=None,
    headless: bool = LOCAL_CHROME_HEADLESS,
):
    if not os.path.exists(account_file) or not await cookie_auth(account_file):
        if not handle:
            result = _build_login_result(False, "cookie_invalid", "cookie文件不存在或已失效", account_file)
            return result if return_detail else False
        xiaohongshu_logger.info(_msg("🥹", "cookie 失效了，准备打开浏览器重新登录"))
        result = await xiaohongshu_cookie_gen(
            account_file,
            qrcode_callback=qrcode_callback,
            headless=headless,
        )
        return result if return_detail else result["success"]

    result = _build_login_result(True, "cookie_valid", "cookie有效", account_file)
    return result if return_detail else True


async def xiaohongshu_cookie_gen(
    account_file,
    qrcode_callback=None,
    poll_interval: int = 3,
    max_checks: int = 100,
    headless: bool = LOCAL_CHROME_HEADLESS,
):
    if headless:
        xiaohongshu_logger.info(_msg("🖼️", "小红书登录将以无头模式运行，小人会输出终端二维码并保存本地二维码图片"))

    account_path = Path(account_file)
    account_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=headless, channel="chromium")
        context = await browser.new_context(
            user_agent=await _xhs_user_agent(browser),
            **XHS_CONTEXT_KWARGS,
        )
        context = await set_init_script(context)
        qrcode_path = None
        qrcode_info = None
        result = _build_login_result(False, "failed", "小红书登录失败", account_file)
        try:
            page = await context.new_page()
            await page.goto(_build_xhs_creator_url("/login"))
            await Humanizer(page).after_navigate()
            qrcode_info = await _save_xhs_qrcode(page, account_file, qrcode_callback=qrcode_callback)
            qrcode_path = Path(qrcode_info["image_path"])
            xiaohongshu_logger.info(_msg("🧍", "请扫码，小人正在耐心等待登录完成"))

            for _ in range(max_checks):
                if await _is_xhs_login_completed(page):
                    await asyncio.sleep(XHS_LOGIN_SUCCESS_SETTLE_SECONDS)
                    await context.storage_state(path=account_file)
                    if await cookie_auth(account_file):
                        xiaohongshu_logger.success(_msg("🥳", "小红书扫码登录成功，小人开心收工"))
                        result = _build_login_result(True, "success", "小红书扫码登录成功", account_file, qrcode_info, page.url)
                    else:
                        result = _build_login_result(
                            False,
                            "cookie_invalid",
                            "小红书扫码流程结束，但 cookie 校验失败",
                            account_file,
                            qrcode_info,
                            page.url,
                        )
                    return result

                await asyncio.sleep(poll_interval)

            result = _build_login_result(
                False,
                "timeout",
                "等待小红书扫码登录超时",
                account_file,
                qrcode_info,
                page.url,
            )
        except Exception as exc:
            result = _build_login_result(False, "failed", str(exc), account_file, current_url=page.url if "page" in locals() else "")
        finally:
            if remove_qrcode_file(qrcode_path):
                xiaohongshu_logger.info(_msg("🧹", f"临时二维码文件已清理: {qrcode_path}"))
            if not result["success"]:
                xiaohongshu_logger.error(_msg("😢", f"登录失败: {result['message']}"))
            await context.close()
            await browser.close()
        return result


class XiaoHongShuBaseUploader(BaseVideoUploader):
    def __init__(
        self,
        publish_date: datetime | int,
        account_file,
        publish_strategy: str = XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = False,
        headless: bool = LOCAL_CHROME_HEADLESS,
        original_declaration: bool | None = None,
        content_type: str | None = None,
        repost_source: str | None = None,
        shoot_location: str | None = None,
        shoot_date: str | None = None,
        no_publish: bool = False,
    ):
        self.publish_date = publish_date
        self.account_file = None if account_file is None else str(account_file)
        self.publish_strategy = publish_strategy
        self.debug = debug
        self.date_format = "%Y年%m月%d日 %H:%M"
        self.local_executable_path = LOCAL_CHROME_PATH
        self.headless = headless
        # 两项声明默认都不操作页面：None / "" 表示保持平台默认。
        self.original_declaration = original_declaration
        self.content_type = content_type
        self.repost_source = (repost_source or "").strip()
        self.shoot_location = (shoot_location or "").strip()
        self.shoot_date = (shoot_date or "").strip()
        self.no_publish = no_publish

    async def validate_base_args(self, *, check_cookie: bool = True):
        if check_cookie:
            if not os.path.exists(self.account_file):
                raise RuntimeError(f"cookie文件不存在，请先完成小红书登录: {self.account_file}")
            if not await cookie_auth(self.account_file):
                raise RuntimeError(f"cookie文件已失效，请先完成小红书登录: {self.account_file}")

        if self.publish_strategy not in {
            XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE,
            XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
        }:
            raise ValueError(f"不支持的发布策略: {self.publish_strategy}")

        if self.publish_strategy == XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED:
            self.publish_date = self.validate_publish_date(self.publish_date)
        else:
            self.publish_date = 0

    async def set_schedule_time_xiaohongshu(
        self,
        page: Page,
        publish_date: datetime,
        *,
        humanizer: Humanizer | None = None,
    ):
        humanizer = humanizer or self._humanizer(page)
        xiaohongshu_logger.info(_msg("🕒", f"小人准备设置定时发布时间: {publish_date.strftime(self.date_format)}"))
        switch = await _resolve_anchor(
            page,
            "定时开关",
            XHS_SCHEDULE_SWITCH_CANDIDATES,
            role="interactive",
            budget=self.publish_budget,
        )
        await humanizer.click(switch.locator)
        await self._settle(page, XHS_SCHEDULE_SETTLE_MS)
        publish_date_hour = publish_date.strftime("%Y-%m-%d %H:%M")
        time_input = await _resolve_anchor(
            page,
            "定时时间输入",
            XHS_SCHEDULE_TIME_CANDIDATES,
            role="editable",
            budget=self.publish_budget,
        )
        # 原生日期输入框点击会展开日历，这里只聚焦后逐字键入（回读归 ticket 40）。
        await time_input.locator.focus()
        await humanizer.type_text(str(publish_date_hour))
        await self._settle(page, XHS_SCHEDULE_SETTLE_MS)

    async def set_location(
        self, page: Page, location: str = "青岛市", *, humanizer: Humanizer | None = None
    ):
        if not location:
            return True

        humanizer = humanizer or self._humanizer(page)
        xiaohongshu_logger.info(_msg("📍", f"小人准备设置位置: {location}"))
        loc_ele = await page.wait_for_selector(
            'div.d-text.d-select-placeholder.d-text-ellipsis.d-text-nowrap',
            timeout=self._wait_ms(XHS_LOCATION_INPUT_TIMEOUT_MS),
        )
        await humanizer.click(loc_ele)
        await self._settle(page, XHS_LOCATION_INPUT_SETTLE_MS)
        await humanizer.type_text(location)
        dropdown_selector = 'div.d-popover.d-popover-default.d-dropdown.--size-min-width-large'
        await self._settle(page, XHS_LOCATION_SUGGEST_SETTLE_MS)
        try:
            await page.wait_for_selector(
                dropdown_selector,
                timeout=self._wait_ms(XHS_LOCATION_DROPDOWN_TIMEOUT_MS),
            )
        except Exception:
            xiaohongshu_logger.warning(_msg("😵", "位置下拉列表没按预期出现，小人继续按旧逻辑查找"))
        await self._settle(page, XHS_LOCATION_INPUT_SETTLE_MS)
        flexible_xpath = (
            f'//div[contains(@class, "d-popover") and contains(@class, "d-dropdown")]'
            f'//div[contains(@class, "d-options-wrapper")]'
            f'//div[contains(@class, "d-grid") and contains(@class, "d-options")]'
            f'//div[contains(@class, "name") and text()="{location}"]'
        )
        await self._settle(page, XHS_LOCATION_OPTIONS_SETTLE_MS)
        try:
            location_option = await page.wait_for_selector(
                flexible_xpath,
                timeout=self._wait_ms(XHS_LOCATION_OPTION_TIMEOUT_MS),
            )

            if not location_option:
                location_option = await page.wait_for_selector(
                    f'//div[contains(@class, "d-popover") and contains(@class, "d-dropdown")]'
                    f'//div[contains(@class, "d-options-wrapper")]'
                    f'//div[contains(@class, "d-grid") and contains(@class, "d-options")]'
                    f'/div[1]//div[contains(@class, "name") and text()="{location}"]',
                    timeout=self._wait_ms(XHS_LOCATION_FALLBACK_TIMEOUT_MS),
                )

            await location_option.scroll_into_view_if_needed()
            await humanizer.between_scroll()
            await humanizer.click(location_option)
            xiaohongshu_logger.success(_msg("🥳", f"位置已经设置成 {location}"))
            return True
        except Exception as e:
            xiaohongshu_logger.error(_msg("😢", f"设置位置失败: {e}"))
            try:
                all_options = await page.query_selector_all(
                    '//div[contains(@class, "d-popover") and contains(@class, "d-dropdown")]'
                    '//div[contains(@class, "d-options-wrapper")]'
                    '//div[contains(@class, "d-grid") and contains(@class, "d-options")]'
                    '/div'
                )
                xiaohongshu_logger.debug(_msg("🧍", f"位置下拉里一共找到 {len(all_options)} 个选项"))
                for i, option in enumerate(all_options[:3]):
                    option_text = await option.inner_text()
                    xiaohongshu_logger.debug(_msg("🧾", f"候选位置 {i + 1}: {option_text.strip()[:50]}"))
            except Exception as inner_e:
                xiaohongshu_logger.debug(_msg("😵", f"读取位置候选列表失败: {inner_e}"))
            return False

    async def fill_title(self, page: Page, *, humanizer: Humanizer | None = None) -> None:
        humanizer = humanizer or self._humanizer(page)
        title_container = await _resolve_anchor(
            page,
            "标题",
            XHS_TITLE_CANDIDATES,
            role="editable",
            budget=self.publish_budget,
        )
        # 标题框原本由 Playwright 的瞬间赋值隐式聚焦；改为显式聚焦后逐字键入。
        await title_container.locator.focus()
        await humanizer.type_text(self.title[:20])

    async def fill_desc(self, page: Page, *, humanizer: Humanizer | None = None) -> None:
        if not getattr(self, "desc", ""):
            return

        humanizer = humanizer or self._humanizer(page)
        desc = await _resolve_anchor(
            page,
            "正文",
            XHS_BODY_CANDIDATES,
            role="editable",
            budget=self.publish_budget,
        )
        await humanizer.click(desc.locator)
        await humanizer.press("Backspace")
        await humanizer.press("ControlOrMeta+A")
        await humanizer.press("Delete")
        await humanizer.type_text(self.desc)
        await humanizer.press("Enter")

    async def fill_tags(self, page: Page, *, humanizer: Humanizer | None = None) -> None:
        if not getattr(self, "tags", None):
            return

        humanizer = humanizer or self._humanizer(page)
        # 小红书标签上限为 10 个，超过会导致死循环卡住发布
        max_tags = 10
        if len(self.tags) > max_tags:
            xiaohongshu_logger.warning(
                _msg("🏷️", f"标签数量 {len(self.tags)} 超过小红书上限 {max_tags}，只取前 {max_tags} 个: {self.tags[:max_tags]}")
            )
            self.tags = self.tags[:max_tags]

        if not getattr(self, "desc", ""):
            desc = await _resolve_anchor(
                page,
                "正文",
                XHS_BODY_CANDIDATES,
                role="editable",
                budget=self.publish_budget,
            )
            await humanizer.click(desc.locator)

        for tag in self.tags:  # 循环处理所有 tags
            # 话题候选下拉框依赖小红书联想接口实时返回，网络抖动/无匹配时会等不到。
            # 标签是可选增强项：等不到候选框就跳过该标签继续，不让整条发布因此失败。
            try:
                await humanizer.type_text("#" + tag)
                await page.locator(XHS_TOPIC_MENU_SELECTOR).wait_for(
                    state="visible",
                    timeout=self._wait_ms(XHS_TOPIC_MENU_TIMEOUT_MS),
                )
                first_item = page.locator(XHS_TOPIC_ITEM_SELECTOR).first
                await first_item.wait_for(
                    state="visible",
                    timeout=self._wait_ms(XHS_TOPIC_ITEM_TIMEOUT_MS),
                )
                await humanizer.click(first_item)
            except Exception as exc:
                xiaohongshu_logger.warning(
                    _msg("🏷️", f"话题『{tag}』未出现候选，跳过该标签继续发布: {exc}")
                )
                # 清掉已键入但未成词的 "#tag" 文本，避免它残留进正文
                for _ in range(len("#" + tag)):
                    await humanizer.press("Backspace")
                continue

    async def fill_meta(self, page: Page, *, humanizer: Humanizer | None = None) -> None:
        humanizer = humanizer or self._humanizer(page)
        await self.fill_title(page, humanizer=humanizer)
        await self.fill_desc(page, humanizer=humanizer)
        await self.fill_tags(page, humanizer=humanizer)

    def start_publish_budget(self) -> PublishTimeoutBudget:
        self._publish_budget = PublishTimeoutBudget(
            "小红书",
            pre_click_message=_XHS_PRE_PUBLISH_TIMEOUT_MESSAGE,
            result_unknown_message=_XHS_PUBLISH_RESULT_UNKNOWN_MESSAGE,
        )
        return self._publish_budget

    def _wait_ms(self, default_ms: int, *, publish_clicked: bool = False) -> int:
        """把一次等待收缩到共享预算内；这是发布链路唯一的时间来源。

        点击前预算耗尽 -> ``budget.pre_click_error()``（退出 1）；
        点击后预算耗尽 -> 返回极小值，由发布循环统一映射为结果未知（退出 9）。
        """
        budget = self.publish_budget
        if publish_clicked:
            return budget.post_click_timeout_ms(default_ms)
        return budget.clamp_ms(default_ms)

    async def _sleep(
        self, seconds: float, *, publish_clicked: bool = False
    ) -> None:
        """轮询/重试间隔同样受预算约束，任何一次 sleep 都不会越过 deadline。"""
        budget = self.publish_budget
        if publish_clicked:
            await asyncio.sleep(max(0.0, min(seconds, budget.remaining_seconds())))
            return
        await asyncio.sleep(budget.clamp_seconds(seconds))

    async def _settle(self, page: Page, milliseconds: int) -> None:
        """固定 UI 静置（点击/输入后的界面动画），不是就绪判据。"""
        await page.wait_for_timeout(self._wait_ms(milliseconds))

    def _humanizer(self, page: Page) -> Humanizer:
        """发布链路的唯一行为层实例：指针位置与随机流保持连续。"""
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """行为层时延只吃预算上限，从不自己抛超时（ticket 15 §2）。

        与 ``_sleep`` 的区别只有一个：预算耗尽时收缩到 0 而不是抛
        ``pre_click_error``。真正的超时判据仍然只发生在锚点/轮询处。
        """
        remaining = max(0.0, self.publish_budget.remaining_seconds())
        await asyncio.sleep(min(seconds, remaining))

    async def _wait_publish_outcome(
        self, page: Page, *, timeout_ms: int | None = None
    ) -> str:
        """轮询成功页，返回 success 或 timeout。

        观察窗口本身也来自共享预算：点击后预算已经耗尽时窗口收缩到 1ms，
        由外层发布循环统一映射为 ``PublishResultUnknownError``（退出 9）。
        """
        if self.publish_budget.remaining_seconds() <= 0:
            # 点击后预算已耗尽：不再空转，交给发布循环映射为结果未知（退出 9）。
            return "timeout"
        window_ms = self._wait_ms(
            XHS_PUBLISH_OBSERVE_WINDOW_MS if timeout_ms is None else timeout_ms,
            publish_clicked=True,
        )
        deadline = time.monotonic() + window_ms / 1000
        while time.monotonic() < deadline:
            if "publish/success" in str(getattr(page, "url", "")):
                return "success"

            await self._sleep(
                min(
                    XHS_PUBLISH_OBSERVE_POLL_SECONDS,
                    max(0.0, deadline - time.monotonic()),
                ),
                publish_clicked=True,
            )

        return "timeout"

    async def apply_declarations(
        self, page: Page, *, humanizer: Humanizer | None = None
    ) -> None:
        """按需设置「原创声明」和「添加内容类型声明」。

        两项能力默认都不操作页面（保持平台默认）：
        - ``original_declaration`` 为 ``True``/``False`` 时才切换原创开关；
        - ``content_type`` 非空时才打开内容类型声明下拉。

        任一步失败只记 warning，不阻断发布。
        """
        if self.original_declaration is None and not self.content_type:
            return

        humanizer = humanizer or self._humanizer(page)
        if self.original_declaration is not None:
            await self._set_original_declaration(page, humanizer=humanizer)

        if self.content_type:
            await self._add_content_declaration(page, humanizer=humanizer)

    async def _set_original_declaration(
        self, page: Page, *, humanizer: Humanizer
    ) -> None:
        enabled = bool(self.original_declaration)
        try:
            switch = (
                await _resolve_anchor(
                    page,
                    "原创开关",
                    XHS_ORIGINAL_SWITCH_CANDIDATES,
                    role="interactive",
                    budget=self.publish_budget,
                )
            ).locator

            current = await self._switch_is_on(switch)
            if current is None:
                # 状态未知时只在“开启”场景点击；关闭场景默认页面已经是关的，
                # 盲目点击反而可能把开关打开。
                if enabled:
                    xiaohongshu_logger.warning(
                        _msg("⚠️", "无法确认原创声明开关状态，尝试点击开启")
                    )
                    await humanizer.click(switch)
                    await self._settle(page, XHS_DECLARATION_SETTLE_MS)
                    await self._confirm_original_declaration(
                        page, humanizer=humanizer
                    )
                else:
                    xiaohongshu_logger.warning(
                        _msg("⚠️", "无法确认原创声明开关状态，跳过关闭")
                    )
            elif current is not enabled:
                await humanizer.click(switch)
                await self._settle(page, XHS_DECLARATION_SETTLE_MS)
                if enabled:
                    await self._confirm_original_declaration(
                        page, humanizer=humanizer
                    )

            xiaohongshu_logger.success(
                _msg("🧾", f"原创声明已{'开启' if enabled else '关闭'}")
            )
        except Exception as exc:
            xiaohongshu_logger.warning(
                _msg("⚠️", f"设置原创声明失败，跳过继续发布: {exc}")
            )
            await self._press_escape(page)

    async def _add_content_declaration(
        self, page: Page, *, humanizer: Humanizer
    ) -> None:
        content_type = self.content_type
        label = XHS_CONTENT_TYPE_LABELS.get(content_type)
        source_label = XHS_SOURCE_DECLARATION_LABELS.get(content_type)
        if label is None and source_label is None:
            xiaohongshu_logger.warning(
                _msg("⚠️", f"未知的内容类型声明: {content_type}")
            )
            return

        try:
            await self._open_content_declaration_menu(page, humanizer=humanizer)
            if source_label:
                await self._click_declaration_option(
                    page, "内容来源声明", humanizer=humanizer
                )
                await self._settle(page, XHS_DECLARATION_SETTLE_MS)
                await self._click_declaration_option(
                    page, source_label, humanizer=humanizer
                )
            else:
                await self._click_declaration_option(page, label, humanizer=humanizer)
            await self._settle(page, XHS_DECLARATION_SETTLE_MS)

            if content_type == "self-shot":
                await self._fill_self_shot(page, humanizer=humanizer)
            elif content_type == "repost":
                await self._fill_repost_source(page, humanizer=humanizer)

            xiaohongshu_logger.success(
                _msg("🧾", f"内容类型声明已设置：{source_label or label}")
            )
        except Exception as exc:
            xiaohongshu_logger.warning(
                _msg("⚠️", f"设置内容类型声明失败，跳过继续发布: {exc}")
            )
            await self._press_escape(page)

    async def _open_content_declaration_menu(
        self, page: Page, *, humanizer: Humanizer
    ) -> None:
        trigger = await _resolve_anchor(
            page,
            "内容类型声明入口",
            XHS_DECLARATION_TRIGGER_CANDIDATES,
            role="visible",
            budget=self.publish_budget,
        )
        try:
            await trigger.locator.scroll_into_view_if_needed(
                timeout=self._wait_ms(XHS_DECLARATION_SCROLL_TIMEOUT_MS)
            )
        except Exception:
            pass
        else:
            await humanizer.between_scroll()
        await humanizer.click(trigger.locator)
        await self._settle(page, XHS_DECLARATION_SETTLE_MS)

    async def _click_declaration_option(
        self, page: Page, label: str, *, humanizer: Humanizer
    ) -> None:
        option = await _resolve_anchor(
            page,
            f"声明选项:{label}",
            _declaration_option_candidates(label),
            role="visible",
            budget=self.publish_budget,
        )
        await humanizer.click(option.locator)

    async def _fill_self_shot(self, page: Page, *, humanizer: Humanizer) -> None:
        """填写「自主拍摄」弹窗的拍摄地点和拍摄日期并确认。"""
        if not self.shoot_location or not self.shoot_date:
            raise RuntimeError("自主拍摄缺少拍摄地点或拍摄日期")

        modal = page.locator("[role='dialog'], .d-modal, .d-dialog").filter(
            has_text="拍摄地点"
        ).last
        await modal.wait_for(
            state="visible",
            timeout=self._wait_ms(XHS_DECLARATION_MODAL_TIMEOUT_MS),
        )

        # 1. 拍摄地点：Element UI autocomplete，输入关键词后点第一条建议。
        location = modal.locator('input[placeholder="下拉选择地点"]').first
        if not await location.count():
            raise RuntimeError("未找到「拍摄地点」输入框")
        await humanizer.click(location)
        await humanizer.type_text(self.shoot_location)

        suggestions = page.locator(".el-autocomplete-suggestion li").filter(
            has_text=self.shoot_location
        )
        if not await suggestions.count():
            suggestions = page.locator(".el-autocomplete-suggestion li").filter(
                has_text=re.compile(r"\S")
            )
        suggestion = suggestions.first
        await suggestion.wait_for(
            state="visible",
            timeout=self._wait_ms(XHS_DECLARATION_SUGGESTION_TIMEOUT_MS),
        )
        await humanizer.click(suggestion)
        await self._settle(page, XHS_DECLARATION_SETTLE_MS)

        # 2. 拍摄日期：日期选择器内置过滤输入框，输入 YYYY-MM-DD 后回车。
        date_input = modal.locator('input[placeholder="下拉选择日期"]').first
        if not await date_input.count():
            raise RuntimeError("未找到「拍摄日期」输入框")
        await humanizer.click(date_input)
        await self._settle(page, XHS_DECLARATION_CONFIRM_SETTLE_MS)

        date_filter = page.locator(".d-datepicker-input-filter input").first
        if not await date_filter.count():
            raise RuntimeError("未找到拍摄日期选择器")
        await date_filter.focus()
        await humanizer.type_text(self.shoot_date)
        await self._settle(page, XHS_DECLARATION_DATE_SETTLE_MS)
        await humanizer.press("Enter")
        await self._settle(page, XHS_DECLARATION_SETTLE_MS)

        # 3. 点弹窗内的「确认」。
        confirm = modal.get_by_role("button", name="确认").first
        if not await confirm.count():
            confirm = modal.get_by_text("确认", exact=True).first
        if not await confirm.count():
            raise RuntimeError("未找到自主拍摄「确认」按钮")
        await humanizer.click(confirm)
        await self._settle(page, XHS_DECLARATION_CONFIRM_SETTLE_MS)

    async def _fill_repost_source(self, page: Page, *, humanizer: Humanizer) -> None:
        if not self.repost_source:
            raise RuntimeError("来源转载缺少媒体名称")

        source_input = page.get_by_placeholder("请输入媒体名称").first
        await source_input.wait_for(
            state="visible",
            timeout=self._wait_ms(XHS_DECLARATION_MODAL_TIMEOUT_MS),
        )
        await humanizer.click(source_input)
        await humanizer.type_text(self.repost_source)
        await self._settle(page, XHS_DECLARATION_FILL_SETTLE_MS)

        confirm = page.get_by_role("button", name="确认").first
        try:
            await confirm.wait_for(
                state="visible",
                timeout=self._wait_ms(XHS_DECLARATION_CONFIRM_TIMEOUT_MS),
            )
            await humanizer.click(confirm)
        except Exception:
            # 弹窗按钮结构兜底：候选层解析（结构 → 中文精确），不再注入 JS 点击。
            resolved = await _resolve_anchor(
                page,
                "转载声明确认按钮",
                XHS_DECLARATION_CONFIRM_CANDIDATES,
                role="visible",
                budget=self.publish_budget,
            )
            await humanizer.click(resolved.locator)

    async def _confirm_original_declaration(
        self, page: Page, *, humanizer: Humanizer
    ) -> None:
        """确认「原创声明」弹窗：勾选须知并点击「声明原创」。

        点击原创开关后小红书会弹出权益说明和《原创声明须知》勾选框；
        不处理这个弹窗会一直挡住发布按钮。
        """
        try:
            modal = (
                await _resolve_anchor(
                    page,
                    "原创声明弹窗",
                    XHS_ORIGINAL_MODAL_CANDIDATES,
                    role="visible",
                    timeout_ms=XHS_DECLARATION_CONFIRM_TIMEOUT_MS,
                    budget=self.publish_budget,
                )
            ).locator
        except ElementMissingError:
            # 有些场景（例如取消原创）点击开关后不弹窗，直接生效。
            return

        checkbox = modal.locator(".d-checkbox").first
        if await checkbox.count():
            await humanizer.click(checkbox)
        else:
            agreement = modal.get_by_text("我已阅读并同意", exact=False).first
            if await agreement.count():
                await humanizer.click(agreement)
        await self._settle(page, XHS_DECLARATION_FILL_SETTLE_MS)

        button = await _resolve_anchor(
            page,
            "声明原创按钮",
            XHS_ORIGINAL_CONFIRM_CANDIDATES,
            role="visible",
            scope=modal,
            budget=self.publish_budget,
        )
        await humanizer.click(button.locator)
        await self._settle(page, XHS_DECLARATION_CONFIRM_SETTLE_MS)

    @staticmethod
    async def _switch_is_on(switch) -> bool | None:
        # 小红书 d-switch 的真实状态在 .d-switch-simulator 的 class 上，
        # 或者在内层 input[type=checkbox].checked 上。
        try:
            simulator = switch.locator(".d-switch-simulator").first
            if await simulator.count():
                classes = str(await simulator.get_attribute("class") or "")
                if "unchecked" in classes:
                    return False
                if "checked" in classes:
                    return True
        except Exception:
            pass

        try:
            checkbox = switch.locator("input[type='checkbox']").first
            if await checkbox.count():
                return await checkbox.is_checked()
        except Exception:
            pass

        for attr in ("aria-checked", "data-checked"):
            value = await switch.get_attribute(attr)
            if value is not None:
                return str(value).strip().lower() in {"true", "1", "on", "checked"}
        return None

    @staticmethod
    async def _press_escape(page: Page) -> None:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass


class XiaoHongShuVideo(XiaoHongShuBaseUploader):
    def __init__(
        self,
        title,
        file_path,
        tags,
        publish_date: datetime | int,
        account_file,
        thumbnail_path=None,
        desc: str | None = None,
        publish_strategy: str = XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = False,
        headless: bool = LOCAL_CHROME_HEADLESS,
        original_declaration: bool | None = None,
        content_type: str | None = None,
        repost_source: str | None = None,
        shoot_location: str | None = None,
        shoot_date: str | None = None,
        no_publish: bool = False,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
            original_declaration=original_declaration,
            content_type=content_type,
            repost_source=repost_source,
            shoot_location=shoot_location,
            shoot_date=shoot_date,
            no_publish=no_publish,
        )
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.thumbnail_path = thumbnail_path
        self.desc = desc or ""

    async def validate_upload_args(self, *, check_cookie: bool = True):
        await self.validate_base_args(check_cookie=check_cookie)
        if not self.title or not str(self.title).strip():
            raise ValueError("视频模式下，title 是必须的")

        self.file_path = str(self.validate_video_file(self.file_path))
        if self.thumbnail_path:
            self.thumbnail_path = str(self.validate_image_file(self.thumbnail_path))

    async def set_thumbnail(
        self,
        page: Page,
        thumbnail_path: str,
        *,
        humanizer: Humanizer | None = None,
    ):
        if not thumbnail_path:
            return

        humanizer = humanizer or self._humanizer(page)
        xiaohongshu_logger.info(_msg("🖼️", "小人准备设置封面"))

        # 封面设置为增强步骤：失败时记 warning 跳过、继续发布（用视频首帧兜底）。
        try:
            # 1. 封面入口 .cover-edit-entry（容器 .cover-edit-stack），文本仅兜底；
            #    打开封面弹窗。
            entry = await _resolve_anchor(
                page,
                "封面入口",
                XHS_COVER_ENTRY_CANDIDATES,
                role="visible",
                budget=self.publish_budget,
            )
            try:
                await entry.locator.scroll_into_view_if_needed(
                    timeout=self._wait_ms(XHS_COVER_SCROLL_TIMEOUT_MS)
                )
            except Exception:
                pass
            else:
                await humanizer.between_scroll()
            await self._settle(page, XHS_COVER_OPEN_SETTLE_MS)
            await humanizer.click(entry.locator)
            await self._settle(page, XHS_COVER_MODAL_SETTLE_MS)

            # 2. 封面弹窗：后续锚点全部限定在弹窗内。
            modal = await _resolve_anchor(
                page,
                "封面弹窗",
                XHS_COVER_MODAL_CANDIDATES,
                role="visible",
                timeout_ms=XHS_COVER_TAB_TIMEOUT_MS,
                budget=self.publish_budget,
            )

            # 3. 切换到「上传封面」tab（默认在「截取封面」）
            upload_tab = await _resolve_anchor(
                page,
                "封面-上传 tab",
                XHS_COVER_TAB_CANDIDATES,
                role="visible",
                scope=modal.locator,
                timeout_ms=XHS_COVER_TAB_TIMEOUT_MS,
                budget=self.publish_budget,
            )
            await humanizer.click(upload_tab.locator)
            await self._settle(page, XHS_COVER_OPEN_SETTLE_MS)

            # 4. 封面图片 file input：限定弹窗内，命中数必须为 1（禁止 .first/.last）。
            file_input = await _resolve_anchor(
                page,
                "封面文件输入",
                XHS_COVER_FILE_INPUT_CANDIDATES,
                role="attached",
                scope=modal.locator,
                budget=self.publish_budget,
            )
            await file_input.locator.set_input_files(thumbnail_path)
            # 等图片加载+裁剪渲染
            await self._settle(page, XHS_COVER_RENDER_SETTLE_MS)

            # 5. 点「确定」按钮（新界面为「完成」）
            confirm = await _resolve_anchor(
                page,
                "封面确定",
                XHS_COVER_CONFIRM_CANDIDATES,
                role="visible",
                scope=modal.locator,
                timeout_ms=XHS_COVER_CONFIRM_TIMEOUT_MS,
                budget=self.publish_budget,
            )
            await humanizer.click(confirm.locator)

            # 6. 等弹窗关闭
            try:
                await modal.locator.wait_for(
                    state="hidden",
                    timeout=self._wait_ms(XHS_COVER_MODAL_CLOSE_TIMEOUT_MS),
                )
            except Exception:
                pass
            xiaohongshu_logger.success(_msg("🥳", "封面已经设置完成"))
        except Exception as exc:
            xiaohongshu_logger.warning(_msg("🖼️", f"封面设置失败，跳过该步骤继续发布（用视频首帧）：{exc}"))
            try:
                await page.keyboard.press("Escape")
                await self._settle(page, XHS_ESCAPE_SETTLE_MS)
            except Exception:
                pass

    async def upload_video_content(self, page: Page, *, mode: str) -> None:
        budget = self.start_publish_budget()
        # 唯一的“是否已派发”事实源：检查点现取此变量，禁止按调用点硬编码。
        publish_clicked = False
        humanizer = self._humanizer(page)
        xiaohongshu_logger.info(_msg("🏃", f"小人开始搬运视频: {self.title}.mp4"))
        xiaohongshu_logger.info(_msg("🧭", "小人正在赶往视频发布页"))
        publish_url = _build_xhs_creator_url(
            "/publish/publish?from=homepage&target=video"
        )
        await page.goto(
            publish_url,
            wait_until="domcontentloaded",
            timeout=budget.clamp_ms(XHS_NAVIGATION_TIMEOUT_MS),
        )
        await humanizer.after_navigate()
        # C1：导航到发布页后立刻分类（本地/托管同一判据）。
        await _check_blocked(page, mode, publish_attempted=publish_clicked)
        await page.wait_for_url(
            publish_url,
            timeout=budget.clamp_ms(XHS_URL_GUARD_TIMEOUT_MS),
        )
        upload_input = await _resolve_anchor(
            page,
            "视频上传输入",
            XHS_VIDEO_FILE_CANDIDATES,
            role="attached",
            timeout_ms=XHS_VIDEO_UPLOAD_INPUT_TIMEOUT_MS,
            budget=budget,
        )
        await upload_input.locator.set_input_files(self.file_path)

        while True:
            # C2：每个可能超过 2s 的等待循环每轮查一次；放在 try 之外，
            # 命中登录/验证页时不会被下面的宽 except 吞掉。
            await _check_blocked(page, mode, publish_attempted=publish_clicked)
            budget.check_pre_click()
            # 超时值在 try 之外计算：预算耗尽不能被上传轮询的 except 吞掉。
            wait_ms = budget.clamp_ms(XHS_VIDEO_UPLOAD_INPUT_TIMEOUT_MS)
            try:
                upload_input = await page.wait_for_selector(
                    'input.upload-input', timeout=wait_ms
                )
                preview_new = await upload_input.query_selector(
                    'xpath=following-sibling::div[contains(@class, "preview-new")]')
                if preview_new:
                    # 获取整个预览区域的文本，更鲁棒地判断上传状态
                    all_text = await preview_new.inner_text()
                    upload_success = any(keyword in all_text for keyword in ['上传成功', '分辨率', '重新上传', '编辑封面', '已上传', '已选择', '100%'])
                    
                    if not upload_success:
                        # 检查是否有特定的状态码或百分比
                        stage_elements = await preview_new.query_selector_all('div.stage')
                        for stage in stage_elements:
                            text_content = await page.evaluate('(element) => element.textContent', stage)
                            if '上传成功' in text_content or '分辨率' in text_content:
                                upload_success = True
                                break
                    
                    if upload_success:
                        xiaohongshu_logger.success(_msg("🥳", "视频已经传完啦"))
                        break
                    
                    if self.debug:
                        normalized_text = all_text.strip().replace("\n", " ")
                        xiaohongshu_logger.debug(_msg("🧍", f"预览区域内容: {normalized_text}"))
                    xiaohongshu_logger.debug(_msg("🧍", "还没看到上传成功标识，小人继续等一会"))
                else:
                    # 尝试检查标题输入框是否已经出现，如果是，说明已经进入编辑状态
                    title_container = page.locator('input[placeholder*="填写标题"]')
                    if await title_container.count() > 0 and await title_container.is_visible():
                        xiaohongshu_logger.success(_msg("🥳", "虽然没看到预览区，但标题框出来了，小人继续"))
                        break
                    xiaohongshu_logger.debug(_msg("🧍", "还没拿到预览区域，小人继续等一会"))
            except Exception as e:
                xiaohongshu_logger.debug(_msg("😵", f"上传状态还没稳定下来，小人继续观察: {e}"))
            await asyncio.sleep(budget.clamp_seconds(XHS_VIDEO_UPLOAD_POLL_SECONDS))

        xiaohongshu_logger.info(_msg("✍️", "小人开始填标题、描述和话题"))
        await self.fill_meta(page, humanizer=humanizer)

        await self.set_thumbnail(page, self.thumbnail_path, humanizer=humanizer)

        # await self.set_location(page, "青岛市")

        await self.apply_declarations(page, humanizer=humanizer)

        if self.publish_strategy == XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time_xiaohongshu(
                page, self.publish_date, humanizer=humanizer
            )

        if self.no_publish:
            xiaohongshu_logger.success(_msg("🧪", "已设置完成，--no-publish 跳过发布"))
            return

        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=xiaohongshu_logger,
            label="小红书发布",
        )

        while True:
            # 退出 1（点击前）/ 9（点击后）两个出口只由预算模块产生。
            if budget.remaining_seconds() <= 0:
                raise budget.timeout_error(publish_clicked)

            try:
                if not publish_clicked:
                    # 即时/定时共用同一个 xhs-publish-btn；is-publish /
                    # submit-disabled 的就绪谓词归 ticket 36（ARM）。
                    publish_button = await _resolve_anchor(
                        page,
                        "发布按钮",
                        XHS_PUBLISH_BUTTON_CANDIDATES,
                        role="interactive",
                        budget=budget,
                        point=XHS_PUBLISH_BUTTON_POINT,
                        publish_clicked=publish_clicked,
                    )
                    await humanizer.before_submit()
                    await humanizer.click(
                        publish_button.locator,
                        point=XHS_PUBLISH_BUTTON_POINT,
                    )
                    publish_clicked = True
                outcome = await self._wait_publish_outcome(page)
                if outcome == "success":
                    xiaohongshu_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))
                    break
                xiaohongshu_logger.info(_msg("🏃", "小人正在冲刺发布视频"))
            except Exception:
                xiaohongshu_logger.info(_msg("🏃", "小人正在冲刺发布视频"))
                if self.debug:
                    await page.screenshot(full_page=True)
            await self._sleep(
                XHS_PUBLISH_RETRY_SECONDS, publish_clicked=publish_clicked
            )

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.validate_upload_args(check_cookie=False)
            await self.upload_in(session)
            return

        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")

        xiaohongshu_logger.info(_msg("🧍", "小人先检查 cookie、视频文件、封面和发布时间"))
        await self.validate_upload_args()
        xiaohongshu_logger.info(_msg("🥳", "上传前检查通过"))
        browser = await playwright.chromium.launch(headless=self.headless, **XHS_LAUNCH_KWARGS)
        context = await browser.new_context(
            storage_state=self.account_file,
            user_agent=await _xhs_user_agent(browser),
            **XHS_CONTEXT_KWARGS,
        )
        context = await set_init_script(context)

        try:
            await self.upload_in(
                BrowserSession(browser=browser, context=context, mode="local")
            )
            await context.storage_state(path=self.account_file)
            xiaohongshu_logger.success(_msg("🥳", "cookie 更新完毕"))
        finally:
            await context.close()
            await browser.close()

    async def upload_in(self, session: BrowserSession) -> None:
        page = await session.context.new_page()
        await self.upload_video_content(page, mode=session.mode)

    async def xiaohongshu_upload_video(self, *, session: BrowserSession | None = None):
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)

    async def main(self):
        await self.xiaohongshu_upload_video()


class XiaoHongShuNote(XiaoHongShuBaseUploader):
    def __init__(
        self,
        image_paths,
        note,
        tags,
        publish_date: datetime | int,
        account_file,
        title: str | None = None,
        desc: str | None = None,
        publish_strategy: str = XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE,
        debug: bool = False,
        headless: bool = LOCAL_CHROME_HEADLESS,
        original_declaration: bool | None = None,
        content_type: str | None = None,
        repost_source: str | None = None,
        shoot_location: str | None = None,
        shoot_date: str | None = None,
        no_publish: bool = False,
    ):
        super().__init__(
            publish_date=publish_date,
            account_file=account_file,
            publish_strategy=publish_strategy,
            debug=debug,
            headless=headless,
            original_declaration=original_declaration,
            content_type=content_type,
            repost_source=repost_source,
            shoot_location=shoot_location,
            shoot_date=shoot_date,
            no_publish=no_publish,
        )
        self.image_paths = image_paths
        self.note = note or ""
        self.tags = tags or []
        self.desc = desc if desc is not None else self.note
        self.title = title or ((self.desc or self.note)[:20] if (self.desc or self.note) else "")

    async def validate_upload_args(self, *, check_cookie: bool = True):
        await self.validate_base_args(check_cookie=check_cookie)
        if not self.image_paths:
            raise ValueError("图文模式下，图片是必须的")
        if not self.title or not str(self.title).strip():
            raise ValueError("图文模式下，title 是必须的")

        if isinstance(self.image_paths, (str, Path)):
            self.image_paths = [self.image_paths]

        normalized_image_paths = []
        for image_path in self.image_paths:
            normalized_image_paths.append(str(self.validate_image_file(image_path)))
        self.image_paths = normalized_image_paths

    async def upload_note_content(self, page: Page, *, mode: str) -> None:
        budget = self.start_publish_budget()
        # 唯一的“是否已派发”事实源：检查点现取此变量，禁止按调用点硬编码。
        publish_clicked = False
        humanizer = self._humanizer(page)
        xiaohongshu_logger.info(_msg("🏃", f"小人开始搬运图文，共 {len(self.image_paths)} 张图片"))
        xiaohongshu_logger.info(_msg("🧭", "小人正在赶往图文发布页"))
        publish_url = _build_xhs_creator_url(
            "/publish/publish?from=homepage&target=image"
        )
        await page.goto(
            publish_url,
            wait_until="domcontentloaded",
            timeout=budget.clamp_ms(XHS_NAVIGATION_TIMEOUT_MS),
        )
        await humanizer.after_navigate()
        # C1：导航到发布页后立刻分类（本地/托管同一判据）。
        await _check_blocked(page, mode, publish_attempted=publish_clicked)
        await page.wait_for_url(
            publish_url,
            timeout=budget.clamp_ms(XHS_URL_GUARD_TIMEOUT_MS),
        )

        upload_input = await _resolve_anchor(
            page,
            "图文上传输入",
            XHS_NOTE_IMAGE_CANDIDATES,
            role="attached",
            timeout_ms=XHS_NOTE_UPLOAD_INPUT_TIMEOUT_MS,
            budget=budget,
        )
        xiaohongshu_logger.info(_msg("📤", "小人正在上传图片"))
        await upload_input.locator.set_input_files(self.image_paths)

        while True:
            # C2：每轮先分类；放在 try 之外，命中不会被宽 except 吞掉。
            await _check_blocked(page, mode, publish_attempted=publish_clicked)
            budget.check_pre_click()
            # 超时值在 try 之外计算：预算耗尽不能被上传轮询的 except 吞掉。
            ready_ms = budget.clamp_ms(XHS_NOTE_UPLOAD_READY_TIMEOUT_MS)
            try:
                title_container = page.locator('input[placeholder*="填写标题"]').first
                await title_container.wait_for(state="visible", timeout=ready_ms)
                xiaohongshu_logger.success(_msg("🥳", "图文素材已经传完，可以开始填写内容了"))
                break
            except Exception:
                xiaohongshu_logger.debug(_msg("🧍", "图文素材还在上传，小人继续等一会"))
                await asyncio.sleep(
                    budget.clamp_seconds(XHS_NOTE_UPLOAD_POLL_SECONDS)
                )

        xiaohongshu_logger.info(_msg("✍️", "小人开始填标题、描述和话题"))
        await self.fill_meta(page, humanizer=humanizer)

        await self.apply_declarations(page, humanizer=humanizer)

        if self.publish_strategy == XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time_xiaohongshu(
                page, self.publish_date, humanizer=humanizer
            )

        if self.no_publish:
            xiaohongshu_logger.success(_msg("🧪", "已设置完成，--no-publish 跳过发布"))
            return

        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=xiaohongshu_logger,
            label="小红书发布",
        )

        while True:
            # 退出 1（点击前）/ 9（点击后）两个出口只由预算模块产生。
            if budget.remaining_seconds() <= 0:
                raise budget.timeout_error(publish_clicked)

            try:
                if not publish_clicked:
                    # 即时/定时共用同一个 xhs-publish-btn；is-publish /
                    # submit-disabled 的就绪谓词归 ticket 36（ARM）。
                    publish_button = await _resolve_anchor(
                        page,
                        "发布按钮",
                        XHS_PUBLISH_BUTTON_CANDIDATES,
                        role="interactive",
                        budget=budget,
                        point=XHS_PUBLISH_BUTTON_POINT,
                        publish_clicked=publish_clicked,
                    )
                    await humanizer.before_submit()
                    await humanizer.click(
                        publish_button.locator,
                        point=XHS_PUBLISH_BUTTON_POINT,
                    )
                    publish_clicked = True
                outcome = await self._wait_publish_outcome(page)
                if outcome == "success":
                    xiaohongshu_logger.success(_msg("🥳", "图文发布成功，小人开心收工"))
                    break
                xiaohongshu_logger.info(_msg("🏃", "小人正在冲刺发布图文"))
            except Exception:
                xiaohongshu_logger.info(_msg("🏃", "小人正在冲刺发布图文"))
                if self.debug:
                    await page.screenshot(full_page=True)
            await self._sleep(
                XHS_PUBLISH_RETRY_SECONDS, publish_clicked=publish_clicked
            )

    async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.validate_upload_args(check_cookie=False)
            await self.upload_in(session)
            return

        if playwright is None:
            raise ValueError("本地模式需要 Playwright 实例")

        xiaohongshu_logger.info(_msg("🧍", "小人先检查 cookie、图片和发布时间"))
        await self.validate_upload_args()
        xiaohongshu_logger.info(_msg("🥳", "图文上传前检查通过"))
        browser = await playwright.chromium.launch(headless=self.headless, **XHS_LAUNCH_KWARGS)
        context = await browser.new_context(
            storage_state=self.account_file,
            user_agent=await _xhs_user_agent(browser),
            **XHS_CONTEXT_KWARGS,
        )
        context = await set_init_script(context)

        try:
            await self.upload_in(
                BrowserSession(browser=browser, context=context, mode="local")
            )
            await context.storage_state(path=self.account_file)
            xiaohongshu_logger.success(_msg("🥳", "cookie 更新完毕"))
        finally:
            await context.close()
            await browser.close()

    async def upload_in(self, session: BrowserSession) -> None:
        page = await session.context.new_page()
        await self.upload_note_content(page, mode=session.mode)

    async def xiaohongshu_upload_note(self, *, session: BrowserSession | None = None):
        if session is not None:
            await self.upload(None, session=session)
            return
        async with async_playwright() as playwright:
            await self.upload(playwright)

    async def main(self):
        await self.xiaohongshu_upload_note()
