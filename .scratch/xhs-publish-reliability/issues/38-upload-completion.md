# 38 — 上传完成闸

**What to build:** 素材没传完就不填元数据。图文逐张派发，每张都以"预览瓦片数量到位 + 该瓦片的进行中遮罩消失"为完成；视频以发布按钮的就绪谓词为完成。任何一次失败立刻整体中止，点击前 `1`。

**Blocked by:** 33（上传入口与"+"瓦片锚点）、36（复用 ARM 谓词）。

**Status:** ready-for-agent

**图文**

- [x] 逐张派发，不批量；张与张之间 1s，每张 500ms 轮询
- [x] 首张用唯一的上传入口（count == 1）派发
- [x] 第 2 张起：点"+"瓦片 → 文件选择器 → 只派发 1 张
- [x] 完成判据 = 预览瓦片数 ≥ i+1 **且** 第 i 个瓦片的进行中遮罩已消失
- [x] 派发后 60s（按剩余预算收紧）未到位 → 中止，报"第 k 张 / 共 N 张 + 未点击发布" → `1`
- [x] 计数到位后复检一次 DOM 静默（500ms / 上限 3s）：仍 ≥N → 进填元数据；>N → warning 继续；<N → 继续等至 60s 窗口耗尽 → 中止
- [x] **禁止** `inputs[0]` / `.first` 兜底（会把视频 input 当图片 input）；**不重传**、不降级少图

**视频**

- [x] 完成判据 = ARM 谓词满足；窗口 `min(600s, 剩余预算)`，1s 轮询
- [x] 失败立即中止，不等窗口：视频失败态（class 恰为 fail）或加载失败文案出现
- [x] 删除全部关键词扫描、阶段扫描、"标题框出现即放行"
- [x] 上传入口恒在、失败态下按钮恒禁用 —— 两者都不得当作信号

**两者共同**

- [x] 上传入口缺失/多义/派发抛错 → 立即中止（不等待）
- [x] 预算耗尽走预算模块的点击前文案，不自造"处理超时"
- [x] `--no-publish` 同样过就绪闸，然后再停
- [x] 失败统一 `1`，不按图文/视频/第几张分叉

**测试与真机**

- [x] 瓦片计数 + 遮罩消失判完成；失败态 → `1`；静默复检三态；第 2 张走文件选择器；预算耗尽文案
- [ ] 真机：图文 2 张正路、视频正路、假 mp4 注入（失败态 → 点击前 `1`，stderr 不含 `publish_attempted=true`）

## Comments

### 实现（离线）

- 新增闸门（`uploader/xiaohongshu_uploader/main.py`）：
  - `_note_upload_gate(page, image_paths, *, budget, mode, humanizer)`：逐张派发 + 逐瓦片完成 + 收口静默复检。
  - `_note_image_ready(page, index)`：`瓦片数 ≥ index+1` **且** `tiles[index].locator('.mask.uploading').count() == 0`（每瓦片，不看全局）。
  - `_dispatch_note_image(...)`：首张 `div.upload-content input.upload-input`（单趟解析，`count == 1`，多义 → `ElementUnusableError`）；第 2 张起 `.img-preview-area .entry` → `expect_file_chooser()` → `chooser.set_files([1 张])`；备选 `.img-list .top input[type=file][multiple]`。全程无 `inputs[0]` / `.first`。
  - `_video_upload_gate(page, *, budget, mode)`：完成判据就是 `_arm_ready`，1s 轮询，窗口 `min(600s, 剩余预算)`；`_video_upload_failure` 只认 `div[class='fail']`（class 恰为 `fail`）与 `.video-container-loading-text`。
- 删除：视频关键词表（`上传成功/分辨率/重新上传/编辑封面/已上传/已选择/100%`）、`div.stage` 扫描、"标题框出现即放行"、图文"等标题框可见"的就绪判定；不再把 `input.upload-input` / `submit-disabled=true` 当失败信号。
- 失败语义：缺失 → `ElementMissingError`，多义/不可用 → `ElementUnusableError`（均 `RuntimeError`，点击前 → 1）；`set_input_files`/文件选择器 `set_files` 抛错统一转为 `ElementUnusableError`（立即中止、不重传）。
- 预算：`check_pre_click()` 每轮先查；轮询间隔经 `budget.clamp_seconds`；耗尽即抛预算模块的 pre-click 文案（无"处理超时"）。
- `--no-publish`：闸门在 `fill_meta` 之前，干跑同样过闸后才在 ARM 停下。
- 单张 60s 窗口的 `k` 用 1 基序号（`第 k 张 / 共 N 张`），文案带 `未点击发布`。

### 测试

- 新增 `tests/test_xhs_upload.py`（24 例）：瓦片计数 + 遮罩消失、每瓦片（非全局）完成、第 2 张走文件选择器、`+` 瓦片缺失/chooser 缺失走备选、1s 张间隔、60s 窗口文案、静默复检三态（≥N/>N/<N）、DOM 未静默仅 warning、缺失/多义/`set_input_files` 失败立即中止、预算耗尽文案、视频 `div.fail`/加载文案立即中止、600s clamp、剩余预算 clamp、`submit-disabled=true` 不算就绪、零关键词扫描（静态）。
- `tests/fakes_xhs_dom.py` 增补 `FakeFileChooser` / `RecordingPage.expect_file_chooser()` / `preview_tiles()`；`expect_file_chooser` 的 timeout 也记入 `wait_calls`。
- 既有用例随语义更新：`test_xhs_budget`（视频不再有 `wait_for_selector`；图文入口缺失改为立即中止）、`test_xhs_blocked`（轮内 C2 改为闸门轮询）、`test_xhs_submit` / `test_humanize` / `test_xhs_selectors`（页面补上预览瓦片/新选择器）。
- 全量：`.../.venv/bin/python -m unittest discover -s tests -t .` → `Ran 1365 tests ... OK (skipped=2)`。

### 未验证（无真机环境）

- 图文 2 张正路（首图入口 + 「+」→ file chooser）未在真机跑通。
- 视频正路与假 mp4 注入（`div.fail` → 点击前 `1`、stderr 不含 `publish_attempted=true`）未在真机跑通。
- `.mask.uploading` 消失 = 客户端上传完成的时序按 ticket 24 取证实现；"服务端收齐"的极端竞态仍只靠一次静默复检防御。
