"""Ticket 26 — 回读 / 越限信号真机取证（只读，全程不点发布、不提交）。

逐条回答 26 的六个问题：

1. 标题越限：`div.title-container div.max_suffix` 是否存在；实际出现的是哪个节点、
   文案格式、出现时机（用 MutationObserver 记录 added node）。
2. 正文越限：`div.edit-container div.length-error` 是否存在；实际节点、文案、阈值、
   话题锚点是否计入正文长度。
3. 定时开关：点击 `.post-time-wrapper .d-switch` 后页面留下什么可观测状态
   （simulator class / aria / 日期输入是否出现 / 发布按钮是否换文案），以及能否可逆地读回。
4. 定时时间输入：写入后 `input.value` 是否提交；Tab / Enter / 失焦前后差异；非法日期表现。
5. 原创开关：确认弹窗关闭后 `.original-wrapper` 的状态是否稳定可读。
6. 内容类型声明 / 封面：入口文本、class、封面 `img.src` 等可观测回读信号（留档）。

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_readback_signals.py \
        --account cookies/xiaohongshu_180.json --image .local/probe/test_carousel1.png
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
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
TITLE_INPUT = 'input[placeholder*="填写标题"]'
BODY_EDITOR = 'div.edit-container div.tiptap[role="textbox"]'

# 供 CSS 选择器 / 容器扫描共用
SELECTORS = {
    "title-container": "div.title-container",
    "title-max-suffix": "div.title-container div.max_suffix",
    "max-suffix-any": "div.max_suffix",
    "suffix-any": ".suffix",
    "title-input": TITLE_INPUT,
    "edit-container": "div.edit-container",
    "length-error": "div.edit-container div.length-error",
    "length-error-any": "div.length-error",
    "body-editor": BODY_EDITOR,
    "post-time-wrapper": ".post-time-wrapper",
    "schedule-switch": ".post-time-wrapper .d-switch",
    "schedule-simulator": ".post-time-wrapper .d-switch-simulator",
    "datepicker-filter": ".d-datepicker-input-filter input.d-text",
    "datepicker-container": ".date-picker-container input",
    "publish-btn": "xhs-publish-btn",
    "original-wrapper": ".original-wrapper",
    "original-switch": ".original-wrapper .d-switch",
    "original-simulator": ".original-wrapper .d-switch-simulator",
    "declaration-select": ".publish-container .d-select",
    "declaration-entry": ".publish-container .d-select-placeholder",
    "cover-stack": ".cover-edit-stack",
    "cover-entry": ".cover-edit-entry",
    "cover-img": ".cover-edit-stack img",
    "modal": ".d-modal.creator-modal-style",
}

SCAN_ROOTS = {
    "edit-container": "div.edit-container",
    "post-time-wrapper": ".post-time-wrapper",
    "original-wrapper": ".original-wrapper",
    "cover-stack": ".cover-edit-stack",
    "declaration-select": ".publish-container .d-select",
}

SNAP_JS = """
({selectors, roots}) => {
  const vis = n => {
    const r = n.getBoundingClientRect();
    const s = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
      && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.1;
  };
  const attrs = n => {
    const keep = ['class','id','role','aria-checked','data-checked','disabled','type',
                  'placeholder','maxlength','src','value','style'];
    const o = {};
    for (const a of Array.from(n.attributes)) {
      if (keep.includes(a.name)) o[a.name] = a.value.slice(0, 200);
    }
    return o;
  };
  const info = n => ({
    tag: n.tagName.toLowerCase(),
    cls: (n.className || '').toString().slice(0, 200),
    text: (n.innerText || n.textContent || '').trim().slice(0, 200),
    attrs: attrs(n),
    visible: vis(n),
    rect: (() => { const r = n.getBoundingClientRect();
                   return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; })(),
    html: (n.outerHTML || '').slice(0, 700),
  });
  const out = {selectors: {}, scans: {}};
  for (const [k, sel] of Object.entries(selectors || {})) {
    let ns = [];
    try { ns = Array.from(document.querySelectorAll(sel)); }
    catch (e) { out.selectors[k] = {error: String(e)}; continue; }
    out.selectors[k] = {count: ns.length, visible: ns.filter(vis).length,
                        items: ns.slice(0, 8).map(info)};
  }
  for (const [k, sel] of Object.entries(roots || {})) {
    const root = document.querySelector(sel);
    if (!root) { out.scans[k] = {missing: true, root: sel}; continue; }
    const hits = Array.from(root.querySelectorAll('*')).filter(n => {
      const s = (n.className || '').toString() + ' ' + (n.getAttribute('id') || '')
        + ' ' + (n.getAttribute('role') || '');
      return /suffix|max|length|error|count|limit|word|char|tip|hint|warn|footer|bottom/i.test(s);
    }).slice(0, 30);
    out.scans[k] = {root: sel, total: hits.length, items: hits.map(info)};
  }
  return out;
}
"""

WATCH_JS = """
(sel) => {
  window.__t26 = window.__t26 || {seen: []};
  if (window.__t26.mo) { try { window.__t26.mo.disconnect(); } catch (e) {} }
  window.__t26.seen = [];
  const root = document.querySelector(sel);
  if (!root) return false;
  const rec = [];
  const cls = n => (n.className || '').toString().slice(0, 160);
  const mo = new MutationObserver(ms => {
    for (const m of ms) {
      if (m.type === 'childList') {
        for (const n of m.addedNodes) {
          if (n.nodeType !== 1) continue;
          rec.push({t: Math.round(performance.now()), kind: 'add',
                    tag: n.tagName.toLowerCase(), cls: cls(n),
                    text: (n.innerText || n.textContent || '').trim().slice(0, 200),
                    html: (n.outerHTML || '').slice(0, 700)});
        }
        for (const n of m.removedNodes) {
          if (n.nodeType !== 1) continue;
          rec.push({t: Math.round(performance.now()), kind: 'remove',
                    tag: n.tagName.toLowerCase(), cls: cls(n),
                    text: (n.innerText || n.textContent || '').trim().slice(0, 200)});
        }
      } else if (m.type === 'attributes') {
        rec.push({t: Math.round(performance.now()), kind: 'attr',
                  tag: m.target.tagName.toLowerCase(), cls: cls(m.target),
                  attr: m.attributeName, old: m.oldValue,
                  now: m.target.getAttribute(m.attributeName)});
      }
      if (rec.length > 400) rec.splice(0, rec.length - 400);
    }
    window.__t26.seen = rec;
  });
  mo.observe(root, {childList: true, subtree: true, attributes: true,
                    attributeOldValue: true,
                    attributeFilter: ['class','aria-checked','data-checked','disabled']});
  window.__t26.mo = mo;
  return true;
}
"""

SEEN_JS = "() => ((window.__t26 && window.__t26.seen) || []).slice(-120)"

class _LoginExpired(RuntimeError):
    """账号 cookie 失效，提前结束（仍写出报告）。"""


LEN_JS = """
() => {
  const ed = document.querySelector('div.edit-container div.tiptap[role="textbox"]');
  const title = document.querySelector('input[placeholder*="填写标题"]');
  return {
    bodyText: ed ? ed.innerText : null,
    bodyTextContent: ed ? ed.textContent : null,
    bodyTextLen: ed ? (ed.innerText || '').length : null,
    titleValue: title ? title.value : null,
    titleLen: title ? title.value.length : null,
    titleMaxlength: title ? title.getAttribute('maxlength') : null,
  };
}
"""


async def snap(page, label: str, raw_dir: Path) -> dict:
    data = await page.evaluate(
        SNAP_JS, {"selectors": SELECTORS, "roots": SCAN_ROOTS}
    )
    data["_label"] = label
    data["_url"] = page.url
    data["_len"] = await page.evaluate(LEN_JS)
    (raw_dir / f"t26-{label}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        await page.screenshot(path=str(raw_dir / f"t26-{label}.png"), full_page=True)
    except Exception as exc:
        print(f"[warn] screenshot {label}: {exc}", file=sys.stderr)
    return data


async def watch(page, selector: str) -> dict:
    ok = await page.evaluate(WATCH_JS, selector)
    return {"root": selector, "watching": bool(ok)}


async def seen(page) -> list:
    return await page.evaluate(SEEN_JS)


def strip_mutations(rows: list) -> list:
    """只保留与越限/状态相关的变更，压缩噪声。"""
    keep = []
    for r in rows:
        blob = (r.get("cls") or "") + " " + (r.get("text") or "") + " " + (r.get("html") or "")
        if r.get("kind") == "attr":
            if r.get("attr") in ("class", "aria-checked", "data-checked", "disabled"):
                keep.append(r)
            continue
        if any(k in blob.lower() for k in (
            "suffix", "max", "length", "error", "count", "limit", "tip",
            "hint", "warn", "checked", "switch", "date", "time", "error",
        )):
            keep.append(r)
    return keep


async def dismiss_overlays(page) -> list:
    clicked = []
    for _ in range(4):
        handled = await page.evaluate(
            """() => {
              const vis = n => {
                const r = n.getBoundingClientRect();
                const s = getComputedStyle(n);
                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
                  && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.1;
              };
              const hits = Array.from(document.querySelectorAll(
                'button, .feature-guide__btn, [class*="guide"] button, [class*="guide__btn"]'
              )).filter(n => vis(n) && ['我知道了', 'I know', 'Got it'].includes((n.innerText || '').trim()));
              hits.forEach(n => n.click());
              return hits.map(n => (n.innerText || '').trim());
            }"""
        )
        if not handled:
            break
        clicked.extend(handled)
        await page.wait_for_timeout(700)
    return clicked


async def clear_body(page) -> None:
    await page.locator(BODY_EDITOR).first.click()
    await page.keyboard.press("ControlOrMeta+A")
    await page.keyboard.press("Backspace")
    await page.wait_for_timeout(250)


async def clear_title(page) -> None:
    await page.locator(TITLE_INPUT).first.fill("")
    await page.wait_for_timeout(200)


async def error_state(page) -> dict:
    return await page.evaluate(
        """() => {
          const q = s => Array.from(document.querySelectorAll(s));
          const vis = n => {
            const r = n.getBoundingClientRect();
            const s = getComputedStyle(n);
            return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
              && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.1;
          };
          const ed = document.querySelector('div.edit-container div.tiptap[role="textbox"]');
          const title = document.querySelector('input[placeholder*="填写标题"]');
          return {
            title_suffix: q('div.title-container div.max_suffix').length,
            max_suffix_any: q('div.max_suffix').length,
            length_error: q('div.edit-container div.length-error').length,
            length_error_any: q('div.length-error').length,
            title_container: q('div.title-container').length,
            suffix_nodes: q('.suffix').map(n => ({count: n.children.length,
              html: (n.innerHTML || '').slice(0, 500), text: (n.innerText || '').trim()})),
            edit_errorish: q('div.edit-container *').filter(n =>
              /length|error|count|limit|max|suffix/i.test((n.className || '').toString())
            ).map(n => ({tag: n.tagName.toLowerCase(), cls: (n.className || '').toString(),
                         text: (n.innerText || '').trim().slice(0, 160), visible: vis(n)})),
            bodyLen: ed ? (ed.innerText || '').length : null,
            titleValue: title ? title.value : null,
          };
        }"""
    )


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "ticket": 26,
        "started": datetime.now().isoformat(timespec="seconds"),
        "note": "全程未点击发布按钮，未提交任何内容",
    }

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
                await page.wait_for_timeout(1200)
                report["landed_url"] = page.url
                if "/login" in page.url or await page.locator(".login-box").count():
                    report["blocked"] = "login"
                    raise _LoginExpired(page.url)

                await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
                await page.locator("div.upload-content input[type=file]").first.set_input_files(
                    args.image
                )
                for _ in range(160):
                    st = await page.evaluate(
                        """() => ({
                          pr: document.querySelectorAll('.img-preview-area .pr').length,
                          up: document.querySelectorAll('.img-preview-area .pr .mask.uploading').length,
                          title: !!document.querySelector('input[placeholder*="填写标题"]'),
                        })"""
                    )
                    if st["title"] and st["pr"] >= 1 and st["up"] == 0:
                        break
                    await asyncio.sleep(0.3)
                report["overlays_dismissed"] = await dismiss_overlays(page)
                report["base"] = await snap(page, "base", raw_dir)

                # ---------------- Q1 标题越限 ----------------
                q1: dict = {}
                try:
                    await clear_title(page)
                    q1["baseline"] = await error_state(page)
                    q1["watch"] = await watch(page, "div.edit-container")

                    await page.locator(TITLE_INPUT).first.click()
                    await page.keyboard.insert_text("测" * 21)
                    q1["after_21cjk_immediate"] = await error_state(page)
                    await page.wait_for_timeout(400)
                    q1["after_21cjk_400ms"] = await error_state(page)
                    await page.wait_for_timeout(1200)
                    q1["after_21cjk_1600ms"] = await error_state(page)
                    q1["mutations_21cjk"] = strip_mutations(await seen(page))
                    await snap(page, "q1-title-overflow-cjk", raw_dir)

                    await clear_title(page)
                    await page.wait_for_timeout(500)
                    q1["after_clear"] = await error_state(page)

                    await page.locator(TITLE_INPUT).first.click()
                    await page.keyboard.insert_text("a" * 41)
                    await page.wait_for_timeout(700)
                    q1["after_41ascii"] = await error_state(page)
                    q1["mutations_41ascii"] = strip_mutations(await seen(page))
                    await snap(page, "q1-title-overflow-ascii", raw_dir)

                    await clear_title(page)
                except Exception as exc:
                    q1["error"] = f"{type(exc).__name__}: {exc}"
                report["q1_title"] = q1

                # ---------------- Q2 正文越限 ----------------
                q2: dict = {}
                try:
                    await clear_body(page)
                    q2["baseline"] = await error_state(page)
                    q2["watch"] = await watch(page, "div.edit-container")

                    chunk = "字" * 100
                    steps = []
                    body_len = 0
                    hit = None
                    await page.locator(BODY_EDITOR).first.click()
                    for i in range(20):
                        await page.keyboard.insert_text(chunk)
                        body_len += 100
                        await page.wait_for_timeout(350)
                        st = await error_state(page)
                        steps.append({
                            "inserted": body_len,
                            "bodyLen": st["bodyLen"],
                            "length_error": st["length_error"],
                            "length_error_any": st["length_error_any"],
                            "errorish": st["edit_errorish"],
                        })
                        if st["length_error"] or st["length_error_any"] or st["edit_errorish"]:
                            hit = st
                            break
                    q2["chunks"] = steps
                    q2["first_hit_at_inserted"] = body_len if hit else None
                    q2["first_hit_state"] = hit
                    q2["mutations_first_hit"] = strip_mutations(await seen(page))
                    await snap(page, "q2-body-overflow", raw_dir)

                    if hit:
                        # 回退，找「无错误的最大长度」
                        removed = 0
                        while removed < 20:
                            st = await error_state(page)
                            if not (st["length_error"] or st["length_error_any"]
                                    or st["edit_errorish"]):
                                break
                            await page.keyboard.press("Backspace")
                            removed += 1
                            await page.wait_for_timeout(180)
                        q2["removed_to_clear"] = removed
                        q2["boundary_clear"] = await error_state(page)
                        await page.keyboard.insert_text("字")
                        await page.wait_for_timeout(300)
                        q2["boundary_plus_one"] = await error_state(page)
                        q2["max_text_len"] = q2["boundary_clear"].get("bodyLen")
                    else:
                        q2["max_text_len"] = None

                    # 话题是否计入：清空后插 1 个话题，再从边界下方向上加字
                    topic: dict = {}
                    try:
                        await clear_body(page)
                        await page.locator(BODY_EDITOR).first.click()
                        await page.keyboard.insert_text("#旅行")
                        await page.wait_for_timeout(2200)
                        first = page.locator(
                            "#creator-editor-topic-container .item .name"
                        ).first
                        topic["suggestion_count"] = await page.locator(
                            "#creator-editor-topic-container .item .name"
                        ).count()
                        if await first.count():
                            await first.click()
                            await page.wait_for_timeout(1200)
                            topic["anchor"] = await page.evaluate(
                                """() => {
                                  const ed = document.querySelector(
                                    'div.edit-container div.tiptap[role="textbox"]');
                                  const as = Array.from(ed.querySelectorAll('a[data-topic]'));
                                  return as.map(a => ({text: a.innerText,
                                    textLen: (a.innerText || '').length,
                                    tcLen: (a.textContent || '').length,
                                    dataTopic: a.getAttribute('data-topic')}));
                                }"""
                            )
                            q2["topic"] = topic
                            await snap(page, "q2-topic-inserted", raw_dir)
                            max_len = q2.get("max_text_len")
                            if max_len:
                                start = max(1, max_len - 60)
                                remaining = start
                                await page.locator(BODY_EDITOR).first.click()
                                await page.keyboard.press("ControlOrMeta+End")
                                while remaining > 0:
                                    n = min(100, remaining)
                                    await page.keyboard.insert_text("字" * n)
                                    remaining -= n
                                await page.wait_for_timeout(300)
                                added = 0
                                topic_steps = []
                                while added < 120:
                                    st = await error_state(page)
                                    if st["length_error"] or st["length_error_any"] or st["edit_errorish"]:
                                        break
                                    await page.keyboard.insert_text("字")
                                    added += 1
                                    await page.wait_for_timeout(120)
                                    if added % 5 == 0:
                                        topic_steps.append({"added": added, "bodyLen": st["bodyLen"]})
                                topic["prefill"] = start
                                topic["added_before_error"] = added
                                topic["error_state"] = await error_state(page)
                                topic["steps"] = topic_steps
                                topic["max_text_len_with_topic"] = (
                                    (await error_state(page))["bodyLen"] - 0
                                )
                                await snap(page, "q2-topic-boundary", raw_dir)
                        else:
                            topic["error"] = "no suggestion item"
                    except Exception as exc:
                        topic["error"] = f"{type(exc).__name__}: {exc}"
                    q2["topic"] = topic
                except Exception as exc:
                    q2["error"] = f"{type(exc).__name__}: {exc}"
                report["q2_body"] = q2

                # ---------------- Q3 定时开关状态 ----------------
                q3: dict = {}
                try:
                    await clear_body(page)
                    await clear_title(page)
                    await dismiss_overlays(page)
                    schedule = page.locator(".post-time-wrapper .d-switch").first
                    await schedule.scroll_into_view_if_needed()
                    await page.wait_for_timeout(400)
                    q3["before"] = (await snap(page, "q3-schedule-before", raw_dir))["selectors"]
                    q3["watch"] = await watch(page, "div.edit-container")

                    await schedule.click()
                    await page.wait_for_timeout(700)
                    q3["after_click_700ms"] = (await snap(page, "q3-schedule-after-700", raw_dir))["selectors"]
                    await page.wait_for_timeout(1500)
                    q3["after_click_2200ms"] = (await snap(page, "q3-schedule-after-2200", raw_dir))["selectors"]
                    q3["mutations_on"] = strip_mutations(await seen(page))

                    await schedule.click()
                    await page.wait_for_timeout(900)
                    q3["after_second_click"] = (await snap(page, "q3-schedule-off", raw_dir))["selectors"]
                    q3["mutations_off"] = strip_mutations(await seen(page))

                    await schedule.click()
                    await page.wait_for_timeout(1200)
                    q3["after_third_click"] = (await snap(page, "q3-schedule-on-again", raw_dir))["selectors"]
                except Exception as exc:
                    q3["error"] = f"{type(exc).__name__}: {exc}"
                report["q3_schedule"] = q3

                # ---------------- Q4 定时时间输入 ----------------
                q4: dict = {}
                try:
                    inp = page.locator(".d-datepicker-input-filter input.d-text").first
                    if not await inp.count():
                        q4["error"] = "datepicker input missing"
                    else:
                        await inp.scroll_into_view_if_needed()
                        valid = (datetime.now() + timedelta(days=3)).replace(
                            hour=10, minute=0, second=0, microsecond=0
                        ).strftime("%Y-%m-%d %H:%M")
                        q4["valid_target"] = valid
                        q4["watch"] = await watch(page, "div.edit-container")

                        await inp.click()
                        await inp.fill(valid)
                        q4["value_immediately"] = await inp.input_value()
                        await page.wait_for_timeout(400)
                        q4["value_400ms"] = await inp.input_value()
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(400)
                        q4["value_after_tab"] = await inp.input_value()
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(400)
                        q4["value_after_enter"] = await inp.input_value()
                        await page.locator(".edit-container .tiptap").first.click()
                        await page.wait_for_timeout(400)
                        q4["value_after_blur"] = await inp.input_value()
                        await inp.click()
                        await page.wait_for_timeout(300)
                        q4["value_after_refocus"] = await inp.input_value()
                        q4["panel"] = await page.evaluate(
                            """() => ({
                              dp_filter: document.querySelectorAll('.d-datepicker-input-filter').length,
                              dp_container: document.querySelectorAll('.date-picker-container').length,
                              dp_panel_visible: Array.from(document.querySelectorAll(
                                '.d-datepicker-input-filter, .date-picker-container'))
                                .filter(n => n.getBoundingClientRect().height > 0).length,
                              bodyText: (document.querySelector('.post-time-wrapper') || {}).innerText,
                            })"""
                        )
                        q4["mutations_valid"] = strip_mutations(await seen(page))
                        await snap(page, "q4-date-valid", raw_dir)

                        # 非法（过去）日期
                        await inp.click()
                        await inp.fill("2026-01-01 10:00")
                        q4["invalid_value_immediately"] = await inp.input_value()
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(700)
                        q4["invalid_value_after_tab"] = await inp.input_value()
                        q4["invalid_nodes"] = await page.evaluate(
                            """() => {
                              const vis = n => {
                                const r = n.getBoundingClientRect();
                                const s = getComputedStyle(n);
                                return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
                                  && s.display !== 'none';
                              };
                              return Array.from(document.querySelectorAll(
                                '.d-datepicker-input-filter *, .date-picker-container *, [class*=error], [class*=tip]'
                              )).filter(n => vis(n) && /日期|时间|过去|无效|错误|不能/.test(n.innerText || ''))
                               .slice(0, 20).map(n => ({tag: n.tagName.toLowerCase(),
                                 cls: (n.className || '').toString().slice(0, 160),
                                 text: (n.innerText || '').trim().slice(0, 160)}));
                            }"""
                        )
                        q4["mutations_invalid"] = strip_mutations(await seen(page))
                        await snap(page, "q4-date-invalid", raw_dir)

                        # 回到合法值，留档
                        await inp.click()
                        await inp.fill(valid)
                        await page.keyboard.press("Tab")
                        await page.wait_for_timeout(500)
                        q4["restored_value"] = await inp.input_value()
                except Exception as exc:
                    q4["error"] = f"{type(exc).__name__}: {exc}"
                report["q4_date_input"] = q4

                # ---------------- Q5 原创开关 ----------------
                q5: dict = {}
                try:
                    await dismiss_overlays(page)
                    q5["before"] = (await snap(page, "q5-original-before", raw_dir))["selectors"]
                    sw = page.locator(".original-wrapper .d-switch").first
                    await sw.scroll_into_view_if_needed()
                    await sw.click()
                    await page.wait_for_timeout(900)
                    q5["modal_open"] = (await snap(page, "q5-original-modal", raw_dir))["selectors"]
                    q5["modal_text"] = await page.evaluate(
                        """() => {
                          const m = document.querySelector('.d-modal.creator-modal-style');
                          return m ? {text: (m.innerText || '').slice(0, 500),
                                      html: (m.innerHTML || '').slice(0, 1200),
                                      buttons: Array.from(m.querySelectorAll('button'))
                                        .map(b => (b.innerText || '').trim()).filter(Boolean),
                                      checkboxes: m.querySelectorAll('.d-checkbox, input[type=checkbox]').length}
                                   : null;
                        }"""
                    )
                    modal = page.locator(".d-modal.creator-modal-style").first
                    if await modal.count():
                        cb = modal.locator(".d-checkbox, input[type=checkbox]").first
                        if await cb.count():
                            try:
                                await cb.click()
                            except Exception as exc:
                                q5["checkbox_error"] = f"{type(exc).__name__}: {exc}"
                            await page.wait_for_timeout(300)
                        confirm = modal.get_by_text("声明原创", exact=True).last
                        if await confirm.count():
                            await confirm.click()
                            await page.wait_for_timeout(1200)
                        else:
                            q5["confirm_missing"] = True
                    q5["after_confirm"] = (await snap(page, "q5-original-after", raw_dir))["selectors"]
                    await page.wait_for_timeout(600)
                    q5["after_confirm_1800ms"] = await page.evaluate(
                        """() => {
                          const w = document.querySelector('.original-wrapper');
                          const s = w ? w.querySelector('.d-switch-simulator') : null;
                          const sw = w ? w.querySelector('.d-switch') : null;
                          return {
                            simulator_cls: s ? (s.className || '').toString() : null,
                            switch_cls: sw ? (sw.className || '').toString() : null,
                            switch_aria: sw ? sw.getAttribute('aria-checked') : null,
                            modal_count: document.querySelectorAll('.d-modal.creator-modal-style').length,
                          };
                        }"""
                    )
                    # 点别处，验证弹窗关闭后状态稳定
                    await page.locator(".edit-container .tiptap").first.click()
                    await page.wait_for_timeout(600)
                    q5["after_blur"] = await page.evaluate(
                        """() => {
                          const w = document.querySelector('.original-wrapper');
                          const s = w ? w.querySelector('.d-switch-simulator') : null;
                          return {simulator_cls: s ? (s.className || '').toString() : null,
                                  modal_count: document.querySelectorAll('.d-modal.creator-modal-style').length};
                        }"""
                    )
                    await snap(page, "q5-original-stable", raw_dir)
                except Exception as exc:
                    q5["error"] = f"{type(exc).__name__}: {exc}"
                report["q5_original"] = q5

                # ---------------- Q6 声明 / 封面的可观测回读 ----------------
                q6: dict = {}
                try:
                    await dismiss_overlays(page)
                    q6["declaration_before"] = (await snap(
                        page, "q6-declaration-before", raw_dir))["selectors"]
                    entry = page.get_by_text("添加内容类型声明", exact=True).first
                    if await entry.count():
                        await entry.scroll_into_view_if_needed()
                        await entry.click()
                        await page.wait_for_timeout(900)
                        q6["declaration_menu"] = (await snap(
                            page, "q6-declaration-menu", raw_dir))["selectors"]
                        option = page.locator(
                            ".declaration-drop-down .d-option, .declaration-drop-down label"
                        ).filter(has_text="虚构演绎").first
                        if await option.count():
                            await option.click()
                            await page.wait_for_timeout(900)
                            q6["declaration_after"] = (await snap(
                                page, "q6-declaration-after", raw_dir))["selectors"]
                            q6["declaration_after_state"] = await page.evaluate(
                                """() => {
                                  const sel = document.querySelector('.publish-container .d-select');
                                  return sel ? {text: (sel.innerText || '').trim().slice(0, 300),
                                                html: (sel.innerHTML || '').slice(0, 1200),
                                                cls: (sel.className || '').toString()} : null;
                                }"""
                            )
                        else:
                            q6["declaration_option_missing"] = True
                    else:
                        q6["declaration_entry_missing"] = True
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(400)

                    q6["cover_before"] = await page.evaluate(
                        """() => {
                          const stack = document.querySelector('.cover-edit-stack');
                          const entry = document.querySelector('.cover-edit-entry');
                          return {
                            stack_html: stack ? stack.outerHTML.slice(0, 1600) : null,
                            entry_text: entry ? (entry.innerText || '').trim() : null,
                            imgs: Array.from(document.querySelectorAll(
                              '.cover-edit-stack img, .cover img, .cover-detect img'))
                              .map(n => ({cls: (n.className || '').toString(), src: n.src})),
                          };
                        }"""
                    )
                    cover_entry = page.locator(".cover-edit-entry").first
                    if await cover_entry.count():
                        await cover_entry.scroll_into_view_if_needed()
                        await cover_entry.click()
                        await page.wait_for_timeout(1200)
                        q6["cover_modal"] = await page.evaluate(
                            """() => {
                              const m = document.querySelector('.d-modal.cover-modal');
                              return m ? {
                                text: (m.innerText || '').trim().slice(0, 600),
                                imgs: Array.from(m.querySelectorAll('img'))
                                  .map(n => ({cls: (n.className || '').toString(), src: n.src})),
                                buttons: Array.from(m.querySelectorAll('button'))
                                  .map(b => (b.innerText || '').trim()).filter(Boolean),
                                cls: (m.className || '').toString(),
                              } : null;
                            }"""
                        )
                        await snap(page, "q6-cover-modal", raw_dir)
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(600)
                        q6["cover_modal_after_esc"] = await page.locator(
                            ".d-modal.cover-modal"
                        ).count()
                        q6["cover_after"] = await page.evaluate(
                            """() => ({
                              imgs: Array.from(document.querySelectorAll(
                                '.cover-edit-stack img, .cover img, .cover-detect img'))
                                .map(n => ({cls: (n.className || '').toString(), src: n.src})),
                            })"""
                        )
                    else:
                        q6["cover_entry_missing"] = True
                except Exception as exc:
                    q6["error"] = f"{type(exc).__name__}: {exc}"
                report["q6_declaration_cover"] = q6

                report["publish_btn_final"] = await page.evaluate(
                    """() => {
                      const b = document.querySelector('xhs-publish-btn');
                      return b ? {text: (b.innerText || '').trim(),
                                  attrs: Object.fromEntries(Array.from(b.attributes)
                                    .map(a => [a.name, a.value]))} : null;
                    }"""
                )
                report["finished"] = datetime.now().isoformat(timespec="seconds")
            finally:
                await page.close()
                await context.close()
        finally:
            try:
                (raw_dir / "t26-report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception:
                pass
            await browser.close()

    (raw_dir / "t26-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except _LoginExpired as exc:
        print(f"login expired: {exc}", file=sys.stderr)
        raise SystemExit(2)
