---
name: rednote-upload
description: 使用 sau rednote 登录、检查会话、上传视频或发布图文；用户指定 Rednote 或小红书国际版时使用。
license: MIT-0
slug: social-auto-upload-rednote-upload
displayName: Rednote 视频与图文发布
version: 1.0.0
summary: 使用独立 Rednote Profile 完成登录、检查及发布流程。
---

# Rednote 上传

1. 运行 `sau rednote --help` 确认安装支持此平台；命令不存在或浏览器缺失时，读取 [运行前提](references/runtime-requirements.md)。
2. 确认内容类型、账号及发布意图。测试接入时使用 `--no-publish`，只有用户要求发布时才省略该参数。干跑仍会向平台上传素材。
3. 本地先用 `sau rednote login --account <name> --headed` 登录，再用 `sau rednote check --account <name>` 检查。登录窗口与日常 Chrome 会话独立；等待 CLI 确认成功并关闭会话。仅 login 引导登录，业务中失效先结束本次命令。
4. 视频使用 `upload-video --file <path> --title <title> --desc <body>`；图文使用 `upload-note --images <paths...> --title <title> --note <body>`。可加 `--tags tag1,tag2`，完整参数查询各子命令的 `--help`。
5. 根据退出码报告结果：干跑成功仅表示发布前准备完成。`9` 或 `publish_attempted=true` 必须人工核对是否已发布；`10` 先恢复登录或完成人机验证。

默认域名为 `https://creator.rednote.com`，可用独立的 `SAU_REDNOTE_CREATOR_BASE_URL` 覆盖。身份只保存在 `browser_profiles/rednote/<原始别名>/<chrome|chromium>`：平台、别名、实际浏览器种类隔离；旧 JSON 不参与读写或清理。别名可重新登录不同账号。

默认系统 Chrome、有头且自然窗口；`--local-browser chromium` 选择配套完整 Chromium，`LOCAL_CHROME_PATH` 优先。显式 headed/headless 优先于 `LOCAL_CHROME_HEADLESS`，缺省为 False，保留已有配置。只准备选定来源，失败不自动切换。占用立即退出 1。明确要求清空时运行 `sau rednote reset-profile --account <name> --browser-kind chrome|chromium`，只清空指定种类，之后重新 login；无需安装浏览器，不自动恢复发布。

本地保留浏览器/Profile 语言，不添加 stealth、UA、请求头或 locale 覆盖，不自动切换语言。沿用小红书的人类化流程，只按实际页面差异调整；能用结构定位就不加文本兜底。确需文本时，只有取证后的英文、中文文案才可以按此顺序使用，不自行翻译。历史 Cookie/context 路径下封面、声明、话题、定时和扫码已实测；新持久化 Profile 的真实账号验收留待最终回归，不把历史记录当作当前登录证据。来源声明必须回读媒体名称或拍摄日期/地点；地点参数使用候选的完整名称，遇到重名停止。图文及 12 秒视频的原创开启已通过；当前页面在视频不足 10 秒或来源转载时禁用原创，不应误判成账号没有权限。纯英文界面和托管 Profile 仍待实际样本。显式封面/声明失败会停止。遇到控件缺失应记录现场差异，不能声称已发布。

托管模式：设置 `MLX_API_TOKEN` 后使用 `--folder-id` 和 `--profile-id`；设置 `ADSPOWER_API_KEY` 后仅使用 `--profile-id`。使用其中一种凭据，并在对应 Profile 人工登录；CLI `login` 仅支持本地模式。托管模式只采用同一 headless 优先级；忽略本地浏览器选择/路径，不访问本地 Profile 或 cookie，保留托管 Profile 设置。

设置声明、封面、定时或处理非零退出码前，读取随 Skill 分发的 [CLI 契约](references/cli-contract.md)。定时发布只在用户提出时使用 `--schedule`；客户端等待使用 `--not-before`，两者均要求 UTC。
