"""Ticket 24 — 多图上传时间线取证（只读，不发布）。

覆盖 09 §6 的 1–3、5 项：
  1. `.pr` 出现时机（选中 vs 上传完成）、上传中每项的进度/忙碌态
  2. 第 2 张入口：`.img-preview-area .entry` 是否触发 filechooser；各 input 的归属
  3. 重复派发同一文件是否 N+1；拖拽排序/删除对计数的影响
  5. 20MB 图片的真实上传耗时（60s 余量）

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_multi_image.py \
        --account cookies/xiaohongshu_180.json \
        --small .local/probe/test_carousel2.png \
        --big .local/probe/test_20mb.png \
        --deep
"""
from __future__ import annotations

import argparse
import asyncio
import json
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

IMAGE_URL = _build_xhs_creator_url("/publish/publish?from=homepage&target=image")

INPUT_TREE_JS = """
() => Array.from(document.querySelectorAll('input[type=file]')).map((n, i) => {
  const chain = [];
  let p = n;
  for (let k = 0; k < 7 && p; k++) {
    chain.push({
      tag: (p.tagName || '').toLowerCase(),
      cls: (p.className || '').toString().slice(0, 200),
      id: p.id || null,
      role: p.getAttribute ? p.getAttribute('role') : null,
    });
    p = p.parentElement;
  }
  const r = n.getBoundingClientRect();
  const st = getComputedStyle(n);
  return {
    index: i,
    accept: n.accept,
    id: n.id,
    name: n.name,
    cls: (n.className || '').toString().slice(0, 160),
    hidden: n.hidden,
    disabled: n.disabled,
    multiple: n.multiple,
    display: st.display,
    visibility: st.visibility,
    opacity: st.opacity,
    rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
    outer: n.outerHTML.slice(0, 400),
    chain,
  };
})
"""

STATE_JS = """
() => {
  const area = document.querySelector('.img-preview-area') || document.querySelector('.img-upload-area');
  const btn = document.querySelector('xhs-publish-btn');
  const prs = Array.from(document.querySelectorAll('.img-preview-area .pr'));
  return {
    url: location.href,
    ready: !!document.querySelector('input.upload-input') || prs.length > 0,
    previewArea: !!document.querySelector('.img-preview-area'),
    uploadArea: !!document.querySelector('.img-upload-area'),
    uploadContent: !!document.querySelector('div.upload-content'),
    pr: prs.length,
    entry: document.querySelectorAll('.img-preview-area .entry').length,
    inputs: document.querySelectorAll('input[type=file]').length,
    btn: btn ? {
      isPublish: btn.getAttribute('is-publish'),
      submitDisabled: btn.getAttribute('submit-disabled'),
    } : null,
    titleInput: !!document.querySelector('div.d-input input'),
    bodyEditor: !!document.querySelector('div.tiptap'),
    areaHtml: area ? area.outerHTML.slice(0, 24000) : null,
  };
}
"""

SAMPLER_JS = """
() => {
  const MAX = 4000;
  if (window.__t24 && window.__t24.timer) clearInterval(window.__t24.timer);
  if (window.__t24 && window.__t24.observer) window.__t24.observer.disconnect();
  const rec = {start: performance.now(), samples: [], mutations: [], mutationsTotal: 0};
  window.__t24 = rec;
  let lastPr = -1;

  const pick = () => {
    const prs = Array.from(document.querySelectorAll('.img-preview-area .pr'));
    const btn = document.querySelector('xhs-publish-btn');
    const area = document.querySelector('.img-preview-area');
    const sample = {
      t: Math.round(performance.now() - rec.start),
      pr: prs.length,
      items: prs.map(n => {
        const img = n.querySelector('img');
        const prog = Array.from(n.querySelectorAll(
          '[class*=progress],[class*=percent],[role=progressbar],[aria-valuenow]'
        )).slice(0, 4).map(p => ({
          tag: p.tagName.toLowerCase(),
          cls: (p.className || '').toString().slice(0, 90),
          now: p.getAttribute('aria-valuenow'),
          text: (p.innerText || '').trim().slice(0, 24),
        }));
        const ic = n.querySelector('.img-container');
        const mask = n.querySelector('.mask');
        return {
          cls: (n.className || '').toString().slice(0, 160),
          ariaBusy: n.getAttribute('aria-busy'),
          imgContainerBusy: ic ? ic.getAttribute('aria-busy') : null,
          maskCls: mask ? (mask.className || '').toString() : null,
          style: (n.getAttribute('style') || '').slice(0, 160),
          text: (n.innerText || '').trim().slice(0, 60),
          imgSrc: img ? (img.getAttribute('src') || '').slice(0, 120) : null,
          imgComplete: img ? img.complete : null,
          prog,
          htmlLen: n.innerHTML.length,
          desc: Array.from(new Set(Array.from(n.querySelectorAll('*')).map(
            e => e.tagName.toLowerCase() + '.' + (e.className || '').toString()
                  .split(' ').filter(Boolean).slice(0, 2).join('.')
          ))).slice(0, 24),
        };
      }),
      entry: document.querySelectorAll('.img-preview-area .entry').length,
      inputs: document.querySelectorAll('input[type=file]').length,
      btn: btn ? {
        isPublish: btn.getAttribute('is-publish'),
        submitDisabled: btn.getAttribute('submit-disabled'),
      } : null,
      areaHtmlLen: area ? area.innerHTML.length : null,
    };
    if (sample.pr !== lastPr) {
      sample.changedFrom = lastPr;
      sample.snapshot = prs.map(n => n.outerHTML.slice(0, 2000));
      lastPr = sample.pr;
    }
    return sample;
  };

  rec.samples.push(pick());
  rec.timer = setInterval(() => {
    if (rec.samples.length < MAX) rec.samples.push(pick());
  }, 250);

  const area = document.querySelector('.img-preview-area')
    || document.querySelector('.img-upload-area')
    || document.body;
  rec.observer = new MutationObserver(muts => {
    rec.mutationsTotal += muts.length;
    if (rec.mutations.length > 1500) return;
    for (const m of muts) {
      const el = m.target;
      const inPreview = el && el.closest
        ? !!el.closest('.img-preview-area, .img-upload-area')
        : true;
      if (!inPreview) continue;
      rec.mutations.push({
        t: Math.round(performance.now() - rec.start),
        type: m.type,
        target: ((el.className || '').toString().slice(0, 70) || el.tagName),
        added: Array.from(m.addedNodes).slice(0, 4).map(
          n => ((n.className || '').toString().slice(0, 60) || n.tagName)
        ),
        removed: m.removedNodes.length,
        attr: m.attributeName,
        attrVal: m.attributeName
          ? String(el.getAttribute(m.attributeName)).slice(0, 60)
          : null,
      });
    }
  });
  rec.observer.observe(area, {
    childList: true, subtree: true, attributes: true,
    attributeFilter: ['class', 'aria-busy', 'src', 'style'],
  });
  return {ok: true, areaFound: !!document.querySelector('.img-preview-area, .img-upload-area')};
}
"""


def install_net_log(page, bucket: dict) -> None:
    pending: dict = {}

    def on_request(req):
        if req.method not in ("POST", "PUT"):
            return
        info = {"method": req.method, "url": req.url[:220], "t0": time.monotonic()}
        pending[req] = info
        bucket.setdefault("requests", []).append(info)

    def on_done(req):
        info = pending.pop(req, None)
        if info is None:
            return
        try:
            body = req.post_data_buffer
            info["bodyBytes"] = len(body) if body is not None else None
        except Exception:
            info["bodyBytes"] = None
        info["t1"] = time.monotonic()
        info["seconds"] = round(info["t1"] - info["t0"], 3)
        try:
            info["status"] = req.response.status if req.response else None
        except Exception:
            info["status"] = None

    page.on("request", on_request)
    page.on("requestfinished", on_done)
    page.on("requestfailed", on_done)


async def stop_and_dump(page, raw_dir: Path, label: str) -> dict:
    data = await page.evaluate(
        """() => {
          const rec = window.__t24;
          if (!rec) return null;
          if (rec.timer) clearInterval(rec.timer);
          if (rec.observer) rec.observer.disconnect();
          return {samples: rec.samples, mutations: rec.mutations,
                  mutationsTotal: rec.mutationsTotal};
        }"""
    )
    if data:
        (raw_dir / f"t24-{label}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return data or {}


async def snap(page, raw_dir: Path, label: str) -> None:
    try:
        await page.screenshot(path=str(raw_dir / f"t24-{label}.png"), full_page=True)
    except Exception as exc:
        print(f"[warn] screenshot {label}: {exc}", file=sys.stderr)


async def wait_count(page, n: int, timeout_s: float) -> float | None:
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        if await page.evaluate(
            "() => document.querySelectorAll('.img-preview-area .pr').length"
        ) >= n:
            return round(time.monotonic() - start, 3)
        await asyncio.sleep(0.2)
    return None


async def wait_mask_done(page, expected: int, timeout_s: float) -> dict:
    """Wait until every tile has left the `.mask.uploading` state."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        st = await page.evaluate(
            """() => ({
              pr: document.querySelectorAll('.img-preview-area .pr').length,
              uploading: document.querySelectorAll(
                '.img-preview-area .pr .mask.uploading').length,
              masks: Array.from(document.querySelectorAll('.img-preview-area .pr .mask'))
                .map(m => (m.className || '').toString()),
            })"""
        )
        if st["pr"] >= expected and st["uploading"] == 0:
            return {"done": True, "at_s": round(time.monotonic() - start, 3), **st}
        await asyncio.sleep(0.25)
    return {"done": False, "at_s": round(time.monotonic() - start, 3)}


async def quiet_wait(page, quiet_s: float, max_s: float) -> dict:
    start = time.monotonic()
    last = -1
    last_change = start
    while time.monotonic() - start < max_s:
        total = await page.evaluate("() => (window.__t24 ? window.__t24.mutationsTotal : -1)")
        if total != last:
            last = total
            last_change = time.monotonic()
        elif time.monotonic() - last_change >= quiet_s:
            return {"quiet_after_s": round(time.monotonic() - start, 2), "mutationsTotal": total}
        await asyncio.sleep(0.4)
    return {"timed_out": True, "after_s": round(time.monotonic() - start, 2), "mutationsTotal": last}


async def open_entry_chooser(page, label: str) -> dict:
    """Click the '+' tile and capture whether/what file chooser it opens."""
    out: dict = {"attempt": label}
    entry = page.locator(".img-preview-area .entry")
    out["entry_count"] = await entry.count()
    out["entry_visible"] = await entry.first.is_visible() if out["entry_count"] else None
    out["entry_box"] = await entry.first.bounding_box() if out["entry_count"] else None
    out["chooser"] = False
    if not out["entry_count"]:
        return out
    try:
        async with page.expect_file_chooser(timeout=6000) as fc_info:
            await entry.first.click()
        fc = await fc_info.value
        elem = fc.element  # patchright/Playwright Python: property, not callable
        out["chooser"] = True
        out["chooser_element"] = await elem.evaluate(
            """n => ({
              tag: n.tagName.toLowerCase(),
              cls: (n.className || '').toString(),
              accept: n.accept || null,
              id: n.id || null,
              rect: (r => [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)])
                    (n.getBoundingClientRect()),
              parent: (n.parentElement && (n.parentElement.className || '').toString()) || null,
              grandparent: (n.parentElement && n.parentElement.parentElement
                            && (n.parentElement.parentElement.className || '').toString()) || null,
            })"""
        )
        out["chooser_file"] = fc
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


async def dispatch_via_entry(page, file: str, label: str) -> dict:
    out = await open_entry_chooser(page, label)
    if out.get("chooser"):
        try:
            await out["chooser_file"].set_files(file)
            out["dispatched"] = True
        except Exception as exc:
            out["set_files_error"] = f"{type(exc).__name__}: {exc}"
        out.pop("chooser_file", None)
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--small", required=True)
    ap.add_argument("--big", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    ap.add_argument("--big-settle-s", type=float, default=180.0)
    ap.add_argument("--first", choices=("small", "big"), default="small")
    ap.add_argument("--deep", action="store_true")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"ticket": 24, "phase": "image", "deep": args.deep}
    net: dict = {}

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
            install_net_log(page, net)
            try:
                await page.goto(IMAGE_URL, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
                await page.wait_for_timeout(2500)

                login_box = await page.locator(XHS_LOGIN_BOX_SELECTOR).count()
                report["login"] = {
                    "url": page.url,
                    "login_box": login_box,
                    "expired": page.url.startswith(_build_xhs_creator_url("/login"))
                    or login_box > 0,
                }
                if report["login"]["expired"]:
                    report["aborted"] = "login expired"
                    print("[abort] login expired", file=sys.stderr)
                    return 2

                report["state_baseline"] = await page.evaluate(STATE_JS)
                report["inputs_baseline"] = await page.evaluate(INPUT_TREE_JS)
                await snap(page, raw_dir, "baseline")

                # ================= Q1/Q5: first image =================
                report["sampler_first"] = await page.evaluate(SAMPLER_JS)
                first_file = args.big if args.first == "big" else args.small
                report["first_file"] = first_file
                report["first_size"] = Path(first_file).stat().st_size
                first_loc = page.locator("div.upload-content input[type=file]")
                report["first_input_count"] = await first_loc.count()
                dispatch_t0 = time.monotonic()
                report["first_dispatch_t0"] = dispatch_t0
                await first_loc.first.set_input_files(first_file)
                report["first_dispatch_returned_s"] = round(time.monotonic() - dispatch_t0, 3)
                got = await wait_count(page, 1, 40)
                report["first_pr_at_s"] = got
                report["first_mask"] = await wait_mask_done(page, 1, args.big_settle_s)
                report["first_settle"] = await quiet_wait(page, 1.5, 30)
                report["first_total_s"] = round(time.monotonic() - dispatch_t0, 3)
                report["state_after_first"] = await page.evaluate(STATE_JS)
                report["inputs_after_first"] = await page.evaluate(INPUT_TREE_JS)
                await snap(page, raw_dir, "after-first")
                report["first_timeline"] = await stop_and_dump(page, raw_dir, "timeline-first")
                report["first_net"] = net.get("requests", [])
                net.clear()

                # ================= Q1/Q2/Q5: second image via .entry =====
                report["sampler_second"] = await page.evaluate(SAMPLER_JS)
                t1 = time.monotonic()
                second_file = args.small if args.first == "big" else args.big
                report["second_file"] = second_file
                report["second_size"] = Path(second_file).stat().st_size
                report["second"] = await dispatch_via_entry(page, second_file, "second")
                report["second_dispatch_t0"] = t1
                report["second_dispatch_returned_s"] = round(time.monotonic() - t1, 3)
                got = await wait_count(page, 2, 60)
                report["second_pr_at_s"] = got
                report["second_mask"] = await wait_mask_done(page, 2, args.big_settle_s)
                report["second_settle"] = await quiet_wait(page, 2.0, 30)
                report["second_total_s"] = round(time.monotonic() - t1, 3)
                report["state_after_second"] = await page.evaluate(STATE_JS)
                report["inputs_after_second"] = await page.evaluate(INPUT_TREE_JS)
                await snap(page, raw_dir, "after-second")
                report["second_timeline"] = await stop_and_dump(page, raw_dir, "timeline-second")
                report["second_net"] = net.get("requests", [])
                net.clear()

                if args.deep:
                    # ---------------- Q3a: repeated dispatch ----------------
                    dup: dict = {}
                    dup["state_before"] = await page.evaluate(STATE_JS)
                    report["sampler_dup"] = await page.evaluate(SAMPLER_JS)
                    t2 = time.monotonic()
                    before_count = await page.evaluate(
                        "() => document.querySelectorAll('.img-preview-area .pr').length"
                    )
                    dup["count_before"] = before_count
                    dup["dispatch"] = await dispatch_via_entry(page, args.small, "dup-small")
                    dup["count_at_dispatch"] = await page.evaluate(
                        "() => document.querySelectorAll('.img-preview-area .pr').length"
                    )
                    dup["pr_at_s"] = await wait_count(page, before_count + 1, 40)
                    dup["settle"] = await quiet_wait(page, 2.0, 60)
                    dup["total_s"] = round(time.monotonic() - t2, 3)
                    dup["state_after"] = await page.evaluate(STATE_JS)
                    dup["timeline"] = await stop_and_dump(page, raw_dir, "timeline-dup")
                    dup["net"] = net.get("requests", [])
                    net.clear()
                    await snap(page, raw_dir, "after-dup")
                    report["duplicate"] = dup

                    # ---------------- Q3b: drag reorder ----------------
                    def order_js():
                        return """() => Array.from(document.querySelectorAll('.img-preview-area .pr'))
                            .map(n => { const i = n.querySelector('img');
                                        return i ? (i.getAttribute('src') || '').slice(-28) : null; })"""

                    drag: dict = {"order_before": await page.evaluate(order_js())}
                    try:
                        prs = page.locator(".img-preview-area .pr")
                        n = await prs.count()
                        drag["pr_count"] = n
                        if n >= 2:
                            b0 = await prs.nth(0).bounding_box()
                            b1 = await prs.nth(1).bounding_box()
                            drag["boxes"] = [b0, b1]
                            if b0 and b1:
                                await page.mouse.move(
                                    b0["x"] + b0["width"] / 2, b0["y"] + b0["height"] / 2
                                )
                                await page.mouse.down()
                                await page.mouse.move(
                                    b1["x"] + b1["width"] / 2 + 40,
                                    b1["y"] + b1["height"] / 2 + 8,
                                    steps=15,
                                )
                                await page.wait_for_timeout(300)
                                await page.mouse.up()
                                await page.wait_for_timeout(2500)
                    except Exception as exc:
                        drag["error"] = f"{type(exc).__name__}: {exc}"
                    drag["order_after"] = await page.evaluate(order_js())
                    drag["count_after"] = await page.evaluate(
                        "() => document.querySelectorAll('.img-preview-area .pr').length"
                    )
                    await snap(page, raw_dir, "after-drag")
                    report["reorder"] = drag

                    # ---------------- Q3c: delete one tile ----------------
                    delete_info: dict = {}
                    try:
                        delete_info["probe"] = await page.evaluate(
                            """() => {
                              const node = document.querySelector('.img-preview-area .pr');
                              if (!node) return null;
                              const cands = Array.from(node.querySelectorAll('*')).filter(n => {
                                const c = (n.className || '').toString().toLowerCase();
                                return /delet|remove|close|trash/.test(c)
                                    || n.tagName.toLowerCase() === 'i';
                              }).map(n => ({tag: n.tagName.toLowerCase(),
                                            cls: (n.className || '').toString().slice(0, 140)}));
                              return {html: node.outerHTML.slice(0, 6000), candidates: cands};
                            }"""
                        )
                        pr = page.locator(".img-preview-area .pr").first
                        await pr.hover()
                        await page.wait_for_timeout(900)
                        delete_info["count_before"] = await page.evaluate(
                            "() => document.querySelectorAll('.img-preview-area .pr').length"
                        )
                        target = pr.locator(".close-btn").first
                        delete_info["delete_selector"] = ".close-btn"
                        if await target.count():
                            delete_info["delete_visible"] = await target.is_visible()
                            await target.click()
                            await page.wait_for_timeout(2500)
                            delete_info["count_after"] = await page.evaluate(
                                "() => document.querySelectorAll('.img-preview-area .pr').length"
                            )
                        else:
                            delete_info["delete_selector"] = None
                    except Exception as exc:
                        delete_info["error"] = f"{type(exc).__name__}: {exc}"
                    report["delete"] = delete_info
                    await snap(page, raw_dir, "after-delete")
            finally:
                await page.close()
                await context.close()
        finally:
            await browser.close()

    (raw_dir / "t24-image-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        k: report.get(k)
        for k in (
            "login", "state_baseline", "sampler_first", "first_file", "first_size",
            "first_pr_at_s", "first_mask", "first_settle", "first_total_s",
            "second_file", "second_size", "second_pr_at_s", "second_mask",
            "second_settle", "second_total_s",
        )
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[ok] raw -> {raw_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
