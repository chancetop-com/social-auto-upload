---
name: baijiahao-upload
description: 使用 social-auto-upload 的 `sau baijiahao` 登录百家号、检查账号并发布视频。Use when 用户要向百家号发布视频或核验百家号登录状态。
license: MIT-0
slug: social-auto-upload-baijiahao-upload
displayName: 百家号视频发布
version: 1.0.0
summary: 登录百家号并发布视频，支持封面和合集。
---

# 百家号视频发布

调用现有 CLI，不另写上传流程。账号名是本地会话别名；发布前先查看 `sau baijiahao upload-video --help`。

```powershell
sau baijiahao login --account creator --headed
sau baijiahao check --account creator
sau baijiahao upload-video --account creator --file videos/demo.mp4 --thumbnail videos/demo.png --title "标题" --desc "简介" --tags 百家号,测试
```

当前仅支持视频，必须用 `--thumbnail` 指定横版封面，可选 `--collection` 指定已有合集；支持 `--not-before` 客户端发布闸门，不支持图文、原生 `--schedule` 或 `--no-publish`。登录出现二维码时把二维码图片展示给用户，等待扫码或人工验证；正常关闭后用同一配置 check。

本地 login/check/upload-video 和直接调用共用 `browser_profiles/baijiahao/<原始别名>/<chrome|chromium>`，浏览器自动持久化状态；旧 JSON 不读写或迁移。默认系统 Chrome、有头；只需安装所选来源，显式 Chromium 用项目固定 Patchright 的完整浏览器：`uv run patchright install --no-shell chromium`。自定义 `LOCAL_CHROME_PATH` 优先并按实际产品种类选资料，否则 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > chrome；显式 headed/headless > `LOCAL_CHROME_HEADLESS` > False，保留用户已有配置。失败不回退，不修改语言或固定窗口。

别名只管理资料，可以登录其他真实账号，两类浏览器各自登录。只有 login 引导登录/验证；其他动作缺少 Profile、明确未登录或验证码退出 10（验证保留 reason=verification），网络、权限、页面和必要字段故障退出 1。重建指定资料：`sau baijiahao reset-profile --account creator --browser-kind chrome`，无需 binary，保留另一浏览器、旧文件和历史结果；之后重新 login。Profile 占用时先结束占用者，不强制接管。

百家号没有不发布开关；回归使用离线替身或隔离受控页面，不能把真实视频提交当安装测试。

发布前核对账号、素材、标题、文案和标签。只有命令及平台提供的本次提交证据才表示成功；超时或状态不明（退出 9）时先去后台核查，不能直接重发。提交后登录/验证异常保留 `publish_attempted=true`，同样先核对作品；重建或重新登录不构成重发依据。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check` 和 `upload-video` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` / `reset-profile` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 托管模式同样采用上述 headless 优先级，忽略本地浏览器种类/路径；不访问本地 Profile 或锁。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。
