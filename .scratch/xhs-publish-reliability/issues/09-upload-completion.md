# 09 — 上传完成判定：图文逐张 + 视频就绪

Status: resolved
Type: grilling
Blocked by: 02, 05, 03
Assignee: wayfinder-session (opencode)

## Question

决定图文与视频“上传完成”的判定。需要确认：

1. **图文**：是否改为逐张上传 + 计数等待（`.img-preview-area .pr` 数量达标）？单张超时多久？某张失败时中止整单还是继续？
2. **与现状关系**：现在是“一次塞全部图片 → 等标题框出现”。新判定是取代还是并存（标题框出现 ≠ 全部上传完成）。
3. **视频**：以“发布按钮可点”为主信号、文案（`上传成功/分辨率/100%`）为辅，还是反过来？现以文案为主、标题框出现作兜底，二者都可能在转码未完成时提前通过。10 分钟上限是否保留。
4. **预算交互**：两处等待是否用 `clamp_ms`。
5. **失败补救**：`handle_upload_error` 是死代码（`main.py:1046`，无调用点）。是补一条真正生效的重传路径，还是删除并改为明确失败。

产出：状态判定表（图文/视频 × 观测 × 动作）+ 超时与重试策略 + 与 03 预算的接口。

## Evidence from 02（真机取证）

- 视频：`xhs-publish-btn` 的 `submit-disabled` 从 `true`→`false` 即就绪信号（965KB 约 12s，采样到 87s 稳定）。`is-publish` 在 t=0 为 `false`。
- **「标题框出现」会提前 9 秒**判定成功；**预览区出现「分辨率」是画质建议警告**，处理期间就在 → 现有关键词判据会提前成立。
- 图文：上传 1 张后 `.img-preview-area .pr` = 1；N>1 计数与单张上限未验证。
- 编辑器内 `input[type=file]` 共 3 个（含封面等），选错 input 的风险需在方案中约束。

## Answer

**决议**：图文与视频共用一条原则——**素材就绪是填元数据的前置闸；闸门判据各自只认一个结构信号；任何一次失败整体中止（exit 1，点击前、确定未发布）**。不重传、不降级少图、不把失败伪装成超时。

### 0. 状态判定表（图文 / 视频 × 观测 × 动作）

| 内容 | 观测 | 动作 | 退出码 |
|---|---|---|---|
| 图文 | 第 i 张已派发，`.img-preview-area .pr` 计数 ≥ i+1 | 等 1s，派发第 i+1 张 | — |
| 图文 | 派发后 60s（clamp 到预算）计数未到 i+1 | **中止整单**，`unusable`，文案带 第 k/共 N 张 + 已尝试顺序 + 未点击发布 | 1 |
| 图文 | 计数 == N，复检一次 DOM 静默（500ms 无变更 / 上限 3s）后仍 ≥ N | 进入 `fill_meta` | — |
| 图文 | 静默后计数 > N | 记 warning，**继续**（多图可事后人工删，abort 会白扔整单） | — |
| 图文 | 静默后计数 < N | 继续等到 60s 窗口耗尽 → 中止 | 1 |
| 视频 | 谓词满足（`is-publish != "false"` 且 `submit-disabled != "true"`，属性缺失视为通过） | 进入 `fill_meta` | — |
| 视频 | 600s（clamp 到预算）谓词未满足 | **中止**，`unusable`，文案带禁用原因 | 1 |
| 两者 | 预算耗尽 | 用 03 的 pre-click 文案（`发布超时（15 分钟）：尚未点击发布，未发布任何内容`），不是「处理超时」 | 1 |
| 两者 | 上传 input 找不到 / 多义 / `set_files` 抛错 | **立即中止**，`missing` / `unusable`，**不等待** | 1 |
| 两者 | `--no-publish` | 仍过就绪闸，然后停 | 0 |

> 退出码不按「第几张」「图文/视频」分叉：1 是给调度器的机器契约——**确定未发布、可无条件重跑**。

### 1. 图文：逐张 + 计数 + 静默复检

- **逐张派发**（不批量）。理由是对上游一次真实事故的采纳：多图快塞会**静默丢图**（`xpzouying/xiaohongshu-mcp@44061fd`「逐张等待图片上传完成，避免多图上传时图片丢失」）；人工路径本身也是增量的（先首图、再用「+上传更多」补）。
- 输入框解析（**对 05 第 4 行的修订**）：
  1. 首张：空状态唯一 `div.upload-content input.upload-input`，`count` 必须 == 1；
  2. 第 2 张起：点 `.img-preview-area .entry`（「+」瓦片）→ `expect_file_chooser()` → `set_files([1 张])`，把「哪个 input」交给真实用户手势；
  3. 备选阶梯（仅当 2 被真机否定）：`.img-upload-area` 容器内 `accept` 匹配图片且 `count == 1` 的 input；
  4. **禁止**照抄上游的「`accept` 匹配不上就取 `inputs[0]`」——上游自己在 issue #868 承认这会把视频 input 当图片 input、静默不生效后表现成 60s 超时。
- 判据：`.img-preview-area .pr` 计数 `>= i+1`，轮询 500ms，单张窗口 **60s**（`clamp`）；张间 `sleep 1s`。
- 收口：最后一张之后再等**一次 DOM 静默**（复用 06 的定义：500ms 无变更、上限 3s），静默后复检计数——这是为了吸收「预览数到位 ≠ 服务端收齐」的窗口（上游 PR #658 描述的「点了发布，页面说图片还未上传成功」竞态，该 PR 至今未合）。
- 不补传：重传同一张有 **N+1** 风险（可能一张都没少、只是计数慢），且失败后重跑代价很低。

### 2. 视频：复用 03 的发布按钮谓词

- 谓词**只有一份**：`xhs-publish-btn` 可见 + `is-publish != "false"` + `submit-disabled != "true"`。09 与 03 共用同一个 helper，**两个窗口**：09 就绪窗 `min(600s, 剩余预算)` / 1s 轮询（`fill_meta` 之前）；03 ARM 窗 `min(60s, 预算)`（点击之前）。
- 必须拆两段：02 实测 965KB 视频 12s 就绪，大视频远超 60s；只留 ARM 会让大视频稳定撞 exit 1。
- **删除**：`['上传成功','分辨率','重新上传','编辑封面','已上传','已选择','100%']` 关键词扫描、`div.stage` 二次扫描、「标题框出现就放行」。02 已证「分辨率」是画质建议警告（处理期间就在）、标题框提前 9 秒出现。
- 10 分钟上限**保留**（`min(600s, 预算)`）。

### 3. 预算接口（对 03 契约的落实）

1. 就绪窗用 `budget.clamp_seconds(600)` / `budget.clamp_ms(60_000)`；每轮先 `check_pre_click()`——预算耗尽抛 03 的 pre-click 文案。
2. 上传段的其它固定超时一并 `clamp_ms`：`upload_input.wait_for(state="attached")`、`page.wait_for_url(publish_url)`（否则 60s/张之外还有裸超时在偷偷超支）。
3. **不为「填元数据 + 发布」预留分段配额**：保持单一 deadline 贯穿（`PublishTimeoutBudget` 的设计前提）。要缓解「就绪吃满预算」应调总预算，不在 09 切蛋糕。

### 4. 死代码与失败面

- 删除 `handle_upload_error`（`main.py:1033`）：无调用点，且选择器 `div.progress-div [class^="upload-btn-input"]` 是 TikTok 的结构、小红书现网不存在。
- 不新增重传路径。失败面收敛为 05 的两类即时错误（`missing` / `unusable`），**不再出现「等 60s 才说是选择器问题」**。
- 上游把视频 `MustSetFiles` 失败变成 panic → 工具层转「内部错误」；我们相反，必须是结构化错误 + 「未点击发布」+「未发布任何内容」。

### 5. 与上游的偏离（按 charter 记录）

| # | 上游 | 本决议 | 理由 |
|---|---|---|---|
| 1 | 一批/固定 sleep（历史）→ 逐张计数 | 逐张 + 计数 + 静默复检 | 上游真实丢图事故；且其「预览数=N 即完成」有已知假完成竞态 |
| 2 | `inputs[0]` 兜底取 input | 禁止 `.first`，走「+」瓦片 file chooser / 容器唯一化 | 上游 issue #868 自承会把视频 input 当图片 input |
| 3 | 视频就绪窗与点击前等待合为一段（无预算概念） | 拆成 09 就绪窗 + 03 ARM 窗，各自 clamp | 我们有 15 分钟总预算；合成一段会让大视频必然失败 |
| 4 | 文案关键词判「上传成功」 | 全删，只认结构信号与 URL | 02 证关键词会提前命中；04 已定不扫文案 |
| 5 | 上传失败只能等窗口耗尽 | 失败面提前为 `missing`/`unusable` | 不重传 = 等下去没有收益，只浪费时间 |

### 6. 需真机验证（→ 新工单 24）

1. `.pr` 是「选中文件时」还是「上传完成时」出现？上传中每项有无进度态（`aria-busy` 只见 `false`、未见 `true`）？
2. 点 `.img-preview-area .entry` 是否触发 file chooser？若否，编辑器内两个同 `accept` 隐藏 input 的归属容器分别是什么？
3. 同一文件重复派发是否 N+1？拖拽排序是否影响 `.pr` 计数可靠性？
4. 视频失败/中断是否有结构信号（`input.upload-input` 是否复现、「重新上传」是独立节点还是文本）？
5. 单张 60s 对大图（如 20MB HEIC）是否偏紧。

> 置信度：逐张丢图=**上游代码 + 提交说明**；`.pr` 计数=N=**实机（单张）**、N>1=**仅推断**；视频谓词=**实机**；`.entry`→file chooser=**仅推断（待 24）**；静默复检=**仅推断（防御性）**。

## Revision 2026-11-11（来自 24 真机取证）

24 证明 `.pr` **在文件选中时**插入、上传完成前一直带 `.mask.uploading`。上文的「计数 + DOM 静默」会提前放行，按 24 修订：

1. **§1 判据改为每项完成态**：第 i 张就绪 = `.img-preview-area .pr` 数量 ≥ i+1 **且** `tiles[i].querySelector('.mask.uploading') == null`。上传中瓦片结构为 `.mask.uploading > .progress-container > svg.spinner-red`；完成时换成 `.mask.hover-mask`。
2. **删除 `aria-busy` 作进度信号的设想**：`.img-container[aria-busy]` 在选中/上传中/完成/失败全程为 `"false"`，无 `true`；页面也没有百分比节点。
3. **§1 输入阶梯确认成立**：`.entry` 确实触发 filechooser，指向 `.img-list .top input[type=file][multiple]`；备选选择器就用它（不要用同容器的 `:not([multiple])`，其用途未取证）。空状态首图仍是 `div.upload-content input.upload-input`。
4. **重复派发同一文件 = 新瓦片（N+1）**，页面不去重；拖拽只改顺序不改数量；删除走 `.mask .close-btn`，计数 −1。计数可靠，但语义是「已接收」，不是「已上传」。
5. **§2 视频加即时失败**：`div.fail`（class 恰为 `fail`，挂在 `.publish-page-content-media-content`）或 `.video-container-loading-text` 出现 → 立即 `unusable` exit 1，不必等 600s。`input.upload-input` 不会「复现」（全程 1 个），`submit-disabled` 在失败态保持 `true`，二者都不能当失败信号。
6. **60s 余量**：20MB PNG 本机 25.5s 完成（1 MiB 分片 ×3 并发），慢速时段 >40s 未完成 → 保留 60s + clamp，不缩短。静默复检保留为服务端收齐的防御。

详见 [24 — 多图上传时间线取证](./24-multi-image-timeline-evidence.md)。
