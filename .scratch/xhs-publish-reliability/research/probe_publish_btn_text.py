"""Ticket 26 补充 — 定时发布开启前后 `xhs-publish-btn` 的自述属性（只读，不点）。

回答 05 遗留的「定时发布是否复用同一个 xhs-publish-btn（只改文本/aria）」。
用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_publish_btn_text.py \
        --account cookies/xiaohongshu_180.json --image .local/probe/test_carousel1.png
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
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

BTN_JS = """
() => {
  const b = document.querySelector('xhs-publish-btn');
  if (!b) return null;
  const attrs = {};
  for (const a of Array.from(b.attributes)) attrs[a.name] = a.value;
  return {
    attrs: attrs,
    text: (b.innerText || '').trim(),
    html: b.outerHTML.slice(0, 2500),
    buttons: Array.from(b.querySelectorAll('button')).map(x => ({
      text: (x.innerText || '').trim(), cls: x.className.toString(),
      attrs: Object.fromEntries(Array.from(x.attributes).map(a => [a.name, a.value])),
    })),
    shadom_buttons: b.shadowRoot ? Array.from(b.shadowRoot.querySelectorAll('button'))
      .map(x => ({text: (x.innerText || '').trim(), cls: x.className.toString()})) : null,
  };
}
"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    out: dict = {"ticket": 26}
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
            await page.evaluate(
                """() => { const b = document.querySelector('button.feature-guide__btn, button');
                           if (b && (b.innerText || '').trim() === '我知道了') b.click(); }"""
            )
            await page.wait_for_timeout(600)
            out["schedule_off"] = await page.evaluate(BTN_JS)
            await page.evaluate(
                """() => { const s = document.querySelector('.post-time-wrapper .d-switch');
                           if (s) s.click(); }"""
            )
            await page.wait_for_timeout(1200)
            out["schedule_on"] = await page.evaluate(BTN_JS)
            await page.screenshot(path=str(raw_dir / "t26e-publish-btn-schedule.png"),
                                  full_page=True)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            await page.close()
            await context.close()
            await browser.close()
    (raw_dir / "t26e-report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, indent=1)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
