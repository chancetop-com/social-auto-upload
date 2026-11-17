---
name: weibo-upload
description: 使用 social-auto-upload 的 `sau weibo` 登录微博并发布视频，可指定封面。Use when 用户要向微博发布视频或检查微博账号状态。
license: MIT-0
slug: social-auto-upload-weibo-upload
displayName: 微博视频发布
version: 1.0.0
summary: 使用 sau 登录微博并发布视频，可指定封面。
---

# 微博视频发布

调用现有 CLI，不另写网页上传流程。账号名是本地 Profile 别名，可以重新登录另一真实账号；Chrome 与 Chromium 各自独立。

## 运行依赖与登录

Skill 只提供说明；执行需要包含微博接入的 social-auto-upload、Python 3.10–3.12 和项目固定版本的 Patchright。先确认 `sau weibo --help` 列出 login/check/upload-video/reset-profile，保留已有 `conf.py`。

默认使用系统 Chrome、有头且自然窗口。Chrome 按官方方式安装；选择完整 Chromium 时执行 `uv run patchright install --no-shell chromium`（CI/Linux 可加 `--with-deps`）。只安装所选来源；自定义 `LOCAL_CHROME_PATH` 优先，否则 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > chrome。显式 `--headed`/`--headless` > `LOCAL_CHROME_HEADLESS` > False，保留已有配置。启动失败按日志中的实际来源排查，不切换来源或模式，不修改页面语言。

```powershell
sau weibo login --account creator --headed
sau weibo check --account creator
sau weibo upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags 微博,测试 --thumbnail covers/demo.png
```

只有 login 创建 Profile 并引导扫码/验证。生成二维码时展示图片供用户扫码；正常关闭后同配置 check。资料位于 `browser_profiles/<chrome|chromium>/weibo/<原始别名>`，浏览器自动保存；旧 Cookie JSON 不读取、导入、写回或自动清理。命令可用、浏览器可启动、账号已登录分别报告。

## 发布与恢复

仅支持视频；标题最多 30 个字，封面必填且不超过 5 MB。`--collection` 选择已有或新建合集，`--not-before` 是客户端发布闸门；不支持图文、原生 `--schedule` 或 `--no-publish`。完整参数以 `sau weibo upload-video --help` 为准。预检和发布共用一个 Profile 占用；自然窗口下先滚动并关闭残留弹层，再校验按钮可交互及点击落点。

发布前核对账号、视频、标题、简介、标签和封面。缺少 Profile、明确未登录或验证退出 `10`，验证保留 `reason=verification`，用相同浏览器选择 login 完成人工恢复；业务不会等待登录后继续。页面、网络、权限或浏览器故障退出 `1`，用法错误退出 `2`。提交后 `publish_attempted=true` 或退出 `9` 都可能已经发布，先在微博后台核查原作品，禁止自动重发。环境回归使用离线或隔离受控页面，不以真实提交验收。

同一 Profile 占用时停止，不清锁或抢占。用户明确要求清空时执行 `sau weibo reset-profile --account creator --browser-kind chrome`（或 chromium），无需 binary，只删除指定种类，保留另一种类、旧文件及历史结果；部分失败修复后重跑明确目标，成功后先 login。重建不授权重发旧任务。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，check/upload-video 使用 provider Profile，其登录态和出口 IP 由 provider 决定。本地浏览器选择/路径忽略，仅采用相同 headless 优先级。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（对应 AdsPower user_id），`--folder-id` 忽略。
- `--account` 被忽略，日志标签采用 profile_id；login/reset-profile 拒绝，请先在对应桌面应用登录 Profile。
- 使用托管模式前，读取运行 `sau` 的项目根目录 `docs/CLI.md` 的“托管浏览器模式（通用）”（[在线入口](https://github.com/dreammis/social-auto-upload/blob/main/docs/CLI.md#托管浏览器模式通用)），确认共同退出码、部署前提、调度责任与身份安全。
