"""Ticket 22 — 英文界面是否存在（只读，不发布）。

对比同一账号、同一 URL 在 `locale=en-US` + `Accept-Language: en-US`
与 `zh-CN` 两种上下文下的文案，并逐项采集工单要求的控件文案：

- 标题 placeholder / 正文 placeholder
- 原创声明开关、原创确认弹窗（只打开，不确认）
- 内容类型声明入口与下拉选项
- 封面弹窗（视频，仅打开）
- 登录页（无会话上下文）

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/22_english_ui_probe.py \
        --account cookies/xiaohongshu_180.json \
        --image .local/probe/test_ok.png \
        --video videos/demo.mp4
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
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

IMAGE_URL = "/publish/publish?from=homepage&target=image"
VIDEO_URL = "/publish/publish?from=homepage&target=video"

CAPTURE_JS = """
() => {
  const vis = n => {
    const r = n.getBoundingClientRect();
    const s = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const txt = (n, max = 300) => (n.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, max);
  const q = s => Array.from(document.querySelectorAll(s));
  const pick = (n, names) => Object.fromEntries(
    Array.from(n.attributes).filter(a => names.includes(a.name)).map(a => [a.name, a.value.slice(0, 240)])
  );
  const btn = q('xhs-publish-btn')[0];
  return {
    url: location.href,
    docLang: document.documentElement.getAttribute('lang'),
    navLang: navigator.language,
    navLangs: navigator.languages,
    intlLocale: Intl.DateTimeFormat().resolvedOptions().locale,
    titlePlaceholders: q('input[placeholder]').map(n => ({
      placeholder: n.getAttribute('placeholder'), visible: vis(n), cls: n.className,
    })),
    bodyPlaceholders: q('p[data-placeholder]').map(n => ({
      placeholder: n.getAttribute('data-placeholder'), text: txt(n), visible: vis(n),
    })),
    switchCards: q('.custom-switch-card').map(n => ({ text: txt(n), visible: vis(n) })),
    selects: q('.d-select-placeholder, .d-select-description').map(n => ({
      text: txt(n), visible: vis(n), cls: n.className,
    })),
    publishBtn: btn ? { text: txt(btn, 80), attrs: pick(btn, ['is-publish', 'submit-disabled']) } : null,
    guideButtons: q('.feature-guide__btn').map(n => ({ text: txt(n, 80), visible: vis(n) })),
    modals: q('[role="dialog"], .d-modal, .d-dialog').map(n => ({
      text: txt(n, 1200), visible: vis(n), cls: String(n.className).slice(0, 160),
    })),
    popovers: q('div.d-popover').filter(vis).map(n => ({ text: txt(n, 1200), cls: String(n.className).slice(0, 160) })),
    coverSection: q('div.upload-cover, .cover-plugin-preview').map(n => ({ text: txt(n, 300), visible: vis(n) })),
    bodyText: (document.body.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 20000),
  };
}
"""


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def capture(page, label: str, raw_dir: Path) -> dict:
    data = await page.evaluate(CAPTURE_JS)
    data["bodyTextHash"] = text_hash(data.get("bodyText") or "")
    (raw_dir / f"22-{label}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        await page.screenshot(path=str(raw_dir / f"22-{label}.png"), full_page=True)
    except Exception as exc:
        print(f"[warn] screenshot {label}: {exc}", file=sys.stderr)
    return data


async def click_selector_js(page, js: str) -> bool:
    return bool(await page.evaluate(js))


async def probe_image_editor(page, label: str, image: str, raw_dir: Path, settle_ms: int) -> dict:
    """上传一张图进编辑器，采集基础控件 + 声明下拉 + 原创弹窗。"""
    out: dict = {}
    await page.goto(_build_xhs_creator_url(IMAGE_URL), wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_selector('input[type="file"]', state="attached", timeout=30000)
    await page.wait_for_timeout(1500)
    await page.locator('input[type="file"]').first.set_input_files(image)
    await page.wait_for_timeout(settle_ms)
    out["base"] = await capture(page, f"{label}-editor", raw_dir)

    # 1) 声明下拉：不依赖文案，点第一个 .d-select-placeholder（'添加内容类型声明'）
    opened = await click_selector_js(
        page,
        """() => {
          const ph = document.querySelector('.d-select-placeholder');
          if (!ph) return false;
          const host = ph.closest('.d-select') || ph.parentElement;
          host.click();
          return true;
        }""",
    )
    await page.wait_for_timeout(1200)
    out["declarationOpened"] = opened
    out["declaration"] = await capture(page, f"{label}-declaration", raw_dir)
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(500)

    # 2) 原创声明：按卡片顺序尝试，命中弹窗即记录（不点确认）
    cards = page.locator(".custom-switch-card")
    n = await cards.count()
    out["originalAttempts"] = []
    for i in range(n):
        try:
            text = (await cards.nth(i).inner_text()).replace("\n", " ").strip()
            if "原创" not in text and "Original" not in text:
                continue
            await cards.nth(i).locator(".d-switch").first.click()
            await page.wait_for_timeout(1800)
            snap = await capture(page, f"{label}-original-modal", raw_dir)
            out["originalAttempts"].append({"index": i, "card": text, "modals": snap["modals"]})
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)
            break
        except Exception as exc:
            out["originalAttempts"].append({"index": i, "error": f"{type(exc).__name__}: {exc}"})
    return out


async def probe_video_cover(page, label: str, video: str, raw_dir: Path) -> dict:
    """上传视频，等到 submit-disabled=false，仅打开封面弹窗采集文案。"""
    out: dict = {}
    await page.goto(_build_xhs_creator_url(VIDEO_URL), wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_selector("input.upload-input", state="attached", timeout=30000)
    await page.wait_for_timeout(1500)
    await page.locator("input.upload-input").first.set_input_files(video)
    ready = False
    for _ in range(60):
        await page.wait_for_timeout(2000)
        state = await page.evaluate(
            """() => {
              const b = document.querySelector('xhs-publish-btn');
              return b ? b.getAttribute('submit-disabled') : null;
            }"""
        )
        if state == "false":
            ready = True
            break
    out["ready"] = ready
    await page.wait_for_timeout(3000)
    out["base"] = await capture(page, f"{label}-video", raw_dir)

    opened = await click_selector_js(
        page,
        """() => {
          const el = document.querySelector('div.upload-cover')
            || document.querySelector('.cover-plugin-preview div.default.pointer, .cover-plugin-preview div.default');
          if (!el) return false;
          el.click();
          return true;
        }""",
    )
    await page.wait_for_timeout(1800)
    out["coverOpened"] = opened
    out["cover"] = await capture(page, f"{label}-cover", raw_dir)
    return out


async def probe_login(browser, raw_dir: Path) -> dict:
    """无会话 + en-US 上下文访问发布页，记录登录页文案。"""
    context = await browser.new_context(
        **{
            **XHS_CONTEXT_KWARGS,
            "locale": "en-US",
            "extra_http_headers": {"Accept-Language": "en-US,en;q=0.9"},
        },
        user_agent=await _xhs_user_agent(browser),
    )
    context = await set_init_script(context)
    page = await context.new_page()
    out: dict = {}
    try:
        resp = await page.goto(
            _build_xhs_creator_url(IMAGE_URL), wait_until="domcontentloaded", timeout=60000
        )
        out["status"] = getattr(resp, "status", None)
        out["headers"] = {
            k: v
            for k, v in (getattr(resp, "headers", {}) or {}).items()
            if k.lower() in {"content-language", "content-type", "vary"}
        }
        await page.wait_for_timeout(5000)
        out["finalUrl"] = page.url
        snap = await page.evaluate(CAPTURE_JS)
        snap["bodyTextHash"] = text_hash(snap.get("bodyText") or "")
        out["capture"] = snap
        login_box = page.locator(XHS_LOGIN_BOX_SELECTOR).first
        out["loginBoxCount"] = await login_box.count()
        if await login_box.count():
            out["loginBoxVisible"] = await login_box.is_visible()
            out["loginBoxText"] = (await login_box.inner_text()).replace("\n", " | ").strip()[:1200]
        (raw_dir / "22-login-en-US.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        try:
            await page.screenshot(path=str(raw_dir / "22-login-en-US.png"), full_page=True)
        except Exception as exc:
            print(f"[warn] screenshot login: {exc}", file=sys.stderr)
    finally:
        await page.close()
        await context.close()
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--video", default=None)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    ap.add_argument("--settle-ms", type=int, default=10000)
    ap.add_argument("--locales", default="zh-CN,en-US")
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {"account": args.account, "locales": {}}

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, **XHS_LAUNCH_KWARGS)
        try:
            ua = await _xhs_user_agent(browser)
            for locale in args.locales.split(","):
                locale = locale.strip()
                tag = "en-US" if locale.lower().startswith("en") else locale
                ctx_kwargs = {
                    **XHS_CONTEXT_KWARGS,
                    "locale": locale,
                    "extra_http_headers": {
                        "Accept-Language": f"{locale},{locale.split('-')[0]};q=0.9"
                    },
                }
                context = await browser.new_context(
                    storage_state=args.account, user_agent=ua, **ctx_kwargs
                )
                context = await set_init_script(context)
                page = await context.new_page()
                entry: dict = {"localeParam": locale}
                try:
                    entry["image"] = await probe_image_editor(
                        page, f"{tag}-image", args.image, raw_dir, args.settle_ms
                    )
                    entry["video"] = await probe_video_cover(
                        page, f"{tag}-video", args.video, raw_dir
                    )
                except Exception as exc:
                    entry["error"] = f"{type(exc).__name__}: {exc}"
                finally:
                    await page.close()
                    await context.close()
                report["locales"][tag] = entry

            # 无会话登录页（en-US）
            report["login"] = await probe_login(browser, raw_dir)
        finally:
            await browser.close()

    # 计算 zh/en 同一节点的文案差异
    diffs: dict = {}
    zh = report["locales"].get("zh-CN") or {}
    en = report["locales"].get("en-US") or {}
    for stage in ("base",):
        z = (zh.get("image") or {}).get(stage) or {}
        e = (en.get("image") or {}).get(stage) or {}
        for key in (
            "docLang",
            "navLang",
            "navLangs",
            "titlePlaceholders",
            "bodyPlaceholders",
            "switchCards",
            "selects",
            "guideButtons",
            "bodyTextHash",
        ):
            if z.get(key) != e.get(key):
                diffs[key] = {"zh-CN": z.get(key), "en-US": e.get(key)}
    report["diff"] = diffs
    report["identicalBodyText"] = (
        ((zh.get("image") or {}).get("base") or {}).get("bodyTextHash")
        == ((en.get("image") or {}).get("base") or {}).get("bodyTextHash")
    )

    out_path = raw_dir / "22-report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:20000])
    print(f"\n[ok] raw -> {raw_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
