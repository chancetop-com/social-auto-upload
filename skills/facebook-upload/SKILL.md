---
name: facebook-upload
description: 使用 sau CLI 登录 Facebook 个人主页，立即发布视频或图文，查询原作品、移至垃圾箱或永久删除。
license: MIT-0
slug: social-auto-upload-facebook-upload
displayName: Facebook 个人主页发布
version: 1.0.0
summary: 管理 Facebook 个人主页登录、视频图文发布和作品核验。
---

# Facebook 个人主页发布与删除

若调度器已预下载远程素材，在上传命令中传 `--task-id <原任务ID> --prepared-media-only` 并沿用完整 URL。命令只读取该任务的缓存，缺少任一远程文件时在进入平台前退出 `1`。本地文件仍按原路径读取。

本 Skill 需要已安装的 `sau` CLI；独立安装 Skill 不会安装 Python 项目。若 `sau --help` 不可用，在项目根目录使用 Python 3.10–3.12 创建环境：`uv venv --python 3.11`，激活后 `uv pip install -e .`。首次没有 conf.py 时从 conf.example.py 复制，已有配置保留。

本地默认使用系统 Chrome、有头。Chrome 由用户正常安装；显式 Chromium 先在同一项目环境运行 `uv run patchright install --no-shell chromium`，再给动作传 `--local-browser chromium`。自定义可执行文件配置 `LOCAL_CHROME_PATH`，实际产品种类决定 Profile；路径优先于 `--local-browser`/`LOCAL_BROWSER`，无路径时显式选择 > `LOCAL_BROWSER` > chrome。只要求选定来源，失败不切换浏览器或模式。有头运行需可用桌面/显示服务；无头环境显式传 `--headless`。保留项目固定 Patchright，安装与运行使用相同 `PLAYWRIGHT_BROWSERS_PATH`（如设置）。

所有本地动作与直接调用采用显式 `--headed`/`--headless` 或布尔值 > `LOCAL_CHROME_HEADLESS` > False，已有 True 不覆盖。浏览器自然窗口、不固定 viewport、不修改界面语言。只有 login 引导登录；登录正常关闭后，用同一来源和别名 check。缺少 Profile/明确未登录/验证码退出 10；网络、权限、页面结构及启动故障退出 1，不能当作需要反复登录。浏览器来源或参数错误退出 2。

需要重建时运行 `sau facebook reset-profile --account creator --browser-kind chrome`（或 chromium）。它无需安装 binary，只删除指定平台/别名/种类，拒绝占用或归属不明资料。重建后先 login；不要因此重发旧任务。

本 Skill 调用现有 CLI。默认不配置代理，浏览器按系统网络直连；网络环境需要代理时显式传 `--proxy` 或设置 `SAU_FACEBOOK_PROXY`。传 `--proxy ""` 可忽略环境变量并直连。

```powershell
sau facebook login --account creator --headed
sau facebook check --account creator
sau facebook upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "正文 #生活 #分享"
sau facebook upload-note --account creator --images videos/demo1.png videos/demo2.png --title "图文标题" --note "正文"
```

登录、检查、视频/图文及作品管理均使用 `browser_profiles/<chrome|chromium>/facebook/<原始别名>`；浏览器保存登录态，旧 Cookie JSON 不读取、不导入或导出。与 `facebook-page` 的 Profile 完全隔离。别名允许重新登录其他真实账号，两类浏览器也可使用不同账号；原作者/作品证据仍须核对。`check` 验证个人主页登录态，不代表 Page 权限或作品发布结果。标题与正文合并为一段配文；公开话题写在正文里，旧 `--tags` 已移除，传入会退出 `2`。当前支持立即发布，未接入个人主页定时；Page 使用独立 `facebook-page` 命令。

取得原作品链接后管理作品：

```powershell
sau facebook verify --account creator --post-url "原作品链接" --owner-id "作者数字ID" --expected-text "原作品正文"
sau facebook delete --account creator --post-url "原作品链接" --owner-id "作者数字ID" --expected-text "原作品正文" --result .local/trash-result.json
sau facebook delete --account creator --post-url "原作品链接" --owner-id "作者数字ID" --expected-text "原作品正文" --from-trash --permanent --result .local/delete-result.json
```

删除前同时核对登录用户、作者、原作品编号和正文。默认移至垃圾箱，30 天后由平台删除，返回 `trashed`；加 `--permanent` 立即永久删除，已经在垃圾箱时再加 `--from-trash`。永久删除不可恢复。

`verify --from-trash` 查询垃圾箱原记录；`verify --deleted` 仅确认编号不在垃圾箱，返回 `absent_from_trash`，不能单凭缺席证明过去发生过永久删除。当前仅检索有限滚动范围的近期作品；没有找到或同文案无法唯一定位时明确失败。

只有平台出现本次提交的成功提示才认为发表已确认。点击后超时或浏览器断开应视为结果未知：先在同一账号个人主页或垃圾箱核对原作品，不重复上传或重复删除。本地素材不会被删除。Facebook 当前没有 no-publish 参数；不要用真实发表或删除来替代离线验收。退出 9 禁止自动重发，退出 10 若带 publish_attempted=true 也须先核对原作品。完整参数以 `sau facebook upload-video --help`、`upload-note --help`、`verify --help` 和 `delete --help` 为准。

## 托管浏览器模式（可选）

兼容 CLI 在同一台机器、同一操作系统用户下默认共享托管 Profile。不同平台各用新页，同一平台上的检查和发布合计限一条，冲突退出 `1`。Facebook 个人与 Page 可并行，两条 Page 命令即使指定不同主页也互斥。最后一条命令离开时关闭整个 Profile，包括桌面原有的标签页。

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check`、`upload-video` 和 `upload-note` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。`verify` / `delete` 仍为本地模式。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 托管 check/上传使用 `profile_id` 作为身份与日志标签，忽略 `--account`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 托管 headless 同样读取上述优先级，但忽略本地来源/路径/安装；verify/delete 仍要求本地 `--account` 并使用本地代理与配置。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。

## 示例脚本

`scripts/examples/` 下的文件是复制用示例，不是运行时依赖。执行前先查看当前 CLI 的 `--help`，替换账号、素材和正文；这些命令可能创建真实作品。

- `facebook_commands.ps1`：PowerShell
- `facebook_commands.sh`：Bash
- `facebook_cli_template.py`：Python subprocess
