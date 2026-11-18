"""Instagram 独立网页会话及照片、轮播、Reels 发布。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from loguru import logger
from patchright.async_api import Error as BrowserError
from patchright.async_api import (
    BrowserContext,
    Locator,
    Page,
    TimeoutError as BrowserTimeoutError,
    async_playwright,
    expect,
)

from uploader.meta_uploader.insgraph_uploader.controls import (
    resolve_instagram_option_controls,
)
from uploader.meta_uploader.insgraph_uploader.controls._rows import (
    dismiss_suggestions,
)
from uploader.meta_uploader.insgraph_uploader.options import (
    APPLY_ORDER,
    DEFAULT_OFF,
    INELIGIBLE,
    MISMATCH,
    MISSING,
    PRESENT,
    SET,
    UNSUPPORTED,
    InstagramPublishOptions,
    OptionMismatchError,
    empty_option_record,
    instagram_caption,
    option_failures,
    option_kind,
    option_status,
    requested_option,
    validate_publish_options,
)
from uploader.publish_timeout import PublishTimeoutBudget
from utils.local_account import local_account_alias
from utils.browser_cleanup import close_browser_resources
from utils.browser_session import BrowserSession
from utils.local_browser_session import local_browser_session
from utils.dom import ElementUnusableError, check, reject_ambiguous, visible_element_snapshot
from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.humanize import Humanizer
from utils.humanize import maybe_dispatched

INSTAGRAM_HOME_URL = "https://www.instagram.com/"
_INSTAGRAM_HOSTS = {"www.instagram.com", "instagram.com"}
# 未配置环境变量或 --proxy 时使用系统直连。
INSTAGRAM_PROXY = os.environ.get("SAU_INSTAGRAM_PROXY")
# 创建弹窗在选素材阶段只有一个 file input（编辑页的封面 input 此时尚未挂载）。
# 用类型定位而不是 accept 文案顺序，避免 accept 改成仅 quicktime/仅图片时失效。
INSTAGRAM_MEDIA_INPUT = 'input[type="file"]'
# Observed header buttons have role/tabindex but no dedicated stable action
# attribute. Scope exact accessible names to the dialog AND the expected stage;
# a premature Share must never be treated as an editor's Next.
INSTAGRAM_PRIMARY_ACTION_NAME = re.compile(r'^(Share|Post|分享|发布)$', re.IGNORECASE)
INSTAGRAM_NEXT_ACTION_NAME = re.compile(r'^(Next|下一步|继续)$', re.IGNORECASE)
# 可选提示的明确关闭文案；未命中时退回对话框最后一个按钮。
PROMPT_DISMISS_TEXT = re.compile(
    r'^(Not Now|Not now|Later|OK|Got it|Continue|以后再说|稍后|暂不|知道了|好的|关闭|取消)$',
    re.IGNORECASE,
)
# 配文页独有 Lexical 编辑器；data-lexical-editor 缺失时仍可凭 contenteditable+textbox 回退。
INSTAGRAM_CAPTION_EDITOR = (
    '[contenteditable="true"][role="textbox"][data-lexical-editor="true"]'
)
INSTAGRAM_CAPTION_EDITOR_FALLBACK = '[contenteditable="true"][role="textbox"]'
# 视频编辑页的封面入口只接受图片，且 accept 顺序不保证；按“含图片、不含视频”定位，
# 并保留精确 accept 顺序作为旧版回退。
INSTAGRAM_COVER_INPUT = (
    'input[type="file"][accept*="image/jpeg"]:not([accept*="video"])'
)
INSTAGRAM_COVER_INPUT_FALLBACK = 'input[type="file"][accept="image/jpeg,image/png"]'
# 并集同时等待两种写法；CSS 会去重，同一元素只计一次，数量哨兵仍有效。
INSTAGRAM_COVER_INPUTS = (
    f'{INSTAGRAM_COVER_INPUT}, {INSTAGRAM_COVER_INPUT_FALLBACK}'
)
# 创建入口只用已观察的链接与图标语义；缺失或歧义时失败，不猜导航次序。
INSTAGRAM_CREATE_ENTRY_LABELS = ('New post', 'Create', '新帖子', '创建')
# Observed creator submenus have no menu role/test id. The Chinese layout uses
# an exposed anchor; the English layout uses a plain div with a Post SVG.
# Match both in one union so duplicate/mixed-language candidates fail safely.
INSTAGRAM_POST_ENTRY = (
    'div[aria-hidden="false"] a[href="#"]:has(svg[aria-label="帖子"]), '
    'svg[aria-label="Post"]'
)

INSTAGRAM_LOGIN_CHECK_TIMEOUT_MS = 20_000
INSTAGRAM_LOGIN_OUTCOME_TIMEOUT_MS = 8_000
# 与 TikTok 对齐：整条上传/发布流程共用 15 分钟总预算。
_INSTAGRAM_PRE_PUBLISH_TIMEOUT_MESSAGE = (
    "Instagram 发布超时（15 分钟）：尚未点击发布，未发布任何内容。"
)
_INSTAGRAM_PUBLISH_RESULT_UNKNOWN_MESSAGE = (
    "Instagram 发布结果未知：发布点击已发出，但未等到最终作品创建响应；"
    "帖子可能已经发布。\n"
    "禁止自动重发。请先到 Instagram 个人主页按配文与发布时间核对；"
    "已存在则不要重发，不存在才可人工重试。"
)

# Retain historical managed-session inputs for identical ignored-option logs.
# Local sessions use only the shared native configuration plus the local proxy.
INSTAGRAM_LAUNCH_KWARGS: dict[str, object] = {"channel": "chrome"}
# These are ignored by managed providers and never applied to local Profiles.
INSTAGRAM_CONTEXT_KWARGS: dict[str, object] = {
    "locale": "en-US",
    "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
}
INSTAGRAM_INIT_SCRIPT = False

_INSTAGRAM_LOGIN_PATH = re.compile(
    r'^/(?:accounts/login|(?:accounts/)?emailsignup|challenge|checkpoint|two_step)(?:/|$)'
)


def _raise_if_login_required(page: Page, *, publish_attempted: bool = False, managed: bool = True) -> None:
    """Map a mid-upload login/challenge/2FA redirect to ``LoginRequiredError``.

    ``publish_attempted`` must be true when the redirect is observed after the
    publish click was dispatched.
    """
    url = urlparse(str(getattr(page, "url", "") or ""))
    path = url.path.lower()
    if url.hostname in _INSTAGRAM_HOSTS and _INSTAGRAM_LOGIN_PATH.match(path):
        verification = path.startswith(('/challenge', '/checkpoint', '/two_step'))
        message = ('Instagram 上传过程中需要重新登录（登录页/验证码/二次验证）：'
                   '请在 Multilogin 应用中登录 Profile 后重试。' if managed else
                   'Instagram 需要重新登录或完成验证：请运行 sau instagram login --account <别名> 完成登录或验证，再重新执行命令。')
        raise LoginRequiredError(
            message,
            reason='verification' if verification and not managed else 'login',
            publish_attempted=publish_attempted,
        )


async def _dismiss_optional_prompt(
    guide: Locator,
    dismiss_button: Locator,
    *,
    humanizer: Humanizer | None = None,
) -> bool:
    """仅关闭已识别的可选提示；缺席可继续，出现后的操作失败必须报错。

    关闭动作是可见点击，走 ``Humanizer.click``。独立调用（测试）未传实例时按
    按钮所属 page 自建一个，仍不退回原生点击。
    """
    try:
        await guide.wait_for(state='visible', timeout=1500)
    except BrowserTimeoutError:
        return False
    await expect(dismiss_button).to_have_count(1)
    if humanizer is None:
        humanizer = Humanizer(dismiss_button.page)
    await humanizer.click(dismiss_button)
    await guide.wait_for(state='hidden')
    return True


def _proxy_options(proxy: str | None) -> dict[str, str] | None:
    """未传参数时使用显式环境配置，否则直连；空字符串可覆盖环境配置并直连。"""
    address = (INSTAGRAM_PROXY if proxy is None else proxy) or ""
    address = address.strip()
    return {"server": address} if address else None


async def _first_present(primary: Locator, fallback: Locator) -> Locator:
    """返回首个已挂载的候选 locator；未挂载时返回 fallback。

    返回的是未取 ``.first`` 的 locator：调用方的 ``to_have_count(1)`` 仍是
    真实的漂移哨兵，多匹配会失败而不是静默选中第一个。
    """
    try:
        if await primary.count():
            return primary
    except Exception:
        pass
    return fallback


async def _composer_heading(dialog: Locator) -> Locator:
    """返回向导标题：只按 role=heading 定位，不使用 hash 类名。"""
    return dialog.get_by_role('heading')


async def _primary_action(dialog: Locator, *, publish: bool = False) -> Locator:
    """Use the observed role/name fallback only within the expected composer stage."""
    name = INSTAGRAM_PRIMARY_ACTION_NAME if publish else INSTAGRAM_NEXT_ACTION_NAME
    return dialog.get_by_role('button', name=name)


async def _caption_editor(dialog: Locator) -> Locator:
    """返回配文编辑器；Lexical 标记缺失时退回 contenteditable 文本框。"""
    return await _first_present(
        dialog.locator(INSTAGRAM_CAPTION_EDITOR),
        dialog.locator(INSTAGRAM_CAPTION_EDITOR_FALLBACK),
    )


async def _require_unique(
    locator: Locator, *, what: str, role: str = 'editable'
) -> None:
    """文本点先收窄到 ``count() == 1``；多义直接硬错，绝不自动取首个。"""
    try:
        count = await locator.count()
    except Exception as error:
        raise ElementUnusableError(
            what=what, role=role, reason='probe-failed'
        ) from error
    if count != 1:
        raise ElementUnusableError(what=what, role=role, reason=f'ambiguous:{count}')


async def _type_caption(
    editor: Locator, caption: str, humanizer: Humanizer
) -> None:
    """清空 Lexical 配文框后逐字写入；``after_type`` 只由 ``type_text`` 付一次。

    清空用 ``sel`` 形态（聚焦 → 全选 → Delete），不 ``fill()``、不粘贴；多行
    文本先把 ``\\r\\n`` 归一成 ``\\n``。>1000 码点由共享层整段 ``insert_text``。
    """
    await _require_unique(editor, what='Instagram 配文')
    text = str(caption).replace('\r\n', '\n').replace('\r', '\n')
    await editor.focus()
    await humanizer.press('ControlOrMeta+A')
    await humanizer.press('Delete')
    await humanizer.type_text(text)


# 配文回读：比较渲染文本（``innerText``）而非 ``textContent``。逐字输入把
# ``\n`` 打成 Enter，Lexical 在段间插 ``<br><br>``：``textContent`` 把两行
# 直接粘在一起，``innerText`` 才保留换行。轮询上限沿用原 ``to_have_text``。
CAPTION_READBACK_TIMEOUT_MS = 30_000
CAPTION_READBACK_POLL_MS = 200


def _normalise_caption_text(text: str) -> str:
    """比较前统一换行并去掉尾部空白；两侧走同一规则。"""
    return str(text).replace('\r\n', '\n').replace('\r', '\n').rstrip()


async def _read_back_caption(
    editor: Locator,
    caption: str,
    *,
    page: Page,
    budget: PublishTimeoutBudget,
) -> None:
    """轮询编辑器的渲染文本，直到与键入的配文**全等**（逐字哨兵）。

    真机 2026-11-13（ticket 05，``--no-publish`` 视频干跑）：键入本身正确，
    旧的 ``to_have_text`` 读 ``textContent`` 丢了 ``<br><br>`` 的换行而误报。
    只换读取形态，不放松比较：丢字、追加、换行丢失都照常失败
    （``AssertionError``；stage ``publish``，退出 1，未发布任何内容）。
    探测异常照常向上抛，绝不因探测失败而放行。
    """
    expected = _normalise_caption_text(caption)
    timeout_ms = budget.clamp_ms(CAPTION_READBACK_TIMEOUT_MS)
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        actual = _normalise_caption_text(await editor.inner_text())
        if actual == expected:
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                'Instagram 配文回读不一致：'
                f'期望 {expected!r}，实际 {actual!r}'
            )
        await page.wait_for_timeout(CAPTION_READBACK_POLL_MS)


async def _click_nav(locator: Locator, humanizer: Humanizer) -> None:
    """可见导航点击：先悬停让左栏展开落定，再坐标点击，付一次 ``after_navigate``。

    真机 2026-11-13（ticket 05，``--no-publish`` 视频干跑）：Instagram 左侧导航
    栏悬停即展开，目标包围盒在移动与 stillOn 复核之间位移 >1px，首个导航点击即
    报 ``point-drift``。spec §2.5.1 的唯一处方是在调用点先 ``Humanizer.hover()``
    再 ``click``（同小红书 ``.cover-edit-entry`` 模式）；``Humanizer.click`` 内部
    零重试、零容差改动，hover 后仍遮挡则照常硬失败。
    """
    await humanizer.hover(locator)
    await humanizer.click(locator)
    await humanizer.after_navigate()


async def _click_submit(locator: Locator, humanizer: Humanizer) -> None:
    """提交点击：``before_submit`` 必须先于鼠标按下。"""
    await humanizer.before_submit()
    await humanizer.click(locator)


async def _create_entry(page: Page, *, budget: PublishTimeoutBudget | None) -> Locator:
    """Select the observed create icon across labels; never guess a rail position."""
    # A union counts every matching anchor, including different language labels.
    # Returning the first matching label would hide an ambiguous second entry.
    candidate = page.locator(', '.join(
        f'a[href="#"]:has(svg[aria-label="{label}" i])'
        for label in INSTAGRAM_CREATE_ENTRY_LABELS
    ))
    await reject_ambiguous(candidate, 'Instagram 创建入口')
    timeout_ms = budget.clamp_ms(30_000) if budget else 30_000
    await expect(candidate).to_have_count(1, timeout=timeout_ms)
    return candidate


async def _media_input(dialog: Locator) -> Locator:
    """按优先级返回创建弹窗的素材入口。

    先认视频/多选这两个实测属性；accept 或 multiple 变化时退回任意 file input。
    返回具体选择器而不是 ``.first``，让调用方的 ``to_have_count(1)`` 保持哨兵作用。
    """
    for selector in (
        'input[type="file"][accept*="video/"]',
        'input[type="file"][multiple]',
        INSTAGRAM_MEDIA_INPUT,
    ):
        candidate = dialog.locator(selector)
        try:
            if await candidate.count():
                return candidate
        except Exception:
            continue
    return dialog.locator(INSTAGRAM_MEDIA_INPUT)


async def _own_profile_link(page: Page) -> Locator:
    """返回当前用户导航主页；导航选中容器缺失时退回头像 alt 文案。"""
    return await _first_present(
        page.locator('a[href]').filter(
            has=page.locator('[aria-selected] img')
        ),
        # 只在导航区域内退回头像 alt，避免命中动态流里其他用户的头像。
        page.locator('nav a[href], [role="navigation"] a[href]').filter(
            has=page.locator(
                'img[alt*="profile picture" i], img[alt*="profile photo" i], '
                'img[alt*="头像"]'
            )
        ),
    )


async def _instagram_dom_login_outcome(page: Page) -> bool | None:
    """Return logged-out state, or None while the page has no conclusive visible evidence."""
    controls = page.locator(
        'a[href^="/direct/inbox/"], a[href^="/accounts/login/"], '
        'input:is([name="username"],[name="email"]):is(:not([type]),[type="text" i],[type="email" i]), '
        'input[type="password"][name="pass"]'
    )
    markers = await visible_element_snapshot(controls, """nodes => {
        const forms = new Map();
        return nodes.map(node => {
            if (node.tagName === 'A') {
                return [node.pathname.startsWith('/direct/inbox/') ? 'inbox' : 'login', null];
            }
            if (node.form && !forms.has(node.form)) forms.set(node.form, forms.size);
            return [node.name, forms.get(node.form) ?? null];
        });
    }""")
    if any(kind == 'inbox' for kind, _ in markers):
        return False
    if any(kind in ('username', 'login') for kind, _ in markers):
        return True
    email_forms = {form for kind, form in markers if kind == 'email' and form is not None}
    if any(kind == 'pass' and form in email_forms for kind, form in markers):
        return True
    return None


async def _is_instagram_logged_out(page: Page, *, timeout_ms: int = 60_000) -> bool:
    """等待明确登录/未登录业务区域；网络或未知页面超时不能解释为登录失效。"""
    async def wait_for_outcome():
        while True:
            path = _instagram_path(page)
            if _INSTAGRAM_LOGIN_PATH.match(path):
                return True
            outcome = await _instagram_dom_login_outcome(page)
            if path != _instagram_path(page):
                continue
            if outcome is not None:
                return outcome
            await asyncio.sleep(0.1)

    try:
        return await asyncio.wait_for(wait_for_outcome(), timeout=timeout_ms / 1000)
    except asyncio.TimeoutError as exc:
        raise RuntimeError('Instagram 页面未出现可确认登录状态的元素') from exc


def _instagram_path(page: Page) -> str:
    url = urlparse(page.url)
    if url.hostname not in _INSTAGRAM_HOSTS:
        raise RuntimeError('Instagram 登录检查未停留在 instagram.com')
    return url.path.lower()


async def is_logged_in(context: BrowserContext) -> bool:
    """Return whether the Multilogin Profile is logged in to Instagram.

    Only ``context.new_page()`` / ``goto`` / ``close`` are used.  Explicit login,
    challenge and 2FA pages return ``False``; network failures, 5xx responses,
    timeouts and unexpected redirects raise.

    No ``.identity.json`` read or account-id comparison happens here: in
    Multilogin mode the Profile is the identity.

    Worst-case budget: 20s navigation + 8s outcome wait, inside 15-30s.
    """
    page = await context.new_page()
    try:
        response = await page.goto(
            INSTAGRAM_HOME_URL,
            wait_until="domcontentloaded",
            timeout=INSTAGRAM_LOGIN_CHECK_TIMEOUT_MS,
        )
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"Instagram 登录状态检查失败：HTTP {status}")

        return not await _is_instagram_logged_out(
            page, timeout_ms=INSTAGRAM_LOGIN_OUTCOME_TIMEOUT_MS
        )
    finally:
        await close_browser_resources(page=page)


async def _multilogin_identity(page: Page, context: BrowserContext) -> dict:
    """Read the live session's own user; never reads ``.identity.json``.

    Multilogin mode treats the Profile as the identity, so there is no account
    file to compare against.  The live user id is still needed to verify that
    the creation response belongs to the session that submitted it.
    """
    cookies = await context.cookies(INSTAGRAM_HOME_URL)
    user_ids = {c["value"] for c in cookies if c.get("name") == "ds_user_id"}
    if len(user_ids) != 1:
        raise RuntimeError("Instagram 当前会话缺少唯一用户 ID")
    own_profile = await _own_profile_link(page)
    await expect(own_profile).to_have_count(1)
    href = await own_profile.get_attribute('href')
    username = urlparse(href).path.strip('/')
    if not username or '/' in username:
        raise RuntimeError("Instagram 当前用户主页链接结构不符")
    return {"user_id": next(iter(user_ids)), "username": username}


async def _navigate_local_page(page: Page, url: str = INSTAGRAM_HOME_URL, *, timeout=120_000):
    response = await page.goto(url, wait_until='domcontentloaded', timeout=timeout)
    status = getattr(response, 'status', None)
    if isinstance(status, int) and status >= 500:
        raise RuntimeError(f'Instagram 页面请求失败：HTTP {status}')
    _instagram_path(page)


async def instagram_identity(page: Page, account_file=None) -> dict:
    """Read the current positive login identity; aliases never bind a user ID."""
    _raise_if_login_required(page, managed=False)
    if await _is_instagram_logged_out(page, timeout_ms=INSTAGRAM_LOGIN_OUTCOME_TIMEOUT_MS):
        raise LoginRequiredError("Instagram 未登录；请执行 sau instagram login --account <别名>。")
    identity = await _multilogin_identity(page, page.context)
    if not isinstance(identity['user_id'], str) or not re.fullmatch(r'[1-9][0-9]*', identity['user_id']):
        raise RuntimeError('Instagram 当前会话用户 ID 格式无效')
    return identity


async def instagram_cookie_auth(account_file=None, *, account_name=None, proxy=None,
                                headless=None, local_browser=None) -> bool:
    """Check the selected local Profile, with no legacy credential I/O."""
    account = _account_alias(account_file, account_name)
    async with async_playwright() as playwright:
        async with local_browser_session(
            playwright, platform='instagram', account=account,
            headless=headless, local_browser=local_browser,
            context_kwargs={'proxy': _proxy_options(proxy)},
        ) as session:
            page = await session.context.new_page()
            await _navigate_local_page(page, timeout=INSTAGRAM_LOGIN_CHECK_TIMEOUT_MS)
            await instagram_identity(page)
            return True


def _account_alias(account_file=None, account_name=None):
    return local_account_alias(account_file, account_name, platform="instagram")


async def instagram_setup(account_file=None, *, handle=False, proxy=None, headless=None,
                          return_detail=False, timeout_seconds=900, account_name=None,
                          local_browser=None):
    """Only login may create a Profile and wait for human authentication."""
    account = _account_alias(account_file, account_name)
    if not handle:
        valid = await instagram_cookie_auth(account_name=account, proxy=proxy,
                                            headless=headless, local_browser=local_browser)
        result = {'success': valid, 'status': 'valid', 'account': account}
        return result if return_detail else valid
    async with async_playwright() as playwright:
        async with local_browser_session(
            playwright, platform='instagram', account=account, create=True,
            headless=headless, local_browser=local_browser,
            context_kwargs={'proxy': _proxy_options(proxy)},
        ) as session:
            page = await session.context.new_page()
            await _navigate_local_page(page, INSTAGRAM_HOME_URL + 'accounts/login/')
            try:
                await page.locator('a[href^="/direct/inbox/"]').wait_for(state='visible', timeout=timeout_seconds * 1000)
            except BrowserTimeoutError:
                _raise_if_login_required(page, managed=False)
                raise
            await instagram_identity(page)
            result = {'success': True, 'status': 'logged_in', 'account': account}
            return result if return_detail else True


def instagram_response_payload(body: str) -> dict:
    """解析已观察的普通 JSON 以及 Meta 防 JSON 劫持前缀，其他格式直接报错。"""
    if body.startswith('for (;;);'):
        body = body[len('for (;;);'):]
    return json.loads(body)


def instagram_created_media(payload: dict, *, owner_id: str, caption: str) -> dict:
    """只接受最终创建响应中匹配用户和配文的作品；处理中和 HTTP 200 均不是成功。"""
    envelope = payload
    payload = envelope.get('payload', envelope)
    if envelope.get('error') or payload.get('status') not in (None, 'ok') or ('statusCode' in payload and payload['statusCode'] != 200):
        raise RuntimeError(f"Instagram 创建未成功: {payload.get('message', payload.get('statusCode', payload.get('status')))}")
    media = payload.get('media') or {}
    if not media.get('code') or not media.get('id'):
        raise RuntimeError('Instagram 创建响应缺少作品编号')
    if str((media.get('user') or {}).get('pk')) != owner_id:
        raise RuntimeError('Instagram 创建响应的作者 ID 不匹配')
    if (media.get('caption') or {}).get('text') != caption:
        raise RuntimeError('Instagram 创建响应的配文不匹配')
    return media


class InstagramUploader:
    """独立网页立即发布；最终创建响应确认成功后返回作品链接。"""

    def __init__(self, account_file: str | Path | None = None, *, title: str, description: str = '', tags: list[str] | None = None,
                 video_file: str | Path | None = None, image_files: list[str | Path] | None = None,
                 thumbnail: str | Path | None = None,
                 proxy: str | None = None, headless: bool | None = None, account_name=None, local_browser=None, result_file: str | Path | None = None,
                 options: InstagramPublishOptions | None = None, no_publish: bool = False):
        self.account_file = account_file
        self.account_name, self.local_browser = account_name, local_browser
        self.title, self.description = title.strip(), description.strip()
        self.tags = [t.strip().lstrip('#') for t in (tags or []) if t.strip().lstrip('#')]
        self.video_file = Path(video_file) if video_file else None
        self.image_files = [Path(p) for p in (image_files or [])]
        self.thumbnail = Path(thumbnail) if thumbnail else None
        self.options = options
        # 干跑：表单与选项全部完成后停在 Share 前，不点击、不观察结果。
        self.no_publish = bool(no_publish)
        # 发布点击是否真的发出：登录跳转的 publish_attempted 只认这个标志，
        # 不再由 status=submission_unknown 推断（提交前失败也会写那个状态）。
        self.publish_clicked = False
        self._managed = False
        if not self.title:
            raise ValueError('标题不能为空')
        # 素材互斥 / 封面适用性 / 配文长度统一走共享纯函数（UsageError → 退出码 2）。
        self._validate_publish_options()
        self.proxy, self.headless = proxy, headless
        self.result_file = Path(result_file) if result_file else Path('.local/instagram-results') / f'{uuid4().hex}.json'
        self.result = {
            'platform': 'instagram',
            'title': self.title,
            'status': 'not_submitted',
            # 四项始终存在；未请求写 not_requested，任何一次选项处理后落盘。
            'options': empty_option_record(self.options),
        }
        self.stage = 'validation'

    def _caption(self) -> str:
        """Instagram 只有配文，将 CLI 标题、正文和标签合并。"""
        return instagram_caption(self.title, self.description, self.tags)

    def _validate_publish_options(self) -> None:
        """spec §3.3 静态校验：构造与上传两处复用，避免绕过 CLI 时退回 ValueError。"""
        validate_publish_options(
            self.options,
            image_count=len(self.image_files),
            caption=self._caption(),
            has_video=bool(self.video_file),
            has_thumbnail=bool(self.thumbnail),
        )

    def _write_result(self) -> None:
        """落盘当前结果；输出字节与既有内联写法一致，且不吞异常。"""
        self.result_file.parent.mkdir(parents=True, exist_ok=True)
        self.result_file.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf-8')

    def start_publish_budget(self) -> PublishTimeoutBudget:
        self._publish_budget = PublishTimeoutBudget(
            "Instagram",
            pre_click_message=_INSTAGRAM_PRE_PUBLISH_TIMEOUT_MESSAGE,
            result_unknown_message=_INSTAGRAM_PUBLISH_RESULT_UNKNOWN_MESSAGE,
        )
        return self._publish_budget

    def _humanizer(self, page: Page) -> Humanizer:
        """一个 page 一个行为层实例：指针位置与随机流保持连续。"""
        cached = getattr(self, '_humanizer_instance', None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """行为层时延只吃剩余预算：耗尽时收缩到 0，从不自己抛超时。"""
        budget = getattr(self, '_publish_budget', None)
        remaining = (
            max(0.0, budget.remaining_seconds()) if budget is not None else seconds
        )
        if seconds > remaining and not getattr(self, '_pause_warned', False):
            logger.warning(
                "人类化停顿被预算裁剪: {}s > {}s",
                round(seconds, 2),
                round(remaining, 2),
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    def _notification_prompt(self, page: Page) -> Locator:
        """已知的通知提示：launcher 图标 + 对话框。

        提示可能在点击创建**之后**才出现（实测 2026-11-10），因此整个上传流程都
        注册 locator handler，并在等待创建弹窗时主动轮询关闭，避免它挡住裁剪页。
        图标只按文件名片段匹配，不绑定 /images/instagram 的完整路径。
        """
        return page.get_by_role('dialog').filter(
            has=page.locator('img[src*="launcher.png"]'))

    @staticmethod
    async def _dismiss_prompt(
        page: Page, prompt: Locator, *, humanizer: Humanizer | None = None
    ) -> bool:
        """关闭已识别的可选提示。

        通知提示是 “Turn On / Not Now”，Reels 介绍是 “Learn more / OK”：
        优先按明确的关闭文案，文案未命中时才退回“最后一个按钮”。两种结构里
        关闭动作都在最后，因此不依赖动作区 ``_a9-z`` hash 类名或固定 ``nth(1)``。
        """
        # 提示可能比调用点晚几百毫秒挂载：不要预先 count() 判缺席，
        # 交给 _dismiss_optional_prompt 的 visible 等待窗口。
        humanizer = humanizer or Humanizer(page)
        labeled = prompt.get_by_role('button', name=PROMPT_DISMISS_TEXT)
        if await labeled.count() == 1:
            return await _dismiss_optional_prompt(
                prompt, labeled, humanizer=humanizer
            )
        return await _dismiss_optional_prompt(
            prompt, prompt.get_by_role('button').last, humanizer=humanizer
        )

    async def _register_notification_handler(self, page: Page) -> Locator:
        """注册覆盖整个发布流程的通知提示 handler，返回提示 locator 供轮询复用。

        提示可能在点击创建**之后**才出现，会挡住裁剪、编辑与配文阶段；因此只由
        ``_upload_steps`` 注册一次，直到流程结束才移除。``_upload_files`` 用返回的
        同一个 locator 主动轮询，避免素材入口被延迟出现的提示卡住。
        """
        notifications = self._notification_prompt(page)
        await page.add_locator_handler(
            notifications,
            lambda: self._dismiss_prompt(
                page, notifications, humanizer=self._humanizer(page)
            ),
        )
        return notifications

    async def _upload_files(self, page: Page, *, budget: PublishTimeoutBudget) -> None:
        """打开创建入口并等待裁剪阶段就绪，拒绝用上传后固定延时推断完成。"""
        budget.check_pre_click()
        humanizer = self._humanizer(page)
        # handler 由 _upload_steps 注册并覆盖后续阶段；这里只复用同一个 locator
        # 主动轮询，不能在此移除 handler，否则编辑与配文阶段失去保护。
        notifications = self._notification_prompt(page)
        dialog = page.get_by_role('dialog')
        entry = await _create_entry(page, budget=budget)
        await expect(entry).to_have_count(
            1, timeout=budget.clamp_ms(30_000)
        )
        await _click_nav(entry, humanizer)
        # 创建弹窗可能被延迟出现的通知提示遮挡：轮询期间主动关闭已知提示，
        # 直到素材入口真的可操作；只有超时才报错，不添加固定等待。
        deadline = time.monotonic() + budget.clamp_ms(30_000) / 1000
        post_menu_selected = False
        while True:
            if await notifications.count():
                await self._dismiss_prompt(
                    page, notifications, humanizer=humanizer
                )
            file_input = await _media_input(dialog)
            media_count = await reject_ambiguous(file_input, 'Instagram 素材入口', role='attached')
            post_entry = page.locator(INSTAGRAM_POST_ENTRY)
            post_count = await reject_ambiguous(post_entry, 'Instagram 创建菜单帖子入口')
            if media_count:
                if post_count:
                    raise RuntimeError('Instagram 创建状态不明确：素材编辑器与帖子菜单同时出现')
                break
            if post_count and not post_menu_selected:
                # Account UI is observed per page, never inferred from alias or
                # browser provider. Ordinary accounts open the composer directly.
                budget.check_pre_click()
                # Humanized clicks scroll, move, then check before mouse.down;
                # a separate humanized hover can move the expanded submenu.
                # Retry only failures known to precede dispatch, within this
                # existing deadline. Never repeat a possibly dispatched click.
                try:
                    if not humanizer.enabled:
                        # Native hover scrolls/moves without clicking. Check
                        # afterwards: pointerenter may disable the container,
                        # and a screen hit test before scrolling would block it.
                        await humanizer.hover(post_entry)
                        usable, reason = await check(post_entry, 'interactive')
                        if not usable:
                            raise ElementUnusableError(
                                'Instagram 创建菜单帖子入口', role='interactive',
                                reason=reason or 'probe-failed',
                            )
                    await humanizer.click(post_entry)
                except ElementUnusableError as error:
                    if error.reason.startswith('ambiguous:') or maybe_dispatched(error):
                        raise
                    logger.warning(
                        'Instagram 创建菜单 Post 点击暂不可用（{}）；继续轮询',
                        error.reason,
                    )
                else:
                    post_menu_selected = True
                    await humanizer.after_navigate()
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    'Instagram 创建弹窗未出现素材入口（可能被未知弹窗遮挡）'
                )
            await page.wait_for_timeout(200)
        await expect(dialog).to_have_count(
            1, timeout=budget.clamp_ms(30_000)
        )
        await expect(file_input).to_have_count(
            1, timeout=budget.clamp_ms(30_000)
        )
        paths = [self.video_file] if self.video_file else self.image_files
        await file_input.set_input_files(  # native-click: file；不可坐标化的 <input type=file>
            [str(p.resolve()) for p in paths]
        )
        if self.video_file:
            # 实际 Reels 介绍使用 reels_nux_icon；只按素材名片段识别，关闭动作复用
            # “对话框最后一个按钮”，不依赖语言、hash 类名或父子层级。
            reels_intro = page.get_by_role('dialog').filter(
                has=page.locator('img[src*="reels_nux"]'))
            await self._dismiss_prompt(page, reels_intro, humanizer=humanizer)
        # 裁剪标题栏主动作实际出现，才可推进；上传失败或未知弹窗阻断会保留现场并报错。
        action = await _primary_action(dialog)
        await expect(action).to_have_count(
            1, timeout=budget.clamp_ms(60_000)
        )

    async def _advance_media_editor(self, page: Page, *, budget: PublishTimeoutBudget) -> None:
        """裁剪、编辑两步各等待标题改变，最终以 Lexical 配文输入框确认。"""
        humanizer = self._humanizer(page)
        # 同一个创建弹窗标题栏存在于三个阶段；局部主动作不含图标，排除返回和媒体工具按钮。
        dialog = page.get_by_role('dialog')
        heading = await _composer_heading(dialog)
        for step in range(2):
            budget.check_pre_click()
            if step == 1 and self.thumbnail:
                # 视频编辑弹窗里封面入口只接受图片；并集同时等待“含图片、不含视频”
                # 与实测精确顺序两种写法，避免入口晚挂载时一次性回退到旧选择器。
                cover = dialog.locator(INSTAGRAM_COVER_INPUTS)
                # 主预览的 video 紧邻封面背景层；右侧视频帧条也有背景图，不能拿帧条验证封面。
                poster = dialog.locator('video + div[style*="background-image"]')
                await expect(cover).to_have_count(
                    1, timeout=budget.clamp_ms(30_000)
                )
                await expect(poster).to_have_count(
                    1, timeout=budget.clamp_ms(30_000)
                )
                previous_style = await poster.get_attribute('style')
                await cover.set_input_files(  # native-click: file；封面入口是 <input type=file>
                    str(self.thumbnail.resolve())
                )
                await expect(poster).not_to_have_attribute(
                    'style', previous_style,
                    timeout=budget.clamp_ms(30_000),
                )
                # 已观察页面直接以原图 blob 替换封面。核对实际预览字节并解码，文件选中本身不代表生效。
                preview = await asyncio.wait_for(poster.evaluate('''async element => {
                    const background = getComputedStyle(element).backgroundImage;
                    const url = background.slice(5, -2);
                    const blob = await (await fetch(url)).blob();
                    const bitmap = await createImageBitmap(blob);
                    const digest = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer());
                    const result = {width: bitmap.width, height: bitmap.height,
                        sha256: Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')};
                    bitmap.close();
                    return result;
                }'''), timeout=budget.clamp_ms(30_000) / 1000)
                if not preview['width'] or not preview['height'] or preview['sha256'] != hashlib.sha256(self.thumbnail.read_bytes()).hexdigest():
                    raise RuntimeError('Instagram 封面主预览与指定图片不匹配')
            await expect(heading).to_have_count(
                1, timeout=budget.clamp_ms(30_000)
            )
            previous = await heading.inner_text()
            action = await _primary_action(dialog)
            await expect(action).to_have_count(
                1, timeout=budget.clamp_ms(30_000)
            )
            await expect(action).to_be_enabled(
                timeout=budget.clamp_ms(30_000)
            )
            await _click_nav(action, humanizer)
            await expect(heading).not_to_have_text(
                previous, timeout=budget.clamp_ms(60_000)
            )
        # data-lexical-editor 标识真实正文编辑器；缺失时退回 contenteditable 文本框，
        # 仍限定当前创建弹窗，避免命中评论输入框。
        editor = await _caption_editor(dialog)
        await expect(editor).to_have_count(
            1, timeout=budget.clamp_ms(30_000)
        )

    async def _log_option_outcome(self, key: str, page: Page | None) -> None:
        """入口缺失/不一致时打印页面语言，便于判断是否账号界面语言未固定。

        界面语言由 Profile 与站点决定；``html[lang]`` 是排查入口缺失的线索。
        """
        record = self.result['options'][key]
        if record['status'] not in (UNSUPPORTED, MISMATCH):
            return
        language = 'unknown'
        if page is not None:
            try:
                language = str(
                    await page.evaluate('document.documentElement.lang') or 'unknown'
                )
            except Exception:
                language = 'unknown'
        logger.warning(
            "Instagram 选项 {} 未生效（{}{}）；页面语言 html[lang]={}",
            key,
            record['status'],
            f"/{record['reason']}" if record.get('reason') else '',
            language,
        )

    def _record_option(
        self, key: str, requested, applied, status: str, reason: str | None = None
    ) -> None:
        """写入单项结果；reason 仅在需要归因时出现。"""
        record = {'requested': requested, 'applied': applied, 'status': status}
        if reason is not None:
            record['reason'] = reason
        self.result['options'][key] = record

    async def _apply_one_option(
        self, key: str, requested, control, *, budget: PublishTimeoutBudget
    ) -> str | None:
        """解析入口、回读、必要时设置并再次回读。

        返回 ``None`` 表示已按页面状态记录结果；返回错误文案表示控件明确判定
        请求无法表达（``OptionMismatchError``），结果已记为 ``mismatch``，文案
        并入管线聚合错误。其他异常交由管线兜底。
        """
        kind = option_kind(key)
        if control is None:
            status, reason = option_status(
                requested, None, kind=kind, presence=MISSING
            )
            self._record_option(key, requested, None, status, reason)
            return None
        presence = await control.resolve()
        if presence != PRESENT:
            status, reason = option_status(
                requested, None, kind=kind, presence=presence
            )
            # 入口不可用且请求的是“关闭”时，spec §5.2 要求记录实际状态（applied=false）；
            # 请求值/开启时该行为 null，且读取可能触发控件副作用，故不读。
            applied = None
            if presence == INELIGIBLE and kind == 'toggle' and requested is False:
                try:
                    applied = await control.read()
                except Exception:
                    applied = None
            self._record_option(key, requested, applied, status, reason)
            return None
        current = await control.read()
        status, reason = option_status(requested, current, kind=kind)
        if status in (SET, DEFAULT_OFF):
            # 页面已是目标状态：不点击，直接按状态归类（§4.2 幂等）。
            self._record_option(key, requested, current, status, reason)
            return None
        budget.check_pre_click()
        try:
            await control.set(requested)
            applied = await control.read()
        except OptionMismatchError as error:
            # 控件已确认无法表达请求：记录它读到的实际值，不中断后续选项。
            self._record_option(key, requested, error.applied, MISMATCH)
            return str(error) or type(error).__name__
        status, reason = option_status(
            requested, applied, kind=kind, presence=PRESENT, acted=True
        )
        self._record_option(key, requested, applied, status, reason)
        return None

    async def _apply_options(
        self, page: Page, *, budget: PublishTimeoutBudget, controls: dict | None = None
    ) -> None:
        """按 spec §4.2 顺序应用发布选项；未请求时零控件交互。"""
        if self.options is None:
            return
        if controls is None:
            controls = resolve_instagram_option_controls(
                page,
                image_count=len(self.image_files),
                budget=budget,
                humanizer=self._humanizer(page),
            )
        details: list[str] = []
        for key in APPLY_ORDER:
            requested = requested_option(self.options, key)
            if requested is None:
                continue
            budget.check_pre_click()
            try:
                detail = await self._apply_one_option(
                    key, requested, controls.get(key), budget=budget
                )
                if detail:
                    details.append(f'{key}: {detail}')
                await self._log_option_outcome(key, page)
            except LoginRequiredError:
                # 登录失效属于硬异常：立即中止，不再操作后续选项（退出 10）。
                raise
            except PublishResultUnknownError as error:
                # 点击发布前不可能“结果未知”；按普通失败中止，不能误报退出 9。
                raise RuntimeError(
                    f'Instagram 发布选项未生效: {key}: {error}'
                ) from error
            except Exception as error:
                # 预算耗尽同样必须中止（§7.2 B12）：check_pre_click 会在耗尽时抛错。
                budget.check_pre_click()
                self._record_option(key, requested, None, MISMATCH)
                details.append(f'{key}: {error}' if str(error) else f'{key}: {type(error).__name__}')
            finally:
                self._write_result()
        failures = option_failures(self.result['options']) + details
        if failures:
            raise RuntimeError('Instagram 发布选项未生效: ' + '; '.join(failures))

    async def _wait_until_publish_ready(
        self, action: Locator, *, budget: PublishTimeoutBudget
    ) -> None:
        """``--no-publish`` 就绪窗：Share 存在且可点，上限 ``min(60s, 剩余预算)``。

        与正常发布的就绪检查同源（同一个 ``_primary_action`` locator），但把
        “存在 + 可点”合并到一个截止时间。超时发生在点击前，所以必须是普通
        ``RuntimeError``（退出 1），不能映射成结果未知（退出 9）。
        """
        budget.check_pre_click()
        deadline = time.monotonic() + min(60, budget.remaining_seconds())
        while True:
            remaining = min(deadline - time.monotonic(), budget.remaining_seconds())
            if remaining <= 0:
                raise RuntimeError(
                    "Instagram 发布就绪超时（上限 60 秒或剩余预算）："
                    "Share 按钮未出现或不可用；尚未点击发布，未发布任何内容。"
                )
            count = await reject_ambiguous(action, "Instagram Share")
            if count == 1:
                try:
                    usable, _ = await asyncio.wait_for(
                        check(action, 'interactive'), timeout=min(0.2, remaining)
                    )
                    if usable:
                        return
                except (BrowserTimeoutError, asyncio.TimeoutError):
                    # The unique button may detach between count and probe;
                    # keep the whole multi-probe check inside the readiness budget.
                    pass
            await asyncio.sleep(min(0.2, remaining))

    async def _publish(
        self, page: Page, identity: dict, *, budget: PublishTimeoutBudget
    ) -> None:
        """先登记最终响应监听再分享，响应不明时记录 unknown 且不重发。"""
        humanizer = self._humanizer(page)
        # 配文页独有 Lexical 编辑器；标题栏唯一主动作此时是分享。
        dialog = page.get_by_role('dialog')
        editor = await _caption_editor(dialog)
        caption = self._caption()
        # 清空后逐字写入（>1000 码点整段 insert_text），随后按渲染文本回读。
        await _type_caption(editor, caption, humanizer)
        await _read_back_caption(editor, caption, page=page, budget=budget)
        # 真机 2026-11-13：逐字输入 #标签 弹出的 hashtag 联想浮层会盖住右侧
        # 选项面板（后续点击报 covered-by）。点标题栏关闭浮层，不改写正文；
        # 标题栏缺席时该 helper 静默跳过，不因此让发布失败。
        await dismiss_suggestions(dialog, humanizer)
        # 选项必须在点击 Share 之前完成；失败时尚未发布，按普通失败处理。
        if self.options is not None:
            # 未请求时保持既有 stage（legacy 失败证据不变）。
            self.stage = 'options'
        await self._apply_options(page, budget=budget)
        action = await _primary_action(dialog, publish=True)
        if self.no_publish:
            # 干跑：上传、配文与全部选项已完成后停在 Share 前；跳过
            # --not-before，不注册响应监听，也不进入结果观察循环。
            self.stage = 'publish'
            await self._wait_until_publish_ready(action, budget=budget)
            self.result['status'] = 'prepared'
            self._write_result()
            logger.info(
                "Instagram 发布就绪，--no-publish 停在 Share 前（未点击发布）"
            )
            return
        await self._wait_until_publish_ready(action, budget=budget)
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=logger,
            label="Instagram 发布",
        )
        budget.check_pre_click()
        if not getattr(self, '_managed', False):
            _raise_if_login_required(page, managed=False)
        # status 只是结果记录；点击是否派发由独立的 publish_clicked 标记。
        self.publish_clicked = False
        self.result.update(identity, status='submission_unknown')
        self._write_result()
        # Reel 首次返回 202，浏览器会继续请求同一创建接口，后续才返回正式 media。
        # 提交前安装队列监听，持续消费本次创建响应；只点击一次，不将上传响应或 202 视为发表成功。
        responses = asyncio.Queue()
        def on_response(response):
            if response.request.method == 'POST' and urlparse(response.url).path.startswith('/api/v1/media/configure'):
                responses.put_nowait(response)
        def on_close(_page):
            responses.put_nowait(budget.timeout_error(True))

        def on_navigation(frame):
            if frame == page.main_frame:
                try:
                    _raise_if_login_required(page, publish_attempted=True, managed=self._managed)
                except LoginRequiredError as error:
                    responses.put_nowait(error)

        page.on('response', on_response)
        page.on('close', on_close)
        page.on('framenavigated', on_navigation)
        try:
            try:
                await _click_submit(action, humanizer)
            except Exception as exc:
                if maybe_dispatched(exc):
                    # 发布点击可能已经发出：按结果未知上抛，禁止再次派发。
                    self.publish_clicked = True
                    raise budget.timeout_error(True) from exc
                raise
            # 点击已经返回：从这里开始的任何失败都算「结果可能已提交」。
            self.publish_clicked = True
            # 点击成功后只等最终创建响应；未拿到响应即超时，按结果未知处理，绝不重发。
            result_deadline = budget.deadline
            while True:
                remaining = result_deadline - time.monotonic()
                if remaining <= 0:
                    raise budget.timeout_error(True)
                try:
                    response = await asyncio.wait_for(
                        responses.get(), timeout=remaining
                    )
                    if isinstance(response, Exception):
                        raise response
                    remaining = result_deadline - time.monotonic()
                    if remaining <= 0:
                        raise budget.timeout_error(True)
                    text = await asyncio.wait_for(
                        response.text(), timeout=remaining
                    )
                except (asyncio.TimeoutError, BrowserError) as exc:
                    raise budget.timeout_error(True) from exc
                try:
                    payload = instagram_response_payload(text)
                    body = payload.get('payload', payload)
                    if body.get('statusCode') == 202:
                        self.result['status'] = 'processing'
                        self._write_result()
                        continue
                    media = instagram_created_media(
                        payload, owner_id=identity['user_id'], caption=caption
                    )
                    break
                except Exception as error:
                    # 点击已发出，无法确认最终作品时一律按结果未知处理，禁止重发。
                    raise budget.timeout_error(True) from error
        finally:
            page.remove_listener('response', on_response)
            page.remove_listener('close', on_close)
            page.remove_listener('framenavigated', on_navigation)
        kind = 'reel' if self.video_file else 'p'
        self.result.update(status='published', content_id=media['id'], post_id=media['code'],
                           post_url=f"{INSTAGRAM_HOME_URL}{kind}/{media['code']}/", schedule=None,
                           media_count=len(media.get('carousel_media') or [media]))
        self._write_result()

    def _validate_media(self) -> None:
        self._validate_publish_options()
        if self.thumbnail:
            if not self.thumbnail.is_file():
                raise FileNotFoundError(f'Instagram 封面不存在: {self.thumbnail}')
            if self.thumbnail.suffix.lower() not in {'.jpg', '.jpeg', '.png'}:
                raise ValueError('Instagram 封面仅支持 JPG/JPEG/PNG')
        paths = [self.video_file] if self.video_file else self.image_files
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f'Instagram 素材不存在: {path}')
            allowed = {'.mp4', '.mov'} if self.video_file else {'.jpg', '.jpeg', '.png', '.avif', '.heic', '.heif'}
            if path.suffix.lower() not in allowed:
                raise ValueError(f'Instagram 不支持的素材类型: {path.suffix}')

    async def _upload_steps(
        self, page: Page, identity: dict, *, budget: PublishTimeoutBudget
    ) -> dict:
        """注册全流程通知提示 handler，再执行上传、编辑与发布。"""
        budget.check_pre_click()
        # 实测通知提示可能在任一阶段弹出并挡住点击；整个流程保持同一个 handler，
        # 只处理已识别的提示，未知弹窗仍按失败处理。
        notifications = await self._register_notification_handler(page)
        try:
            return await self._upload_flow(page, identity, budget=budget)
        finally:
            try:
                await page.remove_locator_handler(notifications)
            except Exception as error:
                logger.warning("Instagram handler cleanup failed; preserving upload result: {}", error)

    async def _upload_flow(
        self, page: Page, identity: dict, *, budget: PublishTimeoutBudget
    ) -> dict:
        """按上传 → 编辑 → 配文发布三段推进，每段前检查发布预算。"""
        budget.check_pre_click()
        self.stage = 'upload'
        await self._upload_files(page, budget=budget)
        budget.check_pre_click()
        self.stage = 'edit'
        await self._advance_media_editor(page, budget=budget)
        budget.check_pre_click()
        self.stage = 'publish'
        if not getattr(self, '_managed', False):
            _raise_if_login_required(page, managed=False)
        await self._publish(page, identity, budget=budget)
        return self.result

    async def _capture_failure(self, page: Page, error: Exception) -> RuntimeError:
        folder = Path('.local/instagram-errors') / uuid4().hex
        folder.mkdir(parents=True)
        self.result.update(stage=self.stage, error=str(error), evidence_dir=str(folder))
        self._write_result()
        await page.screenshot(path=str(folder/'page.png'))
        (folder/'page.html').write_text(await page.content(), encoding='utf-8')
        return RuntimeError(f'Instagram {self.stage} 未完成；结果记录: {self.result_file}；原因: {error}')

    async def _capture_failure_safely(self, page: Page, error: Exception) -> None:
        """结果未知优先保留专用错误类型；现场保存失败不能覆盖退出码 9。"""
        try:
            await self._capture_failure(page, error)
        except Exception as capture_error:
            logger.warning(f"Instagram 失败现场保存失败: {capture_error}")

    async def upload_in(self, session: BrowserSession) -> dict:
        """Run in the caller-owned session without credential files or cleanup."""
        self._managed = session.managed
        # 预算从打开首页开始，覆盖登录检查、素材上传、编辑、配文与发布。
        budget = self.start_publish_budget()
        page = await session.context.new_page()
        page.set_default_timeout(30_000)
        if session.managed:
            await page.goto(INSTAGRAM_HOME_URL, wait_until='domcontentloaded', timeout=budget.clamp_ms(120_000))
        else:
            await _navigate_local_page(page, timeout=budget.clamp_ms(120_000))
        # 一个 page 一个行为层实例：在页面打开后立刻构造并缓存。
        self._humanizer(page)
        if session.managed:
            _raise_if_login_required(page)
            if await _is_instagram_logged_out(
                page, timeout_ms=INSTAGRAM_LOGIN_OUTCOME_TIMEOUT_MS
            ):
                raise LoginRequiredError(
                    'Instagram 登录态无效：请在 Multilogin 应用中登录 Profile 后重试。'
                )
        try:
            self.stage = 'identity'
            if session.managed:
                identity = await _multilogin_identity(page, session.context)
            else:
                identity = await instagram_identity(page)
            return await self._upload_steps(page, identity, budget=budget)
        except LoginRequiredError as error:
            if not session.managed:
                error.publish_attempted = error.publish_attempted or self.publish_clicked
                await self._capture_failure_safely(page, error)
            raise
        except PublishResultUnknownError as error:
            await self._capture_failure_safely(page, error)
            _raise_if_login_required(page, publish_attempted=self.publish_clicked, managed=session.managed)
            raise
        except Exception as error:
            if not session.managed:
                await self._capture_failure_safely(page, error)
            _raise_if_login_required(page, publish_attempted=self.publish_clicked, managed=session.managed)
            if session.managed:
                raise await self._capture_failure(page, error) from error
            raise

    async def upload(self, *, session: BrowserSession | None = None) -> dict:
        """在同一会话核验身份、上传并发表；失败保存阶段与本地证据。"""
        self._validate_media()
        if session is not None:
            return await self.upload_in(session)

        account = _account_alias(self.account_file, self.account_name)
        async with async_playwright() as playwright:
            async with local_browser_session(
                playwright, platform='instagram', account=account,
                headless=self.headless, local_browser=self.local_browser,
                context_kwargs={'proxy': _proxy_options(self.proxy)},
            ) as owned_session:
                return await self.upload_in(owned_session)
