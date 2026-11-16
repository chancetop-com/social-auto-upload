---
name: rednote-upload
description: 使用 sau rednote 登录、检查会话、上传视频或发布图文；用户指定 Rednote 或小红书国际版时使用。
license: MIT-0
slug: social-auto-upload-rednote-upload
displayName: Rednote 视频与图文发布
version: 1.0.0
summary: 使用独立 Rednote 账号和英文浏览器环境完成发布流程。
---

# Rednote 上传

1. 运行 `sau rednote --help` 确认安装支持此平台；命令不存在或浏览器缺失时，读取 [运行前提](references/runtime-requirements.md)。
2. 确认内容类型、账号及发布意图。测试接入时使用 `--no-publish`，只有用户要求发布时才省略该参数。干跑仍会向平台上传素材。
3. 本地先用 `sau rednote login --account <name> --headed` 登录，再用 `sau rednote check --account <name>` 检查。测试窗口与日常 Chrome 会话独立；用户完成登录后等待 CLI 保存成功。
4. 视频使用 `upload-video --file <path> --title <title> --desc <body>`；图文使用 `upload-note --images <paths...> --title <title> --note <body>`。可加 `--tags tag1,tag2`，完整参数查询各子命令的 `--help`。
5. 根据退出码报告结果：干跑成功仅表示发布前准备完成。`9` 或 `publish_attempted=true` 必须人工核对是否已发布；`10` 先恢复登录或完成人机验证。

默认域名为 `https://creator.rednote.com`，本地账号文件为 `cookies/rednote_<name>.json`；使用独立的 `SAU_REDNOTE_CREATOR_BASE_URL` 覆盖域名。保持与小红书账号隔离。

本地网页环境为 `en-US`，后台仍可能显示中文。沿用小红书的人类化流程，只按实际页面差异调整；能用结构定位就不加文本兜底。确需文本时，只有取证后的英文、中文文案才可以按此顺序使用，不自行翻译。封面、五种内容声明、原创开关、话题和定时已在英文 context 的实际中文后台干跑通过；无头扫码并在新浏览器复核也已通过。来源声明必须回读媒体名称或拍摄日期/地点；地点参数使用候选的完整名称，遇到重名停止。图文及 12 秒视频的原创开启已通过；当前页面在视频不足 10 秒或来源转载时禁用原创，不应误判成账号没有权限。纯英文界面和托管 Profile 仍待实际样本。显式封面/声明失败会停止。遇到控件缺失应记录现场差异，不能声称已发布。

托管模式：设置 `MLX_API_TOKEN` 后使用 `--folder-id` 和 `--profile-id`；设置 `ADSPOWER_API_KEY` 后仅使用 `--profile-id`。使用其中一种凭据，并在对应 Profile 人工登录；CLI `login` 仅支持本地模式。托管模式不读写本地 cookie，也不覆盖 Profile 的语言设置。

设置声明、封面、定时或处理非零退出码前，读取随 Skill 分发的 [CLI 契约](references/cli-contract.md)。定时发布只在用户提出时使用 `--schedule`；客户端等待使用 `--not-before`，两者均要求 UTC。
