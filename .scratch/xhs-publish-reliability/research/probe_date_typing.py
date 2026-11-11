"""Ticket 26 第四轮 — 定时时间「真实键入」的提交/回滚行为（只读，不发布）。

第一轮 Q4 在 Tab 之后按 Enter 时页面跳到了草稿箱（草稿页截图见 raw/t26-q6-*），
因此这里把 Enter 单独拆出来验证「Enter 会激活哪个元素」，并且不用任何点击
（失焦用 `document.activeElement.blur()`，避免误点）。

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_date_typing.py \
        --account cookies/xiaohongshu_180.json --image .local/probe/test_carousel1.png
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
TITLE_INPUT = 'input[placeholder*="填写标题"]'

STATE_JS = """
() => {
  const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
  const w = document.querySelector('.post-time-wrapper');
  const ae = document.activeElement;
  return {
    url: location.href,
    title_inputs: document.querySelectorAll('input[placeholder*="填写标题"]').length,
    date_input_count: document.querySelectorAll(
      '.d-datepicker-input-filter input.d-text').length,
    value: inp ? inp.value : null,
    wrapper_text: w ? (w.innerText || '').trim() : null,
    active: ae ? {tag: ae.tagName.toLowerCase(),
                  cls: (ae.className || '').toString().slice(0, 120),
                  text: (ae.innerText || '').trim().slice(0, 60),
                  aria: ae.getAttribute && ae.getAttribute('aria-label')} : null,
    draft_modal: document.querySelectorAll('.d-modal').length,
  };
}
"""


async def dismiss_overlays(page) -> None:
    for _ in range(3):
        n = await page.evaluate(
            """() => {
              const vis = n => { const r = n.getBoundingClientRect();
                                 const s = getComputedStyle(n);
                                 return r.width > 0 && r.height > 0 && s.display !== 'none'; };
              const hits = Array.from(document.querySelectorAll('button, .feature-guide__btn'))
                .filter(n => vis(n) && (n.innerText || '').trim() === '我知道了');
              hits.forEach(n => n.click());
              return hits.length;
            }"""
        )
        if not n:
            break
        await page.wait_for_timeout(600)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    out: dict = {"ticket": 26, "round": "d",
                 "started": datetime.now().isoformat(timespec="seconds"),
                 "note": "全程未点击发布按钮，未提交任何内容；失焦用 JS blur，不用点击"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, **XHS_LAUNCH_KWARGS)
        context = await browser.new_context(
            storage_state=args.account, user_agent=await _xhs_user_agent(browser),
            **XHS_CONTEXT_KWARGS,
        )
        context = await set_init_script(context)
        page = await context.new_page()
        try:
            await page.goto(IMAGE_URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(1000)
            if "/login" in page.url or await page.locator(".login-box").count():
                out["blocked"] = "login"
                raise RuntimeError("login expired")
            await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
            await page.locator("div.upload-content input[type=file]").first.set_input_files(
                args.image
            )
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
            await page.wait_for_timeout(400)

            await page.evaluate(
                """() => { const s = document.querySelector('.post-time-wrapper .d-switch');
                           if (s) s.click(); }"""
            )
            await page.wait_for_timeout(900)
            out["after_switch_on"] = await page.evaluate(STATE_JS)

            valid = (datetime.now() + timedelta(days=3)).replace(
                hour=10, minute=0, second=0, microsecond=0
            ).strftime("%Y-%m-%d %H:%M")
            out["valid_target"] = valid

            await page.evaluate(
                """() => { const inp = document.querySelector(
                             '.d-datepicker-input-filter input.d-text');
                           if (inp) inp.focus(); }"""
            )
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.insert_text(valid)
            out["typed_valid"] = await page.evaluate(STATE_JS)

            await page.keyboard.press("Tab")
            await page.wait_for_timeout(500)
            out["after_tab"] = await page.evaluate(STATE_JS)

            await page.evaluate("() => document.activeElement && document.activeElement.blur()")
            await page.wait_for_timeout(600)
            out["after_js_blur"] = await page.evaluate(STATE_JS)
            await page.screenshot(path=str(raw_dir / "t26d-date-valid.png"), full_page=True)

            # 非法（过去）日期
            await page.evaluate(
                """() => { const inp = document.querySelector(
                             '.d-datepicker-input-filter input.d-text');
                           if (inp) inp.focus(); }"""
            )
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.insert_text("2026-01-01 10:00")
            out["typed_past"] = await page.evaluate(STATE_JS)
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(600)
            out["past_after_tab"] = await page.evaluate(STATE_JS)

            # 不可解析
            await page.evaluate(
                """() => { const inp = document.querySelector(
                             '.d-datepicker-input-filter input.d-text');
                           if (inp) inp.focus(); }"""
            )
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.insert_text("abc")
            out["typed_garbage"] = await page.evaluate(STATE_JS)
            await page.evaluate("() => document.activeElement && document.activeElement.blur()")
            await page.wait_for_timeout(600)
            out["garbage_after_blur"] = await page.evaluate(STATE_JS)
            await page.screenshot(path=str(raw_dir / "t26d-date-garbage.png"), full_page=True)

            # 非法日期面板：是否有可见的错误文案
            out["visible_errorish"] = await page.evaluate(
                """() => {
                  const vis = n => { const r = n.getBoundingClientRect();
                                     const s = getComputedStyle(n);
                                     return r.width > 0 && r.height > 0 && s.display !== 'none'; };
                  return Array.from(document.querySelectorAll(
                    '.post-time-wrapper *, .d-datepicker-input-filter *, .date-picker-container *'))
                    .filter(n => vis(n) && /日期|时间|过去|无效|错误|不能|请选择/.test(n.innerText || ''))
                    .slice(0, 12)
                    .map(n => ({tag: n.tagName.toLowerCase(), cls: (n.className || '').toString(),
                                text: (n.innerText || '').trim().slice(0, 120)}));
                }"""
            )

            # Enter 单独验证：先看 Tab 后焦点落在哪，再决定是否按 Enter
            await page.evaluate(
                """() => { const inp = document.querySelector(
                             '.d-datepicker-input-filter input.d-text');
                           if (inp) inp.focus(); }"""
            )
            await page.keyboard.press("ControlOrMeta+A")
            await page.keyboard.insert_text(valid)
            await page.keyboard.press("Tab")
            await page.wait_for_timeout(300)
            out["before_enter"] = await page.evaluate(STATE_JS)
            await page.keyboard.press("Enter")
            await page.wait_for_timeout(1500)
            out["after_enter"] = await page.evaluate(STATE_JS)
            await page.screenshot(path=str(raw_dir / "t26d-after-enter.png"), full_page=True)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            await page.close()
            await context.close()
            await browser.close()

    out["finished"] = datetime.now().isoformat(timespec="seconds")
    (raw_dir / "t26d-report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=1)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
