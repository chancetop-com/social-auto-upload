---
name: hupu-upload
description: 使用 social-auto-upload 的 `sau hupu` 登录虎扑并发布视频，可指定封面。Use when 用户要向虎扑发布视频或检查虎扑账号状态。
license: MIT-0
slug: social-auto-upload-hupu-upload
displayName: 虎扑视频发布
version: 1.0.0
summary: 登录虎扑并发布视频，可指定封面。
---

# 虎扑视频发布

调用现有 CLI，不另写网页上传流程。账号名是本地 Profile 的管理别名，可重新登录不同真实账号。

```powershell
sau hupu login --account creator --headed
sau hupu check --account creator
sau hupu upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags 虎扑,测试 --thumbnail covers/demo.png
```

当前支持 login、check、upload-video、reset-profile，仅发布视频。标题 4–40 字，封面 `--thumbnail` 可省略；支持客户端 `--not-before`，没有原生 `--schedule` 或 `--no-publish`。

## 本地运行与登录

1. 保留已有 `conf.py`。本地默认系统 Chrome、有头；只准备选定来源：系统 Chrome、`uv run patchright install --no-shell chromium` 安装的完整 Chromium，或 `LOCAL_CHROME_PATH` 指定的可执行文件。路径优先于 `--local-browser chrome|chromium`，再优先于 `LOCAL_BROWSER`（缺省 chrome）。来源失败直接停止，不自动回退。
2. 显式 `--headed` / `--headless` 优先于 `LOCAL_CHROME_HEADLESS`（缺省 False）。login/check/上传及预检沿用同一配置；Chrome 与 Chromium 分开使用 `browser_profiles/<chrome|chromium>/hupu/<原始别名>`，可以各自登录不同真实账号。
3. 运行 login，在浏览器完成 QQ 扫码或必要验证。QQ iframe/popup、终端二维码及业务交互保留；浏览器自然窗口和现有语言保持不变。正常关闭后，用相同浏览器选择运行 check，看到 valid 才继续。旧 Cookie JSON 不参与，也不会自动删除。
4. 只有 login 引导登录。check/上传缺少 Profile、明确未登录或验证退出 10；验证保留 `reason=verification`，网络/页面/权限/必需字段故障退出 1。恢复登录后重新发起任务；提交后先核对作品，禁止自动重发。15 分钟预算与 not-before 保持；结果未知退出 9，`publish_attempted=true` 表示可能已经提交。
5. 用户明确要求清空资料时，运行 `sau hupu reset-profile --account creator --browser-kind chrome`（或 chromium）。命令无需 binary，只清空指定种类；占用时拒绝，其他 Profile、旧资料和历史结果保留。成功后重新 login。

没有 no-publish 开关，环境验收使用隔离受控页面；不要为测试提交真实视频。

发布前核对账号、视频、标题长度、简介、标签和封面。结果不明确时先查虎扑后台，不直接重发。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check` 和 `upload-video` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` 与 `reset-profile` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 托管忽略 `--local-browser`、LOCAL_BROWSER、LOCAL_CHROME_PATH；只采用相同 headless 优先级，不访问本地安装或 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。
