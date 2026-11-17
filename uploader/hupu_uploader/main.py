# -*- coding: utf-8 -*-
"""虎扑视频上传与持久化 Profile 登录。

正式本地 login/check/upload 复用所选 Profile；旧 Cookie API 名称仅保留调用兼容，
不读写 JSON。发布页为 bbs.hupu.com/newpost?tabkey=2，专区为步行街主干道。
"""
from __future__ import annotations

import asyncio
import inspect
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from patchright.async_api import BrowserContext, Page, Playwright, async_playwright

import conf
from uploader.base_video import BaseVideoUploader
from utils.local_account import local_account_alias
from utils.browser_cleanup import close_browser_resources
from utils.browser_session import BrowserSession
from utils.dom import ElementMissingError, ElementUnusableError
from utils.errors import LoginRequiredError, PublishResultUnknownError
from utils.local_browser_session import local_browser_session
from utils.humanize import Humanizer
from utils.humanize import maybe_dispatched
from utils.log import hupu_logger


HUPU_HOME_URL = "https://www.hupu.com/"
HUPU_LOGIN_URL = "https://passport.hupu.com/v2/login?pcPhone=1&jumpurl=https://www.hupu.com&from=https://www.hupu.com"
HUPU_PUBLISH_URL = "https://bbs.hupu.com/newpost?tabkey=2"

# MLX 登录检测只打开一个页面；总预算 20s 导航 + 2.5s 稳定，落在 15-30s 规范内。
HUPU_LOGIN_CHECK_URL = HUPU_PUBLISH_URL
HUPU_LOGIN_CHECK_TIMEOUT_MS = 20_000
HUPU_LOGIN_CHECK_SETTLE_MS = 2_500

# 虎扑发布成功后跳转的帖子 URL 模式
HUPU_POST_URL_PATTERN = re.compile(r"bbs\.hupu\.com/\d+\.html")

_LOGIN_URL_MARKERS = ("passport.hupu.com", "/login", "login?", "captcha", "verify", "two-factor", "2fa")


def _msg(emoji: str, text: str) -> str:
    return f"{emoji} {text}"


def _normalise_text(text: str, *, multiline: bool) -> str:
    """多行先 ``\\r\\n``→``\\n``；单行字段不得含换行/制表符（会变成 Enter/Tab）。"""
    value = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    if multiline:
        return value
    return value.replace("\n", " ")


async def _narrow_unique(
    locator,
    what: str,
    *,
    role: str = "attached",
    required: bool = True,
):
    """把 ``locator`` 收窄到唯一匹配；多义硬错 ``ambiguous:N``，绝不 ``.first``。

    ``required=False`` 时 0 匹配返回 ``None``（虎扑的简介框 / AI 声明下拉
    允许缺席，调用方自己决定跳过）。多义在任何情况下都是硬错。
    """
    count = await locator.count()
    if count > 1:
        raise ElementUnusableError(
            what,
            role=role,
            reason=f"ambiguous:{count}",
            publish_clicked=False,
        )
    if count == 0:
        if required:
            raise ElementMissingError(what, role=role, publish_clicked=False)
        return None
    return locator


async def _emit_qrcode_callback(qrcode_callback, payload: dict):
    if not qrcode_callback:
        return
    callback_result = qrcode_callback(payload)
    if inspect.isawaitable(callback_result):
        await callback_result


def _build_launch_kwargs(headless: bool) -> dict:
    launch_kwargs = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if getattr(conf, "LOCAL_CHROME_PATH", ""):
        launch_kwargs["executable_path"] = conf.LOCAL_CHROME_PATH
    return launch_kwargs


def _account_alias(account_file=None, account_name=None):
    return local_account_alias(account_file, account_name, platform="hupu")


# Managed-only ignored options retain the historical provider startup logs.
# Persistent local sessions never consume these options or override fingerprints.
HUPU_LAUNCH_KWARGS = {
    key: value
    for key, value in _build_launch_kwargs(headless=False).items()
    if key != "headless"
}
HUPU_CONTEXT_KWARGS: dict = {}
HUPU_INIT_SCRIPT = False


def _raise_if_login_required(page: Page | None, *, publish_attempted: bool = False) -> None:
    """Map a mid-upload login/captcha/2FA redirect to ``LoginRequiredError``.

    Only managed sessions call this; local sessions use their own login guidance.
    ``publish_attempted`` must be true when the redirect is observed after the
    publish click was dispatched.
    """
    url = str(getattr(page, "url", "") or "").lower()
    if not url:
        return
    if any(marker in url for marker in _LOGIN_URL_MARKERS):
        raise LoginRequiredError(
            "虎扑上传过程中需要重新登录（登录页/验证码/二次验证）："
            "请在 Multilogin 应用中登录 Profile 后重试。",
            publish_attempted=publish_attempted,
        )


async def is_logged_in(context: BrowserContext, *, managed=True, account=None) -> bool:
    """Probe Hupu business evidence in the supplied Profile context.

    Managed probes close their page; local pages stay with their context owner. Positive
    signals (publish-page upload button or a logged-in user menu) decide True;
    an explicit login page/redirect returns False; network failures, 5xx
    responses, unexpected hosts and a page with no positive signal raise so the
    CLI can exit 1.
    """
    page = await context.new_page()
    try:
        try:
            response = await page.goto(
                HUPU_LOGIN_CHECK_URL, timeout=HUPU_LOGIN_CHECK_TIMEOUT_MS,
                wait_until="domcontentloaded",
            )
        except Exception:
            if not managed:
                _raise_local_login_required(page, account=account)
            raise
        if not managed:
            _check_local_response(response)
        status = getattr(response, "status", None)
        if isinstance(status, int) and status >= 500:
            raise RuntimeError(f"虎扑登录状态检查失败：HTTP {status}")

        wait_for_timeout = getattr(page, "wait_for_timeout", None)
        if wait_for_timeout is not None:
            await wait_for_timeout(HUPU_LOGIN_CHECK_SETTLE_MS)

        current_url = str(getattr(page, "url", "") or "")
        if not managed:
            reason = _local_login_reason(page)
            if reason == "verification":
                raise _local_login_error(account, reason=reason)
            if reason == "login":
                return False
        host = urlsplit(current_url).hostname or ""
        if ("hupu.com" not in current_url if managed else not (host == "hupu.com" or host.endswith(".hupu.com"))):
            raise RuntimeError(
                "虎扑登录状态检查失败：页面未停留在虎扑"
                f"（url={current_url or '<empty>'}）"
            )
        if "passport" in current_url.lower() or "login" in current_url.lower():
            return False

        upload_button = page.get_by_role("button", name="上传视频")
        if await upload_button.count():
            return True

        # 发布页布局变化时只允许改这里的正向选择器，不通过修改 Profile 规避。
        for selector in (".user-info", ".userInfo", ".avatar", "a[href*='/user/']"):
            if await page.locator(selector).count():
                return True

        raise RuntimeError(
            "虎扑登录状态检查失败：未找到上传按钮或已登录用户菜单（页面结构异常）"
        )
    finally:
        if managed:
            await close_browser_resources(page=page)


async def hupu_cookie_gen(account_file=None, qrcode_callback=None, poll_interval=3,
                          max_checks=120, headless=None, *, account_name=None, local_browser=None):
    """Guide login in the selected persistent Profile."""
    return await hupu_setup(account_file, handle=True, return_detail=True,
                            qrcode_callback=qrcode_callback, headless=headless,
                            account_name=account_name, local_browser=local_browser,
                            poll_interval=poll_interval, max_checks=max_checks)


async def _guide_login(context, account, *, qrcode_callback, poll_interval, max_checks):
    page = await context.new_page()
    response = await page.goto(HUPU_LOGIN_URL, timeout=60000, wait_until="load")
    _check_local_response(response)
    await page.wait_for_timeout(3000)
    qq_btn = page.get_by_role("button", name="qq QQ登录")
    if not await qq_btn.count():
        raise RuntimeError("虎扑登录失败：未找到 QQ 登录按钮")
    await qq_btn.click()  # native-click: login；QQ 扫码登录页保持原生点击
    await page.wait_for_timeout(5000)
    # QQ may navigate this page or open a popup. Both belong to this Profile.
    login_page = next((candidate for candidate in reversed(context.pages)
                       if "qq.com" in (urlsplit(candidate.url).hostname or "")), page)
    with tempfile.TemporaryDirectory(prefix="sau-hupu-qr-") as qr_root:
        qrcode_info = await _grab_qq_qrcode(login_page, context, str(Path(qr_root) / "login"))
        if qrcode_info:
            await _emit_qrcode_callback(qrcode_callback, qrcode_info)
            hupu_logger.info(_msg("🧍", "请用 QQ 手机版扫码登录"))
        else:
            hupu_logger.warning(_msg("⚠️", "未能获取 QQ 二维码，请在浏览器中手动登录"))
        for _ in range(max_checks):
            # A callback/home URL is only a cue to probe the real backend.
            urls = [str(candidate.url) for candidate in context.pages]
            if any((urlsplit(url).hostname or "") in ("www.hupu.com", "bbs.hupu.com")
                   or url.startswith("https://passport.hupu.com/pc/qqcallback") for url in urls):
                try:
                    if await is_logged_in(context, managed=False, account=account):
                        return
                except LoginRequiredError:
                    pass  # Only the explicit login action may wait for user verification.
            await page.wait_for_timeout(poll_interval * 1000)
        reason = _local_login_reason(login_page) or "login"
        raise _local_login_error(account, reason=reason)


async def _grab_qq_qrcode(page: Page, context: BrowserContext, account_file: str) -> dict | None:
    """从 QQ 登录 iframe 中获取二维码。"""
    from utils.login_qrcode import decode_qrcode_from_path, print_terminal_qrcode

    # 等待 QQ iframe 加载（最多 15 秒）
    qq_frame = None
    for _ in range(5):
        for frame in page.frames:
            if "xui.ptlogin2.qq.com" in frame.url or "ptlogin2.qq.com" in frame.url:
                qq_frame = frame
                break
        if qq_frame:
            break
        await asyncio.sleep(3)

    if not qq_frame:
        return None

    await asyncio.sleep(3)

    # 获取二维码图片（id="qrlogin_img"）
    qr_selectors = ["#qrlogin_img", 'img[src*="ptqrshow"]', 'img[id*="qr"]']
    for sel in qr_selectors:
        qr_loc = qq_frame.locator(sel).first
        if await qr_loc.count():
            src = await qr_loc.get_attribute("src")
            if src and src.startswith("http"):
                # 下载二维码图片
                try:
                    resp = await context.request.get(src)
                    qr_path = Path(account_file).parent / f"{Path(account_file).stem}_qq_qrcode.png"
                    qr_path.parent.mkdir(parents=True, exist_ok=True)
                    qr_path.write_bytes(await resp.body())

                    # 尝试解码并在终端显示
                    qrcode_content = decode_qrcode_from_path(qr_path)
                    if qrcode_content:
                        print_terminal_qrcode(qrcode_content, qr_path, "QQ手机版")
                    else:
                        hupu_logger.warning(_msg("😵", f"终端无法显示二维码，请打开 {qr_path} 扫码"))

                    return {"image_path": str(qr_path), "image_data_url": ""}
                except Exception as exc:
                    hupu_logger.warning(_msg("⚠️", f"下载 QQ 二维码失败: {exc}"))
                    continue

    return None


def _check_local_response(response):
    status = getattr(response, "status", None)
    if isinstance(status, int) and status >= 400:
        raise RuntimeError(f"虎扑页面请求失败：HTTP {status}")


def _local_login_reason(page):
    url = urlsplit(str(getattr(page, "url", "") or ""))
    host, path = (url.hostname or "").lower(), url.path.lower()
    if host != "hupu.com" and not host.endswith(".hupu.com"):
        return None
    if any(marker in path for marker in ("captcha", "verify", "two-factor", "2fa")):
        return "verification"
    if host == "passport.hupu.com" or "login" in path:
        return "login"
    return None


def _raise_local_login_required(page, *, account=None, publish_attempted=False):
    reason = _local_login_reason(page)
    if reason:
        raise _local_login_error(account, reason=reason, publish_attempted=publish_attempted)


def _local_login_error(account=None, *, reason="login", publish_attempted=False):
    action = "完成人机验证" if reason == "verification" else "重新登录"
    return LoginRequiredError(
        f"虎扑需要{action}（reason={reason}）；请运行 sau hupu login --account {account or '<account>'!r}，"
        "使用相同本地浏览器选择。提交后先核对作品，不要自动重发。",
        reason=reason, publish_attempted=publish_attempted)


async def cookie_auth(account_file=None, *, account_name=None, headless=None, local_browser=None):
    return await hupu_setup(account_file, account_name=account_name,
                            headless=headless, local_browser=local_browser)


async def hupu_setup(account_file=None, handle=False, return_detail=False, qrcode_callback=None,
                     headless=None, *, account_name=None, local_browser=None,
                     poll_interval=3, max_checks=120):
    account = _account_alias(account_file, account_name)
    async with async_playwright() as playwright:
        async with local_browser_session(playwright, platform="hupu", account=account,
                                         headless=headless, local_browser=local_browser,
                                         create=handle) as session:
            try:
                ready = await is_logged_in(session.context, managed=False, account=account)
            except LoginRequiredError:
                if not handle:
                    raise
                ready = False
            if not ready:
                if not handle:
                    raise _local_login_error(account)
                await _guide_login(session.context, account, qrcode_callback=qrcode_callback,
                                   poll_interval=poll_interval, max_checks=max_checks)
            result = {"success": True, "status": "profile_valid", "message": "虎扑 Profile 登录有效",
                      "account_name": account}
            return result if return_detail else True


class HuPuVideo(BaseVideoUploader):
    """虎扑视频上传。

    流程：直接跳转发布页 → 上传视频文件 → 填标题 → 填简介 →
         上传封面 → 选专区（步行街主干道）→ 选原创/二创 → 选 AI 声明 →
         点击「确定发布」→ 等待跳转到帖子页面。
    """
    publish_platform_label = "虎扑"

    def __init__(
        self,
        title,
        file_path,
        tags,
        account_file=None,
        publish_date=0,
        desc: str | None = None,
        thumbnail_path: str | None = None,
        debug: bool = False,
        headless: bool | None = None,
        *, account_name=None, local_browser=None,
    ):
        self.title = title
        self.file_path = file_path
        self.tags = tags or []
        self.account_file = account_file
        self.account_name = account_name
        self.local_browser = local_browser
        self.publish_date = publish_date
        self.desc = desc or ""
        self.thumbnail_path = thumbnail_path
        self.debug = debug
        self.headless = headless
        self.max_title_length = 40
        self.min_title_length = 4

    # -- 人类化交互层 -----------------------------------------------------
    def _humanizer(self, page: Page) -> Humanizer:
        """发布链路的唯一行为层实例：指针位置与随机流保持连续。"""
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """人类化停顿只吃剩余预算，耗尽时收缩到 0，不自己抛超时。"""
        remaining = max(0.0, self.publish_budget.remaining_seconds())
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            hupu_logger.warning(
                "人类化停顿被预算裁剪: {}s > {}s",
                round(seconds, 2),
                round(remaining, 2),
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    async def validate_upload_args(self, *, check_cookie: bool = True):
        if not self.title or not str(self.title).strip():
            raise ValueError("视频标题不能为空")
        if len(self.title) < self.min_title_length:
            raise ValueError(f"视频标题至少{self.min_title_length}个字")
        self.file_path = str(self.validate_video_file(self.file_path))
        if self.thumbnail_path:
            self.thumbnail_path = str(self.validate_image_file(self.thumbnail_path))

    async def upload(self, playwright: Playwright | None = None, *, session: BrowserSession | None = None) -> None:
        if session is not None:
            await self.validate_upload_args(check_cookie=False)
            if not session.managed and not await is_logged_in(session.context, managed=False, account=self.account_name):
                raise _local_login_error(self.account_name)
            await self.upload_in(session)
            return
        if playwright is None:
            async with async_playwright() as playwright:
                await self.upload(playwright)
            return
        async with local_browser_session(
            playwright, platform="hupu", account=_account_alias(self.account_file, self.account_name),
            headless=self.headless, local_browser=self.local_browser,
        ) as session:
            await self.upload(session=session)

    async def upload_in(self, session: BrowserSession, *, page: Page | None = None) -> None:
        """Run the publish flow on the provided session's context only."""
        self.start_publish_budget()
        self._local_profile_upload = not session.managed
        self._publish_attempted = False
        if page is None:
            page = await session.context.new_page()
        try:
            await self._upload_page(page, multilogin=session.managed)
        except (LoginRequiredError, PublishResultUnknownError):
            raise
        except Exception:
            if self._local_profile_upload:
                _raise_local_login_required(page, account=self.account_name,
                                            publish_attempted=self._publish_attempted)
                if self._publish_attempted:
                    raise self.publish_budget.timeout_error(True)
            raise

    async def _upload_page(self, page, *, multilogin):
        humanizer = self._humanizer(page)
        # 直接跳转到视频发布页（绕过首页点击）
        response = await page.goto(HUPU_PUBLISH_URL, timeout=60000, wait_until="load")
        if self._local_profile_upload:
            _check_local_response(response)
            _raise_local_login_required(page, account=self.account_name)
        await humanizer.after_navigate()
        if multilogin:
            _raise_if_login_required(page)
        await page.wait_for_timeout(5000)
        hupu_logger.info(_msg("🏃", f"开始上传视频: {self.title}"))

        # 1) 上传视频文件
        await self._upload_video_file(page)
        if self._local_profile_upload:
            _raise_local_login_required(page, account=self.account_name)

        # 2) 填写标题
        await self._fill_title(page)
        if self._local_profile_upload:
            _raise_local_login_required(page, account=self.account_name)

        # 3) 填写简介
        await self._fill_description(page)
        if self._local_profile_upload:
            _raise_local_login_required(page, account=self.account_name)

        # 4) 上传封面（如有）
        if self.thumbnail_path:
            await self._upload_thumbnail(page)

        # 5) 选择专区（步行街 → 步行街主干道）
        await self._select_zone(page)
        if self._local_profile_upload:
            _raise_local_login_required(page, account=self.account_name)

        # 6) 选择原创/二创 + AI 声明
        await self._check_declarations(page)
        if self._local_profile_upload:
            _raise_local_login_required(page, account=self.account_name)

        # 7) 点击发布
        await self._submit_publish(page, multilogin=multilogin)

    async def _upload_video_file(self, page: Page) -> None:
        """点击「上传视频」按钮并设置文件。"""
        upload_btn = page.get_by_role("button", name="上传视频")
        await upload_btn.wait_for(state="visible", timeout=15000)

        # 通过 file chooser 设置文件
        async with page.expect_file_chooser(timeout=10000) as fc_info:
            await upload_btn.click()  # native-click: file；文件选择器必须由原生点击派发
        file_chooser = await fc_info.value
        await file_chooser.set_files(self.file_path)
        hupu_logger.info(_msg("🏃", f"已选择视频文件: {self.file_path}"))

        # 等待视频上传就绪（标题输入框出现即可填写）
        title_field = page.get_by_placeholder("请输入标题（最少4个字，最多40个字）")
        await title_field.wait_for(
            state="visible", timeout=self.publish_budget.clamp_ms(300000)
        )
        hupu_logger.info(_msg("🥳", "视频已就绪"))

    async def _fill_title(self, page: Page) -> None:
        """填写标题（4-40字）：全选覆盖后逐字输入（单行，不含换行）。"""
        title_field = page.get_by_placeholder("请输入标题（最少4个字，最多40个字）")
        await title_field.wait_for(state="visible", timeout=15000)
        title_field = await _narrow_unique(title_field, "标题输入框", role="editable")
        title = _normalise_text(
            str(self.title)[:self.max_title_length], multiline=False
        )
        humanizer = self._humanizer(page)
        # 单行 input：click → 全选 → Delete → 逐字（sel 形态，一次交互会话）。
        await humanizer.click(title_field)
        await humanizer.press("ControlOrMeta+A")
        await humanizer.press("Delete")
        await humanizer.type_text(title)
        hupu_logger.info(_msg("🏷️", f"标题已填写: {title}"))

    async def _fill_description(self, page: Page) -> None:
        """填写简介：全选覆盖后逐字写入正文 + ``#tag#``（多行）。"""
        desc_field = page.get_by_placeholder("请输入简介")
        if not await desc_field.count():
            hupu_logger.warning(_msg("⚠️", "未找到简介输入框"))
            return

        # 组装描述：正文 + 标签
        content = _normalise_text(self.desc, multiline=True)
        if self.tags:
            tag_str = " ".join(f"#{t}#" for t in self.tags)
            content = f"{content}\n{tag_str}" if content else tag_str

        if content:
            desc_field = await _narrow_unique(desc_field, "简介输入框", role="editable")
            humanizer = self._humanizer(page)
            # 多行编辑器：同一 sel 序列；>1000 码点由 type_text 整段 insert_text。
            await humanizer.click(desc_field)
            await humanizer.press("ControlOrMeta+A")
            await humanizer.press("Delete")
            await humanizer.type_text(content)
            hupu_logger.info(_msg("📝", f"简介已填写（{len(content)}字）"))

    async def _upload_thumbnail(self, page: Page) -> None:
        """上传封面：点击「更换封面」→ 设置文件。"""
        try:
            cover_span = page.locator("span").filter(has_text="更换封面")
            await cover_span.wait_for(state="visible", timeout=10000)

            # 通过 file chooser 设置封面图片
            async with page.expect_file_chooser(timeout=10000) as fc_info:
                await cover_span.click()  # native-click: file；文件选择器必须由原生点击派发
            file_chooser = await fc_info.value
            await file_chooser.set_files(self.thumbnail_path)
            hupu_logger.info(_msg("🏃", f"已选择封面图片: {self.thumbnail_path}"))
            await page.wait_for_timeout(3000)
            hupu_logger.success(_msg("🖼️", "封面已上传"))
        except Exception as exc:
            if getattr(self, "_local_profile_upload", False):
                raise
            hupu_logger.warning(_msg("⚠️", f"封面上传失败: {exc}，继续发布（使用默认封面）"))

    async def _select_zone(self, page: Page) -> None:
        """选择专区：步行街 → 步行街主干道。"""
        humanizer = self._humanizer(page)
        try:
            # 录制脚本：page.get_by_label("发视频").get_by_text("添加专区").click()
            add_zone_btn = page.get_by_label("发视频").get_by_text("添加专区")
            await add_zone_btn.wait_for(state="visible", timeout=10000)
            await humanizer.click(add_zone_btn)
            await page.wait_for_timeout(1500)

            # 选择「步行街」分类
            zone_dialog = page.get_by_label("添加专区")
            step_street = zone_dialog.locator("div").filter(has_text=re.compile(r"^步行街$"))
            await humanizer.click(step_street)
            await page.wait_for_timeout(1000)

            # 选择「步行街主干道」子分类
            main_road = page.get_by_text("步行街主干道")
            await humanizer.click(main_road)
            await page.wait_for_timeout(500)

            # 点击确定
            confirm_btn = page.get_by_role("button", name="确 定")
            await humanizer.click(confirm_btn)
            await page.wait_for_timeout(1000)
            hupu_logger.info(_msg("🏷️", "已选择专区：步行街主干道"))
        except Exception as exc:
            if getattr(self, "_local_profile_upload", False):
                raise
            hupu_logger.warning(_msg("⚠️", f"选择专区失败: {exc}"))

    async def _check_declarations(self, page: Page) -> None:
        """选择原创/二创声明 + AI 声明。"""
        humanizer = self._humanizer(page)
        try:
            # 1) 点击「原创/二创」按钮
            declaration_btn = page.get_by_role("button", name="原创/二创")
            if await declaration_btn.count():
                await humanizer.click(declaration_btn)
                await page.wait_for_timeout(1000)
                hupu_logger.info(_msg("🏷️", "已点击「原创/二创」"))
        except Exception as exc:
            if getattr(self, "_local_profile_upload", False):
                raise
            hupu_logger.warning(_msg("⚠️", f"点击原创/二创失败: {exc}"))

        # 2) 选择「含AI生成内容」。裸 role 选择器先收窄到唯一：多义是硬错，
        #    不静默取 .first，也不被下面的「失败继续」分支吞掉。
        combobox = await _narrow_unique(
            page.get_by_role("combobox"),
            "AI声明下拉",
            role="combobox",
            required=False,
        )
        if combobox is None:
            return
        try:
            await humanizer.click(combobox)
            await page.wait_for_timeout(1000)

            ai_option = page.get_by_text("含AI生成内容")
            if await ai_option.count():
                await humanizer.click(ai_option)
                await page.wait_for_timeout(500)
                hupu_logger.info(_msg("🏷️", "已选择「含AI生成内容」"))
        except Exception as exc:
            if getattr(self, "_local_profile_upload", False):
                raise
            hupu_logger.warning(_msg("⚠️", f"选择 AI 声明失败: {exc}"))

    async def _submit_publish(self, page: Page, *, multilogin: bool = False) -> None:
        """点击「确定发布」并等待跳转到帖子页面。"""
        budget = self.publish_budget
        humanizer = self._humanizer(page)
        # 录制脚本：page.get_by_label("发视频").get_by_text("确定发布").click()
        publish_btn = page.get_by_label("发视频").get_by_text("确定发布")
        await publish_btn.wait_for(
            state="visible", timeout=budget.clamp_ms(15000)
        )
        await budget.wait_until_allowed(
            getattr(self, "publish_not_before", None),
            logger=hupu_logger,
            label="虎扑发布",
        )
        budget.check_pre_click()
        await humanizer.before_submit()
        if getattr(self, "_local_profile_upload", False):
            _raise_local_login_required(page, account=self.account_name)
        try:
            await humanizer.click(publish_btn)
        except Exception as exc:
            if maybe_dispatched(exc):
                self._publish_attempted = True
                if getattr(self, "_local_profile_upload", False):
                    _raise_local_login_required(page, account=self.account_name, publish_attempted=True)
                # 发布点击可能已经发出：按结果未知上抛，禁止再次派发。
                raise budget.timeout_error(True) from exc
            raise
        hupu_logger.info(_msg("🏃", "已点击「确定发布」"))
        publish_clicked = True
        self._publish_attempted = True

        # 等待跳转到帖子详情页（URL 匹配 bbs.hupu.com/{数字}.html）
        while budget.remaining_seconds() > 0:
            if getattr(self, "_local_profile_upload", False):
                _raise_local_login_required(page, account=self.account_name, publish_attempted=True)
            if multilogin:
                _raise_if_login_required(page, publish_attempted=publish_clicked)
            current_url = page.url
            if HUPU_POST_URL_PATTERN.search(current_url):
                hupu_logger.success(_msg("🥳", f"视频发布成功: {current_url}"))
                return

            await page.wait_for_timeout(2000)

        raise budget.timeout_error(True)

    async def main(self, *, session=None):
        await self.upload(session=session)
