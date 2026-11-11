"""Ticket 02/09 取证：视频上传后「发布按钮可点」是否等价于「视频就绪」。

只上传 demo.mp4 到发布页，不填标题、不发布；每 3s 采样一次
xhs-publish-btn 的 is-publish / submit-disabled 与预览区文本。
"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from patchright.async_api import async_playwright
from uploader.xiaohongshu_uploader.main import (
    XHS_CONTEXT_KWARGS, XHS_LAUNCH_KWARGS, _build_xhs_creator_url, _xhs_user_agent,
)
from utils.base_social_media import set_init_script

async def main(video, account, samples=40, interval=3.0):
    rows = []
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True, **XHS_LAUNCH_KWARGS)
        ctx = await b.new_context(storage_state=account, user_agent=await _xhs_user_agent(b), **XHS_CONTEXT_KWARGS)
        ctx = await set_init_script(ctx)
        page = await ctx.new_page()
        await page.goto(_build_xhs_creator_url("/publish/publish?from=homepage&target=video"), wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_selector('input.upload-input', state="attached", timeout=30000)
        await page.wait_for_timeout(2000)
        await page.locator('input.upload-input').first.set_input_files(video)
        start = asyncio.get_event_loop().time()
        for i in range(samples):
            data = await page.evaluate("""() => {
              const btn = document.querySelector('xhs-publish-btn');
              const card = document.querySelector('.custom-switch-card');
              const prev = document.querySelector('div[class*="preview-new"]') || document.querySelector('div[class*="upload-content"]');
              return {
                url: location.href,
                btn: btn ? {isPublish: btn.getAttribute('is-publish'), submitDisabled: btn.getAttribute('submit-disabled')} : null,
                titleBox: !!document.querySelector('input[placeholder*="填写标题"]'),
                text: prev ? (prev.innerText||'').replace(/\\s+/g,' ').slice(0,160) : null,
              };
            }""")
            data["t"] = round(asyncio.get_event_loop().time() - start, 1)
            rows.append(data)
            if data["titleBox"] and data["btn"] and data["btn"]["submitDisabled"] == "false":
                # 不立刻 break：继续多采 3 个点，确认是否稳定
                if i > 0 and rows[-2].get("btn") and rows[-2]["btn"]["submitDisabled"] == "false":
                    pass
            await page.wait_for_timeout(int(interval * 1000))
        await page.screenshot(path=str(Path(__file__).with_name("raw") / "video-after.png"), full_page=True)
        await b.close()
    return rows

if __name__ == "__main__":
    rows = asyncio.run(main(sys.argv[1], sys.argv[2], samples=int(sys.argv[3]) if len(sys.argv)>3 else 40))
    out = Path(__file__).with_name("raw") / "video-readiness.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    for r in rows:
        print(r["t"], r["btn"], "title:", r["titleBox"], "|", (r["text"] or "")[:90])
