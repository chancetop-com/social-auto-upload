"""Instagram 协作者测试共享夹具（非测试模块，pytest 不收集）。

受控 DOM 页面、fake 控制件与超时收紧补丁同时供零浏览器、DOM 与 CLI 用例
复用；这里只放测试数据/替身，不含断言。
"""
from __future__ import annotations

import json
import time
from unittest.mock import patch

from uploader.meta_uploader.insgraph_uploader.controls import (
    collaborators as collaborators_control_module,
)
from uploader.meta_uploader.insgraph_uploader.options import PRESENT


class FakeCollaboratorControl:
    """最小协作者控制件替身：预置 read 序列，可选在 set 时抛错。"""

    def __init__(self, read_values, *, presence=PRESENT, failure=None):
        self._values = list(read_values)
        self.presence = presence
        self.failure = failure
        self.interactions = []

    async def resolve(self):
        self.interactions.append("resolve")
        return self.presence

    async def read(self):
        self.interactions.append("read")
        if not self._values:
            return None
        return self._values.pop(0) if len(self._values) > 1 else self._values[0]

    async def set(self, requested):
        self.interactions.append(("set", list(requested)))
        if self.failure is not None:
            raise self.failure


class ExplodingControl:
    async def resolve(self):
        raise AssertionError("未请求的选项不应被 resolve")

    async def read(self):
        raise AssertionError("未请求的选项不应被 read")

    async def set(self, requested):
        raise AssertionError("未请求的选项不应被 set")


_COLLABORATOR_SCRIPT = """<script>
  const candidates = __CANDIDATES__;
  const selected = __PRESELECT__;
  const rowClick = __ROW_CLICK__;
  const doneCollapses = __DONE_COLLAPSES__;
  const panelInitiallyOpen = __PANEL_INITIALLY_OPEN__;
  const renderChipNodes = __RENDER_CHIPS__;
  const valueAfterFive = __VALUE_AFTER_FIVE__;
  const checkboxDelayMs = __CHECKBOX_DELAY_MS__;
  const confirmDelayMs = __CONFIRM_DELAY_MS__;
  const panelOpens = __PANEL_OPENS__;
  const hideStampedAfter = __HIDE_STAMPED_AFTER__;
  const pageLimit = __PAGE_LIMIT__;
  const limitNotice = __LIMIT_NOTICE__;
  const siblingMode = __SIBLING_MODE__;
  let hideStamps = false;
  const entry = document.getElementById('collab-entry');
  const panel = document.getElementById('collab-panel');
  const results = document.getElementById('collab-results');
  const chips = document.getElementById('chips');
  const done = document.getElementById('collab-done');
  function checkedNames() {
    const names = [];
    for (const candidate of candidates) {
      if (selected.includes(candidate.username) &&
          !names.includes(candidate.username)) {
        names.push(candidate.username);
      }
    }
    return names;
  }
  function recordSelection() {
    document.body.dataset.selected = JSON.stringify(selected);
  }
  function openPanel() {
    if (!panel || !panelOpens) return;
    panel.hidden = false;
    if (siblingMode) {
      for (const decoy of document.querySelectorAll('[data-decoy]')) {
        decoy.hidden = false;
      }
    }
    renderResults();
  }
  function renderChips() {
    if (!chips) return;
    chips.innerHTML = '';
    if (!renderChipNodes) return;
    for (const username of selected) {
      const outer = document.createElement('span');
      const name = document.createElement('span');
      name.textContent = username;
      const closeWrap = document.createElement('div');
      const close = document.createElement('div');
      close.setAttribute('role', 'button');
      close.innerHTML = '<svg aria-label="Close" width="10" height="10"></svg>';
      closeWrap.appendChild(close);
      outer.appendChild(name);
      outer.appendChild(closeWrap);
      chips.appendChild(outer);
    }
  }
  function setBoxState(box, username) {
    const checked = selected.includes(username);
    box.checked = checked;
    box.setAttribute('aria-checked', String(checked));
    if (siblingMode) {
      box.setAttribute(
        'aria-label',
        checked ? 'Checkmark filled icon' : 'Checkmark outline icon');
    }
  }
  function buildCandidateRow(candidate) {
    if (siblingMode) {
      const row = document.createElement('button');
      row.className = '_acmy _acmz';
      row.dataset.username = candidate.username;
      row.style.cssText =
        'display:flex;height:48px;width:560px;align-items:center;gap:8px';
      const avatar = document.createElement('span');
      avatar.style.cssText =
        'display:inline-block;height:44px;width:44px;background:#ddd';
      avatar.setAttribute('role', 'link');
      avatar.setAttribute('aria-label', candidate.username + ' profile');
      const name = document.createElement('div');
      name.className = '_acmu';
      name.textContent = candidate.username;
      const badge = document.createElement('div');
      badge.className = '_acmv _9ys8';
      name.appendChild(badge);
      const display = document.createElement('span');
      display.className = '_acmw';
      display.textContent = candidate.display;
      const label = document.createElement('label');
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.name = 'checkbox';
      setBoxState(box, candidate.username);
      label.appendChild(box);
      row.appendChild(avatar);
      row.appendChild(name);
      row.appendChild(display);
      row.appendChild(label);
      return {row, box};
    }
    const row = document.createElement('div');
    row.setAttribute('role', 'button');
    row.dataset.username = candidate.username;
    row.style.cssText =
      'display:flex;height:48px;width:300px;align-items:center;gap:8px';
    const username = document.createElement('span');
    username.textContent = candidate.username;
    const display = document.createElement('span');
    display.textContent = candidate.display;
    const box = document.createElement('input');
    box.type = 'checkbox';
    setBoxState(box, candidate.username);
    row.appendChild(username);
    row.appendChild(display);
    row.appendChild(box);
    return {row, box};
  }
  function renderResults() {
    if (!results) return;
    results.innerHTML = '';
    const query = String(entry && entry.value || '').trim().toLowerCase();
    for (const candidate of candidates) {
      if (!candidate.username.toLowerCase().includes(query)) continue;
      const {row, box} = buildCandidateRow(candidate);
      row.addEventListener('click', () => {
        document.body.dataset.rowClicks = String(
          Number(document.body.dataset.rowClicks || 0) + 1);
        document.body.dataset.clickedUsername = candidate.username;
        document.body.dataset.clickedIndex = String(candidates.indexOf(candidate));
        if (rowClick === 'detach-entry') {
          // 模拟点击后回读通道消失：输入框被摘除，后续 evaluate 无法解析。
          if (entry) entry.remove();
          return;
        }
        if (rowClick !== 'select') return;
        const toggle = () => {
          const index = selected.indexOf(candidate.username);
          if (index < 0 && pageLimit !== null &&
              selected.length >= pageLimit) {
            const notice = document.getElementById('collab-limit');
            if (notice) {
              notice.textContent = limitNotice;
              notice.hidden = false;
            }
            return;
          }
          if (index >= 0) {
            selected.splice(index, 1);
          } else if (selected.length < 5) {
            selected.push(candidate.username);
          }
          // ``selected`` 是预算测试的触发信号；checkbox/chip 是控件的确认
          // 信号。``confirmDelayMs`` 把两者分开，避免测试里“预算到期”和
          // “确认完成”在同一 tick 竞争。
          recordSelection();
          const confirm = () => {
            setBoxState(box, candidate.username);
            document.body.dataset.checkedRowCount = String(
              results.querySelectorAll('input[type="checkbox"]:checked').length);
            const states = JSON.parse(
              document.body.dataset.checkboxStates || '[]');
            states.push({
              username: candidate.username,
              checked: box.checked,
              aria: box.getAttribute('aria-checked'),
            });
            document.body.dataset.checkboxStates = JSON.stringify(states);
            renderChips();
            if (valueAfterFive !== null && selected.length >= 5 && entry) {
              entry.value = valueAfterFive;
            }
            if (hideStampedAfter &&
                candidate.username === hideStampedAfter) {
              hideStamps = true;
            }
          };
          if (confirmDelayMs > 0) {
            setTimeout(confirm, confirmDelayMs);
          } else {
            confirm();
          }
        };
        if (checkboxDelayMs > 0) {
          setTimeout(toggle, checkboxDelayMs);
        } else {
          toggle();
        }
      });
      results.appendChild(row);
    }
  }
  new MutationObserver(() => {
    if (!hideStamps) return;
    const row = results.querySelector('[data-instagram-collaborator-row]');
    if (row) row.style.display = 'none';
  }).observe(results, {
    subtree: true,
    attributes: true,
    attributeFilter: ['data-instagram-collaborator-row'],
  });
  document.addEventListener('focusin', (event) => {
    if (event.target && event.target.id) {
      document.body.dataset.focusedEntry = event.target.id;
    }
  });
  if (entry) {
    entry.addEventListener('click', () => {
      document.body.dataset.entryClicks = String(
        Number(document.body.dataset.entryClicks || 0) + 1);
      openPanel();
    });
    entry.addEventListener('focus', openPanel);
    entry.addEventListener('input', () => {
      const progress = JSON.parse(document.body.dataset.progress || '[]');
      if (!progress.length ||
          progress[progress.length - 1].query !== entry.value) {
        progress.push({query: entry.value, checked: checkedNames()});
        document.body.dataset.progress = JSON.stringify(progress);
      }
      const queries = JSON.parse(document.body.dataset.queries || '[]');
      queries.push(entry.value);
      document.body.dataset.queries = JSON.stringify(queries);
      renderResults();
    });
  }
  if (done) {
    done.addEventListener('click', () => {
      document.body.dataset.doneClicks = String(
        Number(document.body.dataset.doneClicks || 0) + 1);
      if (doneCollapses === 'hide-done-only') {
        done.hidden = true;
      } else if (doneCollapses) {
        panel.hidden = true;
      }
    });
  }
  renderChips();
  recordSelection();
  if (panelInitiallyOpen) openPanel();
</script>
"""

_COLLABORATOR_PAGE = """
<div role="dialog" id="compose">
  <div role="heading" aria-level="1">Create new post</div>
  <div data-share-clicks="0"></div>
  __ENTRY__
  __RESTRICTION__
  <div id="chips"></div>
  <div id="collab-panel" hidden>
    <div id="collab-limit" role="alert" hidden></div>
    <div id="collab-results"></div>
    <div role="button" id="collab-done">__DONE_LABEL__</div>
  </div>
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
  <div role="button" id="share"
       onclick="const holder=document.querySelector('[data-share-clicks]');
                holder.dataset.shareClicks=String(Number(holder.dataset.shareClicks||0)+1);">Share</div>
</div>
""" + _COLLABORATOR_SCRIPT

_ENTRY_HTML = {
    "structural": (
        '<input id="collab-entry" name="creation-collaborator-input" '
        'placeholder="Add collaborators" autocomplete="off">'
    ),
    "en": (
        '<input id="collab-entry" placeholder="Add collaborators" '
        'autocomplete="off">'
    ),
    "zh": (
        '<input id="collab-entry" placeholder="添加合作者" '
        'autocomplete="off">'
    ),
    "broad": (
        '<input id="collab-entry" placeholder="Search for collaborators" '
        'autocomplete="off">'
    ),
    "disabled": (
        '<input id="collab-entry" name="creation-collaborator-input" '
        'placeholder="Add collaborators" autocomplete="off" disabled>'
    ),
    "missing": "",
}

_SIBLING_PANEL_PAGE = """
<style>
  #collab-panel[hidden] { display: none; }
</style>
<div role="dialog" id="compose" aria-label="Create new post" aria-modal="true"
     style="margin: 120px 160px; width: 640px; height: 420px;">
  <div role="heading" aria-level="1">Create new post</div>
  <div data-share-clicks="0"></div>
  <label style="display:block;">
    <input id="collab-entry" name="creation-collaborator-input"
           placeholder="Add collaborators" autocomplete="off">
  </label>
  <div id="chips"></div>
  <div role="textbox" contenteditable="true" data-lexical-editor="true"></div>
  <div role="button" id="share"
       onclick="const holder=document.querySelector('[data-share-clicks]');
                holder.dataset.shareClicks=String(Number(holder.dataset.shareClicks||0)+1);">Share</div>
</div>
__DECOY__
<div style="position: fixed; left: 120px; top: 330px;
            transform: translate(0, -100%); z-index: 5;">
  <div role="dialog" id="collab-panel" hidden>
    <div id="collab-limit" role="alert" hidden></div>
    <div id="collab-results"></div>
    <div role="button" id="collab-done">__DONE_LABEL__</div>
  </div>
</div>
""" + _COLLABORATOR_SCRIPT

_DECOY_DIALOGS = """
<div role="dialog" id="decoy-text" hidden data-decoy
     style="position: fixed; left: 1000px; top: 500px; width: 220px;
            height: 90px; background: #f5f5f5;">
  <button id="decoy-row"
          style="display: flex; height: 44px; width: 200px; align-items: center;
                 gap: 6px;">
    <div>decoyuser</div>
    <span>Decoy User</span>
    <input type="checkbox" aria-checked="false"
           aria-label="Checkmark outline icon">
  </button>
</div>
<div role="dialog" id="decoy-switch" hidden data-decoy
     style="position: fixed; left: 180px; top: 160px; width: 220px;
            height: 60px; background: #eef;">
  <span>Add AI label</span>
  <input type="checkbox" role="switch" aria-checked="false">
</div>
<script>
  const decoyRow = document.getElementById('decoy-row');
  if (decoyRow) {
    decoyRow.addEventListener('click', () => {
      document.body.dataset.decoyRowClicks = String(
        Number(document.body.dataset.decoyRowClicks || 0) + 1);
    });
  }
</script>
"""


def _render_collaborator_page(
    template: str,
    *,
    candidates=(),
    preselect=(),
    done_label: str = "Done",
    done_collapses=True,
    panel_initially_open: bool = False,
    row_click: str = "select",
    render_chips: bool = True,
    value_after_five: str | None = None,
    checkbox_delay_ms: int = 0,
    confirm_delay_ms: int = 0,
    panel_opens: bool = True,
    hide_stamped_after: str | None = None,
    page_limit: int | None = None,
    limit_notice: str = "You can only add up to 2 collaborators.",
    sibling_mode: bool = False,
    extras: dict[str, str] | None = None,
) -> str:
    replacements = {
        **(extras or {}),
        "__CANDIDATES__": json.dumps(
            [
                {"username": username, "display": display}
                for username, display in candidates
            ],
            ensure_ascii=False,
        ),
        "__PRESELECT__": json.dumps(list(preselect)),
        "__ROW_CLICK__": json.dumps(row_click),
        "__DONE_COLLAPSES__": json.dumps(done_collapses),
        "__PANEL_INITIALLY_OPEN__": "true" if panel_initially_open else "false",
        "__RENDER_CHIPS__": "true" if render_chips else "false",
        "__VALUE_AFTER_FIVE__": json.dumps(value_after_five),
        "__CHECKBOX_DELAY_MS__": str(int(checkbox_delay_ms)),
        "__CONFIRM_DELAY_MS__": str(int(confirm_delay_ms)),
        "__PANEL_OPENS__": "true" if panel_opens else "false",
        "__HIDE_STAMPED_AFTER__": json.dumps(hide_stamped_after),
        "__PAGE_LIMIT__": json.dumps(page_limit),
        "__LIMIT_NOTICE__": json.dumps(limit_notice),
        "__SIBLING_MODE__": "true" if sibling_mode else "false",
        "__DONE_LABEL__": done_label,
    }
    html = template
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)
    return html


def collaborator_page_html(
    candidates=(),
    *,
    entry="structural",
    value_after_five="5 people",
    restriction="",
    obscured=False,
    **options,
) -> str:
    """受控配文页：结构/中英文入口、勾选面板、预览 chip、Done 与 Share 计数。"""
    html = _render_collaborator_page(
        _COLLABORATOR_PAGE,
        candidates=candidates,
        value_after_five=value_after_five,
        sibling_mode=False,
        extras={"__ENTRY__": _ENTRY_HTML[entry], "__RESTRICTION__": restriction},
        **options,
    )
    if not obscured:
        return html
    return (
        f'<div aria-hidden="true">{html}</div>'
        '<div role="dialog" id="discard">'
        '<div>放弃帖子？</div>'
        '<div>如果退出，你所做的编辑不会保存。</div>'
        '<div role="button">放弃</div>'
        '<div role="button">取消</div>'
        '</div>'
    )


def sibling_panel_page_html(
    candidates=(),
    *,
    decoy=False,
    **options,
) -> str:
    """真机结构（2026-11-24）：面板是创建弹窗之外的兄弟 ``role=dialog``。

    候选行是 ``<button>``（username div + 显示名 span + label/checkbox），
    Done 是面板内的 ``div[role=button]``；入口仍在创建弹窗内。
    """
    return _render_collaborator_page(
        _SIBLING_PANEL_PAGE,
        candidates=candidates,
        sibling_mode=True,
        extras={"__DECOY__": _DECOY_DIALOGS if decoy else ""},
        **options,
    )


def timeout_patches(*, suggestion_timeout_ms=250):
    """把控件等待收紧到测试尺度；不改变生产默认值。"""
    return (
        patch.object(collaborators_control_module, "ENTRY_TIMEOUT_MS", 300),
        patch.object(collaborators_control_module, "PANEL_TIMEOUT_MS", 600),
        patch.object(collaborators_control_module, "SUGGESTION_TIMEOUT_MS", suggestion_timeout_ms),
        patch.object(collaborators_control_module, "READBACK_TIMEOUT_MS", 400),
    )


async def expire_budget_after_username(page, budget, username):
    """页面确认 ``username`` 后把发布预算推到过去，制造“列表中途耗尽”。

    触发条件是页面可见的已选集合（chip / checkbox 同源），不是控件私有调用
    次数；这样测试观察的就是真实的中途预算耗尽，而不是实现细节。
    """
    await page.wait_for_function(
        """(username) => {
          try {
            return JSON.parse(document.body.dataset.selected || '[]')
              .includes(username);
          } catch (error) {
            return false;
          }
        }""",
        arg=username,
    )
    budget.deadline = time.monotonic() - 1
