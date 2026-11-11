"""Ticket 26 第三轮 — 补齐：标题计数器时序、真实键入的定时时间提交、封面入口留档。

只读，不发布。三个独立 page：
1. 标题：记录 input 事件 → `.suffix` 变成 `.max_suffix` 的延迟（毫秒）。
2. 定时时间：用真实键入（Control+A + insert_text）而不是 JS 写值，记录 Tab / Enter / 失焦
   前后的 input.value；再单独试一次 Playwright `fill`（短超时）看是否触发页面跳转。
3. 封面（视频页）：`.cover-edit-entry` 是否 attached / visible，JS 点击后弹窗与 img.src。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from patchright.async_api import async_playwright  # noqa: E402

from uploader.xiaohongshu_uploader.main import (  # noqa: E402
    XHS_CONTEXT_KWARGS,
    XHS_LAUNCH_KWARGS,
    _build_xhs_creator_url,
    _xhs_user_agent,
)
from utils.base_social_media import set_init_script  # noqa: E402

IMAGE_URL = _build_xhs_creator_url("/publish/publish?from=homepage&target=image")
VIDEO_URL = _build_xhs_creator_url("/publish/publish?from=homepage&target=video")
TITLE_INPUT = 'input[placeholder*="填写标题"]'
BODY_EDITOR = 'div.edit-container div.tiptap[role="textbox"]'


async def dismiss_overlays(page) -> None:
    for _ in range(4):
        handled = await page.evaluate(
            """() => {
              const vis = n => {
                const r = n.getBoundingClientRect();
                const s = getComputedStyle(n);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
                  && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.1;
              };
              const hits = Array.from(document.querySelectorAll(
                'button, .feature-guide__btn, [class*="guide"] button, [class*="guide__btn"]'
              )).filter(n => vis(n) && (n.innerText || '').trim() === '我知道了');
              hits.forEach(n => n.click());
              return hits.length;
            }"""
        )
        if not handled:
            break
        await page.wait_for_timeout(700)


async def open_editor(browser, account: str, url: str, file: str, is_video: bool):
    context = await browser.new_context(
        storage_state=account, user_agent=await _xhs_user_agent(browser), **XHS_CONTEXT_KWARGS
    )
    context = await set_init_script(context)
    page = await context.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1000)
    if "/login" in page.url or await page.locator(".login-box").count():
        raise RuntimeError("login expired")
    if is_video:
        await page.wait_for_selector("input.upload-input", state="attached", timeout=40000)
        await page.locator("input.upload-input").first.set_input_files(file)
        for _ in range(150):
            if await page.locator(TITLE_INPUT).count():
                break
            await asyncio.sleep(1)
    else:
        await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
        await page.locator("div.upload-content input[type=file]").first.set_input_files(file)
        for _ in range(150):
            st = await page.evaluate(
                """() => ({pr: document.querySelectorAll('.img-preview-area .pr').length,
                           up: document.querySelectorAll('.img-preview-area .pr .mask.uploading').length,
                           title: !!document.querySelector('input[placeholder*="填写标题"]')})"""
            )
            if st["title"] and st["pr"] >= 1 and st["up"] == 0:
                break
            await asyncio.sleep(0.3)
    await dismiss_overlays(page)
    await page.wait_for_timeout(500)
    return page, context


async def phase_title_timing(page, raw_dir: Path) -> dict:
    out: dict = {}
    await page.locator(TITLE_INPUT).first.fill("")
    await page.locator(TITLE_INPUT).first.click()
    await page.evaluate(
        """() => {
          window.__t26c = {tInput: null, tMax: null, cls: []};
          const inp = document.querySelector('input[placeholder*="填写标题"]');
          inp.addEventListener('input', () => {
            if (window.__t26c.tInput === null) window.__t26c.tInput = performance.now();
          }, true);
          const root = document.querySelector('div.edit-container');
          const mo = new MutationObserver(() => {
            if (window.__t26c.tMax !== null) return;
            const m = document.querySelector('.max_suffix');
            if (m) {
              window.__t26c.tMax = performance.now();
              window.__t26c.cls = [m.className.toString(), (m.innerText || '').trim()];
            }
          });
          mo.observe(root, {subtree: true, attributes: true, attributeFilter: ['class'], childList: true});
        }"""
    )
    await page.keyboard.insert_text("测" * 21)
    for _ in range(30):
        st = await page.evaluate("() => window.__t26c")
        if st.get("tMax") is not None:
            break
        await page.wait_for_timeout(50)
    st = await page.evaluate("() => window.__t26c")
    out["title_timing"] = st
    if st.get("tInput") is not None and st.get("tMax") is not None:
        out["delay_ms"] = round(st["tMax"] - st["tInput"])
    out["suffix_after_1s"] = await page.evaluate(
        """() => {
          const m = document.querySelector('.max_suffix');
          return {count: document.querySelectorAll('.max_suffix').length,
                  text: m ? (m.innerText || '').trim() : null,
                  scoped: document.querySelectorAll(
                    'div.title-container .max_suffix').length};
        }"""
    )
    # 失焦后是否仍然存在
    await page.locator(BODY_EDITOR).first.click()
    await page.wait_for_timeout(400)
    out["after_blur"] = await page.evaluate(
        """() => ({max_suffix: document.querySelectorAll('.max_suffix').length,
                   count_tip: document.querySelectorAll('.suffix .count-tip, .max_suffix .count-tip').length,
                   suffix_html: (document.querySelector('.edit-container .suffix') || {}).outerHTML})"""
    )
    return out


async def phase_date_typing(page, raw_dir: Path) -> dict:
    out: dict = {}
    await page.evaluate(
        """() => { const s = document.querySelector('.post-time-wrapper .d-switch');
                   if (s) s.click(); }"""
    )
    await page.wait_for_timeout(1000)
    valid = (datetime.now() + timedelta(days=3)).replace(
        hour=10, minute=0, second=0, microsecond=0
    ).strftime("%Y-%m-%d %H:%M")
    out["target"] = valid

    focused = await page.evaluate(
        """() => {
          const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
          if (!inp) return false;
          inp.focus();
          return document.activeElement === inp;
        }"""
    )
    out["focused"] = focused
    await page.keyboard.press("ControlOrMeta+A")
    await page.keyboard.insert_text(valid)
    out["after_typing"] = await page.evaluate(
        """() => {
          const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
          const w = document.querySelector('.post-time-wrapper');
          return {input_count: document.querySelectorAll(
                    '.d-datepicker-input-filter input.d-text').length,
                  value: inp ? inp.value : null,
                  focused: document.activeElement === inp,
                  wrapper_text: w ? (w.innerText || '').trim() : null};
        }"""
    )
    await page.wait_for_timeout(500)
    out["after_500ms"] = await page.evaluate(
        """() => { const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                   return {value: inp ? inp.value : null, focused: document.activeElement === inp}; }"""
    )
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(500)
    out["after_tab"] = await page.evaluate(
        """() => { const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                   const w = document.querySelector('.post-time-wrapper');
                   return {input_count: document.querySelectorAll(
                             '.d-datepicker-input-filter input.d-text').length,
                           value: inp ? inp.value : null,
                           wrapper_text: w ? (w.innerText || '').trim() : null}; }"""
    )
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(500)
    out["after_enter"] = await page.evaluate(
        """() => { const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                   return {input_count: document.querySelectorAll(
                             '.d-datepicker-input-filter input.d-text').length,
                           value: inp ? inp.value : null}; }"""
    )
    await page.locator(BODY_EDITOR).first.click()
    await page.wait_for_timeout(500)
    out["after_blur"] = await page.evaluate(
        """() => { const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                   const w = document.querySelector('.post-time-wrapper');
                   return {input_count: document.querySelectorAll(
                             '.d-datepicker-input-filter input.d-text').length,
                           value: inp ? inp.value : null,
                           wrapper_text: w ? (w.innerText || '').trim() : null}; }"""
    )
    try:
        await page.screenshot(path=str(raw_dir / "t26c-date-typing.png"), full_page=True)
    except Exception:
        pass

    # 真实 fill（短超时）—— 观察是否触发页面跳转
    filled = {}
    try:
        inp = page.locator(".d-datepicker-input-filter input.d-text").first
        await inp.scroll_into_view_if_needed(timeout=3000)
        await inp.click(timeout=3000)
        await inp.fill(valid, timeout=3000)
        filled["fill_ok"] = True
        filled["value"] = await inp.input_value(timeout=3000)
    except Exception as exc:
        filled["error"] = f"{type(exc).__name__}: {exc}"
    filled["state"] = await page.evaluate(
        """() => ({url: location.href,
                   title: document.querySelectorAll('input[placeholder*="填写标题"]').length,
                   draft_modal: document.querySelectorAll('.d-modal').length,
                   date_inputs: document.querySelectorAll(
                     '.d-datepicker-input-filter input.d-text').length})"""
    )
    out["fill_test"] = filled
    try:
        await page.screenshot(path=str(raw_dir / "t26c-date-fill.png"), full_page=True)
    except Exception:
        pass
    return out


async def phase_cover(page, raw_dir: Path) -> dict:
    out: dict = {}
    out["before"] = await page.evaluate(
        """() => {
          const stack = document.querySelector('.cover-edit-stack');
          const entry = document.querySelector('.cover-edit-entry');
          const vis = n => { const r = n.getBoundingClientRect();
                             const s = getComputedStyle(n);
                             return r.width > 0 && r.height > 0 && s.display !== 'none'; };
          return {
            stack_attached: !!stack, stack_visible: stack ? vis(stack) : null,
            entry_attached: !!entry, entry_visible: entry ? vis(entry) : null,
            entry_text: entry ? (entry.innerText || '').trim() : null,
            stack_html: stack ? stack.outerHTML.slice(0, 2000) : null,
            imgs: Array.from(document.querySelectorAll(
              '.cover-edit-stack img, .cover img, .cover-detect img, .cover-plugin-preview img'))
              .map(n => ({cls: (n.className || '').toString(), src: n.src,
                          visible: n.getBoundingClientRect().height > 0})),
          };
        }"""
    )
    out["clicked"] = await page.evaluate(
        """() => {
          const el = document.querySelector('.cover-edit-entry')
            || document.querySelector('div.upload-cover')
            || document.querySelector('.cover-plugin-preview div.default');
          if (!el) return null;
          el.click();
          return {tag: el.tagName.toLowerCase(), cls: (el.className || '').toString(),
                  text: (el.innerText || '').trim().slice(0, 80)};
        }"""
    )
    await page.wait_for_timeout(1800)
    out["modal"] = await page.evaluate(
        """() => {
          const m = document.querySelector('.d-modal.cover-modal, .d-modal.main-cover-editor-modal');
          if (!m) return null;
          return {cls: m.className.toString(),
                  text: (m.innerText || '').trim().slice(0, 600),
                  imgs: Array.from(m.querySelectorAll('img')).map(n => ({
                    cls: (n.className || '').toString(), src: n.src,
                    visible: n.getBoundingClientRect().height > 0})).slice(0, 12),
                  buttons: Array.from(m.querySelectorAll('button'))
                    .map(b => (b.innerText || '').trim()).filter(Boolean)};
        }"""
    )
    out["after"] = await page.evaluate(
        """() => Array.from(document.querySelectorAll(
          '.cover-edit-stack img, .cover img, .cover-detect img'))
          .map(n => ({cls: (n.className || '').toString(), src: n.src}))
          .slice(0, 8)"""
    )
    try:
        await page.screenshot(path=str(raw_dir / "t26c-cover.png"), full_page=True)
    except Exception:
        pass
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)
    out["modal_after_esc"] = await page.locator(
        ".d-modal.cover-modal, .d-modal.main-cover-editor-modal"
    ).count()
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {"ticket": 26, "round": "c",
                    "started": datetime.now().isoformat(timespec="seconds"),
                    "note": "全程未点击发布按钮，未提交任何内容"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, **XHS_LAUNCH_KWARGS)
        try:
            # 1) 标题时序
            page, context = await open_editor(browser, args.account, IMAGE_URL, args.image, False)
            try:
                report["title_timing"] = await phase_title_timing(page, raw_dir)
            except Exception as exc:
                report["title_timing"] = {"error": f"{type(exc).__name__}: {exc}"}
            finally:
                await page.close()
                await context.close()

            # 2) 定时时间真实键入
            page, context = await open_editor(browser, args.account, IMAGE_URL, args.image, False)
            try:
                report["date_typing"] = await phase_date_typing(page, raw_dir)
            except Exception as exc:
                report["date_typing"] = {"error": f"{type(exc).__name__}: {exc}"}
            finally:
                await page.close()
                await context.close()

            # 3) 封面（视频页）
            page, context = await open_editor(browser, args.account, VIDEO_URL, args.video, True)
            try:
                report["cover"] = await phase_cover(page, raw_dir)
            except Exception as exc:
                report["cover"] = {"error": f"{type(exc).__name__}: {exc}"}
            finally:
                await page.close()
                await context.close()
        finally:
            await browser.close()
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    (raw_dir / "t26c-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=1)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
