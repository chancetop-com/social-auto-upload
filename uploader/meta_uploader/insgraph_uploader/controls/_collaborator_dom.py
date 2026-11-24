"""Instagram 协作者 DOM 探针、选择器常量与页面文案匹配。

本模块只包含纯文本匹配与传给 ``Locator.evaluate`` 的结构/几何探针，不持有
控制流状态；由 ``controls/collaborators.py`` 编排交互与回读。
"""
from __future__ import annotations

import re

# 入口选择器：结构属性优先，然后英文/中文 placeholder 与 aria-label，最后更宽
# 的中英文回退。定位限定在包含可见入口的创建弹窗内；没有弹窗祖先的输入框
# 不参与解析，也不做全页 locator。
ENTRY_SELECTORS = (
    'input[name="creation-collaborator-input"]',
    'input[placeholder="Add collaborators"]',
    'input[aria-label="Add collaborators"]',
    'input[placeholder="添加合作者"]',
    'input[aria-label="添加合作者"]',
    'input[placeholder*="collaborator" i]',
    'input[aria-label*="collaborator" i]',
    'input[placeholder*="合作者"]',
    'input[aria-label*="合作者"]',
)
DONE_LABELS = ("Done", "完成")

_ROW_ATTR = 'data-instagram-collaborator-row'
_PANEL_ATTR = 'data-instagram-collaborator-panel'
_ENTRY_SELECTOR_UNION = ', '.join(ENTRY_SELECTORS)

# 面板与 chip 的 JS 共用同一个空白归一化实现；只声明一次，避免两份漂移。
_JS_NORM_HELPER = (
    "  const norm = (value) => "
    "String(value || '').replace(/\\s+/g, ' ').trim();\n"
)

# 只有页面明确说明账号/地区不具备协作者资格时才使用 account_ineligible；
# 单纯 disabled 记 control_disabled。
_COLLABORATOR_RESTRICTION_PATTERNS = (
    re.compile(
        r"(?:collaborator|合作者|协作者)[^.\n]{0,40}"
        r"(?:not\s+available|isn['’]t\s+available|unavailable|"
        r"not\s+supported|isn['’]t\s+supported|"
        r"不可用|不支持|不符合资格|无法使用|无法邀请|无法添加)"
        r"[^.\n]{0,40}"
        r"(?:account|账号|region|country|地区|国家)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:account|账号)[^.\n]{0,40}"
        r"(?:not\s+eligible|ineligible|不符合资格|无资格)"
        r"[^.\n]{0,40}(?:collaborator|合作者|协作者)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:can['’]?t|cannot|unable\s+to|无法|不能)"
        r"[^.\n]{0,20}"
        r"(?:add|invite|select|添加|邀请|选择)"
        r"[^.\n]{0,20}(?:collaborator|合作者|协作者)",
        re.IGNORECASE,
    ),
)

# 页面可能把账号/地区的协作者上限设得低于静态 5。点击后 checkbox 仍未勾选
# 时，只有页面明确给出“上限/只能/最多/无法再添加”等拒绝信号，才归因为页面
# 拒绝（final_mismatch）；否则仍是点击未生效（selection_failed）。
_COLLABORATOR_LIMIT_PATTERNS = (
    re.compile(
        r"(?:collaborator|collaborators|合作者|协作者)"
        r"[^.\n]{0,60}"
        r"(?:up\s+to|more\s+than|limit(?:ed)?|maximum|max\.?|reached|"
        r"最多|上限|只能|不能再|已达到|达到|"
        r"cannot\s+add|can['’]?t\s+add|unable\s+to\s+add|"
        r"无法添加|无法邀请)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:up\s+to|more\s+than|limit(?:ed)?|maximum|max\.?|reached|"
        r"最多|上限|只能|不能再|已达到|达到|"
        r"cannot\s+add|can['’]?t\s+add|unable\s+to\s+add|"
        r"无法添加|无法邀请)"
        r"[^.\n]{0,60}"
        r"(?:collaborator|collaborators|合作者|协作者)",
        re.IGNORECASE,
    ),
)

_COLLABORATOR_COUNT_SUMMARY = re.compile(
    r"(?:"
    r"(\d+)\s+(?:people|person)"
    r"|"
    r"(?:(?:已添加|已选择|已选)\s*)?(\d+)\s*(?:位用户|位合作者|位协作者|位|人)"
    r")",
    re.IGNORECASE,
)

# 面板解析（真机 2026-11-24）：候选面板是创建弹窗之外的兄弟 role=dialog。
# 先认创建弹窗自身（既有受控 DOM 把结果列表嵌在弹窗内）；否则在所有可见
# role=dialog 中取“含可见非 switch checkbox 行或可见 Done/完成 按钮”且与
# 协作者入口几何最近的弹窗。普通按钮不算面板信号，避免把通知/放弃弹窗
# 误认成已打开的候选面板。
_PANEL_PREDICATES_JS = _JS_NORM_HELPER + """
  const visible = (node) => {
    if (!node || !node.getClientRects().length) return false;
    const style = getComputedStyle(node);
    return style.visibility !== 'hidden' && style.display !== 'none';
  };
  const rowForInput = (input, dialog) => {
    let row = input.closest('button, [role="button"], li, label');
    if (!row) row = input.parentElement;
    while (row && row !== dialog && !norm(row.innerText || row.textContent)) {
      row = row.parentElement;
    }
    return row && row !== dialog ? row : null;
  };
  const collectCandidateRows = (dialog) => {
    if (!dialog || !visible(dialog)) return [];
    const seen = new Set();
    const rows = [];
    for (const input of dialog.querySelectorAll('input[type="checkbox"]')) {
      if ((input.getAttribute('role') || '').toLowerCase() === 'switch') {
        continue;
      }
      if (!visible(input)) continue;
      const row = rowForInput(input, dialog);
      if (!row || !visible(row) || seen.has(row)) continue;
      seen.add(row);
      const text = norm(row.innerText || row.textContent || '');
      if (!text) continue;
      const username = text.split(/\\s+/)[0];
      if (!username) continue;
      rows.push({
        node: row,
        username: username,
        display: text.slice(username.length).trim(),
        checked: Boolean(input.checked) ||
          (input.getAttribute('aria-checked') || '').toLowerCase() === 'true',
      });
    }
    return rows;
  };
  const hasCandidateRows = (dialog) => collectCandidateRows(dialog).length > 0;
  const doneLabels = new Set([__DONE_LABELS__]);
  const hasDoneButton = (dialog) => {
    if (!dialog || !visible(dialog)) return false;
    for (const node of dialog.querySelectorAll('button, [role="button"]')) {
      if (!visible(node)) continue;
      const text = norm(
        node.innerText || node.textContent || ''
      ).toLowerCase();
      const label = norm(node.getAttribute('aria-label') || '').toLowerCase();
      if (doneLabels.has(text) || doneLabels.has(label)) return true;
    }
    return false;
  };
  const isPanelDialog = (dialog) =>
    hasCandidateRows(dialog) || hasDoneButton(dialog);
""".replace(
    "__DONE_LABELS__",
    ', '.join(f"'{label.lower()}'" for label in DONE_LABELS),
)

_PANEL_HELPERS_JS = _PANEL_PREDICATES_JS + """
  const composer = el.closest('[role="dialog"]');
  const entryRect = el.getBoundingClientRect();
  const distanceTo = (node) => {
    const rect = node.getBoundingClientRect();
    const dx = Math.max(
      0, Math.max(rect.left - entryRect.right, entryRect.left - rect.right));
    const dy = Math.max(
      0, Math.max(rect.top - entryRect.bottom, entryRect.top - rect.bottom));
    return Math.hypot(dx, dy);
  };
  const resolvePanel = () => {
    if (isPanelDialog(composer)) return composer;
    let best = null;
    let bestDistance = Infinity;
    for (const dialog of document.querySelectorAll('[role="dialog"]')) {
      if (dialog === composer || !isPanelDialog(dialog)) continue;
      const distance = distanceTo(dialog);
      if (best === null || distance < bestDistance) {
        best = dialog;
        bestDistance = distance;
      }
    }
    return best;
  };
"""

# 检查刚点击 Done 的具体面板节点本身是否仍含候选行或 Done 按钮，
# 避免面板关闭后重新全页扫描时误把其它无关兄弟弹窗当作“未收起”。
_PANEL_OPEN_JS = """(dialog) => {""" + _PANEL_PREDICATES_JS + """
  return isPanelDialog(dialog);
}"""

# 候选行：从 checkbox 出发找最近的 role=button/button/li/label 行；只读取
# username 首 token。AI/评论开关是 role=switch，明确排除。
_ROWS_JS = """(el, action) => {""" + _PANEL_HELPERS_JS + """
  const panel = resolvePanel();
  if (!panel) return null;
  const rows = collectCandidateRows(panel);
  if (!action) {
    return rows.map((row, index) => ({
      index: index,
      username: row.username,
      display: row.display,
      checked: row.checked,
    }));
  }
  const target = rows[action.index];
  if (!target) return null;
  if (norm(target.username).toLowerCase() !==
      norm(action.username).toLowerCase()) return null;
  target.node.setAttribute('data-instagram-collaborator-row', action.stamp);
  return true;
}"""

# 用一次性属性戳把解析出的面板交给 Playwright locator；Done/完成 必须落在
# 这个面板内（兄弟 portal 或创建弹窗），不能全页搜索。
_PANEL_JS = """(el, stamp) => {""" + _PANEL_HELPERS_JS + """
  const panel = resolvePanel();
  if (!panel) return false;
  panel.setAttribute('data-instagram-collaborator-panel', stamp);
  return true;
}"""

# 图文预览图 chip：带 Close/关闭 svg 的 role=button，最近的 span 祖先里
# 有一个 username span。只认这个结构，不读取输入框里的 “5 people” 摘要。
_CHIPS_JS = """(el) => {
  const dialog = el.closest('[role="dialog"]');
  if (!dialog) return [];
""" + _JS_NORM_HELPER + """
  const labels = new Set(['close', '关闭']);
  const names = [];
  const seen = new Set();
  for (const svg of dialog.querySelectorAll('svg[aria-label]')) {
    const label = norm(svg.getAttribute('aria-label')).toLowerCase();
    if (!labels.has(label)) continue;
    const button = svg.closest('[role="button"], button');
    if (!button) continue;
    const chip = button.closest('span');
    if (!chip) continue;
    const name = chip.querySelector('span');
    if (!name) continue;
    const text = norm(name.innerText || name.textContent || '');
    if (!text) continue;
    const key = text.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    names.push(text);
  }
  return names;
}"""


def _extract_matching_sentence(
    body: str | None, patterns: tuple[re.Pattern[str], ...]
) -> str | None:
    """从文案中提取首个命中 ``patterns`` 的完整句子；无匹配返回 ``None``。"""
    if not body:
        return None
    text = ' '.join(str(body).split())
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            endings = [
                index for index in (
                    text.find('.', match.end()),
                    text.find('。', match.end()),
                )
                if index != -1
            ]
            end = min(endings) if endings else min(
                len(text), match.end() + 120
            )
            return text[match.start():end + 1].strip()
    return None


def collaborator_restriction_message(body: str | None) -> str | None:
    """返回页面明确写出的协作者资格限制句；没有则返回 ``None``。"""
    return _extract_matching_sentence(body, _COLLABORATOR_RESTRICTION_PATTERNS)


def collaborator_limit_message(body: str | None) -> str | None:
    """返回页面明确写出的协作者上限/拒绝句；没有则返回 ``None``。"""
    return _extract_matching_sentence(body, _COLLABORATOR_LIMIT_PATTERNS)


def collaborator_count_summary(
    value: str | None, *, query: str | None = None
) -> int | None:
    """解析入口显示的已选人数摘要；普通搜索词（如 ``1person``）返回 ``None``。"""
    text = ' '.join(str(value or '').split())
    if not text:
        return None
    if query is not None and text.lower() == query.strip().lower():
        return None
    match = _COLLABORATOR_COUNT_SUMMARY.fullmatch(text)
    if not match:
        return None
    return int(match.group(1) or match.group(2))
