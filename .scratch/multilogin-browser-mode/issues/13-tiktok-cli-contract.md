# 13 — TikTok CLI 接入契约（仅 MLX 模式）

Status: resolved
Type: grilling
Blocked by: 04, 06
Assignee: —

## Question

Ticket 04 已决定把 TikTok 接入 CLI，但**只在 MLX 模式可用**（无 `MLX_API_TOKEN` 时 `sau tiktok ...` 报错退出 1），实现只接 `uploader/tk_uploader/main_chrome.py`（Chromium/Mimic），Firefox 的 `main.py` 不接入。需要把这个新平台的契约定死，避免实现时照搬现有代码里的本地假设：

1. **命令面**：
   - 平台名是否就是 `tiktok`？注册哪些 action：`check`、`upload-video`，是否还注册 `login`（它只可能是“请到 Multilogin 登录”的拒绝路径）？
   - `upload-video` 的参数集是否与其它平台对齐：`--title`、`--video-file`、`--tags`、`--publish-date`、`--thumbnail`、`--account`、`--headless/--headed`？
   - 未注册的子命令保持 argparse 的退出码 2，注册但 MLX 拒绝的 `login` 退出 1——采用哪种？与 ticket 06 的全局 login 规则保持一致。

2. **账号与身份**：
   - MLX 模式没有 cookie 文件，`--account` 可省略；日志标签缺省用 `profile_id`（与 charter 一致）。是否仍接受 `--account` 作为纯日志别名？
   - `TiktokVideo.__init__` 现有 positional 参数（`title, file_path, tags, publish_date, account_file, thumbnail_path`）是否保持，新增 MLX 字段全部 keyword-only？

3. **uploader 改造**：
   - 现有 `TiktokVideo.upload(playwright)` 自己 `launch` + `new_context(storage_state=...)` + 结束时 `storage_state(path=...)` + `context.close()` + `browser.close()`。MLX 分支是拆出 `upload_with_context(context, ...)`，还是在类内按 ticket 06 的 `browser_session` 分支？
   - 现有 `change_language(page)` 会先访问 tiktok.com，若界面不是英文就点菜单改成 English (US)。MLX 下这会改写 Profile 的界面偏好，且依赖具体菜单文案。**是否改为“要求 Profile 已是英文界面，MLX 分支跳过 change_language”并在部署文档写明？**
   - `detect_upload_status` / `click_publish` 是 `while True` 无上限循环；MLX 分支是否统一加总超时（建议 10–15 分钟），超时退出 1，并在循环内识别验证码/二次验证页面后抛 `LoginRequiredError`（退出 10）？
   - page 选择遵循 ticket 02：优先按 URL 复用已有 page，其次 `pages[0]`，最后才新建；只支持视频（无图文 note）。

4. **登录检测 `is_logged_in(context)`**：
   - 现有 `cookie_auth()` 用 `select` 的 class 正则 `tiktok-.*-SelectFormContainer` 反推，ticket 03 已判定不可靠、必须新写。
   - 建议信号：打开 `https://www.tiktok.com/tiktokstudio/upload?lang=en`，出现上传入口（`button:has-text("Select video")` 或 `div.upload-container` / 上传 iframe）→ 已登录；出现登录表单/跳转到 `/login` → 未登录（退出 10）；网络错误/5xx/超时 → 抛异常（退出 1）。
   - 是否采用这个信号？超时预算（建议 15–30s）与最多打开几个 page（建议 1 个，用完即关）？

5. **范围边界**：
   - 本地模式（无 token）一律在 `run()` 入口拒绝，不进入任何浏览器代码；是否需要在 parser 层拒绝（退出 2）还是运行层拒绝（退出 1）？
   - 是否需要同步更新 README/CLI 帮助文本，注明“TikTok 仅 MLX 模式”？

## Context

- 平台决策表见 ticket 04：TikTok 的 `LOCAL_CHROME_PATH`、`storage_state` 在 MLX 下全部忽略。
- `uploader/tk_uploader/main_chrome.py` 目前没有接入 `sau_cli.py` 的 `PLATFORMS`，也没有对应的 `sau_commands/tiktok.py`。
- 现有登录函数 `get_tiktok_cookie()` 使用 `page.pause()`，依赖 Playwright Inspector，不适合 CLI；因为本地模式被排除，本 ticket 不需要重写本地登录，只需决定 `login` 命令的拒绝行为。
- 依赖 ticket 06 的 `browser_session` 契约与 `LoginRequiredError` 落点。

## Answer

决策（2026-11-05）。

### 1. 命令面

- 平台名：`tiktok`，注册进 `sau_cli.PLATFORMS`；实现只 import `uploader/tk_uploader/main_chrome.py`，`main.py` 不接入。
- Actions：`check`、`upload-video`、`login` 三个都注册。
  - `upload-video` 参数与仓库其它平台**对齐**（不采用 ticket 草稿里的 `--video-file` / `--publish-date` 命名）：

    | 参数 | 必填 | 映射到 `TiktokVideo` |
    |---|---|---|
    | `--file` | 是（`existing_file_path`） | `file_path` |
    | `--title` | 是 | `title` |
    | `--tags` | 否，逗号分隔 | `tags`（`parse_tags`） |
    | `--schedule` | 否，`%Y-%m-%d %H:%M` | `publish_date`（缺失为 `0`） |
    | `--thumbnail` | 否 | `thumbnail_path` |
    | `--account` | 否（MLX 下可省略） | 仅日志标签 |
    | `--headed` / `--headless` | 否（默认 headless） | MLX `headless_mode` |
    | `--debug` | 否 | 沿用 `add_runtime_flags` |
    | `--folder-id` / `--profile-id` | MLX 下必填 | `MultiloginTarget` |

    不支持图文/note，不注册 `upload-note`。
  - `check` 参数：`--account`（可选）、`--folder-id` / `--profile-id`、`--headless/--headed`（MLX 下有意义）。
  - `login`：注册但**永不执行浏览器代码**。MLX 模式 → 提示去 Multilogin 登录，退出 **1**（ticket 06 统一规则）；本地模式 → 提示“TikTok 仅支持 Multilogin 模式”，退出 **1**。
- 未注册的子命令仍由 argparse 退出 **2**；注册后的拒绝是运行层 **1**。

### 2. 账号与身份

- `--account` 可省略；MLX 缺省 label = `profile_id`（ticket 06 / charter）。它只是日志别名，不参与登录检测。
- `TiktokVideo.__init__` 的 positional 顺序**完全保持**：`(title, file_path, tags, publish_date, account_file, thumbnail_path=None)`。
  - 不新增构造参数；`account_file` 的类型放宽为 `str | None`（MLX 传 `None`）。
  - `headless` 仍由 `browser_session` 控制，不塞进 `__init__`；`self.headless = LOCAL_CHROME_HEADLESS` 只服务于 legacy `upload()`。
- 身份一致性按 ticket 12：只判“已登录”，不比对账号。

### 3. uploader 改造

- 按 ticket 06 的 seam：`upload(self, playwright, *, session: BrowserSession | None = None)`；`session` 非空时调用拆出的 `upload_in(session)`，不 launch、不 `new_context`、不 `set_init_script`、不写 `storage_state`、不 close。
- `main_chrome.py` 的 import 从上游 `playwright.async_api` 改为 `patchright.async_api`（与其它 uploader 一致，避免 CLI 同时装两套客户端）；`main.py` 不动。
- **`change_language`：MLX 分支跳过**。部署前提写明 Profile 界面语言必须为 English (US)；页面非英文时上传流程失败退出 1，不自动改 Profile 偏好。URL 继续带 `?lang=en` 作为辅助。
- **无限循环统一加总超时**：`detect_upload_status` / `click_publish` 的 `while True` 在 MLX 分支改为带 deadline 的实现，总预算 **15 分钟**；超时抛 `RuntimeError`（退出 1）。循环内若出现验证码/二次验证/登录页 → 抛 `LoginRequiredError`（退出 10）。
- page 选择按 ticket 02：优先复用 URL 匹配的已有 page → 其次 `pages[0]` → 最后 `context.new_page()`；用完不主动关已有 page。仅视频。

### 4. `is_logged_in(context)`

- 新写 `async def is_logged_in(context: BrowserContext) -> bool`，放在 `main_chrome.py`（紧挨 `cookie_auth`）；现有 `cookie_auth` 保留给本地模式（虽不暴露 CLI）。
- 行为：
  1. 取 1 个 page（复用优先，其次 `pages[0]`，最后新建并负责关闭）；
  2. `goto("https://www.tiktok.com/tiktokstudio/upload?lang=en", wait_until="domcontentloaded", timeout=20000)`；
  3. 出现上传入口（`button:has-text("Select video")`、`div.upload-container` 或上传 iframe）→ `True`；
  4. 跳到 `/login`、出现登录表单/扫码/手机号入口 → `False`；
  5. 网络错误、5xx、超时、结构无法判定 → **抛异常**（退出 1），不返回 `False`；
  6. `finally` 关闭本次新建的 page。
- 总预算 20s，只开 1 个 page；不调用 `change_language`。
- 采用草稿建议的信号，不保留 `select` class 正则反推。

### 5. 范围边界与文案

- **本地模式一律在 `run()` 入口拒绝（退出 1），不进入任何浏览器代码**；不在 parser 层拒绝（否则是 2，与 ticket 06 的 login 规则不一致）：

  ```
  TikTok 仅支持 Multilogin 模式：请设置 MLX_API_TOKEN，并提供 --folder-id / --profile-id。
  ```

- `login` 文案：
  - MLX：`Multilogin 模式不支持 CLI 登录；请在 Multilogin 应用中登录 Profile {profile_id} 后重试。` → 1
  - 本地：上面的“TikTok 仅支持 Multilogin 模式” → 1
- 文档：
  - README / `docs/CLI.md` 增加 tiktok 小节，注明“仅 MLX 模式、需英文界面、无本地登录”；
  - `skills/tiktok-upload/SKILL.md` 目前写着“TikTok 当前没有 `sau tiktok` 命令”，实现时同步更新为 MLX-only 用法，并移除 `cookies/tk_uploader/account.json` 的本地路径描述。

### 6. 退出码

| 场景 | 码 |
|---|---|
| check 已登录 / upload 成功 | 0 |
| 未登录 / 验证码 / 2FA | 10 |
| 本地模式调用 tiktok、`login`、网络错误、超时、上传失败 | 1 |
| 缺参数 / 未知子命令 | 2 |

### 对下游 ticket 的约束

- **ticket 09**：平台表新增 tiktok 行，写明“仅 MLX、英文界面、无本地登录、无图文”；验收清单加“无 token 时退出 1”和“验证码退出 10”。
- **ticket 07**：TikTok 纳入 `test_mlx_platform_contract.py` 的逐平台表（禁止调用 + `is_logged_in` 三分支）。
- **ticket 11**：`main_chrome.py` 必须与其它 uploader 使用同一个 patchright 客户端版本。
