"""雪球长文：结构化原稿、原位置插图、封面、预览与单次发表。"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from loguru import logger
from patchright.async_api import Page, TimeoutError as BrowserTimeoutError, async_playwright, expect

from uploader.publish_timeout import PublishTimeoutBudget
from utils.browser_session import BrowserSession
from utils.errors import PublishResultUnknownError
from utils.humanize import Humanizer, maybe_dispatched
from uploader.xueqiu_uploader.constants import (
    XUEQIU_ARTICLE_URL, XUEQIU_CONTEXT_KWARGS, XUEQIU_DECLARATIONS,
    XUEQIU_IMAGE_SUFFIXES, XUEQIU_LAUNCH_KWARGS, XUEQIU_VISIBILITY,
)
from uploader.xueqiu_uploader.session import (
    load_xueqiu_identity, raise_if_login_required, read_xueqiu_identity,
)
from uploader.xueqiu_uploader.content import load_xueqiu_article
from uploader.xueqiu_uploader.verification import check_xueqiu_article_content, query_xueqiu_article


async def grant_clipboard_permission(page: Page, *, multilogin: bool) -> None:
    """Grant clipboard access locally; Multilogin mode must not call the API."""
    if multilogin:
        return
    await page.context.grant_permissions(
        ["clipboard-read", "clipboard-write"], origin="https://mp.xueqiu.com",
    )


class XueqiuArticle:
    """通过原生粘贴与图片上传保留文章结构，以服务端确认作为发表结果。"""

    def __init__(self, title, content_file, account_file, visibility="公开",
                 declaration="不添加创作声明", prepare_only=False, headless=False, debug=False,
                 cover=None, publish_not_before=None):
        self.title = title.strip()
        self.content_file = Path(content_file).expanduser().resolve()
        self.account_file = Path(account_file).resolve() if account_file is not None else None
        self.visibility = visibility
        self.declaration = declaration
        self.prepare_only = prepare_only
        self.headless = headless
        self.debug = debug
        self.cover = Path(cover).expanduser().resolve() if cover else None
        self.publish_not_before = publish_not_before

    def _budget_ms(self, default_ms: int) -> int:
        budget = getattr(self, "_publish_budget", None)
        return budget.clamp_ms(default_ms) if budget else default_ms

    def _humanizer(self, page: Page) -> Humanizer:
        """发布链路的唯一行为层实例：指针位置与随机流保持连续。"""
        cached = getattr(self, "_humanizer_instance", None)
        if cached is None or cached.page is not page:
            cached = Humanizer(page, sleep=self._humanize_pause)
            self._humanizer_instance = cached
        return cached

    async def _humanize_pause(self, seconds: float) -> None:
        """人类化停顿只吃剩余预算，不自己抛超时。"""
        budget = getattr(self, "_publish_budget", None)
        remaining = (
            max(0.0, budget.remaining_seconds()) if budget is not None else seconds
        )
        if seconds > remaining and not getattr(self, "_pause_warned", False):
            logger.warning(
                "人类化停顿被预算裁剪: {}s > {}s",
                round(seconds, 2),
                round(remaining, 2),
            )
            self._pause_warned = True
        await asyncio.sleep(min(seconds, remaining))

    def validate_upload_args(self, *, check_cookie: bool = True):
        """所有本地参数在创建远端草稿前校验，不猜测尚未观察到的长度上限。

        Cookie/identity binding is local-only; Multilogin mode passes
        ``check_cookie=False`` because the Profile is the identity.
        """
        if not self.title or "\n" in self.title or "\r" in self.title:
            raise ValueError("雪球标题必须为非空单行文字")
        self.document = load_xueqiu_article(self.content_file)
        if self.visibility not in XUEQIU_VISIBILITY:
            raise ValueError(f"分享范围必须为: {', '.join(XUEQIU_VISIBILITY)}")
        if self.declaration not in XUEQIU_DECLARATIONS:
            raise ValueError(f"创作声明必须为: {', '.join(XUEQIU_DECLARATIONS)}")
        for image in self.document.images + ([self.cover] if self.cover else []):
            if image.suffix.lower() not in XUEQIU_IMAGE_SUFFIXES:
                raise ValueError(f"雪球图片支持: {', '.join(XUEQIU_IMAGE_SUFFIXES)}")
            if not image.is_file():
                raise FileNotFoundError(f"图片不存在: {image}")
            if image.stat().st_size == 0:
                raise ValueError(f"图片不能为空: {image}")
        if check_cookie:
            if self.account_file is None or not self.account_file.is_file():
                raise FileNotFoundError("请先执行 sau xueqiu login 保存账号")
            self.identity = load_xueqiu_identity(self.account_file)
        else:
            self.identity = None

    async def fill_article_body(self, page, body, *, multilogin: bool = False):
        """在原稿图片位置放置唯一标记，原生上传后再核对完整图文交错顺序。"""
        humanizer = self._humanizer(page)
        parts = []
        insertions = []
        for part in self.document.parts:
            if isinstance(part, Path):
                marker = f"SAU_IMAGE_{uuid4().hex}"
                parts.append(marker)
                insertions.append((marker, part))
            else:
                parts.append(part)
        await grant_clipboard_permission(page, multilogin=multilogin)
        await page.evaluate("""async html => navigator.clipboard.write([
            new ClipboardItem({'text/html': new Blob([html], {type: 'text/html'})})
        ])""", "".join(parts))
        await humanizer.click(body)
        await body.press("Meta+V" if sys.platform == "darwin" else "Control+V")
        # 标题字段用于失焦；等待本次末尾文字实际进入模型，再开始选择图片标记。
        await page.get_by_placeholder("请输入标题", exact=True).click()  # native-click: focus；失焦正文让编辑器落定粘贴块，非内容交互
        for marker, _ in insertions:
            await expect(body).to_contain_text(marker)
        self.uploaded_images = []
        for index, (marker, image) in enumerate(insertions):
            # 在正文实际文本节点选择唯一标记；使用原生选区而非改写 ProseMirror innerHTML。
            # 实测该选区经 Shift 刷新后会被工具栏上传替换，后续段落保持原位。
            await body.evaluate("""(body, marker) => {
                body.focus(); const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
                let node;
                while (node = walker.nextNode()) {
                    const offset = node.textContent.indexOf(marker);
                    if (offset < 0) continue;
                    const range = document.createRange(); range.setStart(node, offset);
                    range.setEnd(node, offset + marker.length);
                    const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
                    return;
                }
                throw Error('找不到本次原稿图片位置标记');
            }""", marker)
            await body.press("Shift")
            # data-tip 是实测上传动作语义；限定 snb_toolbar 排除独立封面 input。
            async with page.expect_file_chooser() as chooser:
                await humanizer.click(page.locator('#snb_toolbar [data-tip="上传图片"]'))
            file_chooser = await chooser.value
            # input 保留旧文件；只清空原生值而不派发空 change，允许相同文件在不同原稿位置出现。
            await file_chooser.element.evaluate("input => { input.value = ''; }")
            await file_chooser.set_files(str(image))
            await expect(body).not_to_contain_text(marker)
            await expect(body.locator("img")).to_have_count(index + 1, timeout=self._budget_ms(60000))
            # 图片按原稿顺序逐个替换，已断言数量；data/blob 预览不代表服务端完成。
            inserted = body.locator("img").nth(index)
            await expect(inserted).to_have_attribute("src", re.compile(r"^(?:https:)?//xqimg\.imedao\.com/"), timeout=self._budget_ms(60000))
            await expect(inserted).to_have_js_property("complete", True, timeout=self._budget_ms(60000))
            if await inserted.evaluate("e => e.naturalWidth") <= 0:
                raise RuntimeError(f"正文图片无法加载: {image.name}")
            self.uploaded_images.append(await inserted.evaluate("e => e.src"))
        await page.get_by_placeholder("请输入标题", exact=True).click()  # native-click: focus；上传结束后再次失焦正文，让编辑器落定图片块
        await check_xueqiu_article_content(body, self.document)

    async def fill_article_form(self, page: Page, *, multilogin: bool = False):
        """按真实字段填写、读回选项和正文，再独立检查预览与自动保存。"""
        humanizer = self._humanizer(page)
        # 标题占位符表达字段职责；正文 placeholder 在输入后消失，使用 editor 直属可编辑节点，
        # 排除上传图片内部 contenteditable=false 的工具容器，填表前后使用同一定位器。
        title = page.get_by_placeholder("请输入标题", exact=True)
        body = page.locator('#editor > [contenteditable="true"]')
        await expect(title).to_have_count(1)
        await expect(body).to_have_count(1)
        # 新任务只写空编辑器；页面若恢复已有草稿，不覆盖用户原文。
        if (await title.input_value()).strip() or (await body.inner_text()).strip() or await body.locator("img").count():
            raise RuntimeError("雪球编辑器已有内容，拒绝覆盖；请先处理现有草稿")
        # 清空形态为 none：平台已有「非空即拒绝」守卫（上方 input_value 检查），
        # 这里只聚焦后逐字输入，绝不清空标题——全仓清空策略的样板。
        await humanizer.click(title)
        await humanizer.type_text(self.title)
        await expect(title).to_have_value(self.title)
        await self.fill_article_body(page, body, multilogin=multilogin)
        self.cover_url = None
        if self.cover:
            # 封面字段行以 label 限域，input 的 type 表达上传用途，不与工具栏正文上传器混用。
            cover_row = page.locator('div[class*="index_sectionFlex_"]').filter(
                has=page.get_by_text("封面图片：", exact=True),
            )
            await cover_row.locator('input[type="file"]').set_input_files(str(self.cover))
            # 实测封面必须经过独立裁剪弹窗；保留默认裁剪框，不猜测尺寸或操作隐藏状态。
            crop = page.locator('div[class*="modal_modal-content_"]').filter(
                has=page.get_by_text("选择封面图片", exact=True),
            )
            await expect(crop).to_be_visible()
            await expect(crop.locator('img[alt="Crop"]')).to_have_js_property("complete", True)
            if await crop.locator('img[alt="Crop"]').evaluate("e => e.naturalWidth") <= 0:
                raise RuntimeError("封面裁剪预览无法加载")
            await humanizer.click(crop.get_by_role("button", name="确认裁剪", exact=True))
            await expect(crop).to_have_count(0, timeout=self._budget_ms(60000))
            # 实测成功封面以背景图展示，原上传按钮被 hidden；不能检查占位 img 的固定地址。
            cover_preview = cover_row.locator('div[class*="index_input-cover-pic-btn_"]')
            await expect(cover_preview).to_have_attribute("style", re.compile(r".*xqimg\.imedao\.com/.*"), timeout=self._budget_ms(60000))
            self.cover_url = await cover_preview.evaluate(
                "e => new URL(getComputedStyle(e).backgroundImage.slice(5, -2), location.href).href")
        for label, value in (("分享范围：", self.visibility), ("创作声明：", self.declaration)):
            # class 仅保留字段行和组件职责前缀；以本行 label 限域，排除另一组同构下拉菜单。
            row = page.locator('div[class*="index_sectionFlex_"]').filter(
                has=page.get_by_text(label, exact=True),
            )
            selected = row.locator('div[class*="index_selectWrap_"]')
            # 先读当前值：下拉点开再点关会收起容器，已选对时不再动它（幂等）。
            if (await selected.inner_text()).strip() == value:
                continue
            await humanizer.click(selected)
            # optionContainer 是展开选项容器；visible 排除当前未展开的另一菜单。
            option = row.locator('div[class*="index_optionContainer_"]:visible').get_by_text(value, exact=True)
            await expect(option).to_have_count(1)
            await humanizer.click(option)
            await expect(selected).to_contain_text(value)
        # publish_state 是独立自动保存状态区域，不以正文里的同名文字判断保存完成。
        await expect(page.locator('div[class*="publish_state_"]')).to_contain_text("已经保存至草稿", timeout=self._budget_ms(60000))
        await humanizer.click(page.get_by_role("button", name="预览", exact=True))
        # 预览容器的业务前缀在实测 DOM 中稳定；h1 与 content-text 分别承载预览标题、正文。
        preview = page.locator('div[class*="index_preview-content_"]')
        await expect(preview).to_be_visible()
        await expect(preview.locator("h1")).to_have_text(self.title)
        # 预览由异步服务端结果填入，先等本次文字，不能只等空预览外壳可见。
        preview_body = preview.locator('div[class*="index_content-text_"] > div')
        await expect(preview_body).to_contain_text(next(text.strip() for text in self.document.text if text.strip()), timeout=self._budget_ms(30000))
        await check_xueqiu_article_content(preview_body, self.document)
        # 预览 content-text 直属封面 img 与直属 div 内的正文图片并存；只在后者核对插图。
        preview_images = preview.locator('div[class*="index_content-text_"] > div img')
        await expect(preview_images).to_have_count(len(self.uploaded_images))
        for index, source in enumerate(self.uploaded_images):
            # 平台预览会给 // 地址补 https；比较解析后的 src，并按正文顺序排除错图或重排。
            await expect(preview_images.nth(index)).to_have_js_property("src", source)
            await expect(preview_images.nth(index)).to_have_js_property("complete", True)
            if await preview_images.nth(index).evaluate("e => e.naturalWidth") <= 0:
                raise RuntimeError(f"预览中第 {index + 1} 张正文图片无法加载")
        if self.cover_url:
            # 实测 index_first-pic 是预览直属封面，独立于正文 div，核对本次裁剪结果。
            cover_image = preview.locator('div[class*="index_content-text_"] > img[class*="index_first-pic_"]')
            await expect(cover_image).to_have_js_property("src", self.cover_url)
            await expect(cover_image).to_have_js_property("complete", True)
            if await cover_image.evaluate("e => e.naturalWidth") <= 0:
                raise RuntimeError("预览中的封面无法加载")
        if not multilogin and (await read_xueqiu_identity(page))["uid"] != self.identity["uid"]:
            raise RuntimeError("雪球填写期间账号发生变化，已中止")

    async def _close_preview(self, page: Page) -> None:
        """预览遮罩：只能坐标点关闭开关，不删遮罩、不强点。"""
        # index_preview_ 是预览遮罩，直接子级 index_close_ 是实测关闭控件；不删除遮罩或强制点击。
        humanizer = self._humanizer(page)
        await humanizer.click(page.locator('div[class*="index_preview_"] > div[class*="index_close_"]'))
        # 关闭后组件仍保留在 DOM，由父层隐藏；不能要求节点被删除。
        await expect(page.locator('div[class*="index_preview-content_"]')).to_be_hidden()

    async def _submit(self, page: Page, publish) -> None:
        """唯一提交点：人类化停顿后坐标点击；可能已派发按结果未知上抛。"""
        humanizer = self._humanizer(page)
        await humanizer.before_submit()
        try:
            await humanizer.click(publish)
        except Exception as exc:
            if maybe_dispatched(exc):
                # ``mouse.down`` 之后失败：可能已经提交，禁止再次派发。
                raise self._publish_budget.timeout_error(True) from exc
            raise

    def results_dir(self) -> Path:
        """Result manifests sit next to the local account; MLX uses a temp dir."""
        base = (
            self.account_file.parent
            if self.account_file is not None
            else Path(tempfile.gettempdir()) / "sau-mlx"
        )
        return base / "xueqiu_results"

    async def main(self, *, session: BrowserSession | None = None) -> dict:
        """准备模式保留草稿和预览；提交模式只点击一次，结果未知时禁止自动重发。

        ``session`` is the Multilogin seam: it runs only the page/publish body and
        never launches, creates a context, injects scripts, writes cookies, or
        closes anything it does not own.
        """
        if session is not None:
            self.validate_upload_args(check_cookie=False)
            return await self.upload_in(session)

        self.validate_upload_args()
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(
                headless=self.headless, **XUEQIU_LAUNCH_KWARGS,
            )
            try:
                context = await browser.new_context(
                    storage_state=str(self.account_file), **XUEQIU_CONTEXT_KWARGS,
                )
                return await self.upload_in(
                    BrowserSession(browser=browser, context=context, mode="local")
                )
            finally:
                await browser.close()

    async def upload_in(self, session: BrowserSession) -> dict:
        """Business body: editor/preview/publish plus one server response check."""
        budget = PublishTimeoutBudget("雪球")
        self._publish_budget = budget
        results_dir = self.results_dir()
        results_dir.mkdir(parents=True, exist_ok=True)
        result_file = results_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid4().hex[:8]}.json"
        result = {"success": False, "status": "preparing", "title": self.title,
                  "content_file": str(self.content_file),
                  "identity": self.identity, "visibility": self.visibility, "declaration": self.declaration,
                  "result_file": str(result_file), "remote_draft_possible": False}
        multilogin = session.managed
        page = None
        publish_clicked = False
        try:
            page = await session.context.new_page()
            # 人类化实例在 page 创建后建立：HUMANIZE 在构造时快照，之后不再读 env。
            self._humanizer(page)
            response = await page.goto(XUEQIU_ARTICLE_URL, wait_until="domcontentloaded", timeout=45000)
            if response is not None and response.status >= 400:
                raise RuntimeError(f"雪球编辑器访问失败，HTTP {response.status}")
            if multilogin:
                raise_if_login_required(page)
            elif (await read_xueqiu_identity(page))["uid"] != self.identity["uid"]:
                raise RuntimeError("雪球主体与绑定账号不一致")
            result["remote_draft_possible"] = True
            await self.fill_article_form(page, multilogin=multilogin)
            result.update(images=self.uploaded_images, cover=self.cover_url,
                          source_format=self.document.source_format, normalizations=self.document.normalizations,
                          manifest=self.document.manifest)
            await page.screenshot(path=str(result_file.with_suffix(".png")), full_page=True)
            result["screenshot"] = str(result_file.with_suffix(".png"))
            if self.prepare_only:
                result.update(success=True, status="prepared", url=page.url)
                return result
            # index_preview_ 是预览遮罩，直接子级 index_close_ 是实测关闭控件；不删除遮罩或强制点击。
            await self._close_preview(page)
            publish = page.get_by_role("button", name="发布", exact=True)
            # 页面用 class 表达禁用态，不能仅依赖 HTML disabled；保留语义前缀排除哈希变化。
            await expect(publish).not_to_have_class(
                re.compile(r".*publish_disabled_.*"),
                timeout=budget.clamp_ms(30000),
            )
            await budget.wait_until_allowed(
                getattr(self, "publish_not_before", None),
                logger=logger,
                label="雪球发布",
            )
            budget.check_pre_click()
            result.update(status="submission_unknown", editor_url=page.url)
            result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            # 实测最终发表 POST /xq/statuses/update.json 返回作品 ID、user_id、title、text、is_private。
            # 页面随后回首页，因此不能用“跳转作者详情”这一错误假设判断成功。
            publish_clicked = False
            try:
                async with page.expect_response(
                    lambda response: response.request.method == "POST"
                    and response.url == "https://mp.xueqiu.com/xq/statuses/update.json",
                    timeout=budget.clamp_ms(60000),
                ) as submitted:
                    await self._submit(page, publish)
                    publish_clicked = True
                response = await submitted.value
            except BrowserTimeoutError:
                raise budget.timeout_error(publish_clicked) from None
            # 发布点击已经派发：响应解析与字段校验的失败都只能是“结果未知”，
            # 否则 CLI 退出 1 会诱发调度器重试并产生重复作品。
            try:
                payload = await response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("雪球发表响应不是 JSON 对象")
                content_id = payload.get("id")
                if not response.ok or not isinstance(content_id, int) or isinstance(content_id, bool) or content_id <= 0:
                    raise RuntimeError(f"雪球未确认受理: HTTP {response.status}，{payload.get('error_description', payload.get('error_code', '缺少作品 ID'))}")
                if payload.get("title") != self.title:
                    raise RuntimeError("雪球受理作品的标题不符，请核查原作品")
                if not multilogin and str(payload.get("user_id")) != self.identity["uid"]:
                    raise RuntimeError("雪球受理作品的主体与本地绑定账号不符，请核查原作品")
                if payload.get("is_private") is not (self.visibility == "私人"):
                    raise RuntimeError("雪球受理作品的分享范围不符，请核查原作品")
            except PublishResultUnknownError:
                raise
            except Exception as error:
                raise PublishResultUnknownError(
                    f"雪球发表响应无法确认：{error}；帖子可能已经发布，请查原记录，勿重复提交"
                ) from error
            # 先持久化已返回的 ID，即使后续内容核对异常也只能查询原作品，禁止重发。
            result["content_id"] = str(content_id)
            result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            # 平台已确认受理；后续核验、截图与 cookie 保存都是附加记录，失败只能告警。
            result.update(success=True, status="published", url="")
            try:
                author_id = payload.get("user_id") if multilogin else self.identity["uid"]
                if author_id is None or author_id == "":
                    raise ValueError("发表响应缺少作者 ID")
                result["url"] = f"https://xueqiu.com/{author_id}/{content_id}"
            except Exception as error:
                logger.warning(f"雪球发表成功但作品地址生成失败: {error}")
            if not multilogin:
                result["management_verified"] = False
            result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            # 用平台返回的已发表正文创建独立页面核对，不改写编辑器模型，也不追加真实发表动作。
            check_page = None
            try:
                check_page = await session.context.new_page()
                await check_page.set_content(payload.get("text") or "")
                await check_xueqiu_article_content(check_page.locator("body"), self.document, self.uploaded_images)
                if not multilogin:
                    # 发表响应已确认受理；再查已发布原 ID，核验不能误触发第二次提交。
                    record = await query_xueqiu_article(page, self.identity, content_id, self.title, self.visibility)
                    await check_page.set_content(record.get("text") or "")
                    await check_xueqiu_article_content(check_page.locator("body"), self.document, self.uploaded_images)
                    result["management_verified"] = True
            except Exception as error:
                logger.warning(f"雪球发表后核验未完成（发表已确认，结果保留）: {error}")
            finally:
                if check_page is not None:
                    try:
                        await check_page.close()
                    except Exception as error:
                        logger.warning(f"雪球核验页关闭失败（不影响发表结果）: {error}")
            if not multilogin:
                try:
                    await page.screenshot(path=str(result_file.with_suffix(".published.png")), full_page=True)
                    result["published_screenshot"] = str(result_file.with_suffix(".published.png"))
                except Exception as error:
                    logger.warning(f"雪球发表截图失败（不影响发表结果）: {error}")
                try:
                    await session.context.storage_state(path=str(self.account_file))
                except Exception as error:
                    logger.warning(f"雪球 cookie 保存失败（不影响发表结果）: {error}")
            return result
        except PublishResultUnknownError:
            raise
        except Exception as exc:
            if multilogin and page is not None:
                raise_if_login_required(page, publish_attempted=publish_clicked)
            result["error"] = str(exc)
            if result["status"] == "preparing":
                result["status"] = "failed"
            if self.debug and page is not None:
                await page.screenshot(path=str(result_file.with_suffix(".error.png")), full_page=True)
            raise
        finally:
            result_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"雪球操作结果: {result_file}", flush=True)
