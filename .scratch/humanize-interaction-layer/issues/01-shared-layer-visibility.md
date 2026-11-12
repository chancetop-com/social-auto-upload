# 01 — 共享层前置修复：几何可见性谓词

**What to build:** `ensure_in_viewport` 不再依赖 `page.viewport_size`，改为在目标元素自己的 frame 里判断「该比例落点是否几何可见」：主视口内、且未被逐层 `overflow != visible` 祖先裁剪；目标在子 frame 内时把落点投影回主 frame 再问一次。可见 → 不滚；不可见或求值异常 → `scroll_into_view_if_needed`。`Humanizer.click` 行为一行不改（内部零重试、±1px 容差、事件序列不变），`hover` 复用同一谓词。同步删除 `DEFAULT_VIEWPORT_*` 与 1280×720 静默兜底，不新增失败 `reason`。

规格依据：`../humanize-rollout/spec.md` §2.5（含谓词 JS、测试要求与「可见性可修、可点性不修」的切分原则）。

Blocked by: None — can start immediately.

Status: ready-for-agent

- [x] 谓词在元素所在 frame 内执行；同 frame 视口 + 祖先 `overflow` 裁剪都判
- [x] 子 frame 目标额外做父 frame 投影判断（`elementFromPoint` 非空）
- [x] `page.viewport_size` 不再被读；`DEFAULT_VIEWPORT_*` 归零；求值异常一律保守判「需滚动」
- [x] `covered-by:unknown` 文案与语义不变；新增诊断只进 DEBUG 日志
- [x] 测试覆盖：视口内 / 视口外 / 祖先裁剪 / `viewport_size=None` / 父 frame 裁剪 / `evaluate` 抛错
- [x] `tests/test_xhs_dom.py` 的三条视口算术用例改写为谓词用例，其余断言不降级
- [x] 门 A–E 的测试实现落地（扫描名单先只含小红书），XHS 包全绿
- [x] 现有 `tests/test_humanize.py` 契约用例不回归

## Answer

- `ensure_in_viewport` 改为 `locator.evaluate` 在元素自身 frame 内求几何谓词；`page.viewport_size` / `DEFAULT_VIEWPORT_*` / 1280×720 兜底全部删除。子 frame 目标用 `locator.bounding_box()` 回投主 frame 再问 `elementFromPoint`。
- 返回语义保持：只有真的调用了 `scroll_into_view_if_needed` 且成功才 `True`；可见、零尺寸或没有滚动 API 均 `False`。求值/投影异常一律保守判需滚动，诊断只进 `logging` DEBUG，`covered-by:unknown` 文案未动。
- 新增 `tests/humanize_gates.py`：`gate_violations(package)` / `assert_clean(package, root=...)` 以 AST 实现门 A–E；`tests/test_humanize.py` 用合成包逐门验证并把小红书包接入，当前 0 违规。
- `tests/test_xhs_dom.py` 的 `EnsureInViewportTests` 改写为谓词用例（含 `viewport_size` 禁读、子 frame 双向投影、异常保守、零尺寸、无滚动 API），`Humanizer.click` / `hover` 未改一行。
- 全量 `pytest -q`：1526 passed, 2 skipped, 774 subtests passed；合并 `humanize-interaction-layer` 后复跑仍全绿。


