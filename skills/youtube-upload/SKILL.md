---
name: youtube-upload
description: 使用 social-auto-upload 的 `sau youtube` 登录 YouTube、重建本地 Profile、上传或设置视频可见范围。Use when 用户要向 YouTube 发布视频或设置客户端 not-before 等待，或检查 Google/YouTube 登录状态。
license: MIT-0
slug: social-auto-upload-youtube-upload
displayName: YouTube 视频发布
version: 1.0.0
summary: 使用 sau 登录 YouTube、检查 Profile 并上传视频。
---

# YouTube 视频发布

调用现有 `sau youtube` CLI。登录在浏览器中完成 Google 账号登录，不使用二维码；账号名是本地会话别名。

```powershell
sau youtube login --account creator --headed
sau youtube check --account creator
sau youtube upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2 --visibility public
```

标题最多 100 个字符。`--visibility` 可选 `public`、`unlisted`、`private`，默认 `public`；`--thumbnail` 指定封面，`--playlist` 指定已有播放列表。当前只支持立即发布；`--schedule` 尚未实现，传入会退出 `2`。

## 本地运行与恢复

先准备选定来源：默认系统 Chrome，由用户按 Google 官方方式安装；显式 Chromium 用项目环境执行 `uv run patchright install --no-shell chromium`。保留现有 `conf.py`。`LOCAL_CHROME_PATH` 非空时优先并按实际产品识别种类；否则 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > `chrome`。显式 `--headed`/`--headless` > `LOCAL_CHROME_HEADLESS` > 有头；只检查所选来源，失败不回退。检查与上传内部预检使用相同配置。

账号别名定位 `browser_profiles/youtube/<原始别名>/<chrome|chromium>/`，登录、检查、上传复用它。别名可更换真实账号，两种浏览器可使用不同账号，上传使用当前频道。只在 login 中等待 Google 登录与验证；新 Profile 必须先登录，再同配置 check。常规命令不读写或删除旧 Cookie JSON。保留当前界面语言和自然窗口；需要网络代理时设置 `conf.py` 的 `YT_PROXY`，它对本地三项动作一致生效。

```bash
sau youtube login --account creator --local-browser chromium --headed
sau youtube check --account creator --local-browser chromium
sau youtube reset-profile --account creator --browser-kind chrome
```

reset-profile 显式清除指定种类，不需安装浏览器；保留其他种类、账号及历史结果，不自动登录或恢复旧任务。占用或重建失败退出 `1`，部分失败需修复后重跑同一命令。缺 Profile、明确未登录/验证退出 `10`；`reason=verification` 时先完成人机验证。配置用法错误为 `2`；来源、启动、网络、权限或页面故障为 `1`。退出 `9` 或 `publish_attempted=true` 表示可能已提交，先核查作品、禁止自动重发；单纯重建不证明可重发。

`--not-before "YYYY-MM-DDTHH:MM:SSZ"` 在内容准备完成后保持浏览器与 Profile 占用，等到指定 UTC 时刻才提交。YouTube 不提供 `--no-publish`；环境验证使用 login/check，不能把实际上传当不发布回归。安装成功、浏览器可启动和平台已登录分别验证。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check` 和 `upload-video` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 被忽略，日志标签使用 `profile_id`；`login` 和 `reset-profile` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。

```bash
# MLX
export MLX_API_TOKEN="<token>"
sau youtube check --folder-id <folder_id> --profile-id <profile_id>
sau youtube upload-video --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2 --visibility public

# AdsPower（--folder-id 可省略）
export ADSPOWER_API_KEY="$KEY"
sau youtube check --profile-id <profile_id>
sau youtube upload-video --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2 --visibility public
```

托管模式采用相同 headless 优先级，忽略 `LOCAL_BROWSER`、`--local-browser`、`LOCAL_CHROME_PATH` 和 `YT_PROXY`，出口 IP 由 Profile 决定。Profile 必须已人工登录且无待处理验证码/2FA。

发布前再次核对账号、视频、标题、说明、标签、可见范围及立即/not-before 意图。上传或发布遇到超时时先查 YouTube Studio 中的原视频，不盲目重传。上传成功不等于审核完成或公开视频已可播放。
