# social-auto-upload

![Python](https://img.shields.io/badge/Python-3.10--3.12-3776AB?logo=python&logoColor=white)
![License](https://img.shields.io/github/license/dreammis/social-auto-upload)
![Release](https://img.shields.io/github/v/release/dreammis/social-auto-upload?display_name=tag)
[![Agent Skills](https://img.shields.io/badge/Agent%20Skills-8-0D9488?logo=github)](./docs/skill-distribution.md)

`social-auto-upload` 是一个面向内容创作者和运营者的多平台发布工具，提供统一 CLI 和供 Codex、OpenClaw、Claude Code 等 Agent 使用的 Skill。

支持七个平台的视频发布，其中六个平台也提供图文发布。文章可用 `sau article` 在本地渲染。

CLI 命令按平台维护在 `sau_commands/`，发布流程位于 `uploader/`。日常变更记录见 [CHANGELOG.md](./CHANGELOG.md)，稳定版本通过 GitHub Release 发布。

<img src="media/show/tkupload.gif" alt="tiktok show" width="800"/>

## 💎 赞助商

<table width="100%">
 <tr>
    <td width="25%" align="center" valign="middle">
      <a href="https://chilltion.com/?ref=1y5k5k">
        <img src="static/DolOffer.png" alt="DolOffer Sponsor" width="180">
      </a>
    </td>
    <td width="75%" align="left" valign="middle">
      感谢 <a href="https://doloffer.com/" target="_blank">DolOffer</a> 对本项目的支持！对于做内容矩阵、多平台分发和 AI 自动化运营的创作者来说，ChatGPT、Claude、YouTube Premium、Spotify、Apple Music、Notion、Office 等数字工具往往是长期成本。DolOffer 提供 AI、视频、音乐和效率工具相关的订阅与充值服务，帮助用户更低成本地配置常用数字产品。更多说明可查看 <a href="https://github.com/Doloffer-g/guide" target="_blank">DolOffer Guide</a>。使用优惠码 <code>AI8888</code> 可额外享受 9 折优惠，具体价格和服务规则以官网为准。  
    </td>
  </tr>
  <tr>
    <td width="25%" align="center" valign="middle">
      <a href="https://chilltion.com/?ref=1y5k5k">
        <img src="static/chilltion.png" alt="chilltion Sponsor" width="180">
      </a>
    </td>
    <td width="75%" align="left" valign="middle">
      轻视AI：一句话生产MG动画，适合知识，科普，讲解，教程，介绍等类型视频的低成本制作，视频矩阵，养号等，成本只有seedance等1%。现在<a href="https://chilltion.com/?ref=1y5k5k">注册</a>送1500积分
    </td>
  </tr>
    <tr>
        <td width="25%" align="center" valign="middle">
          <a href="http://t.clawpower.vip/1005">
            <img src="static/clawpower.png" alt="ClawPower Sponsor" width="180">
          </a>
        </td>
        <td width="75%" align="left" valign="middle">
          ClawPower 是一家稳定可靠 AI 大模型中转服务商，提供 Claude、GPT、Gemini 60+ 大模型接入。无论是 OpenClaw、Hermes 智能体自动化场景，Claude Code、Codex 编程工具接入，还是公众号、小红书内容创作；都能获得稳定、顺滑、可长期使用的模型服务体验。低至官方价格的 30%，点击<a href="http://t.clawpower.vip/1005">免费领取 5 刀现金</a>体验券
        </td>
      </tr>
  <tr>
    <td width="25%" align="center" valign="middle">
      <img src="static/wechat.png" alt="Sponsor Contact" width="150">
    </td>
    <td width="75%" align="left" valign="middle">
      <strong>成为赞助商</strong><br>
      如果您有意赞助本项目，请扫描左侧微信二维码（添加时请注明来意：<strong>赞助</strong>）。
    </td>
  </tr>
</table>

---


## 目录

- [💡 功能特性](#功能特性)
- [💾 安装指南](#安装指南)
- [🤖 AI Agent](#ai-agent)
- [🏁 快速开始](#快速开始)
- [📝 更新日志](./CHANGELOG.md)
- [📃 详细文档](#详细文档)
- [🐾 交流与支持](#交流与支持)
- [🤝 贡献指南](#贡献指南)
- [📜 许可证](#许可证)
- [⭐ Star History](#star-history)

## 💡功能特性

| 平台 | 登录/账号准备 | 视频 | 图文 | 原生定时 | CLI 入口 | Skill | 说明 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 小红书（浏览器版） | ✅ | ✅ | ✅ | ✅ | `xiaohongshu` | ✅ | 视频与图文发布 |
| Rednote（国际版） | ✅ | 实验性 | 实验性 | 实验性 | `rednote` | ✅ | [本地登录及发布前准备已验收](./docs/rednote.md)，最终提交尚未实测 |
| TikTok | ✅ | ✅ | ✅ | ✅ | `tiktok` | ✅ | 视频与图文发布；支持本地模式与托管浏览器模式（MLX / AdsPower）；托管下 Profile 界面需 English (US) |
| YouTube | ✅ | ✅ | - | - | `youtube` | ✅ | 视频发布 |
| Facebook | ✅ | ✅ | ✅ | - | `facebook` | ✅ | 支持作品查询、移至回收站及永久删除 |
| Facebook Page | ✅ | ✅ | ✅ | ✅ | `facebook-page` | ✅ | 支持视频与图文定时发布、查询和取消定时 |
| Instagram | ✅ | ✅ | ✅ | - | `instagram` | ✅ | 支持 Reels、单图与轮播 |

`实验性` 表示最终提交尚未通过真实账号验收。各平台的 `check`、`upload-video` 及表中支持的 `upload-note` 均可使用本地、AdsPower 或 Multilogin X 模式。


## 💾安装指南

### 自己上手使用

普通用户可按以下文档安装和更新：

- [安装说明](./docs/install.md)
- [更新说明](./docs/update.md)

基础安装 `uv pip install -e .` 只安装项目依赖，不下载或检查浏览器。七个平台默认使用系统 Chrome 和专用持久化 Profile；Chrome 由用户按 [Google 官方指引](https://www.google.com/chrome/)安装，项目不自动安装/更新。可选完整 Chromium 或 `LOCAL_CHROME_PATH` 指定的兼容 binary，只需准备实际来源。托管动作无需本地 Chrome/Chromium。升级保留已有 `conf.py`，包括 `LOCAL_CHROME_HEADLESS=True`；显式 `--headed` / `--headless` 优先。

#### 可选的两条 CI 安装路线

下面是已准备 Python 3.11、uv 和源码的 **Ubuntu 24.04 x64** 示例，未在本次 macOS 验收中执行，也不新增 workflow。先 `uv sync --locked --python 3.11`，按来源任选一条。

系统 Chrome 使用 Google 官方 amd64 DEB；已有兼容安装时复用：

```sh
curl --fail --location --retry 3 https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb --output /tmp/google-chrome.deb
sudo apt-get update
sudo apt-get install -y /tmp/google-chrome.deb xvfb xauth
uv run patchright install-deps chromium
google-chrome --version
```

配套完整 Chromium 使用锁定 Patchright 的安装器，无需 Chrome：

```sh
sudo apt-get update
sudo apt-get install -y xvfb xauth
uv run patchright install --with-deps chromium
# 可选替代上一行：uv run patchright install --with-deps --no-shell chromium
```

无显示的有头命令加 `xvfb-run -a`；Chromium 命令显式加 `--local-browser chromium`，有头/无头均用完整浏览器，只有 headless shell 不够。Chrome DEB 是滚动 stable，记录实际版本；Chromium 缓存按系统/架构及固定 Patchright 版本区分，安装和运行保持相同 `PLAYWRIGHT_BROWSERS_PATH`。已有兼容 binary 可由 `LOCAL_CHROME_PATH` 复用，仍需系统库及相应显示服务。详细依赖、缓存和验证边界见[两条 CI 路线](./docs/install.md#可选-ci-环境两条独立路线)；安装成功、浏览器可启动和平台已登录分别验证。


### AI Agent

若使用 `OpenClaw`、`Codex` 或 `Claude Code` 安装和操作本项目，可将仓库与启动提示词一并交给 Agent：

- [Agent Bootstrap Prompt](./docs/agent-bootstrap.md)

它会引导 Agent：

- 优先按当前主线安装项目
- 优先使用 `uv`、`sau` CLI 和 `skills/`
- 用 `sau --help` 和目标平台的 `--help` 核对已安装的入口


相关入口：

- [CLI 使用说明](./docs/CLI.md)
- [Agent Bootstrap Prompt](./docs/agent-bootstrap.md)
- 跨平台总入口：[social-auto-upload](./skills/social-auto-upload/SKILL.md)
- 各平台 Skill 见 [小红书](./skills/xiaohongshu-upload/SKILL.md)、[Rednote](./skills/rednote-upload/SKILL.md)、[TikTok](./skills/tiktok-upload/SKILL.md)、[YouTube](./skills/youtube-upload/SKILL.md)、[Facebook](./skills/facebook-upload/SKILL.md)、[Facebook Page](./skills/meta-upload/SKILL.md)、[Instagram](./skills/instagram-upload/SKILL.md)。

#### Skill 分发与市场

仓库提供一个跨平台总入口和七个独立平台 Skill。各市场收录、上架方式和新增平台检查清单见[Skill 分发渠道与发布状态](./docs/skill-distribution.md)。

Skill 目录可从 GitHub 安装到兼容 Agent。安装单个 Skill：

```bash
npx skills add dreammis/social-auto-upload --skill xiaohongshu-upload
```

将 `xiaohongshu-upload` 换成总入口或其他平台目录名。各目录对应关系、市场上架方式和状态见 [Skill 分发说明](./docs/skill-distribution.md)。


## 🏁快速开始

### 使用 CLI

按上方平台能力表确认目标账号使用的 CLI 入口和可发布的内容类型。

#### 账号准备

每个平台先登录一次，再检查会话。`--account` 是你给本地会话取的名字，例如 `creator`，用于区分多个账号。

```bash
sau xiaohongshu login --account creator
sau xiaohongshu check --account creator
```

Rednote 的 login/check/视频/图文已使用独立持久化 Profile，默认 Chrome 有头、可选 Chromium/自定义路径，并保留已有 headless 配置。登录态不再依赖旧 Cookie JSON；真实 Profile 验证范围见[最终验收记录](./.scratch/local-chrome-profile-implementation/research/20-final-validation.md)。见 [Rednote 说明](./docs/rednote.md)。

七个平台均提供显式本地 Profile 重建命令。指定浏览器种类和别名后，只清空对应的专用资料。见[重建说明](./docs/CLI.md#重建本地浏览器-profilereset-profile)。

#### 指定发布时刻（可选）

所有发布命令都支持 `--not-before "YYYY-MM-DDTHH:MM:SSZ"`（UTC 绝对时刻，解析后换算到运行机器本地时区）：先完成素材上传与内容编辑，到目标时刻后才点击发布。支持原生定时的平台可同时使用 `--schedule`。

```bash
sau xiaohongshu upload-video --account creator --file videos/demo.mp4 --title "新视频" \
  --not-before "2026-12-01T12:00:00Z"
```

详见 [CLI 使用说明的客户端发布闸门](./docs/CLI.md#客户端发布闸门--not-before)。

#### 托管浏览器模式（可选）

七个平台的登录检查和发布都可以使用已登录的托管 Profile。设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower），两个凭据同时设置会退出 `1`。

同机、同一操作系统用户的兼容 CLI 默认共享同一托管 Profile。不同平台可以同时执行，各自在新标签页工作。同一平台的检查和发布合计限一条命令，冲突者立即退出 `1`。**最后一条已加入的命令离开时会关闭整个 Profile，包括用户从桌面打开的标签页。**

将下例中的 `PROFILE_ID`、`FOLDER_ID` 换成桌面应用中的标识。

##### Multilogin X（MLX）

```bash
export MLX_API_TOKEN="<token>"

# check：0=已登录，10=需要人工登录
sau xiaohongshu check --folder-id "FOLDER_ID" --profile-id "PROFILE_ID"

# 上传使用 profile_id 选择身份和日志标签
sau xiaohongshu upload-video --folder-id "FOLDER_ID" --profile-id "PROFILE_ID" \
  --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
```

MLX 通过本机 Multilogin Launcher 启动 Profile；`--folder-id` / `--profile-id` 必填，Profile 使用 Mimic 内核。

##### AdsPower

```bash
export ADSPOWER_API_KEY="$KEY"

# check：0=已登录，10=需要人工登录
sau xiaohongshu check --profile-id "PROFILE_ID"

# 上传：--folder-id 可省略；传了也会静默忽略
sau xiaohongshu upload-video --profile-id "PROFILE_ID" \
  --file videos/demo.mp4 --title "示例标题" --desc "示例简介"

# 需要人工处理验证码时使用有头模式
sau xiaohongshu upload-video --headed --profile-id "PROFILE_ID" \
  --file videos/demo.mp4 --title "示例标题"
```

AdsPower 通过 Local API（默认 `http://127.0.0.1:50325`）启动 Chromium Profile；`--profile-id` 映射 AdsPower 的 `user_id`，`--folder-id` 忽略。只支持 V2 API，客户端请升级到最新 patch。

共同说明：

- 托管检查和发布忽略 `--account`，使用 `--profile-id` 选择 Profile。本地浏览器动作使用 `--account` 定位专用 Profile。
- 托管模式下 `login` 一律拒绝；请先在对应桌面应用中登录 Profile，并处理验证码/2FA。托管模式不提供 CLI 登录链路。
- 退出码：`0` 成功、`1` 运行失败、`2` 用法错误、`9` 发布结果未知、`10` 需要登录、`11` 请求过于频繁（429）、`130` 用户中断。**MLX 的 429 已由 `1` 改为 `11`**，调度层需改为退避重试。
- 收到 `9`（发布结果未知）时**禁止自动重发**：发布点击已发出但未确认成功，先到平台后台（如 TikTok Studio → Content/Posts）按标题、素材与发布时间核对；已存在不要重发，不存在才可人工重试。
- 部署前提：MLX 需 CLI 与 Multilogin 桌面应用同机、Launcher 可用、Profile 使用 Mimic 内核；AdsPower 需付费版、桌面应用与 CLI 同机、Local API 已开启、Profile 为 Chromium 内核。两者都要求 Profile 已人工登录且无待处理验证码/2FA，TikTok 的 Profile 界面须为 English (US)。
- 不支持：Docker / 跨机 / Linux 无桌面、通过 CLI 在托管模式登录；AdsPower 还不支持无 key 安装、V1 API、Firefox Profile。
- TikTok 本地模式已使用 `browser_profiles/<chrome|chromium>/tiktok/<原始别名>` 持久化资料；默认系统 Chrome、有头（已有 `LOCAL_CHROME_HEADLESS=True` 仍生效）。先运行 `sau tiktok login --account <name> --headed`，人工登录后回终端按 Enter；`check` 与视频/图文复用同一 Profile。可显式 `--local-browser chromium` 或配置 `LOCAL_CHROME_PATH`；只要求选定来源，失败不回退。旧 Cookie JSON 不读写、不自动删除，不再修改语言或固定 viewport；明确未登录退出 `10`，故障退出 `1`。重建使用 `reset-profile --account <name> --browser-kind chrome|chromium`。两类浏览器隔离与四平台真实 no-publish 的证据和边界见[最终验收记录](./.scratch/local-chrome-profile-implementation/research/20-final-validation.md)。
- 小红书的 login/check/视频/图文及直接 uploader 也已使用 `browser_profiles/<chrome|chromium>/xiaohongshu/<原始别名>`，采用同一来源/headless 优先级，保留扫码二维码和当前语言；只有 login 引导登录，旧 JSON 不再读写。`--no-publish` 会上传素材、编辑并等到 ARM 就绪再停止，可能留下草稿；实际证据见[最终验收记录](./.scratch/local-chrome-profile-implementation/research/20-final-validation.md)。
- 与旧版 CLI 或其他工具混用时，调用方需串行使用同一托管 Profile；收到 `10` 安排人工登录；收到 `11` 退避重试；Stop 失败但上传返回 `0` 时清理残留 Profile；跨机调度应远程执行 CLI，而不是把 CLI 指向远程 Local API / Launcher。
- Instagram 全部本地动作已接入持久化 Profile：`browser_profiles/<chrome|chromium>/instagram/<原始别名>`，配置优先级与 TikTok 相同，保留本地代理及当前语言。仅 login 引导登录；check、视频/图文和 verify/delete 不读写旧 Cookie，也不绑定历史账号 ID。作品操作继续核对原作者，设置托管环境变量时仍使用本地账号和配置。视频/图文回归显式使用 `--no-publish`，结果 `prepared` 只证明到达 Share 前；实际证据见[最终验收记录](./.scratch/local-chrome-profile-implementation/research/20-final-validation.md)。

- 托管模式只验证“已登录”，Profile 即身份；各平台本地作品所需的身份比对在托管发布模式下不执行，账号错配风险由调度侧承担。
- 已知限制：命令级登录检测已是 provider-aware 文案；但部分平台在上传过程中遇到登录页、验证码或 2FA 时，uploader 内部错误仍可能提到 Multilogin。这是后续统一文案的已知遗留。

完整参数、平台支持范围、部署前提与安全说明见 [CLI 使用说明的托管浏览器模式](./docs/CLI.md#托管浏览器模式通用)；MLX 与 AdsPower 分别见 [Multilogin X 模式](./docs/CLI.md#multilogin-x-模式) 和 [AdsPower 模式](./docs/CLI.md#adspower-模式)。

#### 视频

按平台选择 `upload-video`：

| 平台 | 平台参数 | 发布说明 |
| --- | --- | --- |
| 小红书、TikTok | `xiaohongshu`、`tiktok` | [CLI 参数](./docs/CLI.md) |
| Rednote（国际版，初始适配） | `rednote` | [登录与发布前验证](./docs/rednote.md) |
| YouTube | `youtube` | [CLI 参数](./docs/CLI.md) |
| Facebook、Facebook Page、Instagram | `facebook`、`facebook-page`、`instagram` | [CLI 参数](./docs/CLI.md) |

```bash
sau xiaohongshu upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
sau youtube upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags tag1,tag2 --playlist "我的系列" --visibility public
sau facebook upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tags Facebook,测试
sau facebook-page upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --page "我的 Page"
```

#### 图文

小红书、Rednote、TikTok、Facebook、Facebook Page 和 Instagram 的独立图片帖、轮播或图片笔记使用 `upload-note`。

```bash
sau xiaohongshu upload-note --account creator --images videos/demo1.png videos/demo2.png videos/demo.png --title "图文标题" --note "图文正文"
# TikTok 本地模式（不设置任一托管凭据）
sau tiktok login --account creator
sau tiktok upload-note --account creator --images videos/demo1.png videos/demo2.png --title "图文标题" --note "图文正文"
# TikTok 托管浏览器模式（MLX；AdsPower 只传 --profile-id）
sau tiktok upload-note --folder-id "FOLDER_ID" --profile-id "PROFILE_ID" --images videos/demo1.png videos/demo2.png --title "图文标题" --note "图文正文"
sau facebook-page upload-note --account creator --images videos/demo1.png --title "Page 图文" --note "正文" --page "我的 Page" --schedule "2026-10-21T02:30:00Z" --result .local/page-result.json
sau facebook upload-note --account creator --images videos/demo1.png videos/demo2.png --title "图片帖" --note "正文"
sau instagram upload-note --account creator --images videos/demo1.png videos/demo2.png --title "图片轮播" --note "正文"
```

Facebook Page 的全部本地动作已接入持久化 Profile：`browser_profiles/<chrome|chromium>/facebook-page/<原始别名>`，与 Facebook 隔离，多个 Page 目标复用同一个登录 Profile。配置优先级与 TikTok 相同，保留代理、定时、作品证据及结果文件；旧 JSON 不再读写。显式目标/历史作品不匹配仍拒绝，verify/delete 在托管环境下仍走本地。本次只做离线与受控 DOM 验证，未登录真实账号、发布或删除作品。

Facebook、Facebook Page 和 Instagram 默认使用系统网络直连。网络环境需要代理时，给对应命令显式添加 `--proxy "代理地址"`，或设置 `SAU_FACEBOOK_PROXY`、`SAU_FACEBOOK_PAGE_PROXY`、`SAU_INSTAGRAM_PROXY`；传 `--proxy ""` 可忽略环境变量并直连。

> YouTube 说明：登录是交互式的（Google 账号，浏览器里完成，无二维码）。这里走浏览器自动化而不是官方 API，
> 是因为**未通过 Google 合规审核的 API 项目上传的视频会被强制锁为私享、无法改公开**，对个人/单频道不实用；
> 浏览器自动化使用项目专用的持久化 Profile；login/check/上传复用同一账号别名和浏览器种类的资料。
> `--playlist` 适合连载/系列追更；`--visibility` 可选 `public`/`unlisted`/`private`。
> 上传会**等进度到 100% 再点发布**（浏览器上传靠窗口开着传，传一半就发布会被掐断卡在中途）。
> youtube.com 被墙的地区：在 `conf.py` 设 `YT_PROXY = "http://127.0.0.1:7890"`（chromium 不吃系统代理，需显式指定）。

#### 本地文章预览

安装 Node.js 22+ 后，可用内置主题将 Markdown 原稿渲染为 HTML。HTML 和 TXT 原稿无需 Node.js。渲染只生成本地文件。[文章格式与主题说明](./docs/article.md)

```bash
sau article themes
sau article setup
sau article render --content-file examples/article.md --theme modern --output output/article.html
```

## 📃详细文档

安装、更新和平台参数见仓库内对应文档：[安装说明](./docs/install.md)、[更新说明](./docs/update.md)、[CLI 使用说明](./docs/CLI.md)。产品介绍与社区信息见 [social-auto-upload 文档站](https://sap-doc.nasdaddy.com/)。

## 🐾交流与支持

[☕ Donate as u like](https://www.buymeacoffee.com/hysn2001m) - 如果您觉得这个项目对您有帮助，可以考虑赞助。

如果您也是独立开发者、技术爱好者，对 #技术变现 #AI创业 #跨境电商 #自动化工具 #视频创作 等话题感兴趣，欢迎加入社群交流。

### Creator

<table>
    <td align="center">
        <a href="https://sap-doc.nasdaddy.com/">
            <img src="media/mp.jpg" width="200px" alt="NasDaddy公众号"/>
            <br />
            <sub><b>微信公众号</b></sub>
        </a>
        <br />
        <a href="https://github.com/dreammis/social-auto-upload/commits?author=dreammis" title="Code">💻</a>
        <br />
        关注公众号，后台回复 `上传` 获取加群方式
    </td>
    <td align="center">
        <a href="https://sap-doc.nasdaddy.com/">
            <img src="media/QR.png" width="200px" alt="赞赏码/入群引导"/>
            <br />
            <sub><b>交流群 (通过公众号获取)</b></sub>
        </a>
        <br />
        <a href="https://sap-doc.nasdaddy.com/" title="Documentation">📖</a>
        <br />
        如果您觉得项目有用，可以考虑打赏支持一下
    </td>
</table>




## 🤝贡献指南

欢迎各种形式的贡献，包括但不限于：

-   提交 Bug报告 和 Feature请求。
-   改进代码、文档。
-   分享使用经验和教程。

如果您希望贡献代码，请遵循以下步骤：

1.  Fork 本仓库。
2.  创建一个新的分支 (`git checkout -b feature/YourFeature` 或 `bugfix/YourBugfix`)。
3.  提交您的更改 (`git commit -m 'Add some feature'`)。
4.  Push到您的分支 (`git push origin feature/YourFeature`)。
5.  创建一个 Pull Request。

提交代码或常规文档前，请确认您有权提交相关内容，并同意这些贡献按照本项目的 MIT License 发布。`skills/` 下的 Skill 按各自 frontmatter 声明为 MIT-0；提交第三方内容时，请同时说明来源及其适用的许可证。

新增或修改平台时，请在同一个 PR 更新 CLI 能力表、对应平台 Skill 和分发目录；缺少 CLI 的平台也要说明实际调用入口。GitHub PR 模板包含逐项检查清单，避免实现完成后漏掉 Skill 发布材料。

## 主要贡献者

<a href="https://github.com/dreammis/social-auto-upload/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=dreammis/social-auto-upload" />
</a>

## 📜许可证

仓库主体采用 [MIT License](LICENSE)。纳入版本控制的 Agent Skills 按各自 `SKILL.md` frontmatter 中声明的许可证发布；当前 8 个产品 Skill 为 MIT-0，以便在要求该许可证的平台分发。该范围不改变仓库其余代码的 MIT License。

本项目依赖的第三方组件和运行时工具仍受其各自许可证约束。下游发行或集成本项目时，请同时检查并保留相关第三方组件要求的版权、许可证和 NOTICE 声明。

## ⭐Star-History

> 如果这个项目对您有帮助，请给一个 ⭐ Star 以表示支持！




[![Star History Chart](https://star-history.dera.page/svg?repos=dreammis/social-auto-upload&type=Date)](https://star-history.dera.page/#dreammis/social-auto-upload&Date)

Facebook 全部正式本地动作已迁移到专用持久化 Profile，与 Facebook Page 隔离；登录、检查、视频/图文和作品核验/删除共用来源/headless 配置，旧 JSON 不读写。账号别名允许换号，作品管理仍校验当前用户、原作者、编号和正文；托管环境下 verify/delete 继续走本地。详见 [Facebook CLI](./docs/CLI.md#facebook-cli-子命令)。
