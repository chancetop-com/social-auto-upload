"""Ticket 24 — 视频失败态的 DOM 结构（只读）。

坏 mp4 上传失败后：
  - 找有没有结构性的错误节点（class 含 error/fail 等）
  - 「重新上传」是独立可点节点还是纯文本；点它是否触发 filechooser、能否恢复

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_video_badfile_dom.py \
        --account cookies/xiaohongshu_180.json --video videos/demo.mp4 --bad .local/probe/bad.mp4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
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

VIDEO_URL = _build_xhs_creator_url("/publish/publish?from=homepage&target=video")

STATE_JS = """
() => {
  const btn = document.querySelector('xhs-publish-btn');
  return {
    submitDisabled: btn ? btn.getAttribute('submit-disabled') : null,
    isPublish: btn ? btn.getAttribute('is-publish') : null,
    uploadContent: !!document.querySelector('div.upload-content'),
    titleInput: !!document.querySelector('div.d-input input'),
    stageText: (document.querySelector('div.stage') || {}).innerText || null,
    uploadInputCount: document.querySelectorAll('input.upload-input').length,
  };
}
"""

DOM_JS = """
() => {
  const round = (el, n = 3) => {
    const out = [];
    let p = el;
    for (let i = 0; i < n && p; i++) {
      out.push({tag: p.tagName.toLowerCase(), cls: (p.className || '').toString().slice(0, 160),
                text: (p.innerText || '').trim().slice(0, 80)});
      p = p.parentElement;
    }
    return out;
  };
  const action = document.querySelector('.video-plugin-title-action');
  const errish = Array.from(document.querySelectorAll(
    '[class*=error], [class*=fail], [class*=err], [class*=invalid]'
  )).slice(0, 12).map(n => ({
    tag: n.tagName.toLowerCase(), cls: (n.className || '').toString().slice(0, 160),
    text: (n.innerText || '').trim().slice(0, 120), outer: n.outerHTML.slice(0, 500),
  }));
  return {
    actionFound: !!action,
    actionOuter: action ? action.outerHTML.slice(0, 700) : null,
    actionChain: action ? round(action, 4) : null,
    actionClickableClosest: action
      ? (() => { let p = action; while (p) {
          if (['A','BUTTON','LABEL'].includes(p.tagName) || p.getAttribute('role') === 'button'
              || typeof p.onclick === 'function') {
            return {tag: p.tagName.toLowerCase(), cls: (p.className || '').toString().slice(0, 160)};
          }
          p = p.parentElement;
        } return null; })()
      : null,
    errish,
    errorTextNodes: (() => {
      const hits = [];
      const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        const t = (node.textContent || '').trim();
        if (t.includes('检测到视频文件') || t.includes('上传失败')) {
          hits.push({text: t.slice(0, 120),
                     parent: node.parentElement ? node.parentElement.tagName.toLowerCase() : null,
                     parentCls: node.parentElement
                       ? (node.parentElement.className || '').toString().slice(0, 160) : null});
        }
      }
      return hits.slice(0, 10);
    })(),
    stageOuter: (document.querySelector('div.stage') || {}).outerHTML
      ? document.querySelector('div.stage').outerHTML.slice(0, 4000) : null,
  };
}
"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--bad", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    bad = Path(args.bad)
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(os.urandom(64 * 1024))
    report: dict = {"ticket": 24, "phase": "video-badfile-dom"}

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
                await page.goto(VIDEO_URL, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
                await page.wait_for_timeout(2500)
                await page.locator("div.upload-content input[type=file]").first.set_input_files(
                    str(bad)
                )
                await page.wait_for_timeout(5000)
                report["failed_state"] = await page.evaluate(STATE_JS)
                report["failed_dom"] = await page.evaluate(DOM_JS)
                await page.screenshot(path=str(raw_dir / "t24-video-bad-dom.png"), full_page=True)

                # does 「重新上传」 open a file chooser, and does a valid file recover it?
                retry: dict = {}
                try:
                    async with page.expect_file_chooser(timeout=6000) as fc_info:
                        await page.locator(".video-plugin-title-action").first.click()
                    fc = await fc_info.value
                    retry["chooser"] = True
                    retry["chooser_element"] = await fc.element.evaluate(
                        "n => ({tag: n.tagName.toLowerCase(), accept: n.accept || null,"
                        " cls: (n.className||'').toString(), multiple: n.multiple})"
                    )
                    await fc.set_files(args.video)
                    retry["dispatched_valid"] = True
                    await page.wait_for_timeout(30000)
                    retry["state_after_retry"] = await page.evaluate(STATE_JS)
                except Exception as exc:
                    retry["chooser"] = False
                    retry["error"] = f"{type(exc).__name__}: {exc}"
                report["retry"] = retry
                await page.screenshot(path=str(raw_dir / "t24-video-bad-retry.png"), full_page=True)
            finally:
                await page.close()
                await context.close()
        finally:
            await browser.close()

    (raw_dir / "t24-video-badfile-dom.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "failed_state": report.get("failed_state"),
        "actionFound": report.get("failed_dom", {}).get("actionFound"),
        "actionOuter": report.get("failed_dom", {}).get("actionOuter"),
        "actionChain": report.get("failed_dom", {}).get("actionChain"),
        "errish": report.get("failed_dom", {}).get("errish"),
        "errorTextNodes": report.get("failed_dom", {}).get("errorTextNodes"),
        "retry": report.get("retry"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
