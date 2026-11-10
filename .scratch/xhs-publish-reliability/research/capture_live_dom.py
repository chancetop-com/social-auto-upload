"""Ticket 02 — 真机 DOM 取证脚本（只读，不发布）。

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/capture_live_dom.py \
        --account cookies/xiaohongshu_180.json \
        --image .local/probe/test_ok.png

行为：
1. 以本地模式同一套 launch/context 参数（channel=chromium、zh-CN、stealth init script、
   UA 去掉 HeadlessChrome）打开三个发布页 URL，记录落地 URL 与锚点命中表，落 HTML 快照。
2. 在图文页 set_input_files 一张图片（仅进入编辑器，不填标题、不点发布），再记录一次命中表。
3. 输出 JSON 结果到 stdout（供人工转写成 research 文档）。

不做：填标题/正文/话题、点击发布、上传视频。
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

URLS = {
    "video": "/publish/publish?from=homepage&target=video",
    "image": "/publish/publish?from=homepage&target=image",
    "official": "/publish/publish?source=official",
}

SELECTORS = {
    # 发布按钮
    "xhs-publish-btn": "xhs-publish-btn",
    "old-publish-btn": ".publish-page-publish-btn button.bg-red",
    "any-发布-button": 'button:has-text("发布")',
    # 标题
    "d-input-input": "div.d-input input",
    "title-placeholder": 'input[placeholder*="填写标题"]',
    # 正文
    "textbox": 'div[role="textbox"][contenteditable="true"]',
    "tiptap": "div.tiptap",
    "ql-editor": "div.ql-editor",
    "body-placeholder": 'p[data-placeholder*="输入正文描述"]',
    # 话题
    "topic-container-name": "#creator-editor-topic-container .item .name",
    "topic-anchor": "a[data-topic]",
    # 图文上传
    "upload-content": "div.upload-content",
    "upload-input": ".upload-input",
    "img-preview": ".img-preview-area .pr",
    "file-input": 'input[type="file"]',
    # 选项
    "post-time-switch": ".post-time-wrapper .d-switch",
    "custom-switch": ".custom-switch-card",
    "switch-simulator": ".d-switch-simulator",
    "datepicker-input": ".date-picker-container input",
    "d-datepicker-input": ".d-datepicker-input-filter input",
    # 浮层
    "d-popover": "div.d-popover",
    "feature-guide-btn": ".feature-guide__btn",
    # 登录
    "login-box": XHS_LOGIN_BOX_SELECTOR,
}

PROBE_JS = """
(args) => {
  const {selectors} = args;
  const out = {};
  for (const [name, sel] of Object.entries(selectors)) {
    let nodes = [];
    try { nodes = Array.from(document.querySelectorAll(sel)); } catch (e) {
      out[name] = {error: String(e)}; continue;
    }
    const visible = nodes.filter(n => {
      const r = n.getBoundingClientRect();
      const st = getComputedStyle(n);
      return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
    });
    const first = nodes[0];
    const attrs = {};
    if (first) {
      for (const a of first.attributes) {
        if (['class', 'placeholder', 'role', 'contenteditable', 'type', 'accept',
             'is-publish', 'submit-disabled', 'disabled', 'aria-disabled',
             'data-topic', 'data-placeholder', 'id'].includes(a.name)) {
          attrs[a.name] = a.value.slice(0, 300);
        }
      }
    }
    out[name] = {
      count: nodes.length,
      visible: visible.length,
      tag: first ? first.tagName.toLowerCase() : null,
      attrs,
      text: first ? (first.innerText || '').trim().slice(0, 80) : null,
    };
  }
  return out;
}
"""


async def probe(page) -> dict:
    return await page.evaluate(PROBE_JS, {"selectors": SELECTORS})


async def snap(page, raw_dir: Path, label: str) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    html = await page.content()
    (raw_dir / f"{label}.html").write_text(html, encoding="utf-8")
    try:
        await page.screenshot(path=str(raw_dir / f"{label}.png"), full_page=True)
    except Exception as exc:  # 截图失败不影响取证
        print(f"[warn] screenshot {label}: {exc}", file=sys.stderr)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    ap.add_argument("--settle-ms", type=int, default=8000)
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    report: dict = {"account": args.account, "visits": {}, "editor": None}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, **XHS_LAUNCH_KWARGS)
        try:
            context = await browser.new_context(
                storage_state=args.account,
                user_agent=await _xhs_user_agent(browser),
                **XHS_CONTEXT_KWARGS,
            )
            context = await set_init_script(context)
            page = await context.new_page()
            try:
                # ---- 1. 三个入口 URL 的落地差异 ----
                for name, path in URLS.items():
                    url = _build_xhs_creator_url(path)
                    entry: dict = {"requested": url}
                    try:
                        resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                        entry["status"] = getattr(resp, "status", None)
                        await page.wait_for_timeout(args.settle_ms)
                        entry["final_url"] = page.url
                        entry["title"] = await page.title()
                        entry["probes"] = await probe(page)
                        await snap(page, raw_dir, f"empty-{name}")
                    except Exception as exc:
                        entry["error"] = f"{type(exc).__name__}: {exc}"
                    report["visits"][name] = entry

                # ---- 2. 图文编辑器状态（上传一张图，不进发布）----
                editor: dict = {}
                try:
                    await page.goto(
                        _build_xhs_creator_url("/publish/publish?from=homepage&target=image"),
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    await page.wait_for_selector(
                        'input[type="file"]', state="attached", timeout=30000
                    )
                    await page.wait_for_timeout(2000)
                    editor["url_before_upload"] = page.url
                    inputs = page.locator('input[type="file"]')
                    if await inputs.count() == 0:
                        editor["error"] = "no file input"
                    else:
                        await inputs.first.set_input_files(args.image)
                        editor["uploaded"] = True
                        await page.wait_for_timeout(args.settle_ms + 6000)
                        editor["url_after_upload"] = page.url
                        editor["probes"] = await probe(page)
                        await snap(page, raw_dir, "editor-image")
                except Exception as exc:
                    editor["error"] = f"{type(exc).__name__}: {exc}"
                report["editor"] = editor
            finally:
                await page.close()
                await context.close()
        finally:
            await browser.close()

    out_path = raw_dir / "probes.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n[ok] raw -> {raw_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
