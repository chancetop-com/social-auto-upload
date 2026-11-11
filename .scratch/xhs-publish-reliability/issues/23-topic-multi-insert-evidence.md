# 23 — 连续多话题插入取证（第 2+ 个候选 / 锚点作用域 / 下拉关闭）

Status: resolved
Type: task
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

08 的决议里嵌了三个**未经真机验证的假设**，其中第一个会直接改写 08 §6（是否补最小光标复位）。用有效登录态在图文编辑器里**连续插入 3 个话题**（不发布），记录：

1. **连续插入**：插入第 1 个话题后，继续键入 `#第二个` / `#第三个`，`#creator-editor-topic-container` 是否仍然出现、`.item` 是否仍然可点？若需要额外动作才能再次触发，记录**最小**的那个动作（不要用上游的 20×ArrowDown + 2×Enter 当默认答案）。
2. **锚点作用域**：`a[data-topic]` 的祖先链里是否**始终**有 `div.tiptap[role=textbox]`？若不是，记录真实容器与选择器。
3. **下拉关闭**：点击候选成功后，`#creator-editor-topic-container` 是否立即消失？不消失持续多久？
   （决定 08 §3 的「双插中止」是理论风险还是现实风险。）
4. **`.name` 文本**：是否始终带前导 `#`（02 样本带）？顺带记录一次候选的实际排序前 5 项与请求词。

## 做法

复用 02 的取证脚本与登录态（`research/capture_live_dom.py`、`probe_editor_controls.py`；`cookies/xiaohongshu_180.json` 或当前有效账号），图文编辑器内操作，**`--no-publish` / 不点发布**。产出 `research/23-topic-multi-insert.md` + 脱敏原始片段（无 cookie、昵称、正文内容）。

## Answer

**真机取证完成（2026-11-11，图文编辑器，连续插入 `旅行 → 美食 → 穿搭`，未发布）。** 三个假设全部有结论，并额外发现一个必须改判据的事实：**编辑区内每次插入恰好 +1**，02 的「2 个同值锚点」是 1 个编辑器节点 + 1 个右侧预览镜像。

1. **连续插入**：第 2/3 个话题直接键入 `#tag` 即出现 50 项候选，**不需要任何复位动作**；`Control+End` 也不需要补。唯一要注意的是**候选就绪时机**：容器在键入后立即以 0 项空壳出现（约 1–111ms），随后消失/重绘，约 430–570ms 才出现 50 项；只等容器 `visible` 会误判「无候选」。
2. **锚点作用域**：编辑器节点**始终**在 `div.tiptap[role=textbox]` 内（`a.tiptap-topic > p > div.tiptap[role=textbox]`）；但整页还有 1 个同值预览镜像，挂在 `.preview-container .image-preview … .info > p > a`，**没有** `contenteditable`。因此 `a[data-topic]` 必须限定编辑区，否则每次插入会被算成 +2。
3. **下拉关闭**：点击成功后 **0–2ms** 内容器从 DOM 移除（不是仅隐藏）。08 §3 的「双插」是理论风险，当前不是现实路径。
4. **`.name`**：采样 30/30 全部带前导 `#`；`data-topic.name` 不带 `#`。三个请求词的精确项**都排第 4**（热度排序），再次证明必须全扫。

**对 08 的修订（已回写 08/05）**：回读判据从「新增 1–2 个」收紧为「编辑区内**恰好 1 个**；>1 = `topic-multi-insert` 中止」；候选就绪条件补 `item_count > 0`。08 §6 的「不采用复位」得到确认，无需新增动作。

- 证据与时间线：[research/23-topic-multi-insert.md](../research/23-topic-multi-insert.md)
- 取证脚本：`research/probe_topic_multi_insert.py`
- 原始数据：`research/raw/23-topic-multi-insert.json`（已脱敏，无 cookie/昵称/正文）
- 置信度：**真机取证**（单账号、图文编辑器、3 个话题）；视频页与 4–10 个连续话题未覆盖。
