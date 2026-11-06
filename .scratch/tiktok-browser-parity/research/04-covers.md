# 04 — 视频与图片封面（TikTok Studio 网页端）

Status: research
Date: 2026-11-05
Scope: 只读调研。未启动浏览器、未登录、未修改业务代码。

## Question

TikTok Studio 网页端如何选择视频/图片封面？具体回答：

1. 视频封面帧选择：是否存在时间轴/帧选择器，如何定位到指定毫秒对应的帧。
2. 自定义封面上传：入口、支持格式与尺寸、与现有 `thumbnail_path` 流程的关系。
3. 图片帖封面：是否通过选择第 N 张图作为封面，页面表现是什么。
4. 封面操作与定时发布、AI 标识、品牌声明的先后顺序是否有限制。
5. 上传完成前是否可以设置封面。

## 结论速览

- **视频有帧选择器**：TikTok Studio 的 Cover 编辑器包含 `FramePicker`，由 11 帧胶片、可拖拽指示器、前后帧按钮组成；点击胶片会按比例映射到毫秒。它没有数字/毫秒输入框，精度受胶片宽度限制（约 `时长/429` 毫秒/像素），不是逐帧精确。
- **视频也支持自定义封面上传**：`Upload cover` 接受 JPEG/PNG/JPG，最小 324×432 px，最大 50 MB，按 3:4 裁剪；它与帧选择是互斥的 `sourceType`，最终都变成一张 `cover_uri` 图片。
- **图片帖没有“第 N 张”选择器**：网页端封面固定为第 1 张，缩略图上有 `Cover` 徽标；要换封面只能把目标图片拖到第 1 位，这会改变图片浏览顺序。移动端 App 可以选任意一张，网页端不行。
- **没有发现封面与定时/AI/品牌之间的硬性顺序限制**，它们都是发布表单上的独立字段；但封面必须在最终点击 `Schedule`/`Post` 之前设置好，视频则必须等处理完成。
- **上传完成前不能可靠地设置视频封面**：产品 UI 字符串明确写 “You can choose a video cover after processing is complete.”，封面区域会显示 `Uploading...` / `Loading...` / `Processing...`。

## 证据强度说明

本文件使用四类标注：

- **【官方文档】**：TikTok Help Center、TikTok Developer Docs、TikTok Creator Academy。
- **【开源实现】**：`wkaisertexas/tiktok-uploader` 与本仓库现有代码。
- **【产品前端代码】**：TikTok Studio 公开的线上 JS bundle（2026-11-05 抓取）。这不是官方文档，但比“推断”强得多；bundle 会随版本变化，选择器和文案可能漂移。
- **【仅推断】**：由代码/文档推导，未直接验证。
- **【未能确认】**：公开资料不足，明确不编造。

---

## Findings

### F1. 视频封面有两个来源：视频帧、上传图片

**【产品前端代码】**

TikTok Studio 的封面组件把两种来源建模为同一个枚举：

```js
CoverSourceType = { FRAME: "frame", UPLOAD: "upload" }
默认值 = { time: 0, sourceType: "frame", uploadedImage: undefined }
```

`CoverPicker` 同时渲染两个子组件：

- `ImageUpload`：左侧的 `Upload cover` 上传区；
- `FramePicker`：右侧的胶片时间轴。

选择上传图片会把 `sourceType` 切到 `upload`；点击胶片会把 `sourceType` 切回 `frame`（`uploadedImage` 可能仍留在组件 state 中，但 `sourceType` 决定它不生效）。因此**两者不能同时生效，最后一次操作获胜**。

这解释了现有 `thumbnail_path` 与未来“按毫秒选帧”的关系：它们不是叠加关系，而是二选一。

### F2. 帧选择器确实存在：11 帧胶片 + 指示器 + 前后按钮

**【产品前端代码】**

`FramePicker` 的关键结构（从线上 bundle 还原）：

- 胶片画布：`width = 39 * frameCount`，默认 `frameCount = 11`，即 **429 px**；高度 **52 px**。
- 胶片上均匀取 11 个时间点：
  ```js
  timestamps[i] = min(floor(i / (frameCount - 1) * duration), duration - 1)
  ```
  即第 0、10%、20% … 100% 的位置。
- 一个宽 52 px、高 69 px 的指示器覆盖在胶片上，可左右拖动。
- 指示器下方有两个无文字按钮：上一帧 / 下一帧，按 `frameDuration` 步进（`frameDuration` 由调用方传入，具体值未能确认）。
- 指示器 hover 时显示 `mm:ss` 格式的时间提示（不是毫秒）。
- 点击胶片任意位置会立即跳转；拖动指示器会连续更新时间。

第三方教程也描述了同样的桌面端交互：“thumbnail slider below the video preview”“drag the selector across your video’s timeline”“system automatically captures several frames for you to choose from”。【开源实现/第三方教程】

### F3. 指定毫秒的映射方式与精度

**【产品前端代码 + 仅推断】**

点击胶片的换算逻辑是：

```js
// B = 39 * frameCount；默认 11 帧时 B = 429
ratio = clamp((clientX - canvas.left) / B, 0, 1)
time_ms = floor(ratio * duration_ms)
```

所以要落到目标毫秒，点击横坐标应为：

```text
x = target_ms / duration_ms * canvas_width
```

**精度上限**约为 `duration_ms / 429`（每像素对应的毫秒数），再加 1 px 的取整误差：

| 视频时长 | 每像素约代表 | 理论最大误差 |
|---:|---:|---:|
| 15 s | 35 ms | ±35 ms |
| 30 s | 70 ms | ±70 ms |
| 60 s | 140 ms | ±140 ms |
| 3 min | 420 ms | ±420 ms |
| 10 min | 1399 ms | ±1399 ms |

拖动指示器的换算略差：可拖动距离是 `429 - 52 = 377 px`，每像素约 `duration/377` 毫秒。

**结论：网页端可以“按毫秒定位”，但不是逐帧/毫秒精确。** 没有数字输入框，也不能直接输入 timestamp。若产品契约要求“精确到指定毫秒”，网页帧选择器不足以作为强保证。

一个未验证的思路：用 `dispatchEvent` 构造带小数 `clientX` 的鼠标事件，理论上可以提高映射精度；但这依赖 React 事件与内部状态，属于实现 hack，不建议写进契约。【仅推断，未能确认】

### F4. 选中的帧最终是“抓帧成图片”，不是把 timestamp 发给服务端

**【产品前端代码 + 仅推断】**

线上 bundle 中，视频封面在发布参数里的表示是 `cover_info.cover_uri`（它出现在“编辑已发布内容”的字段 diff 逻辑中），没有发现 `video_cover_timestamp_ms` 或 `cover_timestamp` 这类字段。`FramePicker` 通过 `captureCurrentFrame({ canvas, timestamp, frameWidth, frameHeight })` 把当前帧画到 canvas，再进入上传流程。

因此更可能的情况是：**网页端在浏览器里把选中帧截成图片，作为 `cover_uri` 上传**；服务端收到的是图片，而不是毫秒值。这样：

- 网页端和自定义上传最终走同一条“封面图片”通道；
- 网页端无法保证与 Content Posting API 的 `video_cover_timestamp_ms` 完全同帧；
- 如果必须精确到某一毫秒，更稳的做法是本地用 ffmpeg 抽帧，再作为自定义封面上传（见“可行性结论”）。

此条中的“抓帧后上传”是根据组件职责与提交字段的推断，未在真实账号中抓包验证。

### F5. 自定义封面上传：入口、格式、尺寸

**【产品前端代码；官方文档确认入口存在】**

官方 Help Center 的 TikTok Studio 功能列表写的是：“Cover: Select a cover image for your video.”，确认网页上传表单有 Cover 项，但没有给自定义封面的格式/尺寸细节。【官方文档】

线上组件给出的实际约束：

- `accept = image/jpeg, image/png, image/jpg`
- 最小尺寸错误文案：`Upload a file that is at least 324 × 432 pixels`
- 文件大小错误文案：`File size can’t exceed 50 MB`
- 不支持格式提示：`File type not supported`
- 编辑器有 `Preview in profile (4:3)` 预览，说明封面按 **3:4 竖版**设计/裁剪（324×432 正是 3:4）
- 上传后出现 `Uploaded cover image` 预览，可点 `Delete uploaded image` 删除并回到帧选择

第三方教程给出的推荐尺寸是 540×720（3:4），并描述“上传后用裁剪框调整，再点 Confirm”。【开源实现/第三方教程】这与 324×432 的最小尺寸和 3:4 比例一致；更高分辨率（如 1080×1440）应也可用，但**官方未给推荐值，未能确认**。

注意：官方文档对**移动端**的封面说明只写了“选一帧”，没有承诺所有账号都有自定义上传；网页端则明确有 Cover 项。自定义上传的可用性仍可能受账号/地区/灰度影响。

### F6. 上传完成前不能设置视频封面

**【产品前端代码；与现有流程一致】**

上传页的 Cover 区域有三段状态文案：

- `uploadingEdit_postPage_coverStatus_upload` = `Uploading...`
- `uploadingEdit_postPage_coverStatus_load` = `Loading...`
- `uploadingEdit_postPage_coverStatus_process` = `Processing...`

以及两条说明：

- `uploadingEdit_postPage_coverExplain_process` = **“You can choose a video cover after processing is complete.”**
- `uploadingEdit_postPage_coverExplain_edit` = **“You can edit the cover after your video is uploaded.”**

这说明封面控件在视频处理完成前不可用/不可靠。第三方教程中“上传时就可以顺手填封面”的说法与此冲突，应以产品文案为准；**建议实现时等 Cover 状态结束、`Edit cover` 可点后再操作**。

### F7. 图片帖封面：网页端固定第 1 张，不能直接选第 N 张

**【产品前端代码；移动端官方文档对照】**

网页端图片帖的封面渲染逻辑非常直接：

```js
isCover: 0 === t   // 只有索引 0 的图片显示 Cover 徽标
```

- 第 1 张缩略图上渲染 `Cover` 标签（`tiktokStudio_uploadPhotos_details_coverPhoto_label` = `Cover`）。
- 图片网格支持拖拽排序（文案：“Drag and drop to reorder.”）。
- 没有 “Set as cover” 按钮、没有封面下拉框；点击图片打开的是预览/替换/删除弹窗，不是“设为封面”。
- 提交 payload 中也是 `image_post_content.cover: photos[0]`，即**服务端收到的封面就是第一张**。
- 相机/上传入口的图片格式文案：`JPG, JPEG, PNG, and WebP`；数量上限文案是动态的（API 侧为最多 35 张），网页端具体上限未能确认。

对比移动端官方文档：【官方文档】

> 图片帖在 Post 屏幕有 `Edit cover`，可以滑到任意一张图片，拖动裁剪框，然后 Save。

所以在移动端“第 N 张作为封面”是可行的；**网页端不可行**（至少当前 bundle 如此）。若必须让第 N 张当封面，只有两条路：

1. 把第 N 张拖到第 1 位——封面变了，但图片浏览顺序也变了；
2. 放弃网页端，改用 App 或 API（`photo_cover_index`）。

这是网页端与 Content Posting API / 移动端的明确能力差距。

### F8. 图片帖网页入口存在，但灰度/地区可用性未能确认

**【产品前端代码；可用性未能确认】**

bundle 中存在完整的 `tiktokStudio_uploadPhotos` 流程和 `POST_PHOTO` 路由组件，包含：

- `Select photos` / 拖拽上传；
- `Photos` 网格、拖拽排序、`Cover` 徽标；
- 标题、描述、声音、可见性；
- `Add photo` / `Delete photo` / `Replace`。

这说明 TikTok Studio 网页端至少在某些账号上支持图片帖。但官方 Help Center 的“How to post a photo”仍然只写 App 步骤；第三方资料对“网页端是否支持图片帖”说法冲突（有的说支持，有的说只有视频）。因此**目标账号是否能看到 Photo 入口，必须登录实测，未能确认**。

### F9. 封面与定时、AI 标识、品牌声明的顺序

**【产品前端代码 + 仅推断；硬性限制未能确认】**

- 封面、定时、AI 标识、品牌声明在页面上是彼此独立的字段/开关；没有发现代码层面“必须先做 A 才能做 B”的依赖。
- AI 标识在 `Show more` / “AI-generated content” 区域，开启时可能弹确认框；品牌声明在 `Show more` → “Disclose post content” 区域，选择“Your brand / Branded content”后可能有 Save/Continue 确认。它们都不读取或重置封面状态。
- **真正的顺序约束在“提交”**：一旦点击 `Schedule`/`Post`，定时帖按官方说法不可编辑（只能删除后重发），所以封面必须在最终提交前完成。TikTok Business Blog 的 Video Scheduler 公告也明确把“edit the cover image”放在“toggle the schedule button”之前。【官方文档】
  - 注意：有第三方教程称新版 UI 可以重新打开定时草稿并修改封面/时间；官方 Help Center 仍写“cannot be edited, only deleted”。两种说法冲突，**【未能确认】**。稳妥做法仍是提交前把封面定好。
- 若封面编辑器是模态框，打开时其他开关不可操作；必须先 Save/Discard 关闭它。这是 UI 层顺序，不是业务约束。
- 发布后：封面/文案可在发布后 7 天内每天编辑一次（产品文案：`Captions and covers can only be edited once a day and within the first 7 days of posting.`）；广告、品牌内容、图片帖等类型可能不允许编辑封面（`Covers for {contentType} can’t be edited.`）。这与发布前设置无关，但会影响“发后再补封面”的兜底方案。【产品前端代码】

**建议的安全顺序**（不是平台强制，而是降低返工）：

```text
上传文件
→ 等视频 Processing 完成
→ 设置封面（帧或上传图）
→ 填写 caption / tags
→ 设置 AI 标识、品牌声明
→ 设置定时
→ 最终 Post / Schedule
```

### F10. 现有 `upload_thumbnails` 的选择器很可能已经过期

**【开源实现 + 产品前端代码对照】**

现有代码：

```python
# main_chrome.py:438-447
await self.locator_base.locator(".cover-container").click()
await self.locator_base.locator(".cover-edit-container >> text=Upload cover").click()
async with page.expect_file_chooser() as fc_info:
    await self.locator_base.locator(".upload-image-upload-area").click()
    ...
await self.locator_base.locator('div.cover-edit-panel:not(.hide-panel)').get_by_role(
    "button", name="Confirm").click()
```

在 2026-11-05 抓取到的 TikTok Studio 线上 bundle 中，**没有找到** `.cover-container`、`.cover-edit-container`、`.upload-image-upload-area`、`.cover-edit-panel` 这些类名（不排除它们存在于未抓取的懒加载 chunk 中，但至少不能作为稳定选择器）。当前封面编辑器使用：

- 文本/ARIA：`Edit cover`、`Upload cover`、`Upload cover image`、`Uploaded cover image`、`Delete uploaded image`
- 当前保存按钮更可能是 `Save`（产品文案 `webCreation_editVideo_buttonSave`），而不是旧版的 `Confirm`
- 帧选择器是无 ARIA 的 `canvas[height="52"]`，不是 `.cover-edit-panel`

因此现有 `upload_thumbnails` 至少存在三类风险：

1. 入口 `.cover-container` 找不到；
2. `Upload cover` 的容器类名找不到；
3. `Confirm` 按钮不存在（当前是 `Save`）。

这不是“TikTok 没有自定义封面”，而是**选择器针对的是旧版 UI**。

---

## UI 路径与候选选择器

### 视频（TikTok Studio）

```text
https://www.tiktok.com/tiktokstudio/upload?lang=en
→ Select video / 拖入文件
→ 等待 Processing 完成（Post 可点、Cover 状态结束）
→ 点击预览区/右侧 Cover 的 “Edit cover”
→ 封面编辑器
   ├─ “Upload cover”：上传 JPG/PNG，裁剪 3:4
   └─ 胶片时间轴：11 帧 + 指示器 + 前后按钮
→ Save（旧版可能是 Confirm）
→ 回到表单：caption / AI / brand / schedule
→ Post 或 Schedule
```

候选选择器（按稳定性从高到低）：

| 目标 | 候选选择器 | 说明 |
|---|---|---|
| 打开封面编辑器 | `get_by_text("Edit cover", exact=True)`；`get_by_role("button", name="Edit cover")` | 当前产品文案；旧代码没有用它 |
| 封面入口兜底 | 预览区封面缩略图 `img` / 含 `cover` 的容器，`.first.click()` | 仅在文本入口找不到时用；不要把 `.cover-container` 当唯一入口 |
| 上传页签 | `get_by_text("Upload cover", exact=True)` | 产品文案稳定 |
| 文件输入 | `[aria-label="Upload cover image"] input[type="file"]` | 最稳；input 是隐藏的，用 `set_input_files` |
| 文件输入兜底 | `input[type="file"][accept*="image/jpeg"]` | 注意页面可能有多个 file input，需限定在封面编辑器内 |
| 已上传预览 | `[aria-label="Uploaded cover image"]` | 用于确认上传成功 |
| 删除已上传图 | `[aria-label="Delete uploaded image"]` | 切回帧选择 |
| 胶片画布 | `canvas[height="52"]` | 默认宽 429；限定在封面编辑器内。不要用 `canvas[width="43"]`（那是指示器预览） |
| 指示器 | `div:has(> canvas[width="43"][height="60"])` 或 `img[alt="Frame preview"]` | 指示器内是 canvas 或默认帧图片 |
| 上一帧/下一帧 | 胶片容器内两个 `button`，`nth(0)` / `nth(1)` | 无 aria-label，必须限定作用域；hover 后才出现 |
| 保存 | `get_by_role("button", name=re.compile(r"^(Save|Confirm)$"))` | 当前更可能是 Save；旧版 Confirm 作为兜底 |
| 封面编辑模态根 | `text=Upload cover` + `text=Preview in profile` 的共同祖先 | 用于限定所有查询，避免命中页面其他 canvas |

按毫秒点击胶片：

```python
duration_ms = await page.evaluate(
    "() => { const v = document.querySelector('video'); return v ? v.duration * 1000 : 0; }"
)
canvas = cover_modal.locator('canvas[height="52"]').first
box = await canvas.bounding_box()
x = box["x"] + (target_ms / duration_ms) * box["width"]
y = box["y"] + box["height"] / 2
await page.mouse.click(x, y)
```

注意：

- `duration` 必须取**封面编辑器对应的视频**；如果页面有多个 video，先限定作用域。
- 若 `duration_ms <= 0`，说明元数据/处理还没完成，不要点。
- 点击后可以 hover 指示器，读取 `mm:ss` tooltip 做粗校验；tooltip 不显示毫秒。
- 若要微调，只能靠前后帧按钮（步长 `frameDuration`，未能确认）或再次点击，不能输入精确毫秒。

### 图片帖（TikTok Studio，若账号有入口）

```text
Upload → Photo / Select photos
→ 选择 1..N 张
→ 图片网格：第 1 张显示 “Cover” 徽标
→ 拖拽排序：把目标图放到第 1 位（=换封面，同时改变顺序）
→ 标题 / 描述 / 声音 / 可见性
→ Post 或 Schedule
```

候选选择器：

| 目标 | 候选选择器 | 说明 |
|---|---|---|
| 图片项 | `div[data-id]` | 产品代码给每个 asset 加了 `data-id` |
| 封面徽标 | `div[data-id] >> text=Cover` | 只在第 1 张出现；是徽标，不是按钮 |
| 添加图片 | `[aria-label="Add photo"]` | 产品代码 |
| 删除图片 | `[aria-label="Delete photo"]` | 产品代码 |
| 图片文件输入 | `input[type="file"][multiple]` | 隐藏 input |
| 标题 | `input[placeholder="Add a catchy title"]` | 产品文案 |
| 描述 | 含 `Writing a long description...` 的 contenteditable/textarea | 需实测确认具体元素 |

**不要**寻找 “Set as cover” 或封面下拉框：当前 bundle 中没有这个 UI。

---

## 与现有 `thumbnail_path` / `upload_thumbnails` 的差异

| 维度 | 现有实现 | 当前网页端 | 影响 |
|---|---|---|---|
| 封面来源 | 只支持自定义图片 `thumbnail_path` | 视频帧 + 自定义图片，二选一 | 需要新增“帧/毫秒”参数或本地抽帧 |
| 入口 | `.cover-container` | `Edit cover` 文本/按钮 | 旧选择器可能直接失败 |
| 上传页签 | `.cover-edit-container >> text=Upload cover` | `Upload cover` + `[aria-label="Upload cover image"]` | 类名不可依赖 |
| 文件区 | `.upload-image-upload-area` | label + 隐藏 input | 直接 `set_input_files` 更稳 |
| 保存 | `get_by_role("button", name="Confirm")` | 更可能是 `Save` | 旧代码可能卡在确认按钮 |
| 等待时机 | `detect_upload_status` 后调用 | 必须等 Processing 完成 | 现有顺序基本正确，但缺“封面就绪”判断 |
| 格式/尺寸校验 | 无 | JPEG/PNG/JPG，≥324×432，≤50 MB | 本地校验可减少失败 |
| 裁剪 | 依赖弹窗默认/手工 | 3:4 裁剪，`Preview in profile (4:3)` | 非 3:4 图片可能被裁切 |
| 结果校验 | 无 | 可读 `Uploaded cover image` 或 preview src | 应增加“封面确实变化”的断言 |
| 图片帖 | 不支持 | 第一张即封面 | 无法直接做“第 N 张封面” |
| 毫秒定位 | 不支持 | 胶片点击 ≈ 按比例映射 | 精度受 `duration/429` 限制 |

### 与 `thumbnail_path` 的兼容建议

- `thumbnail_path` 继续表示“自定义封面图片”，走 `Upload cover` 分支，保持向后兼容。
- 新增 `cover_timestamp_ms`（或 `cover_ms`）表示“从视频取帧”，与 `thumbnail_path` **互斥**；两者同时提供时建议直接报参数错误，而不是悄悄让后者覆盖前者。
- 不要把 `cover_timestamp_ms` 直接塞进现有 `thumbnail_path`（它是文件路径，语义不同）。
- `TiktokVideo.__init__` 的 legacy positional 顺序不能动；新参数放在 `thumbnail_path` 之后，作为关键字参数追加。
- 如果产品要求“精确毫秒”，建议实现为：本地用 ffmpeg 在目标毫秒抽帧 → 生成 3:4 图片 → 走现有 `thumbnail_path` 自定义封面流程。这样不依赖网页胶片精度，也不依赖 `FramePicker` 的内部实现；代价是新增 ffmpeg 依赖和裁剪逻辑。当前仓库没有 ffmpeg 依赖，需另行评估。

### 关于 Issue #228 的风险

`wkaisertexas/tiktok-uploader` 的 issue #228 报告：封面流程看起来成功（上传、裁剪、Confirm、preview src 变成 blob），但最终发布后仍是默认封面。【开源实现】

这说明：

- “预览变了”不等于“服务端接受了封面”；
- 需要在发布后（或发布前通过页面状态）做二次校验；
- 现有代码 `await page.wait_for_timeout(3000)` 不能证明封面生效。

本次未启动浏览器，无法判断该 issue 是旧版 UI、账号灰度还是 TikTok 服务端行为；列为待复核。

---

## 可行性结论

### 1. 视频自定义封面：可行，且是现有能力的延续

- 网页端有明确的 `Upload cover` 入口和 3:4 裁剪。
- 现有 `thumbnail_path` 语义可以直接映射。
- **主要工作是把旧选择器/旧按钮文案更新为当前 UI，并增加格式/尺寸/结果校验。**

### 2. 视频按毫秒选帧：部分可行，不能承诺毫秒级精确

- 网页端有帧选择器，点击胶片可以按比例落到目标毫秒。
- 精度约为 `duration/429` 毫秒/像素；3 分钟视频约 ±420 ms，10 分钟约 ±1.4 s。
- 没有数字输入框；tooltip 只显示 `mm:ss`。
- **如果“指定毫秒”是硬契约，建议本地抽帧后作为自定义封面上传**；如果只是“选个大致画面”，网页胶片足够。

### 3. 图片帖封面：只能第 1 张，不能无副作用地选第 N 张

- 第 1 张 = 封面，页面显示 `Cover` 徽标。
- 换封面 = 拖到第 1 位 = 改变图片顺序。
- 若业务要求“第 N 张当封面但保持原顺序”，网页端**不可行**；需要 App/API，或接受顺序变化。
- 若业务只要求“第一张当封面”，网页端完全可行。

### 4. 顺序：没有硬性依赖，但有“提交前必须完成”的约束

- 封面、定时、AI、品牌是独立字段；没有发现互相重置。
- 定时帖提交后不可编辑（官方口径），所以封面必须在 `Schedule` 前完成。
- 视频封面必须在 Processing 完成后设置。
- 建议按“上传 → 等处理 → 封面 → 文案 → AI/品牌 → 定时 → 提交”的顺序实现。

### 5. 上传完成前设置封面：不可行/不可靠

- 产品文案明确要求 Processing 完成后才能选视频封面。
- 实现时应等待封面状态结束，而不是只等 `Post` 按钮可点。
- 图片帖的封面徽标也只在单张图片上传成功后出现；不要在图片还没上传完时拖拽排序。

---

## 待复核点

1. **真实 DOM**：`Edit cover`、`Upload cover`、`Save` 在目标账号的实际页面上是否与 bundle 文案一致；是否存在 A/B 实验或灰度差异。
2. **`FramePicker` 是否用于 upload 页**：组件存在于共享 bundle，但未在真实上传页确认它被挂载；第三方教程支持“桌面时间轴滑块”的存在，仍需实测确认。
3. **`frameCount` / `frameDuration` 的实际传值**：默认 11 帧、步长未知；不同视频时长/账号可能不同。
4. **保存按钮**：当前是 `Save` 还是 `Confirm`；裁剪是否是独立确认步骤。
5. **自定义封面裁剪行为**：上传非 3:4 图片时，是自动居中裁剪、还是需要拖动裁剪框；是否必须点一次 Confirm。
6. **封面提交字段**：`cover_info.cover_uri` 是否对所有视频封面（帧/上传）都成立；是否还有隐藏的 timestamp 字段。
7. **Issue #228**：预览变化但最终封面未生效，是否仍可复现；需要对发布后的帖子做封面核验。
8. **图片帖网页入口**：目标账号是否显示 Photo 模式；最多多少张、单张最大多少 MB；是否支持定时。
9. **图片帖封面**：是否真的只能第 1 张；是否存在未在 bundle 中出现的“设为封面”右键菜单/实验功能。
10. **顺序交互**：开启 AI 标识/品牌声明后，封面是否被重置或锁定；定时切换后封面是否仍可编辑。代码上没有依赖，但需实测。
11. **发布后兜底**：7 天内每天一次封面编辑是否对所有内容类型可用；品牌内容/广告/图片帖的限制是否适用于目标账号。

---

## Sources

### 本仓库代码

- `uploader/tk_uploader/main_chrome.py:24` — `TIKTOK_UPLOAD_URL`
- `uploader/tk_uploader/main_chrome.py:388-396` — 上传视频 → `detect_upload_status` → `upload_thumbnails` → `set_schedule_time` → `click_publish`
- `uploader/tk_uploader/main_chrome.py:438-447` — 现有 `upload_thumbnails`
- `uploader/tk_uploader/main_chrome.py:492-514` — 现有 `detect_upload_status`
- `uploader/tk_uploader/main_chrome.py:240-294` — 现有 `set_schedule_time`
- `uploader/tk_uploader/tk_config.py:1-4` — iframe/body locator
- `sau_commands/tiktok.py:90,103,116` — `--thumbnail` / `thumbnail_file` / `thumbnail_path`

### 官方文档

- TikTok Help Center — Editing, posting, and deleting / “Adding a video cover”：
  https://support.tiktok.com/en/using-tiktok/creating-videos/editing-posting-and-deleting
  （“On the post screen, tap Select cover… Drag and place the frame… Tap Save.”）
- TikTok Help Center — Making a post / “How to post a photo on TikTok”：
  https://support.tiktok.com/en/using-tiktok/creating-videos/making-a-post
  （图片帖 Post 屏幕有 `Edit cover`；移动端可滑到任意图片）
- TikTok Help Center — Creator tools on TikTok / TikTok Studio：
  https://support.tiktok.com/en/using-tiktok/creating-videos/creator-tools-on-tiktok
  （网页上传可调整 “Cover: Select a cover image for your video.”）
- TikTok for Developers — Direct Post：
  https://developers.tiktok.com/doc/content-posting-api-reference-direct-post/
  （`video_cover_timestamp_ms`；未设置/非法时用第一帧）
- TikTok for Developers — Photo Post：
  https://developers.tiktok.com/doc/content-posting-api-reference-photo-post/
  （`photo_cover_index`，0-based；最多 35 张）
- TikTok Business Blog — Video Scheduler：
  https://www.tiktok.com/business/en-US/blog/introducing-video-scheduler-now-you-can-plan-tiktoks-in-advance
  （上传时编辑封面，然后 toggle schedule；定时后不可编辑）
- TikTok Creator Academy — Video covers：
  https://www.tiktok.com/creator-academy/article/video-covers-thumbnails
  （封面设计/安全区建议；页面正文为 JS 渲染，抓取时未取到完整正文）

### 开源实现

- `wkaisertexas/tiktok-uploader` — `src/tiktok_uploader/config.toml` 的 `[selectors.upload.cover]`：
  https://github.com/wkaisertexas/tiktok-uploader/blob/main/src/tiktok_uploader/config.toml
  （`cover_preview`、`edit_cover_button`、`upload_cover_tab`、`upload_cover`、`upload_confirmation`）
- `wkaisertexas/tiktok-uploader` — `src/tiktok_uploader/upload.py` 的 `_set_cover`：
  https://github.com/wkaisertexas/tiktok-uploader/blob/main/src/tiktok_uploader/upload.py
  （只做自定义图片上传，不选帧）
- `wkaisertexas/tiktok-uploader` issue #228 — “Cover selection issue but thumbnail not selected”：
  https://github.com/wkaisertexas/tiktok-uploader/issues/228
  （预览变化但最终未应用）

### TikTok Studio 线上前端 bundle（2026-11-05 抓取）

- `https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator-center-web/static/js/3148.5b452db5.js`
  - `ImageUpload` / `FramePicker` / `CoverPicker` / `CoverSourceType`
  - `webCreation_uploadCover_resolutionError`：`Upload a file that is at least 324 × 432 pixels`
  - `webCreation_uploadCover_sizeError`：`File size can’t exceed 50 MB`
  - `webCreationCoverEditing_ctaUploadCover`：`Upload cover`
  - `webCreationCoverEditing_previewInProfile`：`Preview in profile (4:3)`
- `https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator-center-web/static/js/9602.bceb34cf.js`
  - `@pgc-web/web-creation:2.0.0.2604` 文案包
  - `uploadingEdit_postPage_coverExplain_process`：`You can choose a video cover after processing is complete.`
  - `uploadingEdit_postPage_coverStatus_upload/load/process`：`Uploading...` / `Loading...` / `Processing...`
  - `uploadingEdit_postPage_coverExplain_edit`：`You can edit the cover after your video is uploaded.`
  - `webCreationCoverEditing_ctaEditCover`：`Edit cover`
  - `webCreation_editVideo_buttonSave`：`Save`
  - `webCreation_editVideo_buttonDisclaimer_captionsCovers`：`Captions and covers can only be edited once a day and within the first 7 days of posting.`
  - `tiktokStudio_uploadPhotos_details_coverPhoto_label`：`Cover`
- `https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator-center-web/static/js/6240.60d62a9e.js`
  - 图片帖：`isCover: 0 === t`、`data-id`、`Add photo` / `Delete photo`、`Cover` 徽标
  - 图片帖提交：`image_post_content.cover: r[0]`
  - `tiktokStudio_uploadPhotos_*` 文案与 `POST_PHOTO` 路由
  - `webCreation_editVideo_cannotEdit_hoverCover`：`Covers for {s_contentType} can’t be edited.`

### 第三方教程/资料（用于 UI 文案与交互交叉验证）

- Jay Cartere — “How to upload custom cover/thumbnail to TikTok”：
  https://jaycartere.com/how-to-upload-custom-cover-thumbnail-to-tiktok/
  （Edit cover → Upload cover → select file → crop → Confirm）
- RouteNote — “How to upload a custom TikTok thumbnail”：
  https://routenote.com/blog/upload-tiktok-thumbnail/
  （JPG/JPEG/PNG，3:4，内置裁剪）
- Kapwing — “How to Change Your TikTok Thumbnail”：
  https://www.kapwing.com/resources/how-to-change-tiktok-thumbnail/
  （移动端 Edit cover / timeline / Upload）
- TryPostBase — “How to Edit the Cover of a TikTok Video”：
  https://www.trypostbase.com/resources/how-to-edit-the-cover-of-a-tiktok-video
  （移动端 Select cover / filmstrip / Save）
- Hollyland — “How to Upload a Post on TikTok from PC”：
  https://store.hollyland.com/blogs/creator-hub/upload-a-post-on-tiktok-from-pc
  （桌面端 “thumbnail slider below the video preview”）
- Lion Fans — “TikTok Web Version Complete Guide 2026”：
  https://lionfans.cc/en/blog/tiktok-web-version
  （网页端自动抓取多帧，可选帧或上传自定义封面）
- CatUI Agent TikTok upload skill（公开自动化脚本说明）：
  https://cdn.jsdelivr.net/npm/catui-agent@1.2.20/dist/extensions/builtin/browser/agent-workspace/domain-skills/tiktok/upload.md
  （网页上传流程、`Show more`、AI 标识、Schedule 按钮文案、beforeunload 等实际操作注意事项）

---

## 一句话给实现者

视频封面不要继续赌 `.cover-container`：当前 UI 是 `Edit cover` + `Upload cover`（ARIA label 更稳）+ `Save`；帧选择器可以按 `x = ms/duration*canvasWidth` 点击，但精度只有 `duration/429` 毫秒/像素。若“毫秒精确”是硬要求，本地抽帧后走自定义封面上传，比操作网页胶片更可靠。图片帖网页端没有第 N 张封面，封面就是第一张；换封面等于换顺序。
