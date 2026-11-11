"""Ticket 26 第二轮 — 正文越限 / 定时时间提交 / 原创 / 声明 / 封面（只读，不发布）。

第一轮（probe_readback_signals.py）踩到的两个问题在这里修正：
- MutationObserver 的旧回调会覆盖新记录（用 generation 号隔离）。
- 正文“越限”判据误把常驻计数器 `editor-length-wrapper / .max-length` 当成错误节点。

分四个独立 page（互不污染）：A 正文越限 + 话题计数、B 定时开关与时间提交、C 原创 + 声明、
D 视频页封面。D 需要 ffmpeg 生成的合法 mp4。

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_readback_signals_b.py \
        --account cookies/xiaohongshu_180.json --image .local/probe/test_carousel1.png \
        --video .local/probe/t26-demo.mp4
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
VIDEO_URL = _build_xhs_creator_url("/publish/publish?from=homepage&target=video")
TITLE_INPUT = 'input[placeholder*="填写标题"]'
BODY_EDITOR = 'div.edit-container div.tiptap[role="textbox"]'

WATCH_JS = """
(sel) => {
  window.__t26b = window.__t26b || {gen: 0, seen: []};
  if (window.__t26b.mo) { try { window.__t26b.mo.disconnect(); } catch (e) {} }
  window.__t26b.gen += 1;
  const gen = window.__t26b.gen;
  window.__t26b.seen = [];
  const root = document.querySelector(sel);
  if (!root) return false;
  const rec = [];
  const cls = n => (n.className || '').toString().slice(0, 160);
  const mo = new MutationObserver(ms => {
    if (window.__t26b.gen !== gen) return;   // 旧 observer 的回调直接丢弃
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
      if (rec.length > 300) rec.splice(0, rec.length - 300);
    }
    window.__t26b.seen = rec;
  });
  mo.observe(root, {childList: true, subtree: true, attributes: true,
                    attributeOldValue: true,
                    attributeFilter: ['class','aria-checked','data-checked','disabled']});
  window.__t26b.mo = mo;
  return true;
}
"""
SEEN_JS = "() => ((window.__t26b && window.__t26b.seen) || []).slice(-80)"

BODY_STATE_JS = """
() => {
  const ed = document.querySelector('div.edit-container div.tiptap[role="textbox"]');
  const wrap = document.querySelector('.editor-length-wrapper');
  const maxEl = document.querySelector('.editor-length-wrapper .max-length');
  const num = wrap ? parseInt((wrap.innerText || '').replace(/\\s/g, ''), 10) : null;
  const vis = n => {
    if (!n) return false;
    const r = n.getBoundingClientRect();
    const s = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const clsOn = sel => Array.from(document.querySelectorAll(sel))
    .map(n => ({cls: (n.className || '').toString(), text: (n.innerText || '').trim().slice(0, 120),
                visible: vis(n),
                color: (() => { try { return getComputedStyle(n).color; } catch (e) { return null; } })()}));
  const errish = Array.from(document.querySelectorAll(
    'div.edit-container *')).filter(n => {
      const c = (n.className || '').toString();
      return /length-error|editor-length-wrapper|max-length|error|exceed|over|danger|warn/i.test(c);
    }).map(n => ({tag: n.tagName.toLowerCase(), cls: (n.className || '').toString(),
                  text: (n.innerText || '').trim().slice(0, 120), visible: vis(n),
                  color: (() => { try { return getComputedStyle(n).color; } catch (e) { return null; } })()}));
  const btn = document.querySelector('xhs-publish-btn');
  return {
    counter: num,
    counter_text: wrap ? (wrap.innerText || '').trim() : null,
    wrapper_cls: wrap ? (wrap.className || '').toString() : null,
    max_cls: maxEl ? (maxEl.className || '').toString() : null,
    max_color: maxEl ? getComputedStyle(maxEl).color : null,
    length_error: document.querySelectorAll('div.length-error').length,
    length_error_scoped: document.querySelectorAll('div.edit-container div.length-error').length,
    max_suffix: document.querySelectorAll('div.max_suffix').length,
    edit_html: (document.querySelector('.bottom-wrapper') || {}).outerHTML
      ? (document.querySelector('.bottom-wrapper') || {}).outerHTML.slice(0, 2000) : null,
    errish: errish,
    publish_btn: btn ? {attrs: Object.fromEntries(Array.from(btn.attributes)
      .map(a => [a.name, a.value])), text: (btn.innerText || '').trim()} : null,
    body_innerText_len: ed ? (ed.innerText || '').length : null,
  };
}
"""


async def vis_js(page, sel: str):
    return await page.evaluate(
        """(sel) => Array.from(document.querySelectorAll(sel)).map(n => {
          const r = n.getBoundingClientRect();
          const s = getComputedStyle(n);
          return {tag: n.tagName.toLowerCase(), cls: (n.className || '').toString(),
                  text: (n.innerText || '').trim().slice(0, 160),
                  visible: r.width > 0 && r.height > 0 && s.visibility !== 'hidden'
                           && s.display !== 'none' && parseFloat(s.opacity || '1') > 0.1,
                  attrs: Object.fromEntries(Array.from(n.attributes)
                    .map(a => [a.name, a.value.slice(0, 200)]))};
        })""",
        sel,
    )


async def shot(page, raw_dir: Path, label: str) -> None:
    try:
        await page.screenshot(path=str(raw_dir / f"t26b-{label}.png"), full_page=True)
    except Exception as exc:
        print(f"[warn] screenshot {label}: {exc}", file=sys.stderr)


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
              )).filter(n => vis(n) && ['我知道了'].includes((n.innerText || '').trim()));
              hits.forEach(n => n.click());
              return hits.map(n => (n.innerText || '').trim());
            }"""
        )
        if not handled:
            break
        clicked.extend(handled)
        await page.wait_for_timeout(700)
    return clicked


async def open_image_editor(browser, account: str, image: str, raw_dir: Path) -> tuple:
    context = await browser.new_context(
        storage_state=account, user_agent=await _xhs_user_agent(browser), **XHS_CONTEXT_KWARGS
    )
    context = await set_init_script(context)
    page = await context.new_page()
    await page.goto(IMAGE_URL, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1000)
    if "/login" in page.url or await page.locator(".login-box").count():
        raise RuntimeError("login expired")
    await page.wait_for_selector('input[type="file"]', state="attached", timeout=40000)
    await page.locator("div.upload-content input[type=file]").first.set_input_files(image)
    for _ in range(160):
        st = await page.evaluate(
            """() => ({pr: document.querySelectorAll('.img-preview-area .pr').length,
                       up: document.querySelectorAll('.img-preview-area .pr .mask.uploading').length,
                       title: !!document.querySelector('input[placeholder*="填写标题"]')})"""
        )
        if st["title"] and st["pr"] >= 1 and st["up"] == 0:
            break
        await asyncio.sleep(0.3)
    await dismiss_overlays(page)
    await page.wait_for_timeout(400)
    return page, context


# --------------------------------------------------------------------------
# A. 正文越限 + 话题计数
# --------------------------------------------------------------------------
async def phase_a(browser, args, raw_dir: Path) -> dict:
    out: dict = {}
    page, context = await open_image_editor(browser, args.account, args.image, raw_dir)
    try:
        await page.locator(BODY_EDITOR).first.click()
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(300)
        out["baseline"] = await page.evaluate(BODY_STATE_JS)
        await page.evaluate(WATCH_JS, "div.edit-container")
        await page.locator(BODY_EDITOR).first.click()

        steps = []
        inserted = 0
        for _ in range(14):
            await page.keyboard.insert_text("字" * 80)
            inserted += 80
            await page.wait_for_timeout(300)
            st = await page.evaluate(BODY_STATE_JS)
            steps.append({"inserted": inserted, "counter": st["counter"],
                          "length_error": st["length_error"],
                          "length_error_scoped": st["length_error_scoped"],
                          "wrapper_cls": st["wrapper_cls"], "max_cls": st["max_cls"],
                          "max_color": st["max_color"],
                          "errish": [e for e in st["errish"] if "editor-length-wrapper" not in e["cls"]],
                          "publish_btn": st["publish_btn"]})
            if st["length_error"] or st["length_error_scoped"] or st["counter"] and st["counter"] > 1000:
                break
        out["steps"] = steps
        out["mutations"] = await page.evaluate(SEEN_JS)
        out["over_state"] = await page.evaluate(BODY_STATE_JS)
        await shot(page, raw_dir, "a-body-over")

        # 回到 1000，验证 1000/1001 边界
        while True:
            st = await page.evaluate(BODY_STATE_JS)
            if st["counter"] is None or st["counter"] <= 1000:
                break
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(80)
        out["at_1000"] = await page.evaluate(BODY_STATE_JS)
        await page.keyboard.insert_text("字")
        await page.wait_for_timeout(500)
        out["at_1001"] = await page.evaluate(BODY_STATE_JS)
        await shot(page, raw_dir, "a-body-1001")

        # 话题是否计入：清空 → 插 1 个话题 → 读计数器
        await page.locator(BODY_EDITOR).first.click()
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.press("Backspace")
        await page.wait_for_timeout(300)
        await page.keyboard.insert_text("#旅行")
        await page.wait_for_timeout(2200)
        out["topic_suggestions"] = await page.locator(
            "#creator-editor-topic-container .item .name"
        ).count()
        first = page.locator("#creator-editor-topic-container .item .name").first
        if await first.count():
            await first.click()
            await page.wait_for_timeout(1200)
            out["topic_anchor_text"] = await page.evaluate(
                """() => {
                  const ed = document.querySelector(
                    'div.edit-container div.tiptap[role="textbox"]');
                  const a = ed ? ed.querySelector('a[data-topic]') : null;
                  return a ? {text: a.innerText, len: (a.innerText || '').length} : null;
                }"""
            )
            out["topic_state"] = await page.evaluate(BODY_STATE_JS)
            await shot(page, raw_dir, "a-topic")

            # 用计数器的“跳变”反推话题被计入多少：插 1 个中文字
            before = out["topic_state"]["counter"]
            await page.keyboard.insert_text("字")
            await page.wait_for_timeout(400)
            after = (await page.evaluate(BODY_STATE_JS))["counter"]
            out["topic_counter_delta_one_char"] = (
                None if before is None or after is None else after - before
            )
            out["topic_state_after_one_char"] = await page.evaluate(BODY_STATE_JS)
            await shot(page, raw_dir, "a-topic-plus-one")
        else:
            out["topic_error"] = "no suggestion item"
    finally:
        await page.close()
        await context.close()
    return out


# --------------------------------------------------------------------------
# B. 定时开关 + 时间输入提交
# --------------------------------------------------------------------------
async def phase_b(browser, args, raw_dir: Path) -> dict:
    out: dict = {}
    page, context = await open_image_editor(browser, args.account, args.image, raw_dir)
    try:
        wrapper = ".post-time-wrapper"
        out["before_html"] = await page.evaluate(
            """() => { const w = document.querySelector('.post-time-wrapper');
                       return w ? w.innerHTML.slice(0, 4000) : null; }"""
        )
        out["before_text"] = await page.evaluate(
            "() => (document.querySelector('.post-time-wrapper') || {}).innerText"
        )
        out["before_switch"] = await vis_js(page, ".post-time-wrapper .d-switch")
        out["before_date_inputs"] = await vis_js(page, ".post-time-wrapper input")

        await page.evaluate(
            """() => { const s = document.querySelector('.post-time-wrapper .d-switch');
                       if (s) s.click(); }"""
        )
        await page.wait_for_timeout(900)
        out["on_switch"] = await vis_js(page, ".post-time-wrapper .d-switch")
        out["on_simulator"] = await vis_js(page, ".post-time-wrapper .d-switch-simulator")
        out["on_date_inputs"] = await vis_js(page, ".post-time-wrapper input")
        out["on_html"] = await page.evaluate(
            """() => { const w = document.querySelector('.post-time-wrapper');
                       return w ? w.innerHTML.slice(0, 4000) : null; }"""
        )
        await shot(page, raw_dir, "b-schedule-on")

        # 用 JS 写值 + 触发 input/change/blur，逐步观察输入框是否存活 / 值是否保留
        valid = (datetime.now() + timedelta(days=3)).replace(
            hour=10, minute=0, second=0, microsecond=0
        ).strftime("%Y-%m-%d %H:%M")
        out["valid_target"] = valid

        async def set_value(js_value: str, label: str) -> dict:
            res: dict = {"label": label, "target": js_value}
            res["set"] = await page.evaluate(
                """(v) => {
                  const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                  if (!inp) return {ok: false, reason: 'input missing'};
                  inp.focus();
                  inp.value = v;
                  inp.dispatchEvent(new Event('input', {bubbles: true}));
                  inp.dispatchEvent(new Event('change', {bubbles: true}));
                  return {ok: true, value: inp.value};
                }""",
                js_value,
            )
            res["after_0ms"] = await page.evaluate(
                """() => {
                  const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                  const w = document.querySelector('.post-time-wrapper');
                  return {input_count: document.querySelectorAll(
                            '.d-datepicker-input-filter input.d-text').length,
                          input_value: inp ? inp.value : null,
                          wrapper_text: w ? (w.innerText || '').trim().slice(0, 300) : null};
                }"""
            )
            await page.wait_for_timeout(500)
            res["after_500ms"] = await page.evaluate(
                """() => {
                  const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                  const w = document.querySelector('.post-time-wrapper');
                  return {input_count: document.querySelectorAll(
                            '.d-datepicker-input-filter input.d-text').length,
                          input_value: inp ? inp.value : null,
                          wrapper_text: w ? (w.innerText || '').trim().slice(0, 300) : null};
                }"""
            )
            res["blur"] = await page.evaluate(
                """() => {
                  const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                  if (!inp) return {ok: false};
                  inp.blur();
                  return {ok: true};
                }"""
            )
            await page.wait_for_timeout(700)
            res["after_blur"] = await page.evaluate(
                """() => {
                  const inp = document.querySelector('.d-datepicker-input-filter input.d-text');
                  const w = document.querySelector('.post-time-wrapper');
                  return {input_count: document.querySelectorAll(
                            '.d-datepicker-input-filter input.d-text').length,
                          input_value: inp ? inp.value : null,
                          wrapper_text: w ? (w.innerText || '').trim().slice(0, 300) : null,
                          wrapper_html: w ? w.innerHTML.slice(0, 2500) : null};
                }"""
            )
            await shot(page, raw_dir, f"b-{label}")
            return res

        out["valid"] = await set_value(valid, "date-valid")
        out["after_valid_errors"] = await vis_js(
            page, ".post-time-wrapper [class*=error], .post-time-wrapper [class*=tip]"
        )

        out["invalid_past"] = await set_value("2026-01-01 10:00", "date-past")
        out["after_past_errors"] = await vis_js(
            page, ".post-time-wrapper [class*=error], .post-time-wrapper [class*=tip], .d-popover"
        )
        out["invalid_garbage"] = await set_value("abc", "date-garbage")
        out["after_garbage_errors"] = await vis_js(
            page, ".post-time-wrapper [class*=error], .post-time-wrapper [class*=tip]"
        )

        # 恢复合法值并留档面板
        out["restore"] = await set_value(valid, "date-restore")

        # 开关关掉，确认可逆（状态可读）
        await page.evaluate(
            """() => { const s = document.querySelector('.post-time-wrapper .d-switch');
                       if (s) s.click(); }"""
        )
        await page.wait_for_timeout(700)
        out["off_simulator"] = await vis_js(page, ".post-time-wrapper .d-switch-simulator")
        out["off_date_inputs"] = await vis_js(page, ".post-time-wrapper input")
        out["off_text"] = await page.evaluate(
            "() => (document.querySelector('.post-time-wrapper') || {}).innerText"
        )
        await shot(page, raw_dir, "b-schedule-off")
    finally:
        await page.close()
        await context.close()
    return out


# --------------------------------------------------------------------------
# C. 原创开关 + 内容类型声明
# --------------------------------------------------------------------------
async def phase_c(browser, args, raw_dir: Path) -> dict:
    out: dict = {}
    page, context = await open_image_editor(browser, args.account, args.image, raw_dir)
    try:
        out["original_before"] = await page.evaluate(
            """() => {
              const w = document.querySelector('.original-wrapper');
              const s = w ? w.querySelector('.d-switch-simulator') : null;
              const sw = w ? w.querySelector('.d-switch') : null;
              return {exists: !!w, simulator_cls: s ? s.className.toString() : null,
                      switch_cls: sw ? sw.className.toString() : null,
                      switch_aria: sw ? sw.getAttribute('aria-checked') : null,
                      text: w ? (w.innerText || '').trim() : null};
            }"""
        )
        await page.evaluate(
            """() => { const s = document.querySelector('.original-wrapper .d-switch');
                       if (s) s.click(); }"""
        )
        await page.wait_for_timeout(900)
        out["modal"] = await page.evaluate(
            """() => {
              const m = document.querySelector('.d-modal.creator-modal-style');
              return m ? {text: (m.innerText || '').trim().slice(0, 600),
                          buttons: Array.from(m.querySelectorAll('button'))
                            .map(b => (b.innerText || '').trim()).filter(Boolean),
                          checkboxes: m.querySelectorAll(
                            '.d-checkbox, input[type=checkbox]').length} : null;
            }"""
        )
        await shot(page, raw_dir, "c-original-modal")
        await page.evaluate(
            """() => {
              const m = document.querySelector('.d-modal.creator-modal-style');
              if (!m) return;
              const cb = m.querySelector('.d-checkbox, input[type=checkbox]');
              if (cb) cb.click();
            }"""
        )
        await page.wait_for_timeout(300)
        clicked = await page.evaluate(
            """() => {
              const m = document.querySelector('.d-modal.creator-modal-style');
              if (!m) return false;
              const btns = Array.from(m.querySelectorAll('button'));
              const b = btns.find(x => (x.innerText || '').trim() === '声明原创');
              if (b) { b.click(); return true; }
              return false;
            }"""
        )
        out["confirm_clicked"] = clicked
        await page.wait_for_timeout(900)
        out["original_after_900ms"] = await page.evaluate(
            """() => {
              const w = document.querySelector('.original-wrapper');
              const s = w ? w.querySelector('.d-switch-simulator') : null;
              const sw = w ? w.querySelector('.d-switch') : null;
              return {simulator_cls: s ? s.className.toString() : null,
                      switch_cls: sw ? sw.className.toString() : null,
                      switch_aria: sw ? sw.getAttribute('aria-checked') : null,
                      modal_count: document.querySelectorAll('.d-modal.creator-modal-style').length,
                      text: w ? (w.innerText || '').trim() : null};
            }"""
        )
        await page.wait_for_timeout(700)
        out["original_after_1600ms"] = await page.evaluate(
            """() => {
              const w = document.querySelector('.original-wrapper');
              const s = w ? w.querySelector('.d-switch-simulator') : null;
              return {simulator_cls: s ? s.className.toString() : null,
                      modal_count: document.querySelectorAll('.d-modal.creator-modal-style').length};
            }"""
        )
        await page.locator(BODY_EDITOR).first.click()
        await page.wait_for_timeout(500)
        out["original_after_blur"] = await page.evaluate(
            """() => {
              const w = document.querySelector('.original-wrapper');
              const s = w ? w.querySelector('.d-switch-simulator') : null;
              return {simulator_cls: s ? s.className.toString() : null,
                      modal_count: document.querySelectorAll('.d-modal.creator-modal-style').length};
            }"""
        )
        await shot(page, raw_dir, "c-original-on")

        # 声明
        out["declaration_before"] = await page.evaluate(
            """() => {
              const sels = Array.from(document.querySelectorAll('.publish-container .d-select'));
              return sels.map(n => ({text: (n.innerText || '').trim().slice(0, 120),
                                     cls: n.className.toString(),
                                     html: n.innerHTML.slice(0, 700)}));
            }"""
        )
        entry = page.get_by_text("添加内容类型声明", exact=True).first
        out["entry_count"] = await entry.count()
        if await entry.count():
            await entry.scroll_into_view_if_needed()
            await entry.click()
            await page.wait_for_timeout(800)
            out["menu"] = await page.evaluate(
                """() => Array.from(document.querySelectorAll(
                  '.declaration-drop-down .d-option, .declaration-drop-down label, .d-popover'))
                  .map(n => ({cls: n.className.toString(), text: (n.innerText || '').trim().slice(0, 160),
                              visible: n.getBoundingClientRect().height > 0})).slice(0, 12)"""
            )
            await shot(page, raw_dir, "c-declaration-menu")
            option = page.locator(
                ".declaration-drop-down .d-option, .declaration-drop-down label"
            ).filter(has_text="虚构演绎").first
            out["option_count"] = await option.count()
            if await option.count():
                await option.click()
                await page.wait_for_timeout(900)
                out["declaration_after"] = await page.evaluate(
                    """() => {
                      const sels = Array.from(document.querySelectorAll('.publish-container .d-select'));
                      return sels.map(n => ({text: (n.innerText || '').trim().slice(0, 120),
                                             cls: n.className.toString(),
                                             html: n.innerHTML.slice(0, 900)}));
                    }"""
                )
                await shot(page, raw_dir, "c-declaration-after")
    finally:
        await page.close()
        await context.close()
    return out


# --------------------------------------------------------------------------
# D. 视频页封面（只读留档）
# --------------------------------------------------------------------------
async def phase_d(browser, args, raw_dir: Path) -> dict:
    out: dict = {}
    context = await browser.new_context(
        storage_state=args.account, user_agent=await _xhs_user_agent(browser), **XHS_CONTEXT_KWARGS
    )
    context = await set_init_script(context)
    page = await context.new_page()
    try:
        await page.goto(VIDEO_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(1000)
        if "/login" in page.url or await page.locator(".login-box").count():
            raise RuntimeError("login expired")
        await page.wait_for_selector("input.upload-input", state="attached", timeout=40000)
        await page.locator("input.upload-input").first.set_input_files(args.video)
        for _ in range(120):
            st = await page.evaluate(
                """() => {
                  const b = document.querySelector('xhs-publish-btn');
                  return {disabled: b ? b.getAttribute('submit-disabled') : null,
                          title: !!document.querySelector('input[placeholder*="填写标题"]'),
                          fail: !!document.querySelector('div.fail')};
                }"""
            )
            if st["title"]:
                break
            if st["fail"]:
                out["upload_failed"] = True
                break
            await asyncio.sleep(1)
        await dismiss_overlays(page)
        await page.wait_for_timeout(500)
        out["cover_before"] = await page.evaluate(
            """() => {
              const stack = document.querySelector('.cover-edit-stack');
              const entry = document.querySelector('.cover-edit-entry');
              return {
                stack_html: stack ? stack.outerHTML.slice(0, 1800) : null,
                entry_text: entry ? (entry.innerText || '').trim() : null,
                imgs: Array.from(document.querySelectorAll(
                  '.cover-edit-stack img, .cover img, .cover-detect img, .cover-plugin-preview img'))
                  .map(n => ({cls: (n.className || '').toString(), src: n.src,
                              visible: n.getBoundingClientRect().height > 0})),
              };
            }"""
        )
        await shot(page, raw_dir, "d-cover-before")
        entry = page.locator(".cover-edit-entry").first
        out["entry_count"] = await entry.count()
        if await entry.count():
            await entry.scroll_into_view_if_needed()
            await entry.click()
            await page.wait_for_timeout(1200)
            out["cover_modal"] = await page.evaluate(
                """() => {
                  const m = document.querySelector(
                    '.d-modal.cover-modal, .d-modal.main-cover-editor-modal, .d-modal.creator-modal-style');
                  return m ? {cls: m.className.toString(),
                              text: (m.innerText || '').trim().slice(0, 700),
                              imgs: Array.from(m.querySelectorAll('img'))
                                .map(n => ({cls: (n.className || '').toString(), src: n.src,
                                            visible: n.getBoundingClientRect().height > 0})),
                              buttons: Array.from(m.querySelectorAll('button'))
                                .map(b => (b.innerText || '').trim()).filter(Boolean)} : null;
                }"""
            )
            await shot(page, raw_dir, "d-cover-modal")
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(600)
            out["cover_modal_after_esc"] = await page.locator(
                ".d-modal.cover-modal, .d-modal.creator-modal-style"
            ).count()
    finally:
        await page.close()
        await context.close()
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    args = ap.parse_args()
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {"ticket": 26, "round": "b",
                    "started": datetime.now().isoformat(timespec="seconds"),
                    "note": "全程未点击发布按钮，未提交任何内容"}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, **XHS_LAUNCH_KWARGS)
        try:
            for name, fn in (
                ("a_body", phase_a), ("b_schedule", phase_b),
                ("c_original_declaration", phase_c), ("d_cover", phase_d),
            ):
                try:
                    report[name] = await fn(browser, args, raw_dir)
                except Exception as exc:
                    report[name] = {"error": f"{type(exc).__name__}: {exc}"}
                    print(f"[warn] {name}: {exc}", file=sys.stderr)
        finally:
            await browser.close()
    report["finished"] = datetime.now().isoformat(timespec="seconds")
    (raw_dir / "t26b-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: ("error" if isinstance(v, dict) and v.get("error") else "ok")
                      for k, v in report.items() if k.startswith(("a_", "b_", "c_", "d_"))},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
