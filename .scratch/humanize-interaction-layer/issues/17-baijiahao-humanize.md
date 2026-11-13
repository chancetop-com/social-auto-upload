# 17 — 百家号：contenteditable 清空与搜索候选全等

**What to build:** 标题、合集搜索、声明与发布接入人类化。标题是 `contenteditable` 且页面可能自动填文件名：保留「点标题 → Ctrl+A → Backspace」清空序列后逐字。合集搜索逐字输入，固定等待换成有界等待，候选项按合集名全等匹配（`.first` 仅降级）。创作声明改点组件本体，删除 force；发布遮挡走清浮层。

规格依据：§3.2、§2.4、§4。波次：W5（本波热点，先做）。

Blocked by: 01

Status: resolved

- [x] 标题清空序列保留；自动填的文件名被完全替换
- [x] 搜索候选按全等命中；命中不到时沿用现有跳过策略，不中止发布
- [x] 声明组件改点本体，force 删除；发布点无 force
- [x] 零 `fill(`、零 `el.click()`
- [x] `tests/test_baijiahao_humanize.py` 三条（含标题替换与搜索全等）
- [x] 百家号入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W5 小节加本平台一行

## Answer

- 单个 `Humanizer(page, sleep=self._humanize_pause)` 在 `context.new_page()` 之后构造并缓存（`cached.page is not page` 失效）；预算裁剪首次发生打一条 warning。
- 标题保留真机手写清空序列：`humanizer.click` → `press("Control+a")` → `press("Backspace")` → `type_text`（短标题补齐/截断逻辑不变），读回证明自动填入的文件名被整体替换（不是追加）。合集搜索改为开下拉 → 聚焦搜索框 → 逐字 `type_text` → `wait_for` 有界等待候选，然后逐项读文本**全等**匹配；`.first` 只用于同一合集被渲染成多个节点时的全等集合内部降级，不对未过滤候选取首项。命中不到沿用「warning + `press("Escape")`」跳过，不中止发布、不选错合集。
- 封面入口/裁剪确认、创作声明组件本体（不再点 antd 装饰层 input）、「含AI生成内容」、声明确定、合集下拉与全等项、发布全部走 `Humanizer.click`；发布前 `before_submit`，遮挡只清浮层（`press("Escape")` 收残留 modal），包内 `force=True` / `fill(` / `el.click()` 均归零。百度 passport 登录与封面弹窗「上传」tab（与 `set_input_files` 成对）保持原生并带 `# native-click: login` / `# native-click: file`。
- 验证：`tests/test_baijiahao_humanize.py` 13 条（事件序列 / 字段读回含文件名替换与合集全等+未命中跳过 / 门 A–E / `HUMANIZE=0` / 实例缓存 / `upload_in` 接线）全绿；包内门 A–E 零违规；全量 `pytest -q` 1630 passed, 2 skipped。
- 偏差/未验证：合集候选的文本可全等性仍是 `needs-live`（spec §9 #11，无真机 DOM）；标题选择器按 spec §3.0 收窄到 `count()==1`，若真机存在多个 `contentEditable` 会以 `ambiguous:N` 硬失败（有意不自动 `.first`）。发布点击本身按本轮 `--no-publish` 约定只有离线证据。
