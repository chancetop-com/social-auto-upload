"""Ticket 02 第二阶段 —— 编辑器内控件取证（只读，不发布）。

在图文编辑器里依次打开：定时发布开关、话题联想、内容类型声明下拉、原创声明弹窗，
记录各锚点是否存在、可见、属性形状。全程不点发布、不填标题。

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_editor_controls.py \
        --account cookies/xiaohongshu_180.json --image .local/probe/test_ok.png
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

SELECTORS = {
    "publish-btn": "xhs-publish-btn",
    "old-publish-btn": ".publish-page-publish-btn button.bg-red",
    "schedule-card": '.custom-switch-card:has-text("定时发布")',
    "schedule-switch": '.post-time-wrapper .d-switch',
    "datepicker-container-input": ".date-picker-container input",
    "datepicker-filter-input": ".d-datepicker-input-filter input.d-text",
    "switch-simulators": ".d-switch-simulator",
    "topic-container": "#creator-editor-topic-container",
    "topic-item-name": "#creator-editor-topic-container .item .name",
    "topic-anchor": "a[data-topic]",
    "declaration-trigger": "text=添加内容类型声明",
    "popover": "div.d-popover",
    "modal": "[role='dialog'], .d-modal, .d-dialog",
    "feature-guide": ".feature-guide__btn",
    "title-input": 'input[placeholder*="填写标题"]',
    "body-editor": "div.tiptap",
    "img-preview": ".img-preview-area .pr",
}

CAPTURE_JS = """
(args) => {
  const {selectors, deep} = args;
  const out = {};
  const visible = n => {
    const r = n.getBoundingClientRect();
    const st = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  for (const [name, sel] of Object.entries(selectors)) {
    let nodes = [];
    try { nodes = Array.from(document.querySelectorAll(sel)); } catch (e) { continue; }
    out[name] = {
      count: nodes.length,
      visible: nodes.filter(visible).length,
      items: nodes.slice(0, 10).map(n => ({
        tag: n.tagName.toLowerCase(),
        text: (n.innerText || '').trim().slice(0, 60),
        attrs: Object.fromEntries(Array.from(n.attributes)
          .filter(a => ['class','is-publish','submit-disabled','data-topic','placeholder',
                        'role','type','disabled','aria-checked','data-checked']
            .includes(a.name))
          .map(a => [a.name, a.value.slice(0, 240)])),
        visible: visible(n),
      })),
    };
  }
  return out;
}
"""


async def capture(page, label: str, raw_dir: Path) -> dict:
    data = await page.evaluate(CAPTURE_JS, {"selectors": SELECTORS, "deep": True})
    (raw_dir / f"controls-{label}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        await page.screenshot(path=str(raw_dir / f"controls-{label}.png"), full_page=True)
    except Exception as exc:
        print(f"[warn] screenshot {label}: {exc}", file=sys.stderr)
    return data


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {}
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
                await page.goto(
                    _build_xhs_creator_url("/publish/publish?from=homepage&target=image"),
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await page.wait_for_selector('input[type="file"]', state="attached", timeout=30000)
                await page.locator('input[type="file"]').first.set_input_files(args.image)
                await page.wait_for_timeout(12000)
                report["base"] = await capture(page, "base", raw_dir)

                # 1) 定时发布开关
                try:
                    card = page.locator(".custom-switch-card").filter(has_text="定时发布").first
                    await card.locator(".d-switch").first.click()
                    await page.wait_for_timeout(1800)
                    report["schedule_on"] = await capture(page, "schedule-on", raw_dir)
                except Exception as exc:
                    report["schedule_on"] = {"error": f"{type(exc).__name__}: {exc}"}

                # 2) 话题联想 + 回读
                try:
                    body = page.locator("div.tiptap").first
                    await body.click()
                    await page.keyboard.type("#旅行")
                    await page.wait_for_timeout(2500)
                    report["topic_suggest"] = await capture(page, "topic-suggest", raw_dir)
                    first = page.locator("#creator-editor-topic-container .item .name").first
                    if await first.count():
                        await first.click()
                        await page.wait_for_timeout(1200)
                        report["topic_inserted"] = await capture(page, "topic-inserted", raw_dir)
                    else:
                        report["topic_inserted"] = {"error": "no suggestion item"}
                except Exception as exc:
                    report["topic_inserted"] = {"error": f"{type(exc).__name__}: {exc}"}

                # 3) 内容类型声明下拉
                try:
                    trigger = page.get_by_text("添加内容类型声明", exact=True).first
                    if await trigger.count():
                        await trigger.click(force=True)
                        await page.wait_for_timeout(1200)
                        report["declaration_menu"] = await capture(page, "declaration", raw_dir)
                    else:
                        report["declaration_menu"] = {"error": "trigger not found"}
                    await page.keyboard.press("Escape")
                except Exception as exc:
                    report["declaration_menu"] = {"error": f"{type(exc).__name__}: {exc}"}

                # 4) 原创声明弹窗（只打开，不确认）
                try:
                    card = page.locator(".custom-switch-card").filter(has_text="原创声明").first
                    await card.locator(".d-switch").first.click()
                    await page.wait_for_timeout(1800)
                    report["original_modal"] = await capture(page, "original-modal", raw_dir)
                except Exception as exc:
                    report["original_modal"] = {"error": f"{type(exc).__name__}: {exc}"}
            finally:
                await page.close()
                await context.close()
        finally:
            await browser.close()

    (raw_dir / "controls-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
