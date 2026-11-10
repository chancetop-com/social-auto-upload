# 03 — 现有 instagram.com 浏览器实现能力清单

Status: resolved
Type: research
Scope: 只读盘点（未修改任何代码/测试）。所有结论均来自当前仓库源码与测试，行号以本仓库当前版本为准。

## 0. 一句话结论

现有实现是**纯 DOM 自动化**的 instagram.com 发布器：它不调用任何官方/私有发布 API，只在发布点击后**旁听**一次 `POST /api/v1/media/configure` 响应来确认结果。已覆盖 Reels、单图、轮播、合并配文、视频自定义封面、立即发布、客户端 `--not-before` 闸门、结果文件与 verify/delete；Content Publishing API 的定时、Stories、feed video、alt text、location、collaborators、product tags、user tags、AI 标识、评论/点赞设置、share-to-feed、audio、媒体尺寸/时长前置校验均未接入。

## 1. 调用链与模块职责

| 层 | 文件 | 职责 |
| --- | --- | --- |
| CLI 解析/分发 | `sau_cli.py:46-71` | 注册各平台子命令，按 `platform` 分发 |
| 退出码映射 | `sau_cli.py:74-99` | 异常→退出码（见 §5.4） |
| Instagram 命令 | `sau_commands/instagram.py:42-90`（注册）、`170-242`（执行） | 参数、请求对象、本地/托管分支 |
| 共享参数 | `sau_commands/arguments.py` | 账号文件路径、标签、`--not-before`、运行 flags |
| 托管浏览器 flags/语义 | `sau_commands/browser.py` | MLX/AdsPower 选择、登录拒绝、身份提示文案 |
| 发布实现 | `uploader/meta_uploader/insgraph_uploader/main.py` | 登录、身份、上传、编辑、封面、配文、发布、结果 |
| verify/delete | `uploader/meta_uploader/insgraph_uploader/posts.py` | 原作品核对、移至最近删除 |
| 发布闸门 | `uploader/publish_gate.py:44-89` | 本地墙钟等待到 `--not-before` |
| 浏览器生命周期 | `utils/browser_session.py:104-262` | local `launch/storage_state` vs managed CDP 附着 |

导出面只有三个符号：`InstagramUploader`、`instagram_cookie_auth`、`instagram_setup`（`uploader/meta_uploader/insgraph_uploader/__init__.py:1-4`）。

## 2. 命令与参数（逐项）

所有子命令的 `--account` 都是 `required=False`，必填性在运行时判定（`sau_commands/instagram.py:49,58,71,84`）：

- 本地模式：`require_local_account` → 缺失报 `UsageError` → 退出码 2（`sau_commands/browser.py:247-263`）。
- 托管模式：`check`/`upload-*` 不需要 `--account`；`verify`/`delete` **始终**需要 `--account`（`sau_commands/instagram.py:182`，`sau_commands/browser.py:254-263`）。

### 2.1 子命令总表

| 子命令 | 必填 | 可选/默认 | 注册位置 |
| --- | --- | --- | --- |
| `login` | 无（本地需 `--account`） | `--account`；`--proxy`（默认 `SAU_INSTAGRAM_PROXY`，未设置则直连）；`--debug`；`--headed`/`--headless`（默认 **False → 可见**）；**无** `--folder-id/--profile-id` | `instagram.py:47-53` |
| `check` | 无（本地需 `--account`） | `--account`；`--proxy`；`--debug`；`--headed`/`--headless`（默认 **True → 无头**，未调用 `set_defaults(headless=False)`）；`--folder-id`；`--profile-id` | `instagram.py:47-56` |
| `upload-video` | `--file`、`--title` | `--thumbnail`；`--desc`（默认 `""`）；`--tags`（默认 `""`）；`--account`；`--proxy`；`--result`；`--not-before`；`--debug`；`--headed/--headless`（默认可见） | `instagram.py:57-69` |
| `upload-note` | `--images`（`nargs="+"`）、`--title` | `--note`（默认 `""`）；`--tags`；`--account`；`--proxy`；`--result`；`--not-before`；`--debug`；`--headed/--headless`（默认可见） | `instagram.py:70-81` |
| `verify` | `--post-url`、`--expected-text` | `--account`（必填，运行时）；`--proxy`；`--result`；`--debug`；`--headed/--headless`（默认可见）；**无** `--folder-id/--profile-id` | `instagram.py:82-90` |
| `delete` | 同 `verify` | 同 `verify` | `instagram.py:82-90` |

### 2.2 参数语义细节

- `--proxy`：默认值取模块常量 `INSTAGRAM_PROXY = os.environ.get("SAU_INSTAGRAM_PROXY")`（`main.py:30`，`instagram.py:50,64,76,87`）。`_proxy_options` 把空串视为直连，可覆盖环境变量（`main.py:93-97`）。托管模式下 `--proxy` 被显式丢弃：`replace(request, proxy=None)`（`instagram.py:146`）。
- `--tags`：逗号分隔，去空白并去掉前导 `#`（`arguments.py:22-31`）。
- `--images`：保持命令行顺序（`arguments.py:34-35`）。
- `--file/--thumbnail/--images`：`existing_file_path` 在 argparse 阶段就校验文件存在（`arguments.py:44-48`）。
- `--result`：`type=Path`，可选；缺省为 `.local/instagram-results/<uuid>.json`（`main.py:291`，`posts.py:67`）。
- `--not-before`：格式 `%Y-%m-%d %H:%M`，只校验格式，允许过去时间（`arguments.py:60-67,70-82`）。
- `--debug`：由 `add_runtime_flags` 注册（`arguments.py:85-90`），但 Instagram 模块内**从未读取** `args.debug`（代码中未明确其作用）。
- `sau_commands/instagram.py:44` 的 `schedule_help` 变量已赋值但未使用（死代码，且 Instagram 无 `--schedule`）。
- `login`、`verify`、`delete` 未注册 `add_browser_flags`，因此传 `--profile-id` 会被 argparse 拒绝（退出码 2）；托管模式下 `verify/delete` 固定走本地 cookie 路径（`instagram.py:181-193`，测试 `tests/test_adspower_article_identity_platforms.py:875-893`）。

## 3. 媒体类型与限制

### 3.1 已实现

| 能力 | 现状 | 位置 |
| --- | --- | --- |
| 视频/Reel | 单文件，`.mp4`/`.mov` | `instagram.py:59`；`main.py:524` |
| 图片 | 单图或轮播，`.jpg/.jpeg/.png/.avif/.heic/.heif` | `instagram.py:72`；`main.py:524` |
| 视频+图片互斥 | 必须且只能一种 | `main.py:286-287`（测试 `test_instagram_uploader.py:46-50`） |
| 自定义封面 | 仅视频；`.jpg/.jpeg/.png`；图片帖传 `--thumbnail` 直接报错 | `main.py:284-285,515-519`；`instagram.py:60,232` |
| 封面生效校验 | 读取预览 blob 的 SHA-256 与本地文件比对，不一致即失败 | `main.py:382-412` |
| 轮播顺序 | 按 `--images` 传入顺序 `set_input_files` | `main.py:362-363`；`arguments.py:34-35` |
| 文件存在性 | argparse 阶段 + `_validate_media` 二次校验 | `arguments.py:44-48`；`main.py:520-526` |
| 标题非空 | 构造时校验 | `main.py:288-289` |

### 3.2 未做的前置校验（代码中未明确 / 交给平台）

- 文件大小、时长、分辨率、宽高比、帧率：**无任何校验**（`_validate_media` 只查后缀与存在性，`main.py:514-526`）。
- 图片张数上下限：代码**无**显式上限；`nargs="+"` 允许 1..N（`instagram.py:72`）。文档只声明「单图与两图轮播已实测」（`docs/CLI.md:614`）。
- 轮播混排（图+视频）：`upload-note` 只收图片，`upload-video` 只收单视频，无混排入口。
- 媒体类型选择：视频固定走 Reels 路径（Reels 介绍弹窗 + 结果 `kind='reel'`），**没有** feed video / Stories 选项（`main.py:364-369,508`）。

## 4. 配文与元数据

### 4.1 已实现的合并规则

`_caption()`：`title`、`description`（`--desc`/`--note`）非空段以 `\n\n` 连接；有标签时再追加一段空格连接的 `#tag`（`main.py:297-302`）。

- 长度上限：合并后 **≤2200 字符**，超限在构造时 `ValueError`（`main.py:294-295`，测试 `test_instagram_uploader.py:46-48`）。
- 落盘方式：`editor.fill(caption)` 写入 Lexical 编辑器，并断言编辑器文本等于 caption（`main.py:439-444`）。
- 结果核验：创建响应的 `media.caption.text` 必须与 caption **完全相等**，否则报错（`main.py:266-267`，测试 `test_instagram_uploader.py:25-35`）。这意味着平台侧任何配文归一化/截断都会导致失败。
- `tags` 只做字符串拼接，不作为 API 字段传递（`main.py:280,300-301`）。

### 4.2 已校验但未暴露为 flag

- 「标题不能为空」（`main.py:288-289`）与 2200 上限是硬约束，但没有独立参数可覆盖。
- 封面只允许 JPG/JPEG/PNG（`main.py:518-519`），无「不裁剪/居中裁剪」等选项。

### 4.3 未实现（无参数、无代码路径）

| 字段 | 状态 | 依据 |
| --- | --- | --- |
| alt text（替代文字） | 未实现 | 代码中无 alt/accessibility 相关逻辑；`docs/CLI.md:616`、`skills/instagram-upload/SKILL.md:26` 明确未接入 |
| 地点 location | 未实现 | 同上 |
| 协作者 collaborators | 未实现 | 同上 |
| 商品标签 product tags | 未实现 | 代码与文档均无 |
| 用户标签 user tags | 未实现 | 代码与文档均无 |
| AI 生成标识 | 未实现 | `docs/CLI.md:616` |
| 关闭评论 / 隐藏点赞数 | 未实现 | `docs/CLI.md:616` |
| share to feed | 未实现 | 无对应控件操作 |
| 音频 / 滤镜 / 裁剪 / 声音 | 未实现（沿用页面默认） | `docs/CLI.md:616`、`SKILL.md:26` |
| 首评 / 品牌内容 /  fundraiser / 提醒 | 未实现 | 代码中无 |
| 定时 `--schedule` | 未实现（仅 `--not-before`） | `docs/CLI.md:616`；`instagram.py:44` 的 `schedule_help` 未使用 |
| Stories | 未实现 | 无子命令/参数 |

## 5. 发布行为

### 5.1 流程阶段

`upload()` → `_validate_media()`（`main.py:590-592`）→ local：打开页面 + `instagram_identity` + `_upload_steps` + 回写 cookie（`main.py:596-613`）；managed：`upload_in`（`main.py:559-588`）。

阶段标记 `self.stage`：`validation` → `identity` → `upload` → `edit` → `publish` → `save_session`（`main.py:292,532-539,575,603`）。

DOM 步骤：

1. 关闭通知弹窗、点第 2 个导航入口打开创建弹窗（`main.py:333-357`）。
2. `set_input_files` 上传素材（`main.py:358-363`）。
3. 视频关闭 Reels 介绍弹窗（`main.py:364-369`）。
4. 两次「主动作」点击推进裁剪→编辑，等标题变化；有封面时先设封面并校验字节（`main.py:375-431`）。
5. 配文页填写 caption，等 `--not-before`，再点发布（`main.py:433-461`）。
6. 监听 `POST /api/v1/media/configure`，202→`processing` 继续等，最终 media→`published`（`main.py:466-512`）。

### 5.2 立即发布与 `--not-before`

- 没有平台原生定时入口；`--not-before` 是**客户端闸门**：全部准备完成（含封面、配文）后阻塞到本地墙钟 ≥ 目标时间才点发布（`publish_gate.py:1-6,44-89`；调用点 `main.py:453-457`）。
- 等待不计入 15 分钟预算：等待时长会顺延 deadline（`main.py:458-461`）。
- 目标时间已过则立即发布（`publish_gate.py:65-67`）。
- 结果中 `schedule` 恒为 `None`（`main.py:510`）。

### 5.3 结果文件 schema

初始：`{"platform": "instagram", "title": ..., "status": "not_submitted"}`（`main.py:292`）。各阶段写盘点：

| 时机 | 状态 | 附加字段 | 位置 |
| --- | --- | --- | --- |
| 点击前 | `submission_unknown` | `user_id`、`username` | `main.py:462-464` |
| 收到 202 | `processing` | 同上 | `main.py:500-502` |
| 收到最终 media | `published` | `content_id`、`post_id`、`post_url`、`schedule=None`、`media_count` | `main.py:508-512` |
| 失败 | 保留当前状态 | `stage`、`error`、`evidence_dir` | `main.py:542-550` |

`content_id` 为 `<media.id>`（形如 `123_42`），`post_id` 为 shortcode，`post_url` 为 `https://www.instagram.com/{reel|p}/<code>/`（`main.py:508-511`）。`media_count` 取 `carousel_media` 长度，否则 1（`main.py:511`）。

verify/delete 结果：初始 `{"platform","post_url","status":"not_submitted"}`（`posts.py:68`）；核对成功补 `post_id`、`content_id`（`<media_id>_<owner_id>`）、`owner_id`、`expected_text`、`status="published"`（`posts.py:58-59`）；delete 写 `deletion_unknown`（`posts.py:93`）→ 成功后 `deleted`（`posts.py:102`）；失败补 `error`、`evidence_dir`（`posts.py:107-115`）。

### 5.4 退出码

| 码 | 含义 | 位置 |
| --- | --- | --- |
| 0 | 成功；本地 `check` 有效 | `sau_cli.py:83`；`instagram.py:218,222` |
| 1 | 一般运行时失败；**点击发布前** 15 分钟超时；本地 `check` 无效 | `sau_cli.py:97-99`；`main.py:325-331`；`instagram.py:221-222` |
| 2 | 用法错误（如本地模式缺 `--account`、未知参数） | `sau_cli.py:90-93` |
| 9 | `PublishResultUnknownError`：已点发布但未确认结果，禁止自动重发 | `sau_cli.py:94-96`；`utils/errors.py:15-20` |
| 10 | `LoginRequiredError` | `sau_cli.py:84-86`；`utils/errors.py:11-12` |
| 11 | `RateLimitedError`（托管 provider HTTP 429） | `sau_cli.py:87-89` |

注意差异：托管 `check` 未登录→退出 10（`instagram.py:214-218`）；本地 `check` 无效→退出 1（`instagram.py:220-222`）。`delete` 的 `deletion_unknown` **不是**退出码 9：异常最终被包装为 `RuntimeError` → 退出 1，未知语义只体现在结果文件（`posts.py:93-115`）。

### 5.5 超时与「结果未知」

- 总预算 15 分钟 `INSTAGRAM_PUBLISH_TIMEOUT_SECONDS`（`main.py:39`），local 从 `upload()` 起算（`main.py:596`），managed 从打开首页前起算（`main.py:562`）。
- 发布前超时 → `RuntimeError`「尚未点击发布」（`main.py:41-43,308-312,325-331`）。
- 点击后等待最终响应超时 → `PublishResultUnknownError`（`main.py:44-49,480-497`）。
- 点击**只发生一次**；202 不算成功，继续等同一接口的后续响应（`main.py:466-505`，测试 `test_instagram_uploader.py:275-338` 断言只点 1 次、202 后仍未 `published`）。
- 未知结果仍会先保存现场证据，但保留专用异常类型以维持退出码 9（`main.py:552-557,583-586,606-609`；测试 `test_instagram_uploader.py:73-95`）。

### 5.6 失败证据

`_capture_failure`：`.local/instagram-errors/<uuid>/` 下写 `page.png` 与 `page.html`，结果文件记录 `stage/error/evidence_dir`（`main.py:542-550`）。verify/delete 同样保存 `page.png`、`page.html`（`posts.py:108-115`）。

### 5.7 重试语义

- 代码中没有任何自动重试/重发逻辑；发布只点一次（`main.py:473`）。
- 未知结果文案明确「禁止自动重发」，要求先人工核对（`main.py:44-49`）。
- 托管 provider 的 HTTP 429 也不重试（`utils/errors.py:27-33`）。

## 6. 账号与登录

| 维度 | 本地模式 | 托管模式（MLX / AdsPower） |
| --- | --- | --- |
| 账号文件 | `cookies/instagram_<account>.json`（`arguments.py:16-19`，`conf.py:3`） | 不读不写 cookie（`instagram.py:142-146`；`main.py:559-564`） |
| 登录命令 | `login` 人工登录（`main.py:217-245`） | 一律拒绝（`instagram.py:173`；`sau_commands/browser.py:313-322`） |
| 登录校验 | `instagram_cookie_auth`：先判未登录，再比对 cookie 文件 `ds_user_id` 与实时会话（`main.py:182-198,201-214`） | `is_logged_in(context)`：只判「已登录」，不比对身份（`main.py:124-159`） |
| 身份来源 | cookie 文件 + 导航头像链接 | 实时 cookie `ds_user_id` + 导航头像（`main.py:162-179`） |
| 身份提示 | 无 | INFO「账号一致性未校验」（`instagram.py:159-162,210-213`；`browser.py:287-297`） |
| 代理 | `--proxy` / `SAU_INSTAGRAM_PROXY` | `--proxy` 丢弃，出口 IP 归 Profile（`instagram.py:142-146`） |
| 会话持久化 | 成功后 `storage_state` 回写（`main.py:603-604`；`browser_session.py:189-200`） | 无回写（`main.py:641` 测试断言） |

`login` 细节：若已有 cookie 有效直接返回 `cookie_valid`；否则开可见 Chrome 到 `/accounts/login/`，等 `a[href^="/direct/inbox/"]` 可见（默认 900s），导出候选状态 → 新会话复验 → 替换正式文件（`main.py:217-245`）。

`check` 细节：本地打印 `valid`/`invalid`（`instagram.py:220-222`）；托管打印 `valid` 或抛 `LoginRequiredError`（`instagram.py:199-218`）。

`verify`/`delete` 始终本地：`require_account` + `resolve_account_file`（`instagram.py:181-193`），即使设置了托管凭据也不切 Profile（测试 `tests/test_adspower_article_identity_platforms.py:875-893`、`tests/test_adspower_cli.py:452-500`、`tests/test_multilogin_cli.py:390-425`）。

## 7. 测试覆盖

| 测试文件 | 覆盖点 | 关键位置 |
| --- | --- | --- |
| `tests/test_instagram_uploader.py` | 最终响应需匹配作者/配文/编号；`for(;;);` 前缀解析；`instagram_created_media` 拒绝 202/缺 media/fail | `25-35` |
| 同上 | 作品 URL 形状与非法域/端口拒绝 | `37-44` |
| 同上 | 2200 配文上限、视频+图片互斥 | `46-50` |
| 同上 | 发布前 deadline 异常类型与文案 | `52-60` |
| 同上 | 点击前后超时的异常类型区分 | `62-71` |
| 同上 | 结果未知仍先保存现场且保留退出码 9 语义 | `73-95` |
| 同上 | 真 Chrome：点击后无最终响应 → `PublishResultUnknownError` | `97-130` |
| 同上 | `verify`/`delete` CLI 可达且 `delete` 标志正确 | `132-139` |
| 同上 | `--thumbnail` 接线；非法封面在启动浏览器前失败 | `141-166` |
| 同上 | 通知/Reels 提示「出现/缺席/关闭失败」三分支（真 Chrome） | `170-223` |
| 同上 | 封面预览延迟替换、字节不符必须停在编辑页 | `225-273` |
| 同上 | 延迟登录页不误判；跨作者同文案拒绝；202 后必须等正式 media；只点一次 | `275-338` |
| `tests/test_mlx_meta.py` | 本地 launch/context 黄金参数、`INSTAGRAM_*` 常量 | `419-452` |
| 同上 | 本地上传保留身份比对与 cookie 回写 | `454-480` |
| 同上 | MLX 上传跳过身份文件与 cookie IO、只 `new_page` 一次 | `606-644` |
| 同上 | 上传中跳登录页 → `LoginRequiredError` | `646-660` |
| 同上 | `is_logged_in` true/false/异常矩阵（登录页、challenge、2FA、网络、5xx、外域） | `753-796` |
| 同上 | 托管 `check` 0/10/1；`upload-video`/`upload-note` 托管路径；未登录 10；失败 1；本地上传不触碰 `browser_session` | `1267-1445` |
| `tests/test_adspower_article_identity_platforms.py` | 托管上传不转发 `--proxy`；身份提示格式；launch kwargs 不转发；AdsPower 跳过身份文件比对；`verify/delete` 本地；托管下仍要求 `--account` | `195-229,330-350,660-700,757-800,875-960` |
| `tests/test_adspower_cli.py` | 托管模式下本地动作缺 `--account` → 退出 2 且不构造 cookie 路径 | `452-500` |
| `tests/test_multilogin_cli.py` | 同上（MLX 版） | `390-425` |
| `tests/test_adspower_platform_contract.py` | 扫描 `uploader/`、`sau_commands/`，禁止平台模块按 provider 名分支 | `18-45` |

未覆盖：真实账号端到端发布、Stories/feed video、地点/协作者/alt text（因为未实现）、图片数量上限、大文件/时长边界、`--not-before` 的端到端等待（仅 `publish_gate` 单测层面的语义在文档中描述，本文件未见 Instagram 专属测试）。

## 8. 实现状态三分法汇总

**已实现**：Reels（MP4/MOV）、单图、轮播（按序）、视频封面 + 字节级校验、标题/正文/标签合并 ≤2200、立即发布、`--not-before` 客户端闸门、15 分钟预算、结果文件与三态（`published`/`processing`/`submission_unknown`）、退出码 0/1/2/9/10/11、失败证据、verify、delete（移至最近删除）、本地 cookie 登录/校验、MLX/AdsPower 托管、代理（本地）。

**已校验但未暴露为 flag**：标题非空、2200 上限、封面扩展名白名单、视频/图片互斥、封面仅限视频。

**未实现**：`--schedule`、Stories、feed video 选择、alt text、location、collaborators、product tags、user tags、AI 标识、关闭评论、隐藏点赞、share to feed、audio/滤镜/裁剪/声音、首评、品牌内容、媒体大小/时长/宽高比校验、图片数量上限、发布后状态查询 API（只能 verify 已知 URL）、删除的批量/永久删除。

**代码中未明确**：`--debug` 在 Instagram 路径的作用；图片张数上限的具体数值（依赖平台）；平台侧对配文/媒体的归一化行为。

## 9. 与 Content Publishing API 的最明显缺口（供 04/05 使用）

1. **定时发布**：API 有 `scheduled_publish_time`；浏览器只有客户端 `--not-before`，结果 `schedule=None`（`main.py:453-461,510`）。
2. **媒体类型**：API 支持单图/轮播/Reels/feed video/Stories；浏览器只有 Reels + 图片（`main.py:508`，无 Stories/feed video 入口）。
3. **发布元数据**：alt text、location、collaborators、product tags、user tags、AI 标识、comments disabled、share to feed、cover/thumb offset、audio 全部无入口（`docs/CLI.md:616`）。
4. **容器语义**：API 是「建容器→轮询状态→publish」；浏览器无容器抽象，只旁听 `POST /api/v1/media/configure`，把 202 映射为 `processing`（`main.py:466-505`）。
5. **错误与幂等**：API 有结构化错误码/速率限制；浏览器只有「已点发布未确认→退出 9，禁止重发」，无幂等键、无发布后自动对账（`main.py:44-49`）。
6. **媒体约束前置校验**：API 有大小/时长/宽高比限制；代码只校验扩展名（`main.py:514-526`）。
7. **配文严格相等校验**：结果必须与本地 caption 完全一致，平台任何归一化都会失败（`main.py:266-267`），比 API 的「提交即返回 id」更脆弱。
