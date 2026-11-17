---
name: alipay-upload
description: 使用 social-auto-upload 的 `sau alipay` 登录支付宝生活号并发布视频。Use when 用户要向支付宝生活号发布视频或检查创作账号状态。
license: MIT-0
slug: social-auto-upload-alipay-upload
displayName: 支付宝生活号视频发布
version: 1.0.0
summary: 登录支付宝生活号并发布视频，支持封面与合集。
---

# 支付宝生活号视频发布

调用现有 `sau alipay` CLI。首次使用前，用户需要在支付宝内容创作后台登录并确认账号已开通生活号内容创作权限。

```powershell
sau alipay login --account creator --headed
sau alipay check --account creator
sau alipay upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags 生活号,测试
```

当前仅支持视频，不支持图文、原生 `--schedule` 或 `--no-publish`；保留 `--not-before` 客户端发布闸门。可选 `--thumbnail` 指定封面，`--collection` 指定已有合集。账号名是本地会话别名；登录需要扫码时，把二维码图片展示给用户。

发布前核对账号、素材、标题、简介和标签。不要把 CLI 返回“已提交”扩大解释成审核通过或公开可见；结果不确定时先查支付宝后台，不盲目重试。

## 本地浏览器与登录

本地 login/check/upload-video 和直接 uploader 共用 `browser_profiles/<chrome|chromium>/alipay/<原始别名>`。默认系统 Chrome、有头；只需准备所选浏览器。选择完整 Chromium 时执行 `uv run patchright install --no-shell chromium` 并传 `--local-browser chromium`。`LOCAL_CHROME_PATH` 非空时优先并按实际浏览器种类选择资料；否则 `--local-browser` > `LOCAL_BROWSER` > chrome。显式 headed/headless 或直接调用布尔值 > `LOCAL_CHROME_HEADLESS` > False，保留用户现有 conf.py。失败不换来源/模式，不固定窗口或改语言；生活号 qiankun 微应用保持无 stealth。

浏览器自行保存状态，旧 Cookie JSON 不读写、不导入、不删除。别名可以重新登录其他真实账号，两种浏览器各自登录。只有 login 引导扫码；它保留二维码回调并以内容创作入口确认成功。先 login、正常关闭，再同配置 check。缺少 Profile、登录页/iframe 或验证退出 10（验证为 reason=verification）；网络、HTTP、超时、页面结构、权限或必需字段故障退出 1。退出 10 安排人工登录/验证；若有 publish_attempted=true，先核查作品。退出 9 表示发布结果未知，禁止自动重发；已派发后只观察，不因 AIGC 提示补点发布。

显式重建：`sau alipay reset-profile --account creator --browser-kind chrome`。无需 binary，只清空指定资料，保留另一浏览器、旧文件及历史结果；占用时拒绝接管，清空后重新 login。支付宝无不发布开关，安装与窗口验收使用离线替身/隔离受控页面，不提交真实视频。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check` 和 `upload-video` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式只采用上述 headless 优先级，忽略本地 browser/path 配置且不访问本地 Profile；`--account` 仅作日志标签，缺省为 `profile_id`；`login` 和 `reset-profile` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。
