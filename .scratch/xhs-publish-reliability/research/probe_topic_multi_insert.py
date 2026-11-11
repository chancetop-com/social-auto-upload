"""Ticket 23 — 连续多话题插入取证（只读，不发布）。

在图文编辑器里连续插入 3 个话题，记录：
1. 第 2/3 个话题的联想容器是否仍出现；若不需要额外动作，记录「无动作即可」。
2. `a[data-topic]` 的祖先链 / 是否始终在 `div.tiptap[role=textbox]` 内。
3. 点击候先后下拉容器多久消失（100ms 采样，最多 2.5s）。
4. `.name` 是否带前导 `#` + 每个请求词的候选排序前 10 项。

用法：
    .venv/bin/python .scratch/xhs-publish-reliability/research/probe_topic_multi_insert.py \
        --account cookies/xiaohongshu_180.json --image .local/probe/test_ok.png

不做：填标题、点发布、改任何发布选项。
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

TOPIC_CONTAINER = "#creator-editor-topic-container"

VISIBLE_JS = """
(sel) => {
  const nodes = Array.from(document.querySelectorAll(sel));
  const visible = nodes.filter(n => {
    const r = n.getBoundingClientRect();
    const st = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  });
  return {count: nodes.length, visible: visible.length};
}
"""

DROPDOWN_JS = """
() => {
  const containers = Array.from(document.querySelectorAll('#creator-editor-topic-container'));
  const vis = containers.filter(n => {
    const r = n.getBoundingClientRect();
    const st = getComputedStyle(n);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  });
  const items = containers.length
    ? Array.from(containers[0].querySelectorAll('.item'))
    : [];
  return {
    container_count: containers.length,
    container_visible: vis.length,
    item_count: items.length,
    container_html: vis.length ? (vis[0].outerHTML || '').slice(0, 2000) : null,
    items_top10: items.slice(0, 10).map(it => ({
      name: ((it.querySelector('.name') || {}).textContent || '').trim(),
      text: (it.innerText || '').trim().slice(0, 80),
      visible: (() => {
        const r = it.getBoundingClientRect();
        const st = getComputedStyle(it);
        return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
      })(),
    })),
  };
}
"""

SNAPSHOT_JS = """
() => {
  const anchors = Array.from(document.querySelectorAll('a[data-topic]'));
  const editors = Array.from(document.querySelectorAll('div.tiptap[role="textbox"]'));
  const editor = editors[0] || document.querySelector('div.tiptap');
  const chain = n => {
    const out = [];
    let el = n;
    for (let i = 0; i < 8 && el; i += 1) {
      out.push({
        tag: el.tagName ? el.tagName.toLowerCase() : null,
        id: el.id || null,
        cls: typeof el.className === 'string' ? el.className.slice(0, 160) : null,
        role: el.getAttribute ? el.getAttribute('role') : null,
        contenteditable: el.getAttribute ? el.getAttribute('contenteditable') : null,
      });
      el = el.parentElement;
    }
    return out;
  };
  const describe = a => {
    let parsed = null;
    try { parsed = JSON.parse(a.getAttribute('data-topic') || 'null'); } catch (e) { parsed = null; }
    return {
      text: (a.textContent || '').trim(),
      data_topic_name: parsed && typeof parsed === 'object' ? parsed.name : null,
      data_topic_raw: (a.getAttribute('data-topic') || '').slice(0, 600),
      in_tiptap_textbox: !!document.querySelector('div.tiptap[role="textbox"]')
        && document.querySelector('div.tiptap[role="textbox"]').contains(a),
      in_tiptap: !!document.querySelector('div.tiptap') && document.querySelector('div.tiptap').contains(a),
      inside_editor_root: editor ? editor.contains(a) : null,
      chain: chain(a),
    };
  };
  const containers = Array.from(document.querySelectorAll('#creator-editor-topic-container'));
  return {
    url: location.href,
    editor_count: editors.length,
    editor_found: !!editor,
    editor_role: editor ? editor.getAttribute('role') : null,
    editor_class: editor && typeof editor.className === 'string' ? editor.className : null,
    editor_text: editor ? (editor.innerText || '').slice(0, 500) : null,
    editor_html_len: editor ? (editor.innerHTML || '').length : null,
    anchor_count: anchors.length,
    anchors: anchors.map(describe),
    login_box_count: document.querySelectorAll('div[class*="login-box"]').length,
    dropdown: {
      container_count: containers.length,
      container_visible: containers.filter(n => {
        const r = n.getBoundingClientRect();
        const st = getComputedStyle(n);
        return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
      }).length,
    },
  };
}
"""


async def snapshot(page) -> dict:
    return await page.evaluate(SNAPSHOT_JS)


async def dropdown_state(page) -> dict:
    return await page.evaluate(DROPDOWN_JS)


def normalize(name: str) -> str:
    return " ".join(name.lstrip("#").strip().split()).casefold()


async def wait_for_dropdown(page, timeout_ms: int = 5000) -> list[dict]:
    start = time.monotonic()
    trace: list[dict] = []
    while True:
        state = await dropdown_state(page)
        elapsed = int((time.monotonic() - start) * 1000)
        trace.append(
            {
                "t_ms": elapsed,
                "container_visible": state["container_visible"],
                "item_count": state["item_count"],
            }
        )
        if state["container_visible"] and state["item_count"]:
            return trace
        if elapsed >= timeout_ms:
            return trace
        await page.wait_for_timeout(100)


async def wait_for_close(page, timeout_ms: int = 2500) -> list[dict]:
    start = time.monotonic()
    trace: list[dict] = []
    while True:
        state = await dropdown_state(page)
        elapsed = int((time.monotonic() - start) * 1000)
        trace.append(
            {
                "t_ms": elapsed,
                "container_visible": state["container_visible"],
                "container_count": state["container_count"],
                "item_count": state["item_count"],
            }
        )
        if state["container_visible"] == 0 or elapsed >= timeout_ms:
            return trace
        await page.wait_for_timeout(100)


async def first_dropdown_close_ms(trace: list[dict]) -> int | None:
    for sample in trace:
        if sample["container_visible"] == 0:
            return sample["t_ms"]
    return None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--topics", default="旅行,美食,穿搭")
    ap.add_argument("--raw-dir", default=str(Path(__file__).with_name("raw")))
    ap.add_argument("--settle-ms", type=int, default=12000)
    args = ap.parse_args()

    topics = [t.strip().lstrip("#") for t in args.topics.split(",") if t.strip()]
    raw_dir = Path(args.raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)

    report: dict = {
        "account": Path(args.account).name,
        "topics": topics,
        "steps": [],
        "error": None,
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
                await page.goto(
                    _build_xhs_creator_url("/publish/publish?from=homepage&target=image"),
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                await page.wait_for_selector('input[type="file"]', state="attached", timeout=30000)
                await page.locator('input[type="file"]').first.set_input_files(args.image)
                await page.wait_for_timeout(args.settle_ms)

                report["landing_url"] = page.url
                report["login_box"] = await page.evaluate(
                    """
                    (sel) => {
                      const n = document.querySelector(sel);
                      if (!n) return {count: 0, visible: false};
                      const r = n.getBoundingClientRect();
                      const st = getComputedStyle(n);
                      return {count: 1, visible: r.width > 0 && r.height > 0
                        && st.visibility !== 'hidden' && st.display !== 'none'};
                    }
                    """,
                    XHS_LOGIN_BOX_SELECTOR,
                )
                report["before"] = await snapshot(page)

                if "login" in page.url or report["login_box"]["visible"]:
                    report["error"] = "login-required"
                    raise RuntimeError("login required — cookie 失效，未进入编辑器")

                body = page.locator("div.tiptap").first
                await body.click()

                for index, topic in enumerate(topics, start=1):
                    step: dict = {
                        "index": index,
                        "topic": topic,
                        "query": "#" + topic,
                        "before": await snapshot(page),
                    }

                    before_anchor_count = step["before"]["anchor_count"]
                    t0 = time.monotonic()
                    await page.keyboard.type("#" + topic, delay=30)
                    step["typed_ms"] = int((time.monotonic() - t0) * 1000)

                    step["dropdown_wait_trace"] = await wait_for_dropdown(page)
                    state = await dropdown_state(page)
                    step["candidates"] = state
                    step["dropdown_appeared_without_action"] = state["container_visible"] > 0

                    clicked = None
                    if state["container_visible"] and state["item_count"]:
                        names = [item["name"] for item in state["items_top10"]]
                        target_idx = None
                        for i, name in enumerate(names):
                            if normalize(name) == normalize(topic):
                                target_idx = i
                                break
                        if target_idx is None:
                            target_idx = 0
                        item = page.locator(f"{TOPIC_CONTAINER} .item").nth(target_idx)
                        await item.click(timeout=3000)
                        clicked = {
                            "index": target_idx,
                            "name": names[target_idx] if target_idx < len(names) else None,
                            "exact_match": normalize(names[target_idx] or "") == normalize(topic)
                            if target_idx < len(names)
                            else False,
                        }
                    step["clicked"] = clicked

                    if clicked is not None:
                        step["dropdown_close_trace"] = await wait_for_close(page)
                        step["dropdown_close_ms"] = await first_dropdown_close_ms(
                            step["dropdown_close_trace"]
                        )
                    else:
                        step["dropdown_close_trace"] = []
                        step["dropdown_close_ms"] = None

                    await page.wait_for_timeout(400)
                    after = await snapshot(page)
                    step["after"] = after

                    new_count = after["anchor_count"] - before_anchor_count
                    step["anchor_delta"] = new_count
                    step["new_anchor_names"] = [
                        a["data_topic_name"] for a in after["anchors"]
                    ]
                    step["all_anchors_in_tiptap_textbox"] = all(
                        a["in_tiptap_textbox"] for a in after["anchors"]
                    ) if after["anchors"] else None
                    report["steps"].append(step)

                    if clicked is None:
                        # 不用 Scroll/Arrow 兜底：本票只取证“无动作是否可行”。
                        report["error"] = f"topic {index} ({topic}): dropdown did not appear"
                        break

                    if new_count <= 0:
                        report["error"] = f"topic {index} ({topic}): no anchor added"
                        break
            except Exception as exc:
                if report["error"] is None:
                    report["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                await page.close()
                await context.close()
        finally:
            await browser.close()

    report["measured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    out_path = raw_dir / "23-topic-multi-insert.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] raw -> {out_path}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
