---
name: social-auto-upload
description: 为 social-auto-upload 提供总入口，按平台和内容类型选择对应发布流程。Use when 用户要在本仓库支持的平台发布视频或图文，或需要把内容分发到多个指定平台。
license: MIT-0
slug: social-auto-upload
displayName: social-auto-upload 多平台发布入口
version: 1.0.0
summary: 按用户指定的平台和内容类型选择发布流程。
---

# social-auto-upload 总入口

先确认用户指定的平台、内容类型、账号别名和发布方式。用户没有指定平台时先询问，不自行选择目标平台。

## 选择平台入口

| 平台 | 专用 Skill | CLI 平台名 |
| --- | --- | --- |
| 小红书 | `xiaohongshu-upload` | `xiaohongshu` |
| Rednote（国际版，初始适配） | `rednote-upload` | `rednote` |
| TikTok | `tiktok-upload` | `tiktok`（本地或托管浏览器模式） |
| YouTube | `youtube-upload` | `youtube` |
| Facebook 个人主页 | `facebook-upload` | `facebook` |
| Facebook Page | `meta-upload` | `facebook-page` |
| Instagram | `instagram-upload` | `instagram` |

## 本地浏览器准备

七个平台均使用 `browser_profiles/<chrome|chromium>/<平台>/<原始别名>`，仅 login 引导登录；正常关闭后以同配置 check。默认系统 Chrome 由用户按 [Google 官方指引](https://www.google.com/chrome/)安装；选择 Chromium 时用项目环境的 `uv run patchright install chromium`，可加 `--no-shell`，完整浏览器同时服务有头与无头。基础安装和 help 无浏览器要求。

保留已有 conf.py。非空 `LOCAL_CHROME_PATH` 优先，其次显式 `--local-browser` > `LOCAL_BROWSER` > chrome；显式 headed/headless > `LOCAL_CHROME_HEADLESS` > False。旧 Cookie 不读写，别名可换号。仅显式 `reset-profile --account <别名> --browser-kind chrome|chromium` 清空指定 Profile，无需 binary，保留另一种类和历史结果；占用时拒绝。

## 托管浏览器模式

七个平台均支持两种托管浏览器模式：

- **Multilogin X（MLX）**：设置 `MLX_API_TOKEN`；`check` / `upload-*` 需要 `--folder-id` 与 `--profile-id`。
- **AdsPower**：设置 `ADSPOWER_API_KEY`；只需要 `--profile-id`（映射 AdsPower `user_id`），`--folder-id` 忽略。

两种模式都使用 Profile 的登录态与出口 IP。托管检查和发布忽略 `--account`，身份和日志标签均取自 `--profile-id`。请先在对应桌面应用中登录。`verify` / `delete` 仍使用本地 Profile，`sau article` 在本地渲染原稿。

同机、同一操作系统用户的兼容 CLI 默认共享同一托管 Profile。不同平台可以同时执行，各自在新标签页工作。同一平台的检查和发布合计限一条命令，冲突者立即退出 `1`。**最后一条已加入的命令离开时会关闭整个 Profile，包括用户从桌面打开的标签页。**

## 指定发布时刻

所有 `upload-video` 和 `upload-note` 命令都支持 `--not-before "YYYY-MM-DDTHH:MM:SSZ"`。内容准备完成后，命令会等到该 UTC 时刻再提交。支持原生 `--schedule` 的平台可同时使用两者，此时 `--not-before` 应早于平台发布时间。支持 `--no-publish` 的入口在显式传入该参数后跳过等待，停在提交前。

## 人类化交互层

发布流程默认开启人类化交互（逐字符输入、人类指针点击），不需要任何参数。
设置 `HUMANIZE=0` 即整体退回原生输入与点击，这是唯一的运行时回滚开关。
发布链路出问题时先设 `HUMANIZE=0` 复现并确认是否仍存在，再按 `docs/CLI.md` 的「人类化交互层（全平台）」上报。

## 工作流程

1. 如已安装对应平台 Skill，先读取并遵循它；从仓库运行时读取 `skills/<skill-name>/SKILL.md`。
2. 若仓库可用，从 `skills/<skill-name>/SKILL.md` 读取平台说明；否则先提供对应安装命令。执行 CLI 前使用 `sau <平台> --help` 确认当前参数。不要猜测参数；TikTok 默认本地模式，设置 `MLX_API_TOKEN` 或 `ADSPOWER_API_KEY` 后为托管浏览器模式。
3. 先检查目标账号状态；登录需要用户在平台页面完成时，交给用户操作，不索取或保存密码。
4. 发布前核对文件、标题、文案、标签、可见范围、发布时间及目标账号。只发布用户明确指定的平台；同一份内容也要逐个平台核对要求。
5. 只有命令或平台提供本次提交的成功证据才报告已发布。超时或结果未知时先查原作品，不盲目重发。

## 安装入口

从公开 GitHub 仓库安装总入口：

```bash
npx skills add dreammis/social-auto-upload --skill social-auto-upload
```

指定平台时将 `social-auto-upload` 换成表格中的专用 Skill 名称。完整平台能力和分发状态见 GitHub 源仓库的 README 与分发文档。
