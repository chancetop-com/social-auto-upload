---
name: meta-upload
description: 使用 sau CLI 登录 Facebook Page，发布视频或图文、设置定时排期、查询原作品并删除。
license: MIT-0
slug: social-auto-upload-meta-upload
displayName: Facebook Page 发布
version: 1.0.0
summary: 发布 Facebook Page 视频或图文，并管理排期。
---

# Facebook Page 发布与删除

若调度器已预下载远程素材，在上传命令中传 `--task-id <原任务ID> --prepared-media-only` 并沿用完整 URL。命令只读取该任务的缓存，缺少任一远程文件时在进入平台前退出 `1`。本地文件仍按原路径读取。

本 Skill 调用现有 `sau facebook-page`，不重复实现浏览器逻辑。Instagram 已改为独立网页命令 `sau instagram`（见 `instagram-upload` Skill），不使用 Business Suite 绑定 Instagram。

默认不配置代理，浏览器按系统网络直连；网络环境需要代理时显式传 `--proxy` 或设置 `SAU_FACEBOOK_PAGE_PROXY`。

本地 login/check/视频/图文/verify/delete 使用 `browser_profiles/<chrome|chromium>/facebook-page/<原始别名>/`。一个登录 Profile 可管理多个 Page，`--page` 是发布目标，不能作为账号目录；资料与 `facebook` 隔离。别名可重新登录另一真实账号，原作品仍须核对 Page、编号和配文。

先准备所选浏览器，再登录：默认系统 Chrome、有头；保留已有 `LOCAL_CHROME_HEADLESS` 配置，显式 `--headed` / `--headless` 优先。`LOCAL_CHROME_PATH` 覆盖来源并按实际产品种类选 Profile；否则 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > `chrome`。Chrome 按官方方式安装；完整 Chromium 可用 `uv run patchright install --no-shell chromium`。只要求选定来源，失败不切换。保留当前语言、浏览器窗口和本地代理。

只有 login 引导登录；登录成功并关闭后以同配置 check。缺少 Profile、明确未登录或验证退出 `10`，验证先人工完成；网络、权限和页面故障退出 `1`。正常命令不读写、导入或删除旧 Cookie JSON。只需清空选定资料时运行 `sau facebook-page reset-profile --account creator --browser-kind chrome`（或 `chromium`）；命令无需浏览器，拒绝占用目标，保留另一种类、Facebook 资料和历史结果，不恢复旧发布任务。

先登录并检查：

```powershell
sau facebook-page login --account creator --headed
sau facebook-page check --account creator
sau facebook-page upload-note --account creator --page "我的 Page" --images videos/demo1.png --title "标题" --note "正文" --result .local/page-result.json
sau facebook-page upload-video --account creator --page "我的 Page" --file videos/demo.mp4 --title "标题" --desc "正文" --schedule "2026-10-21T02:30:00Z" --result .local/reel-result.json
```

视频与图文均可传 `--schedule "YYYY-MM-DDTHH:MM:00Z"`（UTC 绝对时刻，填写前换算到浏览器时区），至少提前 2 小时；留空立即提交。`--page` 填准确 Page 名称。公开话题写在 `--desc` / `--note` 里；旧 `--tags` 已移除，传入会退出 `2`。Page Reel 的独立关键词栏保留页面原值，CLI 不写入。传 `--proxy ""` 可忽略环境变量并直连。

结果默认保存到 `.local/meta-results/`，建议显式传 `--result`，避免手工抄写编号。`scheduled` 表示平台确认排期并核对原记录；`published` 表示图文已发布；视频立即提交在创建响应无错误且完成弹窗出现后返回 `processing`，表示平台已受理并正在处理，尚不能证明已公开播放，`content_id` 可能暂时没有。`submission_unknown` 只表示提交证据不足，必须先查询原记录，不重发。

用结果中的 Page ID、Page 名、内容编号和正文查询或删除：

```powershell
sau facebook-page verify --account creator --page "我的 Page" --page-id "Page数字ID" --content-id "内容编号" --expected-text "原作品正文" --scheduled
sau facebook-page delete --account creator --page "我的 Page" --page-id "Page数字ID" --content-id "内容编号" --expected-text "原作品正文" --scheduled --result .local/delete-result.json
```

`--scheduled` 选择定时列表；删除会取消排期并永久移除，返回 `deleted`。管理已发布作品时不加它，当前平台会移至垃圾箱，返回 `trashed`，30 天后自动删除；未接入 Page 垃圾箱提前永久删除。已定时作品实际发布后编号可能变化，需使用已发布列表中的编号。

提交后登录/验证异常保留 `publish_attempted=true`；结果未知退出 `9`，先核查原作品，再决定后续操作。本平台尚无 `--no-publish`，以上上传/删除命令会实际提交；本次持久化接入验证仅使用离线替身和受控页面。

只覆盖已加载的近期列表，不保证自动查找全部历史作品。同文案不能唯一定位、Page 或编号不符时不删除。删除后超时或浏览器断开时先核对原记录，不自动重删；本地素材保留。完整参数以 `sau facebook-page upload-video --help`、`upload-note --help`、`verify --help` 和 `delete --help` 为准。

## 托管浏览器模式（可选）

兼容 CLI 在同一台机器、同一操作系统用户下默认共享托管 Profile。不同平台各用新页，同一平台上的检查和发布合计限一条，冲突退出 `1`。Facebook 个人与 Page 可并行，两条 Page 命令即使指定不同主页也互斥。最后一条命令离开时关闭整个 Profile，包括桌面原有的标签页。

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check`、`upload-video` 和 `upload-note` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。`verify` / `delete` 仍为本地模式。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 托管 check/上传的身份由 `profile_id` 决定，`--account` 不决定本地资料；`login` 和 reset-profile 拒绝。请先在对应桌面应用中登录。headless 使用上述优先级，完全忽略本地浏览器选择和路径；verify/delete 仍要求原始 `--account`，使用本地 Profile、代理和运行配置。
- 使用托管模式前，读取运行 `sau` 的项目根目录 `docs/CLI.md` 的“托管浏览器模式（通用）”（[在线入口](https://github.com/dreammis/social-auto-upload/blob/main/docs/CLI.md#托管浏览器模式通用)），确认共同退出码、部署前提、调度责任与身份安全。

## 示例脚本

`scripts/examples/` 下的文件是复制用示例，不是运行时依赖。执行前先查看当前 CLI 的 `--help`，替换账号、素材和正文；这些命令可能创建真实作品。

- `meta_commands.ps1`：PowerShell
- `meta_commands.sh`：Bash
- `meta_cli_template.py`：Python subprocess
