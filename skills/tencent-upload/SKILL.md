---
name: tencent-upload
description: 使用 social-auto-upload 的 `sau tencent` 登录视频号并发布或定时发布视频、保存草稿。Use when 用户要向微信视频号发布视频或检查视频号账号状态。
license: MIT-0
slug: social-auto-upload-tencent-upload
displayName: 微信视频号发布
version: 1.0.0
summary: 登录视频号并发布、定时发布或保存视频草稿。
---

# 视频号发布

调用现有 `sau tencent` CLI，不另写网页上传流程。先确认 `sau tencent --help`；账号名是本地会话别名。

```powershell
sau tencent login --account creator --headed
sau tencent check --account creator --headed
sau tencent upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags 视频号,测试
```

视频号仅支持视频发布。可选参数包括 `--schedule "YYYY-MM-DDTHH:MM:00Z"`、`--draft`、`--collection`、`--short-title`、`--category`、`--thumbnail-landscape` 和 `--thumbnail-portrait`。`--thumbnail` 是竖版封面的兼容参数。合集必须已存在。

本地资料为 `browser_profiles/<chrome|chromium>/tencent/<原始别名>`；login/check/视频及内部预检共用选定 Profile，旧 Cookie JSON 不读写、不导入或自动删除。仅 login 创建资料并等待扫码；生成二维码时直接展示图片。登录后正常关闭，再同配置 check；安装成功和浏览器可启动不证明平台已登录。

保留用户 `conf.py`。默认系统 Chrome、有头；Chrome 由用户安装，完整 Chromium 可用 `uv run patchright install --no-shell chromium` 准备。显式 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > `chrome`；`LOCAL_CHROME_PATH` 覆盖来源并按真实种类隔离 Profile。显式 headed/headless > `LOCAL_CHROME_HEADLESS` > False；只要求选定来源，失败不回退，不固定 viewport 或修改语言。

别名允许换号，两种浏览器资料独立。同 Profile 占用退出 1，等待原操作结束再使用；需要清空时显式执行 `sau tencent reset-profile --account creator --browser-kind chrome`（或 chromium），无需 binary，只删指定资料。重建后先 login，不能据此重跑旧发布任务。

缺少资料、未登录或人机验证退出 10；上传中的验证会结束本次业务，按提示在所选 Profile 完成后再安排操作。网络/页面/权限故障退出 1，不解释为登录失效。退出 9 或 `publish_attempted=true` 表示可能已提交，先到平台核查作品，禁止自动重发。定时仅在用户给出明确时间时使用；`--draft` 会写入平台草稿，不代表发布，也不是离线验证。视频号没有 `--no-publish`，验证改动使用离线替身或受控页面；不会新增图文入口。

发布前确认目标账号、视频、标题、简介、标签及立即发布/定时/草稿意图。只依据 CLI 输出和平台页面确认结果，不把命令启动成功当成发布成功。完整参数以 `sau tencent upload-video --help` 为准。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check` 和 `upload-video` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 托管忽略本地来源/路径，只采用相同 headless 优先级；reset-profile 拒绝。
- 使用托管模式前，读取运行 `sau` 的项目根目录 `docs/CLI.md` 的“托管浏览器模式（通用）”（[在线入口](https://github.com/dreammis/social-auto-upload/blob/main/docs/CLI.md#托管浏览器模式通用)），确认共同退出码、部署前提、调度责任与身份安全。
