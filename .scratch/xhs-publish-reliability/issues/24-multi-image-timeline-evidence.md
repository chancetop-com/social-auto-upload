# 24 — 多图上传时间线取证（`.pr` 时序 / 第 2 张入口 / 视频失败态）

Status: resolved
Type: task
Blocked by: —
Assignee: wayfinder-session (opencode)

## Question

09 的判定表里有五条**未经真机验证**的假设，其中 1–2 会直接改判据（`count == N` 够不够、第 2 张怎么派发）。用有效登录态在图文/视频发布页**只上传、不发布**，逐项取证：

1. **`.pr` 出现时机**：`.img-preview-area .pr` 是在「文件选中」时增加，还是「该张上传完成」时增加？上传中每项有没有完成态信号——`.img-container[aria-busy]` 是否会出现 `true`（现只见过 `false`）、内部是否有进度百分比节点？
2. **第 2 张入口**：点 `.img-preview-area .entry`（「+」瓦片）是否触发 `filechooser`？若不触发，编辑器状态里两个同 `accept` 的隐藏 `input[type=file]` 分别属于哪个容器/入口（给出可唯一化的父节点选择器）；并记录「同一文件重复派发」是否让计数变成 N+1。
3. **计数可靠性**：拖拽排序是否改变 `.pr` 顺序或数量；删除一张后计数是否减 1。
4. **视频失败态**：坏文件 / 断网 / 大文件中断时，页面有没有**结构**信号（`input.upload-input` 是否复现、「重新上传」是独立按钮节点还是纯文本、`submit-disabled` 是否回退到 `true`）？
5. **60s 余量**：单张 20MB 级别图片（HEIC/PNG）在真实网络下的上传耗时分布，判断 60s 是否偏紧。

## 约束

- **不发布**（与 02 同口径）：只到「素材就绪 + 填元数据」，`--no-publish` 或脚本直调上传段。
- 复用 `research/capture_live_dom.py` 的取数方式，按 500ms 采样时间线落 `research/raw/`，产出命中表。
- 结论写回 `## Answer`，并标注 **代码明确 / 实测 / 仅推断**。

## 影响

- 第 1 项若证明「`.pr` 选中即出现」，则 09 §1 的「计数 + DOM 静默」需升级为「每项完成态」判据。
- 第 2 项决定 09 §1 的输入框阶梯是否成立（`.entry` → file chooser 为首选）。
- 第 4 项若给定结构信号，可把视频「白等 10 分钟」缩短为即时失败（09 已把该能力留给本票）。

## Answer

取证时间：2026-11-11；环境与 02 同口径（headless Chromium 156，patchright，`channel=chromium`、`zh-CN`、stealth init script、UA 去 `HeadlessChrome`）；账号复用 `cookies/xiaohongshu_180.json`（登录态有效）；**只上传、不发布**，未填写标题/正文。
脚本：`research/probe_multi_image.py`、`research/probe_entry_input.py`、`research/probe_video_failure.py`、`research/probe_video_badfile_dom.py`、`research/gen_large_image.py`；原始时间线在 `research/raw/t24-*.json|png`。

### 0. 结论（先看这里）

1. **`.pr` 在「文件选中」时插入，不是上传完成时**。插入即带 `.mask.uploading`，一直持续到该张上传完成才换成 `.mask.hover-mask`。→ 09 §1 的「`.pr` 计数 ≥ i+1」**只能证明已接收，不能证明已上传**，必须升级为「每项完成态」。
2. **每项完成态有结构信号**：`tile.querySelector('.mask.uploading') == null`（上传中该节点存在，内含 `.progress-container` + `svg.spinner-red`；没有百分比文本、没有 `aria-valuenow`）。
3. **`.img-container[aria-busy]` 全程是 `"false"`**（上传中、完成、失败都是），不能当进度/完成信号。
4. **`.entry` 触发 filechooser**，指向 `.img-list .top input[type=file][multiple]`。编辑器里两个同 `accept` 的图片 input 都在 `.img-list > .top` 下，**只能靠 `[multiple]` 区分**。
5. **同一文件重复派发 = 新瓦片（N+1）**；拖拽只改顺序、不改数量；删除走 `.mask .close-btn`，计数 −1。
6. **视频坏文件有结构失败态 `div.fail`**（`submit-disabled` 保持 `true`，`input.upload-input` 不会「复现」——它一直在）；「重新上传」是独立可点节点 `span.video-plugin-title-action`，可恢复。
7. **20MB PNG 本机 25.5s 就绪**；慢速时刻同一文件 >40s 仍未传完。60s 可用，但余量不算宽。

### 1. `.pr` 出现时机与每项完成态（问题 1）

| 文件 | `.pr` 出现（自派发） | 首个上传 PUT | `.mask.uploading` 消失 | 结论 |
|---|---|---|---|---|
| 20.0 MiB PNG（2600×2688） | **4.07s**（插入即 `mask uploading`） | 4.64s | **25.5s** | `.pr` 早于第一个 PUT |
| 1.4 MiB PNG（700×700） | **0.20s** | 0.40s | 2.1s | 同上 |

- **实测**：`.pr` 插入的 MutationObserver 记录在第 4.07s（页面时钟），上传建单 POST 在 4.11s、首个分片 PUT 在 4.64s → 瓦片先于任何上传请求出现，属「选中即插入」。
- **实测**：上传中瓦片结构为 `.pr > .img-container > (.format-img > img[src=blob:], .img-idx, .mask.uploading > .progress-container > svg.spinner-red)`；完成时整段被替换成 `.mask.hover-mask`（含 `.close-btn.hoverShow`、`.image-editor-control`）。
- **实测**：`.img-container[aria-busy]` 在上传中采样到 `"false"`、完成/失败也是 `"false"`；**从未出现 `true`**。
- **实测**：没有进度百分比节点（无 `aria-valuenow`、无 `NN%` 文本）；`.progress-container` 只有一个旋转 svg。
- **仅推断（实现建议）**：每项完成谓词

  ```js
  const tiles = document.querySelectorAll('.img-preview-area .pr');
  tiles.length >= i + 1 && !tiles[i].querySelector('.mask.uploading')
  ```

  以瓦片元素为单位判断，不要用全局 `.mask.uploading` 计数（多张并发时无法定位第 i 张）。
- 09 §1 的「最后一张后 DOM 静默」可以保留为廉价防御，但**不再承担正确性**。

### 2. 第 2 张入口（问题 2）

- **实测**：`.img-preview-area .entry`（「+」瓦片，可见）点击**确实触发 filechooser**；chooser 元素是 `input[type=file]`，`accept=".jpg,.jpeg,.png,.webp"`，`multiple=true`，父链 `div.top < div.img-list < div.publish-page-content-media-content`。
- 用 document 捕获期 click 监听器复核：被点的就是 `multiple=true` 的那个 input（`.entry` 直接 `input.click()` 到它）。
- 编辑器内 file input 清单（`实测`）：

| # | accept | multiple | 父容器 | 用途 |
|---|---|---|---|---|
| 0 | `.jpg,.jpeg,.png,.webp` | **true** | `.img-list > .top` | 批量图片；**`.entry` 用的就是它** |
| 1 | `.jpg,.jpeg,.png,.webp` | false | `.img-list > .top` | 单图 input（同容器，无法靠父节点区分） |
| 2 | `.pdf,.doc,.docx,.ppt,.pptx` | false | `.file-relation-container` | 文档，与图片无关 |

- 可唯一化的选择器（`实测`）：
  - 空状态首图：`div.upload-content input.upload-input`（`multiple=true`，`accept` 为图片）。
  - 编辑器「+」同款：`.img-list .top input[type=file][multiple]`。
  - 单图 input：`.img-list .top input[type=file]:not([multiple])`（**不要**用它做图片兜底，其真实用途未取证）。
- 09 §1 的阶梯**成立**：`.entry` → filechooser 可作首选；备选应写成 `.img-list .top input[type=file][multiple]`，而不是宽泛的「容器内唯一 input」。禁止 `inputs[0]`/`.first` 仍然成立（第 3 个 input 是文档）。
- **实测**：同一文件再次经 `.entry` 派发 → 计数 2 → 3，**N+1 确认**（页面不做去重，每次派发都是一个新瓦片）。

### 3. 计数可靠性（问题 3）

| 操作 | 观测 | 结论 |
|---|---|---|
| 拖拽第 1 张到第 2 位 | 顺序 `[A,B,C] → [B,A,C]`，计数 3 | **只改顺序，不改数量**（`.pr[data-draggable="true"]`） |
| 删除第 1 张（hover → `.mask .close-btn`） | 计数 3 → 2 | **删除可靠 −1** |
| 重复派发同一文件 | 计数 2 → 3 | **N+1** |

→ 计数本身可靠，但它表达的是「已接收的图片集合」，**不等于「已上传完成」**（见 §1）。

### 4. 视频失败态（问题 4）

**坏文件（64 KiB 随机字节 + `.mp4` 后缀）**：

- **实测**：派发后 ~0.5s 就进入编辑器形态（发布按钮出现、`submit-disabled="true"`、标题框出现、上传区消失）；~1.0s 出现失败态；40s 内保持稳定。
- 结构信号（`实测`）：
  - `div.fail`（class 恰为 `fail`）挂在 `.publish-page-content-media-content` 下，内含 `.name`、`.operator > .stage`（失败原因文案）。
  - `div.video-container-loading-text` 同时存在（文案「视频上传失败，请重新上传」）。
  - `div.stage` 的文本是「上传失败 + 具体原因」。
- **纠正 09 的假设**：`input.upload-input` **不会「复现」**——空状态、上传中、失败、成功它都恒为 1 个，不能作失败/恢复信号。
- `xhs-publish-btn[submit-disabled]` 在失败态保持 `"true"`（永不转 `false`）。「处理中超时」与「失败」只能靠 `div.fail` 区分，**不要靠 submit-disabled**。
- **实测**：「重新上传」是 `span.video-plugin-title-action`（带 svg 图标；父级 `div.video-plugin-title`），是**独立可点控件**，不是裸文本。点击它触发 filechooser（`input.upload-input`，`accept=.mp4,.mov,.flv,.f4v,.mkv,.rm,.rmvb,.m4v,.mpg,.mpeg,.ts`，`multiple=false`）；选入 `demo.mp4` 后 30s 内 `submit-disabled` 转 `"false"`，失败态清除 → **恢复路径有效**。

**断网中断（965 KiB `demo.mp4`，上传限速 60 KiB/s，4s 时切离线 12s）**：

- **实测（切点未精确证明）**：观察到 3 个 spectrum PUT；12s 离线窗口结束后未出现任何失败 UI，最终 `submit-disabled` 在 ~19s 转 `"false"`。表现与「SDK 透明重试」一致，无需用户操作。
- **未验证**：大文件（数十 MB）真正传到一半时中断是否会走 `div.fail`，还是无限重试。本票没有足够大的视频样本，留作后续（见 §5 的边界）。

→ 对 09 的直接含义：视频就绪窗可以加一条**即时失败**：`div.fail` 出现（或 `video-container-loading-text` 出现）→ 立即 `unusable` exit 1，不必等满 600s。这是结构信号、零中文依赖。

### 5. 60s 余量（问题 5）

| 文件 | 本机上传耗时（派发→完成） | 备注 |
|---|---|---|
| 20.0 MiB PNG | **25.5s** | 21 个分片（20×1 MiB + 4 KB），3 并发，单片 2–4s |
| 20.0 MiB PNG（同日另一时段） | **>40s 仍未完成** | 单片 5–10s（家庭上行波动），32s 时仍有 3 片在传 |
| 1.4 MiB PNG | 2.1s | 单片 |

- **实测**：上传走 1 MiB 分片、约 3 并发；页面加载时另有 5 MiB speed-test PUT（与本次判据无关，但会占上行）。
- **判断（仅推断）**：60s 对 20MB 不是「必然偏紧」，但余量依赖上行带宽；慢速时刻已经逼近 40s+，再叠加缩略图/服务端处理，**建议保留 60s + clamp，不缩短**；若以后允许更大图片（>30MB）需要重新评估。
- 图片完成（`mask.uploading` 消失）与最后一个分片完成基本同一时刻（25.5s vs 末片 ~24.8s），说明该信号覆盖「客户端上传完成」，不覆盖「服务端收齐」的极端竞态 —— 09 的静默复检仍有防御价值。

### 6. 写回 09 的修订（已执行）

- §1 判据：`计数 ≥ i+1` → **`计数 ≥ i+1 && tiles[i] 无 .mask.uploading`**（每项完成态）；删除把 `aria-busy` 当进度信号的设想。
- §1 输入阶梯：保留 `.entry → filechooser`；备选选择器明确为 `.img-list .top input[type=file][multiple]`。
- §2 视频：就绪窗增加 `div.fail` 即时失败，不再只能等 600s。
- §2 视频：`input.upload-input` 不是失败信号；`submit-disabled` 不区分「处理中/失败」。

### 7. 置信度汇总

| 结论 | 置信度 |
|---|---|
| `.pr` 选中即出现、`.mask.uploading` 是每项完成信号 | **实测**（20MB + 1.4MB 两条时间线） |
| `aria-busy` 恒为 false、无百分比节点 | **实测** |
| `.entry` → chooser → `[multiple]` 图片 input | **实测**（chooser + click 捕获双证） |
| 重复派发 N+1 / 拖拽只改序 / 删除 −1 | **实测** |
| 视频坏文件 `div.fail` + `submit-disabled=true` + 可恢复重传 | **实测** |
| 断网中断 → 透明重试、无失败 UI | **实测，切点未精确证明** |
| 大文件真中断的失败面 | **未验证** |
| 60s 余量 | **实测样本 + 仅推断的建议** |

### 8. 原始数据

`research/raw/t24-image-report.json`、`t24-timeline-first.json`、`t24-timeline-second.json`、`t24-timeline-dup.json`、`t24-entry-input.json`、`t24-video-report.json`、`t24-video-badfile-dom.json`、`t24-*.png`（未脱敏，勿入 git）。

