"""Ticket 24 — 第 2 张入口到底派发到哪个 input（只读）。

上传一张小图进入编辑器后，点 `.img-preview-area .entry`，用 document 捕获期
click 监听器记录被点的 input，并与两个同 accept input 的 `multiple` 对照。

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_entry_input.py \
        --account cookies/xiaohongshu_180.json --image .local/probe/test_carousel2.png
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

INPUT_TREE_JS = """
() => Array.from(document.querySelectorAll('input[type=file]')).map((n, i) => {
  const chain = []; let p = n;
  for (let k = 0; k < 5 && p; k++) {
    chain.push({tag: (p.tagName || '').toLowerCase(),
                cls: (p.className || '').toString().slice(0, 140)});
    p = p.parentElement;
  }
  return {
    index: i, accept: n.accept, multiple: n.multiple, id: n.id, name: n.name,
    display: getComputedStyle(n).display, chain,
    uniqueSelector: (n.multiple
      ? '.img-list .top input[type=file][multiple]'
      : '.img-list .top input[type=file]:not([multiple])'),
  };
})
"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"ticket": 24, "phase": "entry-input"}

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
                await page.goto(IMAGE_URL, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
                await page.wait_for_timeout(2500)
                report["inputs_empty"] = await page.evaluate(INPUT_TREE_JS)

                await page.locator("div.upload-content input[type=file]").first.set_input_files(
                    args.image
                )
                # wait until the tile leaves the uploading mask
                for _ in range(120):
                    st = await page.evaluate(
                        """() => ({pr: document.querySelectorAll('.img-preview-area .pr').length,
                                   up: document.querySelectorAll(
                                     '.img-preview-area .pr .mask.uploading').length})"""
                    )
                    if st["pr"] >= 1 and st["up"] == 0:
                        break
                    await asyncio.sleep(0.25)
                report["inputs_editor"] = await page.evaluate(INPUT_TREE_JS)

                await page.evaluate(
                    """() => {
                      window.__clickedInputs = [];
                      document.addEventListener('click', e => {
                        if (e.target && e.target.tagName === 'INPUT') {
                          const n = e.target;
                          window.__clickedInputs.push({
                            accept: n.accept, multiple: n.multiple, id: n.id || null,
                            display: getComputedStyle(n).display,
                            parentCls: (n.parentElement && n.parentElement.className || '').toString(),
                            grandparentCls: (n.parentElement && n.parentElement.parentElement
                                             && n.parentElement.parentElement.className || '').toString(),
                          });
                        }
                      }, true);
                    }"""
                )
                result: dict = {}
                try:
                    async with page.expect_file_chooser(timeout=6000) as fc_info:
                        await page.locator(".img-preview-area .entry").first.click()
                    fc = await fc_info.value
                    result["chooser"] = True
                    result["chooser_element"] = await fc.element.evaluate(
                        """n => ({accept: n.accept, multiple: n.multiple, id: n.id || null,
                                  parentCls: (n.parentElement && n.parentElement.className || '').toString(),
                                  grandparentCls: (n.parentElement && n.parentElement.parentElement
                                                   && n.parentElement.parentElement.className || '').toString()})"""
                    )
                except Exception as exc:
                    result["chooser"] = False
                    result["error"] = f"{type(exc).__name__}: {exc}"
                result["clicked_inputs"] = await page.evaluate(
                    "() => window.__clickedInputs || []"
                )
                report["entry_click"] = result
                await page.screenshot(
                    path=str(raw_dir / "t24-entry-input.png"), full_page=True
                )
            finally:
                await page.close()
                await context.close()
        finally:
            await browser.close()

    (raw_dir / "t24-entry-input.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
