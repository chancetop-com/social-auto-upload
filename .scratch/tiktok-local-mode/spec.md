# TikTok CLI 本地模式 — 实施规格

- 状态：实现中；真实账号登录/发布验收未执行（与 ticket 19 同样属外部依赖）。
- 背景：`tiktok-browser-parity` 只交付了 Multilogin（MLX）模式。本次扩展让 `sau tiktok` 在未设置 `MLX_API_TOKEN` 时走原有本地 Chromium + cookie 文件路径；MLX 行为不变。

## 1. 目标

1. 未设置 `MLX_API_TOKEN`（或为空/纯空白）时，`sau tiktok` 进入本地模式，而不是直接退出 `1`。
2. 本地模式支持 `login`、`check`、`upload-video`、`upload-note`。
3. 本地 cookie 路径统一为 `cookies/tiktok_<account>.json`（通过 `resolve_account_file("tiktok", account)`）。
4. 本地模式复用现有 `TiktokBaseUploader` 的 9 步流程、发布循环、发布选项与退出码 `9` 语义。
5. MLX 模式的参数、行为、退出码、cookie 隔离保持完全不变。

## 2. 模式激活与参数

| 条件 | 模式 | `--account` | `--folder-id` / `--profile-id` |
| --- | --- | --- | --- |
| `MLX_API_TOKEN` 非空 | Multilogin X | 可选，缺省为 `profile_id` 作为日志标签 | 必填 |
| `MLX_API_TOKEN` 未设置/空/纯空白 | 本地 | **必填** | 忽略 |

- 本地模式缺少 `--account` → `UsageError`，退出 `2`，且在启动浏览器前失败。
- MLX 模式 `login` 继续拒绝（退出 `1`）。
- 本地模式 `login` 可用。

## 3. 本地登录

- `sau tiktok login --account <name>`：
  1. 打开**有头** Chromium，进入 `https://www.tiktok.com/login?lang=en`。即使已有有效 cookie，也必须重新打开登录页（`force`），方便切换账号。
  2. 提示用户在浏览器中完成 TikTok 登录，然后回到终端按 Enter。
  3. 保存 `storage_state` 到 `cookies/tiktok_<account>.json`。
  4. 再用 `cookie_auth` 复核一次；无效则退出 `1`。
- 非交互式终端（`stdin` 不是 TTY）→ 明确报错退出 `1`，不静默挂起。
- `login` 不注册 `--folder-id` / `--profile-id`（仓库跨平台契约）；传了会由 argparse 退出 `2`。这两个参数只用于 `check` / `upload-*`。MLX 下 `login` 仍拒绝退出 `1`。
- 不实现 QR / 无头登录；这不是本次目标。

## 4. 本地 check

- `sau tiktok check --account <name>`：
  - 使用本地 cookie 文件校验 TikTok Studio 上传页。
  - 有效 → stdout `valid`，退出 `0`。
  - 无效/缺失/登录页/5xx/网络错误/浏览器启动失败/cookie 文件不可读（损坏 JSON）→ stdout `invalid`，退出 `1`。
  - 缺失 `--account` → 退出 `2`。
- MLX `check` 保持 `0` / `10` / `1` / `2` 语义不变。

## 5. 本地上传

- `upload-video` / `upload-note`：
  - 先 `tiktok_setup(handle=False)` 校验 cookie；缺失/失效时提示先运行 `sau tiktok login --account <name>`，退出 `1`。
  - 用本地 Chromium 启动、读完 cookie 后执行与 MLX 相同的 `_upload_on_page` 九步流程。`check` / `login` / 上传必须使用同一组 `TIKTOK_LAUNCH_KWARGS`，避免校验的浏览器与实际发布浏览器不一致。
  - 上传结束后写回 cookie 文件。
  - 总预算沿用 15 分钟（`TIKTOK_PUBLISH_TIMEOUT_SECONDS`），避免进程无限挂起。
  - 发布结果未知仍按 `PublishResultUnknownError` → 退出 `9`；从未点击发布 → `1`。
  - 本地模式不调用 `_raise_if_login_required`（历史本地行为）；登录失效通常表现为运行失败 `1`，用户需重新 `login`。
- `--headless` / `--headed` 透传到本地 Chromium；`login` 始终有头。
- 图片/视频参数校验、发布选项、回读、封面、定时、Photos tab 探测全部复用 MLX 已有实现。

## 6. 非目标

- TikTok Content Posting API、OAuth、开发者 App。
- QR 扫码登录、无头登录、自动处理验证码/2FA。
- Firefox 版 `uploader/tk_uploader/main.py` 接线。
- 改变 MLX 的 Profile/日志/退出码契约。
- 真实账号发布验收（外部依赖；与 ticket 19 一并保持“待验收”）。

## 7. 验证

- 离线 `unittest`：
  - 本地 `check` 有效/无效/缺 `--account`。
  - 本地 `login` 成功/失败。
  - 本地 `upload-video` / `upload-note` 使用 cookie 路径、调用 `upload(playwright)` 而不是 `browser_session`。
  - 本地 cookie 缺失时退出 `1` 且不启动上传。
  - 本地模式不再出现“仅支持 Multilogin”的拒绝。
  - MLX 上传不解析 cookie 文件、不进入本地分支。
- `git diff --check` 干净。
- 默认真实账号登录/发布未执行，文档与 CHANGELOG 标注“待验收”。
