# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import tempfile
import time
from collections import Counter
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

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
from utils.browser_session import log_local_session_ready
from utils.browser_session import provider_label
from utils.controls import read_switch_state
from utils.dom import Candidate
from utils.dom import ElementMissingError
from utils.dom import ElementUnusableError
from utils.dom import OverlayRule
from utils.dom import Resolved
from utils.dom import check
from utils.dom import clear_overlays
from utils.dom import ensure_in_viewport
from utils.dom import resolve
from utils.dom import wait_dom_quiet
from utils.dom import wait_resolved
from utils.errors import LoginRequiredError
from utils.humanize import MAYBE_DISPATCHED
from utils.humanize import MAYBE_DISPATCHED_VALUE
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

XHS_LOGIN_CHECK_SETTLE_MS = 3_000

# 本地模式唯一的零网络前置：会话 cookie 名称（spec §3 U9 A）。
XHS_SESSION_COOKIE_NAME = "galaxy_creator_session_id"
# 检查发布页的观测窗口：导航 30s + 静置 3s（探测失败是退出 1，不是失效）。
XHS_PROBE_NAVIGATION_TIMEOUT_MS = 30_000
XHS_PROBE_SETTLE_MS = XHS_LOGIN_CHECK_SETTLE_MS
# 真机实测：发布页上传入口在 domcontentloaded 后约 5s 才挂载（冷启动更慢），
# 因此锚点必须在有界窗口内轮询，不能做 3s 单次快照（U9 D 的 attached 档正是
# 为了不被慢加载误判）。
XHS_PROBE_ANCHOR_WINDOW_SECONDS = 15.0
XHS_PROBE_POLL_MS = 500

# ---------------------------------------------------------------------------
# 发布链路的等待上限（毫秒）。这些常量只是「上限」：真正传给 Playwright 的
# timeout 一律经 PublishTimeoutBudget.clamp_ms() 收缩到 15 分钟 deadline 内，
# 因此本模块不允许出现裸的 timeout=<数字> 字面量（见 tests/test_xhs_budget.py）。
# ---------------------------------------------------------------------------
XHS_NAVIGATION_TIMEOUT_MS = 30_000
XHS_URL_GUARD_TIMEOUT_MS = 30_000
XHS_LOCATION_INPUT_TIMEOUT_MS = 30_000
XHS_LOCATION_DROPDOWN_TIMEOUT_MS = 3_000
XHS_LOCATION_OPTION_TIMEOUT_MS = 3_000
XHS_LOCATION_FALLBACK_TIMEOUT_MS = 2_000
# 话题：候选就绪窗口与回读窗口（spec §3 U7）。两者都再经剩余预算收紧。
XHS_TOPIC_READY_WINDOW_MS = 5_000
XHS_TOPIC_READBACK_WINDOW_MS = 1_000
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
# 提交语义（spec §3 U2）：ARM → FIRE → OBSERVE。
#
# 只有这三个窗口参与发布判定；任何等待都以「确定未派发 / 可能已派发」为
# 分界，绝不按文案猜测结果。
# ---------------------------------------------------------------------------
XHS_ARM_WINDOW_SECONDS = 60.0
XHS_ARM_POLL_SECONDS = 1.0
XHS_OBSERVE_WINDOW_SECONDS = 15.0
XHS_OBSERVE_POLL_SECONDS = 0.5
XHS_PUBLISH_PATH = "/publish/publish"

# ---------------------------------------------------------------------------
# 上传完成闸（spec §3 U6）：素材就绪是填元数据的前置闸。
#
# 图文按「第 i 张= 瓦片数 ≥ i+1 且该瓦片无 .mask.uploading」逐张判定；
# 视频复用 U2 的 ARM 谓词，窗口 min(600s, 剩余预算)。失败一律点击前 1。
# ---------------------------------------------------------------------------
XHS_NOTE_PREVIEW_TILE_SELECTOR = ".img-preview-area .pr"
XHS_NOTE_TILE_UPLOADING_MASK_SELECTOR = ".mask.uploading"
XHS_NOTE_IMAGE_WINDOW_SECONDS = 60.0
XHS_NOTE_IMAGE_POLL_SECONDS = 0.5
XHS_NOTE_IMAGE_GAP_SECONDS = 1.0
XHS_DOM_QUIET_MS = 500
XHS_DOM_QUIET_CAP_MS = 3_000
XHS_FILE_CHOOSER_TIMEOUT_MS = 5_000
XHS_VIDEO_READY_WINDOW_SECONDS = 600.0
XHS_VIDEO_READY_POLL_SECONDS = 1.0
# 失败态只认 class 恰为 fail 的 div（ticket 24 实机）；用属性等值选择器
# 表达「恰为」，避免命中 fail-* 之类的新增类名。
XHS_VIDEO_FAIL_SELECTOR = "div[class='fail']"

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

# 轮询/重试间隔（秒）：全部经 PublishTimeoutBudget.clamp_seconds() 收缩。
XHS_LOGIN_SUCCESS_SETTLE_SECONDS = 2.0
# 话题候选 200ms、编辑区回读 50ms（spec §3 U7）。
XHS_TOPIC_POLL_SECONDS = 0.2
XHS_TOPIC_READBACK_POLL_SECONDS = 0.05

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
# 上传入口在发布页 domcontentloaded 后数秒才挂载（真机测得 ~5s），首目标必须
# 有界等待；但解析失败后立刻中止，绝不进入 60s 上传完成窗口。
XHS_UPLOAD_ANCHOR_TIMEOUT_MS = 15_000
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

# U3 D 覆盖层注册表：数据驱动，共享层不认识这些选择器。
# 只做「点已知节点 / 按 Esc」，永不摘节点、注样式或点空白。
XHS_OVERLAY_GUIDE_RULE = OverlayRule(
    ".feature-guide__btn",
    action="click",
    label="新手引导按钮",
)
XHS_OVERLAY_NOTE_EDITOR_RULE = OverlayRule(
    'div[role="dialog"]:has-text("图片可以编辑啦")',
    action="click-child",
    target_selector="button",
    label="图片可编辑提示",
)
XHS_OVERLAY_POPOVER_RULE = OverlayRule(
    "div.d-popover",
    action="esc",
    label="浮层",
)
# 2026-11-12 真机：视频发布页的「PK封面」功能引导会盖住封面入口与选项区。
XHS_OVERLAY_PK_COVER_RULE = OverlayRule(
    "div.pk-cover-guide",
    action="click-child",
    target_selector=".pk-cover-guide-close",
    label="PK封面引导",
)
XHS_OVERLAY_RULES = (
    XHS_OVERLAY_GUIDE_RULE,
    XHS_OVERLAY_NOTE_EDITOR_RULE,
    XHS_OVERLAY_PK_COVER_RULE,
    XHS_OVERLAY_POPOVER_RULE,
)
# 正文字段输入期间只允许清「我知道了」引导按钮（数据子集，不是模式开关）。
XHS_TYPING_OVERLAY_RULES = (XHS_OVERLAY_GUIDE_RULE,)

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
XHS_TOPIC_ITEM_NAME_CHILD_SELECTOR = ".name"
XHS_TOPIC_MAX_CLICKS = 3
XHS_TOPIC_READBACK_CANDIDATES = (
    Candidate('div.tiptap[role="textbox"] a[data-topic]'),
)

# 标签上限的唯一口径：只在校验期截断（spec §3 U7）。
XHS_MAX_TAGS = 10

# ---------------------------------------------------------------------------
# 元数据长度与回读（spec §3 U8）。
#
# 标题是平台加权口径（UTF-16 码元 >127 记 2，加总后除 2 向上取整 ≤20）；
# 正文是逐字符口径（≤1000），话题锚点按 `#name` + 分隔符计入。
# 越限的现场信号只认节点存在性：标题 `.max_suffix` / `.c-input_max`，
# 正文 `div.length-error`；不读数值、不判可见。
# ---------------------------------------------------------------------------
XHS_TITLE_MAX_LENGTH = 20
XHS_BODY_MAX_LENGTH = 1000
XHS_TITLE_MAX_SUFFIX_SELECTORS = (
    ".edit-container .suffix.max_suffix",
    ".d-input-wrapper.c-input_max",
)
XHS_BODY_LENGTH_ERROR_SELECTOR = "div.edit-container div.length-error"
# 输入后先等 350ms，再轮询到 500ms；不是超时，是平台渲染延迟窗口。
XHS_TITLE_WARN_MIN_MS = 350
XHS_TITLE_WARN_WINDOW_MS = 500
XHS_TITLE_WARN_POLL_MS = 50
# 定时边界（spec §3 U8 D）：now + 2h < t <= now + 14d；墙上时间语义。
XHS_MAX_SCHEDULE_LEAD_TIME = timedelta(days=14)
# 失焦后到单次回读之间的渲染静置（C2）。
XHS_SCHEDULE_READBACK_SETTLE_MS = 300
XHS_SCHEDULE_SWITCH_SIMULATOR_SELECTOR = ".d-switch-simulator"
XHS_SCHEDULE_DATE_INPUT_SELECTOR = ".date-picker-container input"


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
    """声明下拉选项：一级下拉 → 二级来源下拉 → 裸文案点击。

    真机 2026-11-12：「内容来源声明」的二级菜单是普通
    ``div.d-popover.d-dropdown``（没有 ``declaration-drop-down``），裸文案
    会命中父项/名称/span 共 3 个节点；必须先用容器收窄。
    """
    pattern = re.compile(rf"^{re.escape(label)}$")
    return (
        _zh_css(
            f'.declaration-drop-down .d-option:text-is("{label}")',
            factory=lambda scope: scope.locator(
                XHS_DECLARATION_OPTION_SELECTOR
            ).filter(has_text=pattern),
        ),
        _zh_css(
            f'div.d-popover.d-dropdown .d-option:text-is("{label}")',
            factory=lambda scope: scope.locator(
                "div.d-popover.d-dropdown .d-option"
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

# 17. 添加图片瓦片（第 2 张起）：「+」瓦片点击触发 file chooser；
#     备选是编辑器里唯一的 multiple 图片 input（ticket 24 实测）。
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


# ---------------------------------------------------------------------------
# 提交语义（spec §3 U2）
# ---------------------------------------------------------------------------


async def _read_bool_attr(locator, name: str) -> str | None:
    """读取按钮的布尔属性；缺失或读失败都返回 ``None``（视为通过）。"""
    try:
        value = await locator.get_attribute(name)
    except Exception:
        return None
    if value is None:
        return None
    return str(value).strip().lower()


def _current_path(page: Page) -> str | None:
    """OBSERVE 的唯一判据来源：``page.url`` 的 path；读失败返回 ``None``。

    ``None`` 不表示成功（读不到 URL 时按仍在页面上处理，最终由窗口
    超时映射为退出 9）。
    """
    try:
        url = page.url
    except Exception:
        return None
    if not isinstance(url, str) or not url:
        return None
    try:
        return urlsplit(url).path
    except ValueError:
        return None


async def _arm_ready(
    page: Page, *, budget: PublishTimeoutBudget | None
) -> tuple[bool, str | None]:
    """唯一的发布就绪谓词（spec §3 U2）。

    四个条件全部满足才算就绪：

    1. ``xhs-publish-btn`` 存在且唯一；
    2. 按 ``interactive`` 档可用（disabled / pointer-events / 落点 hit-test）；
    3. ``is-publish != "false"``（属性缺失视为通过）；
    4. ``submit-disabled != "true"``（属性缺失视为通过）。

    每次调用都重新解析 locator，绝不缓存、绝不回落到旧版按钮；``budget``
    只用于契约对齐（谓词本身无等待）。
    """
    locator = page.locator(XHS_PUBLISH_BUTTON_SELECTOR)
    # 长表单里发布按钮常在首屏下方：先滚入视口，再做 interactive 落点判定。
    await ensure_in_viewport(page, locator, point=XHS_PUBLISH_BUTTON_POINT)
    ready, reason = await check(
        locator,
        "interactive",
        point=XHS_PUBLISH_BUTTON_POINT,
    )
    if not ready:
        return False, reason

    if await _read_bool_attr(locator, "is-publish") == "false":
        return False, "is-publish-false"
    if await _read_bool_attr(locator, "submit-disabled") == "true":
        return False, "submit-disabled-true"
    return True, reason


async def _wait_for_arm(
    page: Page,
    *,
    budget: PublishTimeoutBudget,
    mode: str,
    publish_clicked: bool,
) -> None:
    """ARM：1s 轮询就绪谓词，窗口 ``min(60s, 剩余预算)``。

    窗口或预算用尽都意味着**确定未派发**（退出 1）。每轮先跑 C2 分类：
    命中登录/验证页 → ``publish_attempted=False`` 的 ``LoginRequiredError``。
    """
    started = time.monotonic()
    while True:
        # C2 优先于预算出口：命中登录/验证页时永远是 10，而不是 1。
        await _check_blocked(page, mode, publish_attempted=publish_clicked)
        budget.check_pre_click()
        ready, _reason = await _arm_ready(page, budget=budget)
        if ready:
            return

        elapsed = time.monotonic() - started
        remaining_budget = budget.remaining_seconds()
        window_left = XHS_ARM_WINDOW_SECONDS - elapsed
        if window_left <= 0:
            # 确定没有点击：沿用预算模块的点击前出口（退出 1）。
            raise budget.pre_click_error()
        await asyncio.sleep(
            min(XHS_ARM_POLL_SECONDS, window_left, remaining_budget)
        )


async def _fire_publish(
    page: Page,
    *,
    budget: PublishTimeoutBudget,
    humanizer: Humanizer,
    mode: str,
) -> None:
    """FIRE：先置位再派发，单次运行至多一次 ``mouse.down``。

    派发前严格顺序：``before_submit`` 停顿 → 重新解析/落点复核 → 人类化
    点击。``mouse.down`` 之前任何异常 = 确定未派发（原样上抛，退出 1）；
    之后任何异常 = 可能已派发，只分类一次：命中登录/验证 → 10（带
    ``publish_attempted``），否则 → 9。派发后绝不再次触碰按钮。
    """
    publish_clicked = False
    try:
        await humanizer.before_submit()
        # 停顿可能吃掉最后的预算：派发前再确认一次（退出 1）。
        budget.check_pre_click()
        ready, reason = await _arm_ready(page, budget=budget)
        if not ready:
            raise ElementUnusableError(
                "发布按钮",
                role="interactive",
                selector=XHS_PUBLISH_BUTTON_SELECTOR,
                reason=reason or "not-ready",
                publish_clicked=publish_clicked,
            )
        locator = page.locator(XHS_PUBLISH_BUTTON_SELECTOR)
        # 不变量：置位在不可回退点（mouse.down）之前。
        publish_clicked = True
        await humanizer.click(locator, point=XHS_PUBLISH_BUTTON_POINT)
    except Exception as exc:
        if not publish_clicked:
            raise
        if getattr(exc, MAYBE_DISPATCHED, None) != MAYBE_DISPATCHED_VALUE:
            # 人类化点击在 mouse.down 之前失败：确定未派发。
            raise
        # 可能已派发：分类优先于结果未知（10 而不是 9）。
        await _check_blocked(page, mode, publish_attempted=publish_clicked)
        raise budget.timeout_error(publish_clicked) from exc


async def _observe_publish(
    page: Page,
    *,
    budget: PublishTimeoutBudget,
    publish_clicked: bool,
    mode: str,
) -> None:
    """OBSERVE：500ms 轮询，窗口 ``min(15s, 剩余预算)``。

    每轮顺序固定：先 C4 分类（命中 → 10 + ``publish_attempted``），再看
    URL。判据只认 ``urlsplit(page.url).path``：不再包含 ``/publish/publish``
    即成功（0）；15s 或预算用尽仍在页面上 → 9。这里不做任何文案扫描。
    """
    started = time.monotonic()
    while True:
        await _check_blocked(page, mode, publish_attempted=publish_clicked)

        path = _current_path(page)
        if path is not None and XHS_PUBLISH_PATH not in path:
            return

        elapsed = time.monotonic() - started
        remaining_budget = budget.remaining_seconds()
        window_left = XHS_OBSERVE_WINDOW_SECONDS - elapsed
        if remaining_budget <= 0 or window_left <= 0:
            raise budget.timeout_error(publish_clicked)
        await asyncio.sleep(
            min(XHS_OBSERVE_POLL_SECONDS, window_left, remaining_budget)
        )


async def _note_preview_tile_count(page: Page) -> int | None:
    """读预览瓦片数；读失败返回 ``None``（本轮不算完成）。"""
    try:
        return int(await page.locator(XHS_NOTE_PREVIEW_TILE_SELECTOR).count())
    except Exception:
        return None


async def _note_tile_uploading(page: Page, index: int) -> bool | None:
    """第 ``index`` 个瓦片是否仍带进行中遮罩；读失败返回 ``None``。"""
    try:
        tile = page.locator(XHS_NOTE_PREVIEW_TILE_SELECTOR).nth(index)
        mask = tile.locator(XHS_NOTE_TILE_UPLOADING_MASK_SELECTOR)
        return (await mask.count()) > 0
    except Exception:
        return None


async def _note_image_ready(page: Page, index: int) -> bool:
    """第 ``index`` 张的完成判据（spec §3 U6）。

    瓦片数必须 ≥ ``index + 1``，**且** 该瓦片自身的 ``.mask.uploading``
    已消失。绝不看全局遮罩数：多张并发时全局计数无法定位第 i 张。
    """
    count = await _note_preview_tile_count(page)
    if count is None or count < index + 1:
        return False
    uploading = await _note_tile_uploading(page, index)
    return uploading is False


def _note_image_abort(index: int, total: int) -> ElementUnusableError:
    """单张 60s 窗口耗尽：点击前、确定未发布（退出 1）。"""
    return ElementUnusableError(
        "图文素材上传",
        role="attached",
        selector=XHS_NOTE_PREVIEW_TILE_SELECTOR,
        reason=f"第 {index + 1} 张 / 共 {total} 张上传未完成",
        publish_clicked=False,
    )


async def _dispatch_note_image(
    page: Page,
    index: int,
    path,
    *,
    budget: PublishTimeoutBudget,
    humanizer: Humanizer,
) -> None:
    """逐张派发：首张走唯一上传入口，第 2 张起走「+」瓦片的文件选择器。

    禁止 ``inputs[0]`` / ``.first`` 兜底（会把视频 input 当图片 input）；
    任何一次派发失败都立即上抛 ``RuntimeError``（missing/unusable），不重传。
    """
    payload = [str(path)]
    if index == 0:
        resolved = await _resolve_anchor(
            page,
            "图文上传输入",
            XHS_NOTE_IMAGE_CANDIDATES,
            role="attached",
            budget=budget,
            timeout_ms=XHS_UPLOAD_ANCHOR_TIMEOUT_MS,
        )
        try:
            await resolved.locator.set_input_files(payload)
        except Exception as exc:
            raise ElementUnusableError(
                "图文素材派发",
                role="attached",
                selector=resolved.selector,
                reason=f"set_input_files 失败：{exc}",
                publish_clicked=False,
            ) from exc
        return

    chooser = None
    try:
        tile = await _resolve_anchor(
            page,
            "添加图片瓦片",
            (Candidate(XHS_NOTE_ADD_IMAGE_TILE_SELECTOR),),
            role="attached",
            budget=budget,
            timeout_ms=XHS_UPLOAD_ANCHOR_TIMEOUT_MS,
        )
        async with page.expect_file_chooser(
            timeout=budget.clamp_ms(XHS_FILE_CHOOSER_TIMEOUT_MS)
        ) as chooser_info:
            await humanizer.click(tile.locator)
        chooser = await chooser_info.value
    except Exception as exc:
        # mouse.down 之后失败 = 点击可能已派发：不许再走备选（避免双派发）。
        if getattr(exc, MAYBE_DISPATCHED, None) == MAYBE_DISPATCHED_VALUE:
            raise ElementUnusableError(
                "添加图片瓦片",
                role="interactive",
                selector=XHS_NOTE_ADD_IMAGE_TILE_SELECTOR,
                reason=f"文件选择器未出现：{exc}",
                publish_clicked=False,
            ) from exc
        chooser = None

    if chooser is not None:
        try:
            await chooser.set_files(payload)
        except Exception as exc:
            raise ElementUnusableError(
                "图文素材派发",
                role="attached",
                selector=XHS_NOTE_ADD_IMAGE_TILE_SELECTOR,
                reason=f"文件选择器 set_files 失败：{exc}",
                publish_clicked=False,
            ) from exc
        return

    # 备选：编辑器里唯一的 multiple 图片 input（ticket 24 实测）。
    fallback = await _resolve_anchor(
        page,
        "图片追加输入",
        XHS_NOTE_ADD_IMAGE_INPUT_CANDIDATES,
        role="attached",
        budget=budget,
        timeout_ms=XHS_UPLOAD_ANCHOR_TIMEOUT_MS,
    )
    try:
        await fallback.locator.set_input_files(payload)
    except Exception as exc:
        raise ElementUnusableError(
            "图文素材派发",
            role="attached",
            selector=fallback.selector,
            reason=f"set_input_files 失败：{exc}",
            publish_clicked=False,
        ) from exc


async def _wait_note_image(
    page: Page,
    *,
    index: int,
    total: int,
    budget: PublishTimeoutBudget,
    mode: str,
    started: float,
) -> None:
    """等第 ``index`` 张完成：500ms 轮询，窗口 60s（按剩余预算收紧）。"""
    while True:
        await _check_blocked(page, mode, publish_attempted=False)
        budget.check_pre_click()
        if await _note_image_ready(page, index):
            return

        elapsed = time.monotonic() - started
        window_left = XHS_NOTE_IMAGE_WINDOW_SECONDS - elapsed
        if window_left <= 0:
            raise _note_image_abort(index, total)
        await asyncio.sleep(
            min(
                XHS_NOTE_IMAGE_POLL_SECONDS,
                window_left,
                budget.clamp_seconds(XHS_NOTE_IMAGE_POLL_SECONDS),
            )
        )


async def _note_upload_gate(
    page: Page,
    image_paths,
    *,
    budget: PublishTimeoutBudget,
    mode: str,
    humanizer: Humanizer,
) -> None:
    """图文上传完成闸：逐张派发 + 逐瓦片完成 + 最后一张后静默复检。"""
    total = len(image_paths)
    if total == 0:
        return

    started = time.monotonic()
    for index, path in enumerate(image_paths):
        await _check_blocked(page, mode, publish_attempted=False)
        budget.check_pre_click()
        if index:
            await asyncio.sleep(
                min(
                    XHS_NOTE_IMAGE_GAP_SECONDS,
                    budget.clamp_seconds(XHS_NOTE_IMAGE_GAP_SECONDS),
                )
            )
        started = time.monotonic()
        await _dispatch_note_image(
            page, index, path, budget=budget, humanizer=humanizer
        )
        await _wait_note_image(
            page,
            index=index,
            total=total,
            budget=budget,
            mode=mode,
            started=started,
        )
        xiaohongshu_logger.debug(
            _msg("🖼️", f"第 {index + 1} 张 / 共 {total} 张上传完成")
        )

    # 收口：最后一张后只做一次 DOM 静默复检（500ms / 上限 3s）。
    quiet = await wait_dom_quiet(
        page,
        quiet_ms=XHS_DOM_QUIET_MS,
        cap_ms=XHS_DOM_QUIET_CAP_MS,
        budget=budget,
    )
    if not quiet:
        xiaohongshu_logger.warning(
            _msg("🕳️", "上传收口未等到 DOM 静默（dom-not-quiet），按预览计数继续复检")
        )

    count = await _note_preview_tile_count(page)
    if count is not None and count > total:
        xiaohongshu_logger.warning(
            _msg(
                "🖼️",
                f"预览瓦片 {count} 张多于待发 {total} 张，按多图继续（可人工删）",
            )
        )
        return
    if count is not None and count >= total:
        xiaohongshu_logger.success(_msg("🥳", "图文素材已经传完，可以开始填写内容了"))
        return

    # 静默后计数掉回 N 以下：继续等至最后一张的 60s 窗口耗尽。
    await _wait_note_image(
        page,
        index=total - 1,
        total=total,
        budget=budget,
        mode=mode,
        started=started,
    )


async def _video_upload_failure(page: Page) -> str | None:
    """视频的唯一即时失败信号：``div.fail``（class 恰为 fail，ticket 24 实机）。

    ``.video-container-loading-text`` **不是**信号：2026-11-12 真机复测显示
    正路上传中它显示「视频上传中」，失败态才显示失败文案，且同时存在
    ``div.fail``；因此只用纯结构节点判定，避免把进度当失败，也避免恢复文案扫描。``input.upload-input`` 恒在、``submit-disabled`` 失败
    态恒 ``true``，二者同样不能当信号。上游只等发布按钮（10 分钟），这里的
    ``div.fail`` 即时中止是我方有意加强（spec §7）。
    """
    try:
        if await page.locator(XHS_VIDEO_FAIL_SELECTOR).count() > 0:
            return "视频上传失败（div.fail）"
    except Exception:
        return None
    return None


async def _video_upload_gate(
    page: Page, *, budget: PublishTimeoutBudget, mode: str
) -> None:
    """视频上传完成闸：完成判据 = ARM 谓词满足。

    窗口 ``min(600s, 剩余预算)``、1s 轮询；``div.fail`` 立即中止
    （不等到窗口耗尽）。``.video-container-loading-text`` 是进度文案，不判失败。
    """
    started = time.monotonic()
    reason = None
    while True:
        # 上传闸永远在派发之前：publish_attempted 恒为 False。
        await _check_blocked(page, mode, publish_attempted=False)
        budget.check_pre_click()
        failure = await _video_upload_failure(page)
        if failure is not None:
            raise ElementUnusableError(
                "视频素材上传",
                role="interactive",
                selector=XHS_VIDEO_FAIL_SELECTOR,
                reason=failure,
                publish_clicked=False,
            )

        ready, reason = await _arm_ready(page, budget=budget)
        if ready:
            return

        elapsed = time.monotonic() - started
        window_left = XHS_VIDEO_READY_WINDOW_SECONDS - elapsed
        if window_left <= 0:
            raise ElementUnusableError(
                "视频素材上传",
                role="interactive",
                selector=XHS_PUBLISH_BUTTON_SELECTOR,
                reason=(
                    f"{int(XHS_VIDEO_READY_WINDOW_SECONDS)} 秒内未就绪："
                    f"{reason or 'unknown'}"
                ),
                publish_clicked=False,
            )
        await asyncio.sleep(
            min(
                XHS_VIDEO_READY_POLL_SECONDS,
                window_left,
                budget.clamp_seconds(XHS_VIDEO_READY_POLL_SECONDS),
            )
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


async def _run_dom_quiet_gate(
    page: Page, *, budget: PublishTimeoutBudget
) -> None:
    """首次交互前的一次性 DOM 静默门（spec §3 U3 A.2/A.3）。

    连续 500ms 无变更通过，总上限 3s；未静默只打 ``dom-not-quiet``
    warning，**绝不失败、绝不重试**。整条链路只调用一次。
    """
    quiet = await wait_dom_quiet(
        page,
        quiet_ms=XHS_DOM_QUIET_MS,
        cap_ms=XHS_DOM_QUIET_CAP_MS,
        budget=budget,
    )
    if not quiet:
        xiaohongshu_logger.warning(
            _msg("🕳️", "页面未在 3 秒内静默（dom-not-quiet），继续后续动作")
        )


async def _clear_known_overlays(
    page: Page, rules: tuple[OverlayRule, ...], *, budget: PublishTimeoutBudget
) -> None:
    """按注册表清障；覆盖层处理保持 best-effort（见 ``utils.dom``）。"""
    await clear_overlays(page, rules, budget=budget)


def format_tag_cap_warning(tags) -> str:
    """标签超限的唯一文案：CLI 与上传器校验期共用（spec §3 U7）。"""
    items = list(tags or [])
    dropped = items[XHS_MAX_TAGS:]
    return (
        f"标签数量 {len(items)} 超过小红书上限 {XHS_MAX_TAGS}，"
        f"只取前 {XHS_MAX_TAGS} 个；已丢弃: {dropped}"
    )


def _cap_tags(tags) -> list[str]:
    """校验期截断：超过 10 个只取前 10，并列出被丢弃的条目。"""
    items = list(tags or [])
    if len(items) <= XHS_MAX_TAGS:
        return items
    xiaohongshu_logger.warning(_msg("🏷️", format_tag_cap_warning(items)))
    return items[:XHS_MAX_TAGS]


def _utf16_weight(char: str) -> int:
    """单个字符的平台权重：每个 UTF-16 码元 >127 记 2，否则记 1。"""
    units = char.encode("utf-16-le")
    return sum(
        2 if int.from_bytes(units[index : index + 2], "little") > 127 else 1
        for index in range(0, len(units), 2)
    )


def xhs_title_length(title: str) -> int:
    """小红书标题长度：``ceil(Σ code-unit weight / 2)``，上限 20。

    emoji（代理对）占 4 权重 → 计 2；CJK 每个占 2 权重 → 计 1；
    ASCII 每个占 1 权重 → 两个 ASCII 计 1。组合字符按两个码点计。
    """
    weighted = sum(_utf16_weight(char) for char in str(title or ""))
    return (weighted + 1) // 2


def xhs_truncate_title(title: str, limit: int = XHS_TITLE_MAX_LENGTH) -> str:
    """按平台口径截断到 ``limit``，绝不切开代理对。"""
    used = 0
    kept: list[str] = []
    for char in str(title or ""):
        weight = _utf16_weight(char)
        if (used + weight + 1) // 2 > limit:
            break
        used += weight
        kept.append(char)
    return "".join(kept)


def validate_title_length(title: str) -> str:
    """显式标题预检：超限抛 ``ValueError``（浏览器未启动），绝不截断。"""
    length = xhs_title_length(title)
    if length > XHS_TITLE_MAX_LENGTH:
        raise ValueError(
            f"标题过长：当前 {length} / 上限 {XHS_TITLE_MAX_LENGTH}"
            "（小红书口径：按 UTF-16 码元加权，码元 >127 记 2、否则记 1，"
            "加总后除 2 向上取整）"
        )
    return title


def xhs_body_length(desc: str, tags=None) -> int:
    """正文长度口径：正文逐字符计 1；话题锚点按 ``#name`` + 分隔符计。

    ``#旅行pov[话题]#`` → ``#旅行pov``（6）+ 一个分隔符 = 7。上限 1000。

    这个函数与 ``XHS_BODY_MAX_LENGTH`` 一起编码 spec §3 U8 D 的计数规则
    （正文逐字符、话题按 ``#name`` 另加分隔符），离线测试据此断言；它不是
    页面状态回读的一部分。
    """
    total = len(str(desc or ""))
    for tag in tags or ():
        name = str(tag or "")
        if name.startswith("#"):
            name = name[1:]
        total += len(name) + 2
    return total


def _wall_clock(value: datetime) -> datetime:
    """墙上时间：aware 输入的 offset 一律忽略（只取它自带的年月日时分）。"""
    return value.replace(tzinfo=None)


def xhs_validate_schedule_time(
    publish_date: datetime, *, now: datetime | None = None
) -> datetime:
    """窗口 ``now + 2h < t <= now + 14d``，墙上时间语义。"""
    if not isinstance(publish_date, datetime):
        raise TypeError("publish_date 必须是 datetime 类型或 0")
    wall = _wall_clock(publish_date)
    current = _wall_clock(now) if now is not None else datetime.now()
    if wall <= current:
        raise ValueError("定时发布时间必须晚于当前时间")
    if wall <= current + BaseVideoUploader.MIN_SCHEDULE_LEAD_TIME:
        raise ValueError("定时发布时间必须大于当前时间 2 小时")
    if wall > current + XHS_MAX_SCHEDULE_LEAD_TIME:
        raise ValueError("定时发布时间不能晚于当前时间 14 天")
    return wall


def _format_schedule_value(publish_date: datetime) -> str:
    return _wall_clock(publish_date).strftime("%Y-%m-%d %H:%M")


def _parse_schedule_value(raw) -> datetime | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _same_schedule_minute(left: datetime, right: datetime) -> bool:
    return left.replace(second=0, microsecond=0) == right.replace(
        second=0, microsecond=0
    )


async def _element_exists(page: Page, selector: str) -> bool:
    """节点存在性（只用于集合基数/存在性判据，不判可见、不读文本）。

    判据是 ``count() >= 1``：出现即失败。多义（``ambiguous:N``）同样是
    「存在」，绝不能因为 ``check(..., "attached")`` 拒绝歧义就把越限节点
    当成不存在而放行（spec §3 U8 D）。
    """
    try:
        locator = page.locator(selector)
        return int(await locator.count()) >= 1
    except Exception:
        return False


async def _simulator_switch_state(switch) -> bool | None:
    """读小红书 ``.d-switch-simulator`` 的 class：``checked``/``unchecked``。

    ``None`` = 读不出来（不是「关着」）。真机上开关状态只在 class 上，
    ``aria-checked`` 常缺席；共享层 ``read_switch_state`` 仍是首选，
    这里只作平台兜底。
    """
    try:
        simulator = switch.locator(XHS_SCHEDULE_SWITCH_SIMULATOR_SELECTOR).first
        if await simulator.count() != 1:
            return None
        classes = str(await simulator.get_attribute("class") or "")
    except Exception:
        return None
    tokens = classes.split()
    if "unchecked" in tokens:
        return False
    if "checked" in tokens:
        return True
    return None


async def _schedule_switch_checked(switch) -> bool:
    """C1/C2/C3 共用：simulator class 含 ``checked`` 且不含 ``unchecked``。"""
    return (await _simulator_switch_state(switch)) is True


def _normalise_topic(value) -> str:
    """话题名归一化（两侧同规则）：去前导 # → strip → 折叠空白 → casefold。"""
    text = str(value or "")
    if text.startswith("#"):
        text = text[1:]
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def _parse_topic_name(raw) -> str | None:
    """``data-topic`` → JSON → ``name``；解析失败返回 ``None``（名字未知）。"""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    return name


def _multiset_difference(after, before) -> list[str]:
    """多重集合差：``after - before``，保留重复项的计数。"""
    remaining = Counter(before)
    new_values: list[str] = []
    for value in after:
        if remaining[value] > 0:
            remaining[value] -= 1
        else:
            new_values.append(value)
    return new_values


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
    wait: bool = True,
) -> Resolved:
    """按矩阵候选解析一个锚点，并打一条命中日志。

    ``scope`` 默认整页；弹窗内的锚点传弹窗 locator，保证选择器被容器限定。
    结构分支只打 ``debug``；非结构分支（upstream / text-zh）额外打一条
    ``info``，让真机日志一眼看出是否走了兜底。

    ``wait=False`` 是单趟解析；上传入口/「+」瓦片用
    ``XHS_UPLOAD_ANCHOR_TIMEOUT_MS`` 有界等待“挂载”，一旦缺失/多义立即中止
    （spec §3 U6「不等待」指不进入 60s 上传完成窗口）。
    """
    target = page if scope is None else scope
    if wait:
        resolved = await wait_resolved(
            target,
            candidates,
            role=role,
            timeout_ms=timeout_ms,
            budget=budget,
            point=point,
            publish_clicked=publish_clicked,
        )
    else:
        resolved = await resolve(
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


def _local_login_required() -> LoginRequiredError:
    """本地会话前置失败的唯一错误形状（退出 10，未启动浏览器）。"""
    return LoginRequiredError(
        _blocked_message("login", "local", publish_attempted=False),
        reason="login",
        publish_attempted=False,
    )


async def local_session_preflight(account_file) -> None:
    """零网络本地前置：账号文件存在 + 会话 cookie 存在 + 未过期。

    ``expires <= 0`` 表示会话 cookie / 过期时间未知，按规格放行。任何读取
    失败都视为「无法证明会话存在」→ ``LoginRequiredError``，绝不启动浏览器。
    """
    path = Path(str(account_file))
    if not path.is_file():
        raise _local_login_required()

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise _local_login_required() from None

    cookies = state.get("cookies") if isinstance(state, dict) else None
    if not isinstance(cookies, list):
        raise _local_login_required()

    session_cookie = None
    for cookie in cookies:
        if isinstance(cookie, dict) and cookie.get("name") == XHS_SESSION_COOKIE_NAME:
            session_cookie = cookie
            break
    if session_cookie is None:
        raise _local_login_required()

    expires = session_cookie.get("expires")
    try:
        expiry = float(expires) if expires is not None else 0.0
    except (TypeError, ValueError):
        expiry = 0.0
    if expiry > 0 and expiry <= time.time():
        raise _local_login_required()


async def save_storage_state_atomic(context: BrowserContext, account_file) -> None:
    """把当前 context 的 storage_state 原子写回账号文件（temp + replace）。"""
    state = await context.storage_state()
    target = Path(str(account_file))
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_path = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)
        os.replace(temp_path, target)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


async def probe_session(context: BrowserContext) -> tuple[str, str]:
    """发布页唯一观测（check 与登录后复核共用）。

    一次 ``new_page`` → 导航发布页 → 静置 → 分类器 → 上传入口 ``attached``
    （count ≥ 1）。返回 ``("valid" | kind, 当前 URL)``；导航 5xx / 超时 /
    离开创作域 / 页面结构异常一律抛 ``RuntimeError``（探测失败 = 退出 1）。
    """
    page = await context.new_page()
    try:
        try:
            response = await page.goto(
                XHS_LOGIN_CHECK_URL,
                wait_until="domcontentloaded",
                timeout=XHS_PROBE_NAVIGATION_TIMEOUT_MS,
            )
        except Exception as exc:
            raise RuntimeError(
                f"小红书发布页检查失败：导航未完成（{exc}）"
            ) from exc

        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"小红书发布页检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(XHS_PROBE_SETTLE_MS)

        current_url = str(getattr(page, "url", "") or "")
        if not current_url.startswith(_build_xhs_creator_url("/")):
            raise RuntimeError(
                "小红书发布页检查失败：页面未停留在小红书创作者中心"
                f"（url={current_url or '<empty>'}）"
            )

        kind = await classify_blocked(page)
        if kind is not None:
            return kind, current_url

        # 有界轮询：上传入口可能在 domcontentloaded 后数秒才挂载；每轮先看
        # 风控分类（迟到跳转仍判 10），再看任一上传锚点 attached（count ≥ 1）。
        deadline = time.monotonic() + XHS_PROBE_ANCHOR_WINDOW_SECONDS
        while True:
            kind = await classify_blocked(page)
            if kind is not None:
                return kind, current_url

            for selector in XHS_LOGIN_POSITIVE_SELECTORS:
                try:
                    count = await page.locator(selector).count()
                except Exception:
                    count = 0
                if count >= 1:
                    return "valid", current_url

            if time.monotonic() >= deadline:
                break
            if wait_for_timeout is not None:
                await wait_for_timeout(XHS_PROBE_POLL_MS)

        raise RuntimeError(
            "小红书发布页检查失败：未找到上传入口（页面结构异常）"
        )
    finally:
        await page.close()


async def xiaohongshu_setup(
    account_file,
    handle=False,
    return_detail=False,
    qrcode_callback=None,
    headless: bool = LOCAL_CHROME_HEADLESS,
):
    # 登录命令总是允许重新扫码；不再用网络探测决定是否跳过。
    if handle:
        xiaohongshu_logger.info(_msg("🖼️", "准备打开浏览器扫码登录小红书"))
        result = await xiaohongshu_cookie_gen(
            account_file,
            qrcode_callback=qrcode_callback,
            headless=headless,
        )
        return result if return_detail else result["success"]

    try:
        await local_session_preflight(account_file)
    except LoginRequiredError:
        result = _build_login_result(
            False, "cookie_invalid", "cookie文件不存在或已失效", account_file
        )
        return result if return_detail else False

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
                # 扫码完成判据只有分类器：返回 None 即离开登录/验证页。
                if await classify_blocked(page) is None:
                    await asyncio.sleep(XHS_LOGIN_SUCCESS_SETTLE_SECONDS)
                    kind, evidence = await probe_session(context)
                    if kind == "valid":
                        await save_storage_state_atomic(context, account_file)
                        xiaohongshu_logger.success(_msg("🥳", "小红书扫码登录成功，小人开心收工"))
                        result = _build_login_result(
                            True,
                            "success",
                            "小红书扫码登录成功",
                            account_file,
                            qrcode_info,
                            evidence or page.url,
                        )
                    else:
                        result = _build_login_result(
                            False,
                            "cookie_invalid",
                            "小红书扫码流程结束，但发布页复核未通过",
                            account_file,
                            qrcode_info,
                            evidence or page.url,
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
            # 唯一的本地前置：零网络，失败 = 退出 10 且不启动浏览器。
            await local_session_preflight(self.account_file)

        if self.publish_strategy not in {
            XIAOHONGSHU_PUBLISH_STRATEGY_IMMEDIATE,
            XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED,
        }:
            raise ValueError(f"不支持的发布策略: {self.publish_strategy}")

        if self.publish_strategy == XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED:
            if isinstance(self.publish_date, datetime):
                # 墙上时间语义：aware 输入的 offset 不参与校验，也不参与格式化。
                self.publish_date = xhs_validate_schedule_time(self.publish_date)
            else:
                self.publish_date = self.validate_publish_date(self.publish_date)
        else:
            self.publish_date = 0

        # 标签上限的唯一口径：校验期一处截断（发布前、开浏览器前）。
        self.tags = _cap_tags(getattr(self, "tags", []) or [])

    async def set_schedule_time_xiaohongshu(
        self,
        page: Page,
        publish_date: datetime,
        *,
        humanizer: Humanizer | None = None,
    ):
        humanizer = humanizer or self._humanizer(page)
        xiaohongshu_logger.info(_msg("🕒", f"小人准备设置定时发布时间: {_format_schedule_value(publish_date)}"))
        switch = await _resolve_anchor(
            page,
            "定时开关",
            XHS_SCHEDULE_SWITCH_CANDIDATES,
            role="visible",
            budget=self.publish_budget,
        )
        await humanizer.click(switch.locator)
        # C1：点后立刻回读开关状态与时间输入框 attached（不用固定 sleep）。
        await self._assert_schedule_switch_on(
            page, switch.locator, stage="C1"
        )
        if not await _element_exists(page, XHS_SCHEDULE_DATE_INPUT_SELECTOR):
            raise ElementUnusableError(
                "定时时间输入",
                role="attached",
                selector=XHS_SCHEDULE_DATE_INPUT_SELECTOR,
                reason="C1 时间输入框未 attached",
                publish_clicked=False,
            )

        time_input = await _resolve_anchor(
            page,
            "定时时间输入",
            XHS_SCHEDULE_TIME_CANDIDATES,
            role="editable",
            budget=self.publish_budget,
        )
        # 真机 2026-11-12：filter input 默认已带一个值（now+~1h），focus 后
        # 直接键入会**追加**成两段日期。必须先全选，再逐字替换。
        await time_input.locator.focus()
        await humanizer.press("ControlOrMeta+A")
        await humanizer.type_text(_format_schedule_value(publish_date))
        # 失焦只允许 blur()：Tab 会把焦点交给发布按钮，Enter 会触发暂存离开。
        await time_input.locator.blur()
        await self._settle(page, XHS_SCHEDULE_READBACK_SETTLE_MS)
        # C2：blur → 约 300ms → 单次读 input.value，按分钟比较；不重试。
        await self._assert_schedule_switch_on(
            page, switch.locator, stage="C2"
        )
        await self._assert_schedule_value(
            page, time_input.locator, publish_date, stage="C2"
        )

    async def _assert_schedule_switch_on(self, page: Page, switch, *, stage: str):
        if await _schedule_switch_checked(switch):
            return
        raise ElementUnusableError(
            "定时开关",
            role="attached",
            selector=XHS_SCHEDULE_SWITCH_CANDIDATES[0].selector,
            reason=f"{stage} 开关未选中",
            publish_clicked=False,
        )

    async def _assert_schedule_value(
        self, page: Page, input_locator, publish_date: datetime, *, stage: str
    ):
        try:
            raw = await input_locator.input_value()
        except Exception as exc:
            raw = None
            read_error = exc
        else:
            read_error = None

        parsed = _parse_schedule_value(raw)
        expected = _wall_clock(publish_date)
        if parsed is None or not _same_schedule_minute(parsed, expected):
            detail = (
                f"读取失败: {read_error}"
                if read_error is not None
                else f"实际 {raw!r}"
            )
            raise ElementUnusableError(
                "定时发布时间",
                role="attached",
                selector=XHS_SCHEDULE_TIME_CANDIDATES[0].selector,
                reason=(
                    f"{stage} 回读不一致：期望 "
                    f"{_format_schedule_value(expected)}，{detail}"
                ),
                publish_clicked=False,
            )

    async def _verify_schedule_before_fire(self, page: Page) -> None:
        """C3：ARM 就绪后、FIRE 前，再证一次定时开关、值与时效。

        即时发布（``publish_date`` 为空）完全不进入 C1–C3；``--no-publish``
        干跑同样执行本检查。
        """
        if (
            self.publish_strategy
            != XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED
            or self.publish_date == 0
        ):
            return

        switch = await _resolve_anchor(
            page,
            "定时开关",
            XHS_SCHEDULE_SWITCH_CANDIDATES,
            role="attached",
            budget=self.publish_budget,
        )
        await self._assert_schedule_switch_on(page, switch.locator, stage="C3")

        time_input = await _resolve_anchor(
            page,
            "定时时间输入",
            XHS_SCHEDULE_TIME_CANDIDATES,
            role="attached",
            budget=self.publish_budget,
        )
        await self._assert_schedule_value(
            page, time_input.locator, self.publish_date, stage="C3"
        )

        if _wall_clock(self.publish_date) <= datetime.now():
            raise ElementUnusableError(
                "定时发布时间",
                role="attached",
                selector=XHS_SCHEDULE_TIME_CANDIDATES[0].selector,
                reason="C3 请求时间已过期（不再晚于本机当前时间）",
                publish_clicked=False,
            )

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
        # 原样填充：静默截断已删除（越限只在校验期拒绝，见 U8 B）。
        await humanizer.type_text(self.title)
        await self._assert_title_not_over_limit(page)

    async def _assert_title_not_over_limit(self, page: Page) -> None:
        """输入后等 ≥350ms / 轮询至 500ms，再查越限后缀节点的存在性。"""
        await self._settle(page, XHS_TITLE_WARN_MIN_MS)
        extra_rounds = max(
            1,
            (XHS_TITLE_WARN_WINDOW_MS - XHS_TITLE_WARN_MIN_MS)
            // XHS_TITLE_WARN_POLL_MS,
        )
        for round_index in range(extra_rounds + 1):
            selector = await self._title_limit_suffix(page)
            if selector is not None:
                raise ElementUnusableError(
                    "标题",
                    role="attached",
                    selector=selector,
                    reason="标题超出平台长度上限（越限后缀节点存在）",
                    publish_clicked=False,
                )
            if round_index == extra_rounds:
                return
            await self._settle(page, XHS_TITLE_WARN_POLL_MS)

    async def _title_limit_suffix(self, page: Page) -> str | None:
        for selector in XHS_TITLE_MAX_SUFFIX_SELECTORS:
            if await _element_exists(page, selector):
                return selector
        return None

    async def _assert_body_not_over_limit(self, page: Page) -> None:
        """正文 + 话题全部输入完成后，单次检查长度错误节点（存在即失败）。"""
        if not await _element_exists(page, XHS_BODY_LENGTH_ERROR_SELECTOR):
            return
        raise ElementUnusableError(
            "正文",
            role="attached",
            selector=XHS_BODY_LENGTH_ERROR_SELECTOR,
            reason="正文超出平台长度上限（长度错误节点存在）",
            publish_clicked=False,
        )

    async def fill_desc(self, page: Page, *, humanizer: Humanizer | None = None) -> None:
        if not getattr(self, "desc", ""):
            return

        humanizer = humanizer or self._humanizer(page)
        # 输入期间只允许清「我知道了」引导按钮（不点空白、不摘节点）。
        await _clear_known_overlays(
            page, XHS_TYPING_OVERLAY_RULES, budget=self.publish_budget
        )
        desc = await _resolve_anchor(
            page,
            "正文",
            XHS_BODY_CANDIDATES,
            role="editable",
            budget=self.publish_budget,
        )
        # 输入类字段对照上游：先滚入视口再 focus，不做坐标点击（底部固定
        # 发布按钮会盖住编辑区中心，坐标落点不可靠）。
        await ensure_in_viewport(page, desc.locator)
        await desc.locator.focus()
        await humanizer.press("Backspace")
        await humanizer.press("ControlOrMeta+A")
        await humanizer.press("Delete")
        await humanizer.type_text(self.desc)
        await humanizer.press("Enter")

    async def fill_tags(self, page: Page, *, humanizer: Humanizer | None = None) -> None:
        if not getattr(self, "tags", None):
            return

        humanizer = humanizer or self._humanizer(page)
        if not getattr(self, "desc", ""):
            await _clear_known_overlays(
                page, XHS_TYPING_OVERLAY_RULES, budget=self.publish_budget
            )
            desc = await _resolve_anchor(
                page,
                "正文",
                XHS_BODY_CANDIDATES,
                role="editable",
                budget=self.publish_budget,
            )
            await ensure_in_viewport(page, desc.locator)
            await desc.locator.focus()

        for tag in self.tags:
            # 话题是增强项：插入失败降级为纯文本，绝不因此中止发布（spec §3 U7）。
            # 但预算耗尽不是「话题失败」：先走点击前预算出口（exit 1）。
            self.publish_budget.check_pre_click()
            await humanizer.type_text("#" + tag)
            await self._insert_topic(page, tag, humanizer)

    def _topic_window_ms(self, default_ms: int) -> int:
        """把话题窗口收紧到剩余预算；预算耗尽直接抛 ``pre_click_error()``。

        绝不允许返回 0 制造「窗口为 0 → 静默降级」的假成功：话题阶段仍在
        点击发布之前，预算耗尽必须退出 1（spec §3 U1/U7）。
        """
        return self.publish_budget.clamp_ms(default_ms)

    async def _scan_topic_candidate(self, page: Page, tag: str):
        """顺序扫描全部渲染候选项，返回 ``(item, item_count)``。

        只认 name **全等**的项（无前缀/包含匹配）；多个全等取最前并打 info。
        容器需 ATTACHED、被点项需 INTERACTIVE。读取失败按「无候选」处理。
        """
        container = page.locator(XHS_TOPIC_MENU_SELECTOR)
        try:
            attached, _reason = await check(container, "attached")
        except Exception:
            attached = False
        if not attached:
            return None, 0

        items_locator = page.locator(XHS_TOPIC_ITEM_SELECTOR)
        try:
            count = int(await items_locator.count())
        except Exception:
            return None, 0
        if count <= 0:
            return None, 0

        target = _normalise_topic(tag)
        matches = []
        try:
            for index in range(count):
                item = items_locator.nth(index)
                name = await item.locator(
                    XHS_TOPIC_ITEM_NAME_CHILD_SELECTOR
                ).text_content()
                if _normalise_topic(name) == target:
                    matches.append(item)
        except Exception:
            # 读取候选失败 = 这一轮没有候选；话题缺失只降级，不失败。
            return None, count

        if not matches:
            return None, count
        if len(matches) > 1:
            xiaohongshu_logger.info(
                _msg("🏷️", f"topic-ambiguous:{len(matches)}")
            )
        candidate = matches[0]
        try:
            usable, _reason = await check(candidate, "interactive")
        except Exception:
            usable = False
        if not usable:
            return None, count
        return candidate, count

    async def _read_topic_nodes(self, page: Page) -> list[str] | None:
        """读正文编辑器根内的全部话题锚点（只读 ``data-topic``，只需 ATTACHED）。

        选择器自带 ``div.tiptap[role="textbox"]`` 作用域，预览镜像不在其中。
        读取失败返回 ``None``：调用点据此区分「读不到」与「0 个新增」。
        """
        try:
            locator = XHS_TOPIC_READBACK_CANDIDATES[0].build(page)
            count = int(await locator.count())
        except Exception:
            return None
        values: list[str] = []
        for index in range(count):
            try:
                raw = await locator.nth(index).get_attribute("data-topic")
            except Exception:
                return None
            values.append(raw or "")
        return values

    async def _readback_new_topics(
        self, page: Page, baseline: list[str]
    ) -> list[str] | None:
        """点击后统一回读：50ms 轮询，窗口 ``min(1s, 剩余预算)``。"""
        deadline = time.monotonic() + self._topic_window_ms(
            XHS_TOPIC_READBACK_WINDOW_MS
        ) / 1000
        after: list[str] | None = None
        while True:
            after = await self._read_topic_nodes(page)
            if after is not None:
                new_nodes = _multiset_difference(after, baseline)
                if new_nodes:
                    return new_nodes
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return [] if after is not None else None
            await asyncio.sleep(min(XHS_TOPIC_READBACK_POLL_SECONDS, remaining))

    def _topic_failure(
        self,
        reason: str,
        tag: str,
        *,
        observed_names,
        new_nodes,
        attempts: int,
        elapsed_ms: int = 0,
    ) -> ElementUnusableError:
        """话题失败对象：``reason`` 之外的四个字段挂在实例上（ticket 39）。"""
        error = ElementUnusableError(
            what=f"话题『{tag}』",
            role="interactive",
            selector=XHS_TOPIC_ITEM_SELECTOR,
            reason=reason,
            tried=[(XHS_TOPIC_ITEM_SELECTOR, None)],
            elapsed_ms=elapsed_ms,
            publish_clicked=False,
        )
        error.tag = tag
        error.observed_names = list(observed_names)
        error.new_nodes = list(new_nodes)
        error.attempts = int(attempts)
        return error

    async def _insert_topic(
        self, page: Page, tag: str, humanizer: Humanizer
    ) -> None:
        """找候选 → 最多点击 3 次 → 循环外统一回读一次。"""
        started = time.monotonic()
        deadline = started + self._topic_window_ms(
            XHS_TOPIC_READY_WINDOW_MS
        ) / 1000
        attempts = 0
        baseline: list[str] | None = None

        while attempts < XHS_TOPIC_MAX_CLICKS and time.monotonic() < deadline:
            # 每次重试前都过预算闸：耗尽 → pre_click_error（exit 1）。
            self.publish_budget.check_pre_click()
            candidate, item_count = await self._scan_topic_candidate(page, tag)
            if candidate is None:
                if attempts > 0 or item_count > 0:
                    # 点过之后候选消失 = 正常成功信号；有项但无全等 = 无候选。
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(XHS_TOPIC_POLL_SECONDS, remaining))
                continue

            if baseline is None:
                # 基线按标签条目固定：第一次点击前取一次，重试不刷新。
                baseline = await self._read_topic_nodes(page)
                if baseline is None:
                    # 读不到编辑区就不点：宁可降级也不插入无法校验的内容。
                    break

            await humanizer.click(candidate)
            attempts += 1
            if attempts >= XHS_TOPIC_MAX_CLICKS:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(XHS_TOPIC_POLL_SECONDS, remaining))

        if attempts == 0:
            await self._degrade_topic(tag, humanizer, attempts=attempts)
            return

        new_nodes = await self._readback_new_topics(page, baseline or [])
        if new_nodes is None:
            raise self._topic_failure(
                "topic-mismatch",
                tag,
                observed_names=[],
                new_nodes=[],
                attempts=attempts,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

        observed_names = [_parse_topic_name(raw) for raw in new_nodes]
        if len(new_nodes) > 1:
            raise self._topic_failure(
                "topic-multi-insert",
                tag,
                observed_names=observed_names,
                new_nodes=new_nodes,
                attempts=attempts,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        if not new_nodes:
            await self._degrade_topic(tag, humanizer, attempts=attempts)
            return
        if _normalise_topic(observed_names[0]) == _normalise_topic(tag):
            xiaohongshu_logger.info(_msg("🏷️", f"topic-match:{tag}"))
            return

        raise self._topic_failure(
            "topic-mismatch",
            tag,
            observed_names=observed_names,
            new_nodes=new_nodes,
            attempts=attempts,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    async def _degrade_topic(
        self, tag: str, humanizer: Humanizer, *, attempts: int
    ) -> None:
        """降级：保留纯文本 ``#tag`` + 一个空格；不按 Backspace 清理。"""
        await humanizer.press("Space")
        xiaohongshu_logger.warning(
            _msg(
                "🏷️",
                f"话题『{tag}』未插入（尝试 {attempts} 次），"
                "保留纯文本继续发布",
            )
        )

    async def fill_meta(self, page: Page, *, humanizer: Humanizer | None = None) -> None:
        humanizer = humanizer or self._humanizer(page)
        await self.fill_title(page, humanizer=humanizer)
        await self.fill_desc(page, humanizer=humanizer)
        await self.fill_tags(page, humanizer=humanizer)
        # 唯一闸门：正文与话题全部输入完成后单次检查越限节点。
        await self._assert_body_not_over_limit(page)

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

        预算耗尽时收缩到 0 而不是抛 ``pre_click_error``。真正的超时判据
        仍然只发生在锚点/ARM/OBSERVE 处。
        """
        remaining = max(0.0, self.publish_budget.remaining_seconds())
        await asyncio.sleep(min(seconds, remaining))

    async def apply_declarations(
        self, page: Page, *, humanizer: Humanizer | None = None
    ) -> None:
        """按需设置「原创声明」和「添加内容类型声明」。

        两项能力默认都不操作页面（保持平台默认）：
        - ``original_declaration`` 为 ``True``/``False`` 时才切换原创开关；
        - ``content_type`` 非空时才打开内容类型声明下拉。

        原创 ``true`` 是硬闸：点前读状态、未开则点击 + 确认弹窗，任一步失败
        即上抛（退出 1）；原创 ``false`` 与内容类型/封面仍是 warning 继续。
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
        if self.original_declaration is True:
            await self._enable_original_declaration(page, humanizer=humanizer)
        else:
            await self._disable_original_declaration(page, humanizer=humanizer)

    async def _enable_original_declaration(
        self, page: Page, *, humanizer: Humanizer
    ) -> None:
        """原创 true：点前读 → 未开则点击 → 勾选须知 → 声明原创；失败即 1。"""
        switch = (
            await _resolve_anchor(
                page,
                "原创开关",
                XHS_ORIGINAL_SWITCH_CANDIDATES,
                role="visible",
                budget=self.publish_budget,
            )
        ).locator

        current = await self._read_original_switch_state(switch)
        if current is True:
            xiaohongshu_logger.success(_msg("🧾", "原创声明已开启（无需切换）"))
            return

        if current is None:
            xiaohongshu_logger.warning(
                _msg("⚠️", "无法确认原创声明开关状态，按未开启处理并点击")
            )
        await humanizer.click(switch)
        await self._settle(page, XHS_DECLARATION_SETTLE_MS)
        # 点后不读状态：确认弹窗走完即视为成功；任一步失败上抛（1）。
        await self._confirm_original_declaration(page, humanizer=humanizer)
        xiaohongshu_logger.success(_msg("🧾", "原创声明已开启"))

    async def _disable_original_declaration(
        self, page: Page, *, humanizer: Humanizer
    ) -> None:
        """原创 false：开着则点一次关；控件缺失视为已关；失败 warning 继续。"""
        try:
            switch = (
                await _resolve_anchor(
                    page,
                    "原创开关",
                    XHS_ORIGINAL_SWITCH_CANDIDATES,
                    role="visible",
                    budget=self.publish_budget,
                )
            ).locator
        except (ElementMissingError, ElementUnusableError) as exc:
            xiaohongshu_logger.warning(
                _msg("⚠️", f"原创开关不存在或不可用，视为已关闭: {exc}")
            )
            return

        try:
            current = await self._read_original_switch_state(switch)
            if current is True:
                # 点后不读，也不二次点击。
                await humanizer.click(switch)
                await self._settle(page, XHS_DECLARATION_SETTLE_MS)
            elif current is None:
                xiaohongshu_logger.warning(
                    _msg("⚠️", "无法确认原创声明开关状态，跳过关闭")
                )
            xiaohongshu_logger.success(_msg("🧾", "原创声明已关闭"))
        except Exception as exc:
            xiaohongshu_logger.warning(
                _msg("⚠️", f"关闭原创声明失败，跳过继续发布: {exc}")
            )
            await self._press_escape(page)

    @staticmethod
    async def _read_original_switch_state(switch) -> bool | None:
        """点前读状态：共享层优先，平台 simulator class 兜底（三态）。"""
        current = await read_switch_state(switch)
        if current is not None:
            return current
        return await _simulator_switch_state(switch)

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
        await ensure_in_viewport(page, location)
        await location.focus()
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
        await ensure_in_viewport(page, source_input)
        await source_input.focus()
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
        不处理这个弹窗会一直挡住发布按钮。开启原创时弹窗缺失 = 无法证明
        声明生效 → 上抛（退出 1），不再静默放过。
        """
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
        validate_title_length(self.title)

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
            # 0. PK封面引导会盖住封面入口（2026-11-12 真机）：先按注册表清障。
            await _clear_known_overlays(
                page, XHS_OVERLAY_RULES, budget=self.publish_budget
            )
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
        # 首次交互前的一次性 DOM 静默门 + 已知覆盖层清障（spec §3 U3 D）。
        await _run_dom_quiet_gate(page, budget=budget)
        await _clear_known_overlays(page, XHS_OVERLAY_RULES, budget=budget)
        upload_input = await _resolve_anchor(
            page,
            "视频上传输入",
            XHS_VIDEO_FILE_CANDIDATES,
            role="attached",
            budget=budget,
            timeout_ms=XHS_UPLOAD_ANCHOR_TIMEOUT_MS,
        )
        try:
            await upload_input.locator.set_input_files(self.file_path)
        except Exception as exc:
            raise ElementUnusableError(
                "视频素材派发",
                role="attached",
                selector=upload_input.selector,
                reason=f"set_input_files 失败：{exc}",
                publish_clicked=False,
            ) from exc

        await _video_upload_gate(page, budget=budget, mode=mode)
        xiaohongshu_logger.success(_msg("🥳", "视频已经传完啦"))

        xiaohongshu_logger.info(_msg("✍️", "小人开始填标题、描述和话题"))
        await self.fill_meta(page, humanizer=humanizer)

        await self.set_thumbnail(page, self.thumbnail_path, humanizer=humanizer)

        # await self.set_location(page, "青岛市")

        await self.apply_declarations(page, humanizer=humanizer)

        if self.publish_strategy == XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time_xiaohongshu(
                page, self.publish_date, humanizer=humanizer
            )

        # 封面步骤可能留下弹窗；解析/点击发布按钮前再清一次已知覆盖层。
        await _clear_known_overlays(page, XHS_OVERLAY_RULES, budget=budget)

        if self.no_publish:
            # 干跑升级为「跑到 ARM 就绪」：跳过 --not-before 等待，
            # 但仍执行 C1/C2/C3 与定时回读；不进入 FIRE。
            await _check_blocked(page, mode, publish_attempted=publish_clicked)
            await _wait_for_arm(
                page, budget=budget, mode=mode, publish_clicked=publish_clicked
            )
            await self._verify_schedule_before_fire(page)
            xiaohongshu_logger.success(
                _msg("🧪", "ARM 就绪，--no-publish 停在发布按钮前（未点击发布）")
            )
            return

        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=xiaohongshu_logger,
            label="小红书发布",
        )

        # C3：--not-before 等待之后、ARM 之前必查（未派发）。
        await _check_blocked(page, mode, publish_attempted=publish_clicked)
        await _wait_for_arm(
            page, budget=budget, mode=mode, publish_clicked=publish_clicked
        )
        # 定时 C3：ARM 就绪后、FIRE 前再证开关/值/时效。
        await self._verify_schedule_before_fire(page)
        await _fire_publish(
            page, budget=budget, humanizer=humanizer, mode=mode
        )
        # 派发成功后置位；结果观察与分类都从这里现取。
        publish_clicked = True
        await _observe_publish(
            page,
            budget=budget,
            publish_clicked=publish_clicked,
            mode=mode,
        )
        xiaohongshu_logger.success(_msg("🥳", "视频发布成功，小人开心收工"))

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
        log_local_session_ready(
            headless=self.headless, account_file=self.account_file
        )

        try:
            await self.upload_in(
                BrowserSession(browser=browser, context=context, mode="local")
            )
            await save_storage_state_atomic(context, self.account_file)
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
        # 显式标题原样保留（超限在校验期拒绝，绝不静默截断）；自动推导标题
        # 按同一平台口径截到 ≤20，并在校验期补一条 warning。
        explicit = bool(title and str(title).strip())
        if explicit:
            self.title = title
            self._title_explicit = True
            self._title_auto_truncated = False
        else:
            derived = self.desc or self.note or ""
            self.title = xhs_truncate_title(derived, XHS_TITLE_MAX_LENGTH)
            self._title_explicit = False
            self._title_auto_truncated = self.title != derived

    async def validate_upload_args(self, *, check_cookie: bool = True):
        await self.validate_base_args(check_cookie=check_cookie)
        if not self.image_paths:
            raise ValueError("图文模式下，图片是必须的")
        if not self.title or not str(self.title).strip():
            raise ValueError("图文模式下，title 是必须的")

        if getattr(self, "_title_explicit", True):
            validate_title_length(self.title)
        elif getattr(self, "_title_auto_truncated", False):
            xiaohongshu_logger.warning(
                _msg(
                    "✂️",
                    f"自动推导标题超出上限，已按平台口径截到 "
                    f"{XHS_TITLE_MAX_LENGTH} 字: {self.title}",
                )
            )

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

        # 首次交互前的一次性 DOM 静默门 + 已知覆盖层清障（spec §3 U3 D）。
        await _run_dom_quiet_gate(page, budget=budget)
        await _clear_known_overlays(page, XHS_OVERLAY_RULES, budget=budget)

        xiaohongshu_logger.info(_msg("📤", "小人正在逐张上传图片"))
        await _note_upload_gate(
            page,
            self.image_paths,
            budget=budget,
            mode=mode,
            humanizer=humanizer,
        )

        xiaohongshu_logger.info(_msg("✍️", "小人开始填标题、描述和话题"))
        await self.fill_meta(page, humanizer=humanizer)

        await self.apply_declarations(page, humanizer=humanizer)

        if self.publish_strategy == XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED and self.publish_date != 0:
            await self.set_schedule_time_xiaohongshu(
                page, self.publish_date, humanizer=humanizer
            )

        if self.no_publish:
            # 干跑升级为「跑到 ARM 就绪」：跳过 --not-before 等待，
            # 但仍执行 C1/C2/C3 与定时回读；不进入 FIRE。
            await _check_blocked(page, mode, publish_attempted=publish_clicked)
            await _wait_for_arm(
                page, budget=budget, mode=mode, publish_clicked=publish_clicked
            )
            await self._verify_schedule_before_fire(page)
            xiaohongshu_logger.success(
                _msg("🧪", "ARM 就绪，--no-publish 停在发布按钮前（未点击发布）")
            )
            return

        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=xiaohongshu_logger,
            label="小红书发布",
        )

        # C3：--not-before 等待之后、ARM 之前必查（未派发）。
        await _check_blocked(page, mode, publish_attempted=publish_clicked)
        await _wait_for_arm(
            page, budget=budget, mode=mode, publish_clicked=publish_clicked
        )
        # 定时 C3：ARM 就绪后、FIRE 前再证开关/值/时效。
        await self._verify_schedule_before_fire(page)
        await _fire_publish(
            page, budget=budget, humanizer=humanizer, mode=mode
        )
        # 派发成功后置位；结果观察与分类都从这里现取。
        publish_clicked = True
        await _observe_publish(
            page,
            budget=budget,
            publish_clicked=publish_clicked,
            mode=mode,
        )
        xiaohongshu_logger.success(_msg("🥳", "图文发布成功，小人开心收工"))

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
        log_local_session_ready(
            headless=self.headless, account_file=self.account_file
        )

        try:
            await self.upload_in(
                BrowserSession(browser=browser, context=context, mode="local")
            )
            await save_storage_state_atomic(context, self.account_file)
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
