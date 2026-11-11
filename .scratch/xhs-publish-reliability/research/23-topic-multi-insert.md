# 23 — 连续多话题插入真机取证

- 取证时间：2026-11-11（本机，headless Chromium，patchright）
- 账号：复用 `cookies/xiaohongshu_180.json`（登录态有效），**未填标题、未点发布**；浏览器关闭后草稿未提交
- 环境：与本地模式同参数——`channel="chromium"`、`locale=zh-CN`、`Accept-Language: zh-CN,zh;q=0.9`、stealth init script、UA 去掉 `HeadlessChrome`
- 脚本：`research/probe_topic_multi_insert.py`（新增）
- 原始数据：`research/raw/23-topic-multi-insert.json`（只含测试话题与候选文本，**无 cookie / 昵称 / 正文内容**）
- 场景：图文编辑器，上传 1 张测试图后，依次键入 `#旅行` → `#美食` → `#穿搭`，每次都点**归一化全等**的候选；全程不发布
- 置信度口径：**真机取证** = 本次实际观察到；**仅推断** = 本次未覆盖

## 1. 连续插入：第 2/3 个话题不需要任何额外动作

| # | 请求词 | 候选数 | 全等项位置 | 点击后编辑区内新增锚点 | 需要复位动作？ |
|---|---|---|---|---|---|
| 1 | `#旅行` | 50 | 第 **4** 项 `#旅行` | **1** | 否（首次插入） |
| 2 | `#美食` | 50 | 第 **4** 项 `#美食` | **1** | **否** |
| 3 | `#穿搭` | 50 | 第 **4** 项 `#穿搭` | **1** | **否** |

- 插入第 1 个话题后，光标留在编辑区内，直接继续键入 `#美食` / `#穿搭`，`#creator-editor-topic-container` **照常出现**，`.item` 照常可点。
- 因此 08 §6 的「不抄 `ArrowDown×20 + Enter×2`」成立；**也不需要补 `Control+End` 或其它最小复位动作**（复查条件未触发）。
- 三次键入耗时 105–200ms（`keyboard.type(delay=30)`），无额外等待。

### 候选列表的就绪时机（比“容器可见”晚）

100ms 采样，三个请求词形态一致：

| t(ms) | 容器 visible | `.item` 数 | 说明 |
|---|---|---|---|
| 1–111 | 1 | **0** | 容器先以空壳出现 |
| 222–360 | 0 | 0 | 空壳消失（疑似重绘） |
| **432–567** | 1 | **50** | 候选真正渲染完成 |

→ **`#creator-editor-topic-container` 可见 ≠ 候选可读**。若在容器刚可见时扫 `.item`，会读到 0 项并把「有候选」误判成「无候选」而错误降级。08 §3 的「每轮重新扫全部渲染项」必须配一个 **`item_count > 0`** 的就绪条件，而不是只等容器 `visible`。

## 2. 锚点作用域：页面级始终有 2 个，编辑区内始终只有 1 个

### 编辑区内（真正的正文）

每次插入在 `div.tiptap[role="textbox"]` 内**恰好新增 1 个**锚点，祖先链稳定：

```
a.tiptap-topic[contenteditable=false]
  └─ p
      └─ div.tiptap.ProseMirror[role=textbox][contenteditable=true]
          └─ div.tiptap-container
              └─ div.editor-content
                  └─ div.editor-container
                      └─ div.edit-container
                          └─ div.publish-page-content-base
```

### 编辑区外（预览镜像）

页面级 `document.querySelectorAll('a[data-topic]')` 每次插入出现 **2 个**，第 2 个是图文预览区的镜像：

```
a.tiptap-topic
  └─ p
      └─ div.info
          └─ div.scroll-container
              └─ div.image-area
                  └─ div.image-container
                      └─ div.image-preview
                          └─ div.preview-container
```

- 两个节点 `data-topic` 完全相同（同 `id` / `link` / `name`），可见文本也相同（`#旅行[话题]#`），但预览节点没有 `contenteditable` 属性。
- **纠正 02 的读法**：02 记录的「一次插入产生 2 个同值 `a[data-topic]`」是 **1 个编辑器节点 + 1 个预览镜像**，不是编辑器内 2 个节点。
- **结论（真机取证）**：`a[data-topic]` 不能整页查；必须限定 `div.tiptap[role="textbox"] a[data-topic]`。08 §4-1 的作用域假设正确，而且是**必需**的。
- **对 08 §4-5 / §1 的连带修订**：编辑区内每次插入就是 **+1**。原判据「新增 1–2 个 → 成功」会把「一次点击插了两次」（2 个新增）当成正常；应改为 **恰好 1 个 → 成功；0 个 → 缺失；>1 个 → `topic-multi-insert` 中止**。此时 02 曾担心的「双插 4 个新增」只在整页作用域下成立；限定编辑区后双插是 2 个。

## 3. 下拉关闭：点击成功后立即消失

| # | 点击后首次采样 | 容器 DOM 数 | 结论 |
|---|---|---|---|
| 1 | **2ms** | 0 | 已消失 |
| 2 | **0ms** | 0 | 已消失 |
| 3 | **1ms** | 0 | 已消失 |

- 100ms 采样下第一次就已为 0，且 `#creator-editor-topic-container` 从 DOM 移除（count 0），不是仅隐藏。
- → 08 §3 的「下拉不关闭 → 第 2 次点击再插一次」是**理论风险，当前不是现实风险**。双插中止仍保留（防止重绘竞态与未来改版），但不必把它当成常见路径。
- 也说明「点一次后候选消失」可作为「点击已生效」的弱信号，但不能替代 §4 的回读。

## 4. `.name` 文本与候选排序

- 30 个采样候选（3 词 × 前 10）**全部**带前导 `#`；`data-topic.name`（回读结果）全部**不带** `#`。
- 归一化规则（去 `#` → strip → 折叠空白 → casefold）两边都兼容，保持原决议即可。
- 三个请求词的候选前 5 项（真机排序）：

| 请求词 | 1 | 2 | 3 | 4（全等） | 5 |
|---|---|---|---|---|---|
| `旅行` | `#旅行pov` | `#旅行中的非遗体验` | `#旅行镜头里的爸妈` | **`#旅行`** | `#旅行箱` |
| `美食` | `#美食掌门人` | `#美食特种兵` | `#美食兴趣班之有手就会` | **`#美食`** | `#美食教程` |
| `穿搭` | `#穿搭bot` | `#穿搭暗号对一下` | `#穿搭经验howto` | **`#穿搭`** | `#穿搭灵感` |

- 精确项**三次都排第 4**，与热度排序一致；「首项不等即判无候选」会三次全错。08 §2 的「顺序全扫全部渲染项」是必需的。

## 5. 对 08 的决议修订

| 08 条目 | 原决议 | 23 取证后 |
|---|---|---|
| §6 输入前复位 | 不采用；仅当第 2+ 个下拉不出现再补最小动作 | **确认不采用**；实测无动作即可连续插入，不补 `Control+End` |
| §4-1 回读作用域 | 编辑器根 `div.tiptap[role=textbox]` 内 | **确认并强化**；整页会把预览镜像算进来（2×） |
| §4-5 成功判据 | 新增 1–2 个且 name 全等 | **改为恰好 1 个**；>1 = `topic-multi-insert` |
| §1 中止阈值 | 新增 >2 → 中止 | **改为 >1 → 中止**（编辑区作用域） |
| §3 候选就绪 | 轮询 200ms、每轮重扫 | 补充：必须等 `item_count > 0`，容器可见时可能为 0 项 |
| §3 双插代价 | 下拉不关闭 → 第 2 次点击再插 | 降级为**理论风险**；实测关闭 0–2ms，容器直接从 DOM 移除 |

## 6. 本次未覆盖

- 只测了图文编辑器（视频发布页的正文/预览结构未测）；单账号、单次会话、3 个话题。
- 未测「连续插入第 4–10 个」；按上限 10 个的极端场景仍需实现侧用同一判据兜底。
- 未测中文输入法/粘贴路径（本票只测 `keyboard.type`）。
- 锚点在点击后出现的精确毫秒未做 50ms 级采样（本脚本在点击后 400ms 取快照；08 §4 的 50ms/1s 窗口未受影响）。
- 预览镜像节点的出现时机未单独计时；限定编辑区后不影响判据。

## 7. 脱敏原始片段

```json
{
  "anchor_count": 6,
  "editor_anchor_count": 3,
  "preview_anchor_count": 3,
  "editor_chain": [
    "a.tiptap-topic[contenteditable=false]",
    "p",
    "div.tiptap.ProseMirror[role=textbox][contenteditable=true]"
  ],
  "preview_chain": [
    "a.tiptap-topic",
    "p",
    "div.info",
    "div.scroll-container",
    "div.image-area",
    "div.image-container",
    "div.image-preview",
    "div.preview-container"
  ],
  "editor_text_after_3": "#旅行[话题]#\u00a0#美食[话题]#\u00a0#穿搭[话题]#\u00a0",
  "dropdown_close_ms": [2, 0, 1],
  "items_ready_ms": [479, 432, 567]
}
```
