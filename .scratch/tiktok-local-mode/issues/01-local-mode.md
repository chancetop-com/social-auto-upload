# 01 — TikTok CLI 本地模式

Status: resolved
Type: task
Blocked by: 无
规格依据: [spec.md](../spec.md)

## What to build

让 `sau tiktok` 在未设置 `MLX_API_TOKEN` 时走本地 Chromium + cookie 文件路径，支持 `login`、`check`、`upload-video`、`upload-note`；MLX 模式行为不变。

## Acceptance criteria

- [x] 未设置/空/纯空白 `MLX_API_TOKEN` → 本地模式；非空 → MLX。
- [x] 本地模式 `--account` 必填，缺失退出 `2` 且在启动浏览器前失败；`--folder-id` / `--profile-id` 被忽略。
- [x] 本地 cookie 路径为 `cookies/tiktok_<account>.json`；MLX 不读写 cookie 文件。
- [x] `sau tiktok login` 始终打开有头浏览器，登录后回终端按 Enter 保存 cookie；非交互式终端明确报错。
- [x] 本地 `check` 有效 → `valid`/`0`，无效/缺失/登录页/5xx/网络错误/启动失败 → `invalid`/`1`。
- [x] 本地 `upload-video` / `upload-note` 复用 9 步上传骨架、发布选项、15 分钟预算与退出码 `9`。
- [x] `check` / `login` / 上传使用同一组本地 Chromium 启动参数。
- [x] MLX 的 `browser_session`、`is_logged_in`、退出码 `10`、`login` 拒绝行为不变。
- [x] 文档、Skill、CHANGELOG 更新，并标注明真实账号登录/发布“待验收”。
- [x] 离线测试覆盖本地成功/失败/缺 `--account`/`--headed`/cookie 路径/启动失败/不可读 cookie，且无 MLX 回归。

## Comments

- 已实现并合入 `integration/tiktok-browser-parity`（merge `ef9834b`，feature HEAD `d1ebcba`）；TikTok 专项 207 tests 全绿，全量 745 tests 仅保留既有基线 5 failures + 1 error + 2 skips；真实账号登录/发布未执行，保持“待验收”。
