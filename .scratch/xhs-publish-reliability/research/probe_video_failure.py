"""Ticket 24 — 视频上传失败态取证（只读，不发布）。

覆盖 09 §6 第 4 项：
  - 坏文件（假 mp4）：页面有没有结构信号（upload input 复现 / 「重新上传」节点 /
    submit-disabled 回退 / 预览区形态）
  - 网络中断（上传中切离线再恢复）：失败面与自动恢复行为

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_video_failure.py \
        --account cookies/xiaohongshu_180.json \
        --video videos/demo.mp4 \
        --bad .local/probe/bad.mp4
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
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

VIDEO_URL = _build_xhs_creator_url("/publish/publish?from=homepage&target=video")

STATE_JS = """
() => {
  const btn = document.querySelector('xhs-publish-btn');
  const textHits = {};
  for (const needle of ['重新上传', '上传失败', '上传成功', '分辨率', '点击重试', '重试']) {
    const hits = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const t = (node.textContent || '').trim();
      if (t.includes(needle)) {
        const el = node.parentElement;
        hits.push({
          tag: el ? el.tagName.toLowerCase() : null,
          cls: el ? (el.className || '').toString().slice(0, 120) : null,
          text: t.slice(0, 80),
          clickable: !!(el && (el.onclick || el.tagName === 'BUTTON' || el.getAttribute('role') === 'button')),
        });
      }
    }
    textHits[needle] = hits.slice(0, 6);
  }
  const stages = Array.from(document.querySelectorAll(
    '.stage, .upload-content, .video-preview, .preview-area, .upload-input'
  )).map(n => ({tag: n.tagName.toLowerCase(), cls: (n.className || '').toString().slice(0, 160),
                text: (n.innerText || '').trim().slice(0, 120)}));
  return {
    url: location.href,
    uploadContent: !!document.querySelector('div.upload-content'),
    uploadInputCount: document.querySelectorAll('input.upload-input').length,
    allFileInputs: document.querySelectorAll('input[type=file]').length,
    publishBtn: !!btn,
    btn: btn ? {isPublish: btn.getAttribute('is-publish'),
                submitDisabled: btn.getAttribute('submit-disabled')} : null,
    titleInput: !!document.querySelector('div.d-input input'),
    bodyEditor: !!document.querySelector('div.tiptap'),
    textHits,
    stages,
    bodyText: (document.body.innerText || '').trim().slice(0, 900),
  };
}
"""


class Sampler:
    def __init__(self, page, interval_s: float = 0.5):
        self.page = page
        self.interval = interval_s
        self.rows: list = []
        self._task = None

    async def _loop(self):
        while True:
            try:
                self.rows.append(
                    {"t": round(time.monotonic() - self.t0, 2),
                     "state": await self.page.evaluate(STATE_JS)}
                )
            except Exception as exc:
                self.rows.append({"t": round(time.monotonic() - self.t0, 2),
                                  "error": f"{type(exc).__name__}: {exc}"})
            await asyncio.sleep(self.interval)

    def start(self):
        self.t0 = time.monotonic()
        self._task = asyncio.create_task(self._loop())

    async def stop(self):
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


def install_net_log(page, bucket: dict) -> None:
    def on_req(req):
        if req.method in ("POST", "PUT") and (
            "ros-upload" in req.url or "upload" in req.url
        ):
            bucket.setdefault("requests", []).append(
                {"t": time.monotonic(), "method": req.method, "url": req.url[:200]}
            )

    page.on("request", on_req)


async def snap(page, raw_dir: Path, label: str) -> None:
    try:
        await page.screenshot(path=str(raw_dir / f"t24-{label}.png"), full_page=True)
    except Exception as exc:
        print(f"[warn] screenshot {label}: {exc}", file=sys.stderr)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--bad", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    ap.add_argument("--observe-s", type=float, default=40.0)
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    # corrupt "video": random bytes with .mp4 extension
    bad = Path(args.bad)
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(os.urandom(64 * 1024))
    report: dict = {"ticket": 24, "phase": "video-failure"}

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
            net: dict = {}
            install_net_log(page, net)
            try:
                # ================= A. corrupt file =================
                await page.goto(VIDEO_URL, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
                await page.wait_for_timeout(2500)
                login_box = await page.locator(XHS_LOGIN_BOX_SELECTOR).count()
                report["login"] = {"url": page.url, "login_box": login_box,
                                   "expired": page.url.startswith(_build_xhs_creator_url("/login"))
                                   or login_box > 0}
                if report["login"]["expired"]:
                    print("[abort] login expired", file=sys.stderr)
                    return 2
                report["baseline"] = await page.evaluate(STATE_JS)

                sampler = Sampler(page)
                sampler.start()
                await page.locator("div.upload-content input[type=file]").first.set_input_files(
                    str(bad)
                )
                await asyncio.sleep(args.observe_s)
                await sampler.stop()
                report["bad_file"] = {
                    "file": str(bad),
                    "size": bad.stat().st_size,
                    "samples": sampler.rows,
                    "net": net.get("requests", []),
                }
                report["bad_file_final"] = await page.evaluate(STATE_JS)
                await snap(page, raw_dir, "video-bad-final")
                net.clear()

                # ================= B. network interruption =================
                await page.goto(VIDEO_URL, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
                await page.wait_for_timeout(2000)
                report["before_cut"] = await page.evaluate(STATE_JS)

                sampler = Sampler(page)
                sampler.start()
                # slow the uplink so the cut lands mid-upload
                cdp = await context.new_cdp_session(page)
                await cdp.send(
                    "Network.emulateNetworkConditions",
                    {"offline": False, "latency": 20,
                     "downloadThroughput": 4 * 1024 * 1024,
                     "uploadThroughput": 60 * 1024},
                )
                await page.locator("div.upload-content input[type=file]").first.set_input_files(
                    args.video
                )
                await asyncio.sleep(4)
                await cdp.send(
                    "Network.emulateNetworkConditions",
                    {"offline": True, "latency": 0,
                     "downloadThroughput": -1, "uploadThroughput": -1},
                )
                await asyncio.sleep(12)
                cut_state = await page.evaluate(STATE_JS)
                await cdp.send(
                    "Network.emulateNetworkConditions",
                    {"offline": False, "latency": 20,
                     "downloadThroughput": 4 * 1024 * 1024,
                     "uploadThroughput": 200 * 1024},
                )
                await asyncio.sleep(args.observe_s)
                await sampler.stop()
                report["network_cut"] = {
                    "state_during_cut": cut_state,
                    "final": await page.evaluate(STATE_JS),
                    "samples": sampler.rows,
                    "net": net.get("requests", []),
                }
                await snap(page, raw_dir, "video-cut-final")
            finally:
                await page.close()
                await context.close()
        finally:
            await browser.close()

    (raw_dir / "t24-video-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "login": report.get("login"),
        "bad_final": report.get("bad_file_final"),
        "bad_sample_count": len(report.get("bad_file", {}).get("samples", [])),
        "cut_state": report.get("network_cut", {}).get("state_during_cut"),
        "cut_final": report.get("network_cut", {}).get("final"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
