"""Ticket 22 补采 —— 封面弹窗与登录二维码面板（en-US 上下文，只读，不发布）。

首轮 `22_english_ui_probe.py` 的两处没采到：

- 视频页「设置封面」点击被 `pk-cover-guide-popover`（「我知道了」全覆盖层）吞掉，
  封面弹窗从未打开；
- 登录页默认停在短信登录 tab，未切到「APP扫一扫登录」二维码面板。

本脚本只补这两处，全部在 `locale=en-US` + `Accept-Language: en-US` 下进行。

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/22_english_ui_cover_login.py \
        --account cookies/xiaohongshu_180.json --video videos/demo.mp4
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
    XHS_LOGIN_BOX_SELECTOR,
    _build_xhs_creator_url,
    _xhs_user_agent,
)
from utils.base_social_media import set_init_script  # noqa: E402

EN_KWARGS = {
    **XHS_CONTEXT_KWARGS,
    "locale": "en-US",
    "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
}

CAPTURE_JS = """
() => {
  const vis = n => {
    const r = n.getBoundingClientRect();
    const s = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const txt = (n, max = 1500) => (n.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, max);
  const q = s => Array.from(document.querySelectorAll(s));
  return {
    url: location.href,
    navLang: navigator.language,
    modals: q('[role="dialog"], .d-modal, .d-dialog, [class*="modal"], [class*="cover-popup"], [class*="cover-modal"]')
      .filter(vis)
      .map(n => ({ text: txt(n), cls: String(n.className).slice(0, 200) })),
    dialogsWithButton: q('button, .d-button, div[class*="button"]')
      .filter(vis)
      .map(n => txt(n, 60))
      .filter(Boolean)
      .slice(0, 40),
    bodyText: (document.body.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 20000),
  };
}
"""


async def capture(page, label: str, raw_dir: Path) -> dict:
    data = await page.evaluate(CAPTURE_JS)
    (raw_dir / f"22-{label}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        await page.screenshot(path=str(raw_dir / f"22-{label}.png"), full_page=True)
    except Exception as exc:
        print(f"[warn] screenshot {label}: {exc}", file=sys.stderr)
    return data


async def dismiss_overlays(page) -> list[str]:
    """点掉所有可见的「我知道了」引导（文案用于记录，逻辑不依赖它）。"""
    clicked = []
    for _ in range(4):
        handled = await page.evaluate(
            """() => {
              const vis = n => {
                const r = n.getBoundingClientRect();
                const s = getComputedStyle(n);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
              };
              const hits = Array.from(document.querySelectorAll('button, .feature-guide__btn, [class*="guide"] button, [class*="guide__btn"]'))
                .filter(n => vis(n) && ['我知道了', 'I know', 'Got it'].includes((n.innerText || '').trim()));
              hits.forEach(n => n.click());
              return hits.map(n => (n.innerText || '').trim());
            }"""
        )
        if not handled:
            break
        clicked.extend(handled)
        await page.wait_for_timeout(800)
    return clicked


async def probe_cover(browser, account: str, video: str, raw_dir: Path) -> dict:
    out: dict = {}
    context = await browser.new_context(
        storage_state=account, user_agent=await _xhs_user_agent(browser), **EN_KWARGS
    )
    context = await set_init_script(context)
    page = await context.new_page()
    try:
        await page.goto(
            _build_xhs_creator_url("/publish/publish?from=homepage&target=video"),
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_selector("input.upload-input", state="attached", timeout=30000)
        await page.wait_for_timeout(1500)
        await page.locator("input.upload-input").first.set_input_files(video)
        ready = False
        for _ in range(60):
            await page.wait_for_timeout(2000)
            state = await page.evaluate(
                """() => {
                  const b = document.querySelector('xhs-publish-btn');
                  const cover = document.querySelector('div.upload-cover, .cover-plugin-preview');
                  return {disabled: b ? b.getAttribute('submit-disabled') : null, cover: !!cover};
                }"""
            )
            if state["disabled"] == "false" and state["cover"]:
                ready = True
                break
        out["ready"] = ready
        await page.wait_for_timeout(3000)
        out["dismissed"] = await dismiss_overlays(page)
        out["before"] = await capture(page, "en-US-cover-before", raw_dir)

        opened = await page.evaluate(
            """() => {
              const el = document.querySelector('div.upload-cover')
                || document.querySelector('.cover-plugin-preview div.default.pointer, .cover-plugin-preview div.default');
              if (!el) return false;
              el.click();
              return true;
            }"""
        )
        await page.wait_for_timeout(2000)
        out["coverOpened"] = opened
        out["after"] = await capture(page, "en-US-cover-modal", raw_dir)
    finally:
        await page.close()
        await context.close()
    return out


async def probe_login(browser, raw_dir: Path) -> dict:
    out: dict = {}
    context = await browser.new_context(
        user_agent=await _xhs_user_agent(browser), **EN_KWARGS
    )
    context = await set_init_script(context)
    page = await context.new_page()
    try:
        await page.goto(
            _build_xhs_creator_url("/publish/publish?from=homepage&target=image"),
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(5000)
        out["finalUrl"] = page.url
        box = page.locator(XHS_LOGIN_BOX_SELECTOR).first
        out["defaultText"] = (await box.inner_text()).replace("\n", " | ").strip()[:1200]
        out["images"] = await page.evaluate(
            """() => Array.from(document.querySelectorAll('div[class*="login-box"] img'))
                 .map(n => ({cls: String(n.className).slice(0, 120), src: String(n.src).slice(0, 60)}))"""
        )
        # 切到二维码面板：点登录框里的二维码切换图标（结构定位 `img.css-wemwzq`，与现网一致）
        switched = await page.evaluate(
            """() => {
              const box = document.querySelector('div[class*="login-box"]');
              if (!box) return false;
              const icon = box.querySelector('img.css-wemwzq')
                || Array.from(box.querySelectorAll('img'))[0];
              if (!icon) return false;
              icon.click();
              return true;
            }"""
        )
        await page.wait_for_timeout(2000)
        out["switchedToQr"] = switched
        out["qrBoxText"] = (await box.inner_text()).replace("\n", " | ").strip()[:1200]
        out["qrImages"] = await page.evaluate(
            """() => Array.from(document.querySelectorAll('div[class*="login-box"] img'))
                 .map(n => ({cls: String(n.className).slice(0, 120), src: String(n.src).slice(0, 60)}))"""
        )
        out["qrPanel"] = await capture(page, "en-US-login-qr", raw_dir)
    finally:
        await page.close()
        await context.close()
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, **XHS_LAUNCH_KWARGS)
        try:
            report["cover"] = await probe_cover(browser, args.account, args.video, raw_dir)
            report["login"] = await probe_login(browser, raw_dir)
        finally:
            await browser.close()

    (raw_dir / "22-report-extra.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2)[:12000])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
