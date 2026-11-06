# 09 — 视频/图片共用流程与扩展点

Status: resolved
Type: grilling
Blocked by: 01, 02, 03, 04, 05

## Question

基于现有 `main_chrome.py` 的视频发布流程，新能力如何插入而不破坏旧行为？需要确定：

1. 视频与图片帖是否共用同一个 `upload()` / `_upload_on_page()` 骨架；分叉点放在“选择文件”还是更晚的表单填写阶段。
2. 新增能力（隐私、互动、AI 标识、品牌声明、封面）做成可组合的步骤函数，还是在 `_upload_on_page` 里顺序调用；步骤失败时如何定位。
3. 现有 `TiktokVideo.__init__` 的 positional 参数与 `TiktokVideoUploadRequest` 如何扩展；是否新增 `TiktokNote` 类或复用同一类。
4. `tk_config.py` 的定位器与 `main_chrome.py` 的内联选择器如何组织，避免两套真相。
5. 登录检测、15 分钟总超时、`LoginRequiredError`、cookie/session 逻辑如何被两条路径复用。
6. 哪些现有函数需要拆分（如 `add_title_tags`、`detect_upload_status`、`click_publish`），拆分是否会影响现有测试。

## Answer

### 1. 骨架与分叉点

采用「基类 + 视频/图文字类」的模板方法（对齐视频号 `TencentBaseUploader`），**不复制流程**。抖音/快手/小红书那种「基类只放片段、子类各抄一份 `upload()`/`upload_in()`」是历史沉积，本仓不再照抄：TikTok 的发布重试循环、deadline 检查、登录映射是三处高风险逻辑，只保留一份。

- `TiktokBaseUploader(BaseVideoUploader)`：`upload_in()`（选页 + multilogin + deadline）、`_upload_on_page()` 模板、`_check_publish_deadline`、`choose_base_locator`、`fill_caption`、`apply_options`（内部 `apply_privacy` / `apply_interactions` / `apply_aigc` / `apply_brand` / `readback_options`）、`apply_schedule`、`click_publish`。
- `TiktokVideo(TiktokBaseUploader)`：`attach_media`（`Select video` chooser）、`fill_metadata`（caption + tags）、`wait_media_ready`（原 `detect_upload_status`：Post 可点 + 失败重试）、`apply_cover`（原 `upload_thumbnails`）、`read_result`（原 `get_last_video_id`）；保留本地模式 `upload()`、`change_language`、`handle_upload_error`。
- `TiktokNote(TiktokBaseUploader)`：`ensure_mode`（确认 `?tab=photo`，必要时点 `Photos` tab）、`attach_media`（**先切 tab 再** `set_input_files`，否则默认 input `accept=video/*` 静默吞图）、`fill_metadata`（Title + Description + tags）、`wait_media_ready`（等 Title/Description 表单与图片处理完成）、`apply_cover`（no-op，第 1 张即封面）、`read_result`（`/tiktokstudio/upload/post/photo?item_id=`）。`upload()` 只有 session 分支，本地模式直接报错。

模板顺序（与现有视频流程逐字等价，`fill_metadata` 在 `wait_media_ready` 之前——这正是当前"先填标题再等上传完成"的行为）：

```python
async def _upload_on_page(self, page, *, multilogin, deadline):
    await self.open_upload_page(page, multilogin=multilogin)  # goto + 等 shell + choose_base_locator + ensure_mode
    await self.attach_media(page)
    await self.fill_metadata(page)
    await self.wait_media_ready(page, deadline=deadline, multilogin=multilogin)
    await self.apply_options(page)
    await self.apply_cover(page)
    await self.apply_schedule(page)
    await self.click_publish(page, deadline=deadline, multilogin=multilogin)
    self.last_item_id = await self.read_result(page)
```

**分叉点比"选择文件"更早**：`open_upload_page` 里的 URL（`?tab=photo`）与 `Photos` tab 切换已是模式专属；表单填写是第三个分叉点，不是唯一。子类可 override 任意步骤（例如图片帖没有 reuse 设置，可覆写 `apply_options`）。

全部代码仍留在 `uploader/tk_uploader/main_chrome.py`，不新增模块（该文件当前 525 行；超过约 800 行再按仓库多文件先例拆分）。

### 2. 步骤组合与失败定位

步骤是基类上的实例方法，按固定顺序调用；新增能力以独立命名方法存在，不引入 steps 列表 / 状态机。

失败定位与全仓一致：**不新增异常类型**（仓库只有 `LoginRequiredError` / `UsageError`）。

- 每个步骤进入时打一行带步骤名的日志（沿用 `tiktok_logger.info`）。
- 失败时异常消息必须含步骤名与期望/实际，例如 `隐私设置失败：期望 Everyone，实际 Followers`。
- `LoginRequiredError` 原样上抛，保持 06 的退出码映射（10 / 9 / 1）不变。

### 3. 类与入参

```python
@dataclass(frozen=True, slots=True)
class TiktokPublishOptions:
    privacy: str | None = None          # public / friends / followers / only-me
    allow_comments: bool | None = None  # None = 不动页面默认
    allow_reuse: bool | None = None
    aigc: bool | None = None
    your_brand: bool | None = None
    branded_content: bool | None = None
```

- 位置：`uploader/tk_uploader/main_chrome.py`（避免 CLI → uploader 的反向依赖）。
- `TiktokVideo.__init__(title, file_path, tags, publish_date, account_file, thumbnail_path=None, *, options=None)`：前 5 个 positional 顺序逐字不变，新增项一律 keyword-only。
- `TiktokNote.__init__(image_paths, note, tags, publish_date, account_file, *, title=None, options=None, debug=..., headless=...)`。
- `TiktokVideoUploadRequest` 增加 `options: TiktokPublishOptions | None = None`；新增 `TiktokNoteUploadRequest` 与 `_build_note_uploader`（视频 builder 名字不改）。

### 4. 选择器与常量

选择器**内联在所属步骤方法**：共享步骤在基类，模式专属步骤在子类。共享步骤上提后，描述编辑器、发布按钮、定时控件等同一控件只存在一处引用，因此不存在"两套真相"。

`tk_config.py` 从"定位器壳"改为常量文件（对齐 `dayu/constants.py`、`zhihu/constants.py`）：`TIKTOK_UPLOAD_URL`、`?tab=photo`、图片张数上限 35、单张 ≤50 MB、Title ≤90、Description ≤4000、hashtag ≤50。保留 `Tk_Locator.tk_iframe` / `default` 供 `choose_base_locator` 与未接线的 Firefox 分支使用。

### 5. 登录、超时与错误映射

完全复用，零新常量：

- CLI 在 `upload-video` / `upload-note` 前各调用一次 `is_logged_in(session.context)`。
- `upload_in` 在基类统一计算 `deadline = time.monotonic() + TIKTOK_PUBLISH_TIMEOUT_SECONDS`（multilogin 才启用）。
- 循环内继续调用模块级 `_raise_if_login_required(page)`。
- 图片帖使用同一个 15 分钟预算（35×50 MB 极端情况若确不够，后续单独调常量，不在本规格中预设）。

### 6. 现有方法拆分

| 现方法 | 去处 |
| --- | --- |
| `_upload_on_page` | 基类，重写为 9 步模板 |
| `upload_in` / `_check_publish_deadline` / `click_publish` / `choose_base_locator` | 基类，名字不改 |
| `set_schedule_time` | 基类 `apply_schedule` |
| `add_title_tags` | 基类 `fill_caption(text, tags)`（逻辑不变，`self.title` 改参数） |
| `detect_upload_status` | `TiktokVideo.wait_media_ready` |
| `upload_thumbnails` | `TiktokVideo.apply_cover` |
| `get_last_video_id` | `TiktokVideo.read_result` |
| `handle_upload_error` / `change_language` / 本地 `upload()` | 留在 `TiktokVideo` |
| `upload()`（session 分支） | 基类 `upload_in`；视频保留"本地 + session"双分支 |

### 7. 对现有测试的影响

- `test_init_positional_order_is_unchanged`：改为断言前 5 个 positional 前缀不变 + 新参数必须 keyword-only。
- `test_actions_are_check_upload_video_login_only`：断言集合加入 `upload-note`。
- 2 行调用改名：`detect_upload_status` → `wait_media_ready`。
- `click_publish` 改为继承后签名不变，两处测试调用零改动。
- 其余测试（session 复用、deadline、登录映射、stop 归属）不受影响。

### 遗留（交给 08 标注，不阻塞本工单）

- 图片帖网页端是否实际渲染 AIGC / 品牌控件仍需真实账号实测；行为已由 06 兜底：控件缺失即退出 1。
- `--json` 输出仍未决定（05/06 均未涉及），保持雾。

## Comments
