# 安装说明

这个文档分成两部分：

- `For Humans`：给正常使用仓库的开发者、创作者、CLI 用户看
- `For AI Agents`：给 OpenClaw、Codex、Claude Code 一类 agent 看

如果你是“正在使用 agent 客户端的人”，想先给 agent 一段启动提示词，而不是直接阅读下面的执行细节，先看：

- [Agent Bootstrap Prompt](./agent-bootstrap.md)

## For Humans

### 1. 克隆项目

```bash
git clone https://github.com/dreammis/social-auto-upload.git
cd social-auto-upload
```

### 2. 创建虚拟环境

推荐使用 `uv`：

Windows PowerShell：

```powershell
uv venv
.venv\Scripts\activate
```

Linux / macOS：

```bash
uv venv
source .venv/bin/activate
```

### 3. 安装主线依赖

当前主线依赖已经放到 `pyproject.toml`，推荐直接执行：

```bash
uv pip install -e .
```

安装完成后，会注册 `sau` 命令。

### 4. 按所选浏览器准备运行环境

项目保留固定版本的 Patchright。TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、抖音、快手、视频号、百家号、微博、虎扑、支付宝生活号、大鱼号、知乎、雪球 的全部正式本地浏览器动作使用持久化 Profile，默认选择系统 Chrome。基础 Python 安装和 CLI help 不下载或检查浏览器；托管动作不要求本地 Chrome/Chromium，Bilibili 仍使用 biliup。

- **Chrome 路线**：用户从 [Google Chrome 官方下载页](https://www.google.com/chrome/) 安装适合系统的 Chrome；项目使用 `channel="chrome"`，不会自动安装或更新它。macOS 选择相应 Apple 芯片或 Intel 版本。
- **Chromium 路线**：在项目 Python 环境执行 `uv run patchright install --no-shell chromium`，并使用 `--local-browser chromium`。有头和无头均使用完整 `channel="chromium"`；`--only-shell` 不能满足这一模式。普通 `uv run patchright install chromium` 同样可用，会额外安装 shell；`--no-shell` 是节省下载的可选方式。
- **已有自定义浏览器**：在 `conf.py` 设置 `LOCAL_CHROME_PATH`。只检查该来源；启动前根据可靠产品信息识别 Chrome / Chromium，无法识别则停止。仅改文件名或传浏览器选择不能强行指定其种类。

只需准备实际选择的来源；失败不会自动换 binary 或 headless。Linux / CI 需为所选有头浏览器提供显示服务，并按其官方要求安装系统库；可为配套 Chromium 使用 `uv run patchright install --with-deps --no-shell chromium`。仅支持无头的运行环境显式传 `--headless`。若设置 `PLAYWRIGHT_BROWSERS_PATH`，安装和运行保持同一值；不新增 CI workflow。

网络受限时可按需设置 `PLAYWRIGHT_DOWNLOAD_HOST`；镜像来源及可用性由使用者确认，不替代系统 Chrome 官方安装。

### 可选 CI 环境：两条独立路线

以下是已 checkout、装好 Python 3.11 与 uv 的 **Ubuntu 24.04 x64** 环境示例（如 `ubuntu-24.04` runner）。它们是按既有[Chrome 安装研究](../.scratch/local-chrome-profile/research/chrome-arm64-installation.md)和[Chromium 运行研究](../.scratch/local-chrome-profile/research/chromium-runtime-contract.md)整理的安装说明，本次没有执行 Linux CI，也不新增 workflow。按所选来源只执行一条；两条都用项目锁文件固定 Patchright 与其驱动。

**路线 A：Google 官方 Chrome amd64 DEB。** 已装好兼容系统 Chrome 时复用它，跳过下载安装。缺少时由用户或其部署脚本按 [Google 官方安装说明](https://support.google.com/chrome/answer/95346?hl=en)准备；项目本身不安装或更新 Chrome，`patchright install chrome` 不是默认路线。

```sh
uv sync --locked --python 3.11
curl --fail --location --retry 3 \
  https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
  --output /tmp/google-chrome.deb
sudo apt-get update
sudo apt-get install -y /tmp/google-chrome.deb xvfb xauth
uv run patchright install-deps chromium
google-chrome --version
test -x /opt/google/chrome/chrome
```

apt 安装 DEB 声明的系统库，`install-deps chromium` 补充驱动要求的 Linux 依赖，不下载另一份 Chromium。该 DEB 是 x64 滚动 stable，URL 固定不表示 Chrome 版本锁定；记录实际版本并由部署环境管理更新，不套用于 ARM64 runner。

**路线 B：项目固定 Patchright 配套完整 Chromium。** 不需要系统 Chrome：

```sh
uv sync --locked --python 3.11
sudo apt-get update
sudo apt-get install -y xvfb xauth
uv run patchright install --with-deps chromium
# 可选：将上一行换为以下命令，省去未使用的 headless shell。
# uv run patchright install --with-deps --no-shell chromium
```

普通安装与 `--no-shell` 都提供完整浏览器；仅 `--only-shell` 不满足契约。运行时显式 `--local-browser chromium`，有头和无头始终选择 `channel="chromium"`。浏览器缓存按操作系统、架构、锁文件/固定 Patchright 版本区分；驱动升级后安装对应浏览器。设置 `PLAYWRIGHT_BROWSERS_PATH` 时，安装和运行使用同一值，不从另一环境的缓存推定已就绪。

两条路线的有头运行在无显示环境加 `xvfb-run -a`，例如 `xvfb-run -a uv run sau <平台> check --account <别名> --headed`（Chromium 再加 `--local-browser chromium`）。无头任务可显式 `--headless`，仍需上述完整 binary 和系统库。Xvfb 只提供显示服务，不完成平台登录。安装验证可用隔离临时 Profile 打开空白页，真实账号须另行 login 后同配置 check。

已有兼容的 Chrome/Chromium binary 可通过 `LOCAL_CHROME_PATH` 复用，省去相应浏览器下载；Linux 系统库和有头显示服务仍需准备。记录产品、路径和版本，不承诺任意版本或降级兼容，不复制其他浏览器种类的账号资料。

### 5. 配置 conf.py

首次安装且 `conf.py` 不存在时复制示例；升级保留已有配置（包括 `LOCAL_CHROME_HEADLESS=True`）：

```bash
test -f conf.py || cp conf.example.py conf.py
```

Windows 也可以直接手动复制并重命名。

当前通常还会用到这些配置项：

- `LOCAL_CHROME_PATH`：非空时优先作为实际可执行文件。
- `LOCAL_BROWSER`：TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、抖音、快手、视频号、百家号、微博、虎扑、支付宝生活号、大鱼号、知乎、雪球 无路径覆盖时，显式 `--local-browser` > 此配置 > `chrome`。
- `LOCAL_CHROME_HEADLESS`：TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、抖音、快手、视频号、百家号、微博、虎扑、支付宝生活号、大鱼号、知乎、雪球 的 CLI 和直接调用采用显式 `--headed`/`--headless` 或布尔值 > 配置 > `False`。托管 TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、抖音、快手、视频号、百家号、微博、虎扑、支付宝生活号、大鱼号、知乎、雪球 同样解析 headless，但完全忽略本地来源配置。

### 6. 验证 CLI 是否可用

```bash
sau --help
sau douyin --help
sau kuaishou --help
sau xiaohongshu --help
sau bilibili --help
```

如果命令找不到，优先确认：

- 当前虚拟环境是否已激活
- 是否执行过 `uv pip install -e .`

### 7. 抖音主线示例

```bash
sau douyin login --account <account_name>
sau douyin check --account <account_name>
sau douyin upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
图文正文1:
$noteText = @"图文正文"@    
sau douyin upload-note --account <account_name> --images videos/demo1.png videos/demo2.png --title "图文标题" --note $noteText --tags 'tag1,tag2'
图文正文2:
sau douyin upload-note --account <account_name> --images videos/demo1.png videos/demo2.png --title "图文标题" --notef '图文文件路径' --tags 'tag1,tag2'
添加 BGM（可选）:
sau douyin upload-note --account <account_name> --images videos/demo1.png videos/demo2.png --title "图文标题" --note $noteText --tags 'tag1,tag2' --bgm '音乐名称'
``` 

抖音 login/check/视频/图文及直接 uploader 使用 `browser_profiles/<chrome|chromium>/douyin/<原始别名>/`。默认系统 Chrome、有头；`LOCAL_CHROME_PATH` 非空优先，否则显式 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > Chrome。显式 `--headed`/`--headless` > `LOCAL_CHROME_HEADLESS` > False，保留用户已有配置。只要求所选浏览器，失败不回退；Chrome 由用户安装，Chromium 用 `uv run patchright install --no-shell chromium`。预检与发布共用一个会话，浏览器保存完整状态，旧 Cookie JSON 不导入、读写或删除。

只有 login 引导扫码或验证；缺少 Profile、明确未登录/验证退出 `10`，网络、权限和页面故障退出 `1`。同别名可以重新登录另一真实账号，Chrome 与 Chromium 各自隔离。发布中遇到验证即结束本次任务；提交后退出 `10` 会附 `publish_attempted=true`，退出 `9` 表示结果未知，都先核对作品再决定重试。重建使用 `sau douyin reset-profile --account creator --browser-kind chrome`，无需 binary，拒绝占用，保留另一浏览器及历史结果；不会自动恢复发布任务。抖音没有 `--no-publish`，环境验证使用离线或受控页面，不能以真实提交验收。

托管模式保留 `verify_code.txt`/交互终端短信验证码流程；本地发布遇到验证立即退出，先用同配置 login 完成验证。

### 8. 快手主线示例

```bash
sau kuaishou login --account <account_name>
sau kuaishou check --account <account_name>
sau kuaishou upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
sau kuaishou upload-note --account <account_name> --images videos/demo1.png videos/demo2.png videos/demo.png --title "图文标题" --note "图文正文"
```

### 9. 小红书主线示例

login/check/视频/图文复用专用持久化 Profile。登录扫码后正常关闭，再用同配置 check；只有 login 引导登录。`--local-browser chromium` 可选完整 Chromium，默认系统 Chrome；显式 headed/headless 覆盖配置。保留当前语言，不读写或迁移旧 Cookie JSON。安装可用、浏览器可启动和平台已登录是三项不同结果。


```bash
sau xiaohongshu login --account <account_name>
sau xiaohongshu check --account <account_name>
sau xiaohongshu upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
sau xiaohongshu upload-note --account <account_name> --images videos/demo1.png videos/demo2.png videos/demo.png --title "图文标题" --note "图文正文"
```

### 10. Bilibili 主线示例

```bash
sau bilibili login --account <account_name>
sau bilibili check --account <account_name>
sau bilibili upload-video --account <account_name> --file videos/demo.mp4 --title "示例标题" --desc "示例简介" --tid 249
```

补充说明：

- `creator` 之类的名字只是示例值，真正传的是用户自定义的 `account_name`
- 一个 `account_name` 对应一个账号文件，可以准备多个账号并发使用
- 浏览器平台统一元数据约定：
- 视频使用 `title + desc + tags`
- 图文使用 `title + note + tags`
- 用户不需要手动安装 `biliup`
- 首次运行 Bilibili 相关命令时，程序会自动下载 `biliup`
- 后续运行会自动检查上游 release 并自动更新
- Bilibili 登录建议由用户自己在本地真实终端里执行；如果终端里的二维码显示不完整，可直接打开当前目录下的 `qrcode.png` 扫码
- 如果国内网络访问 GitHub Release 较慢，可先用 `https://gh-proxy.com/` 或 `https://gh-proxy.org/` 辅助访问对应 release 地址排障
- 示例：
  - `https://gh-proxy.org/https://github.com/biliup/biliup/releases/download/v1.1.29/biliupR-v1.1.29-aarch64-linux.tar.xz`

## For AI Agents

如果你是一个可执行命令的 agent，请优先按下面顺序处理：

1. 先假设仓库根目录就是当前工作目录
2. 优先使用 `uv` 管理环境（`uv pip install -e .`）
3. 安装命令优先使用：

```bash
uv pip install -e .
```

4. 根据任务的实际来源准备浏览器：默认系统 Chrome 由用户按 Google 官方指引安装；选择完整 Chromium 时执行 `uv run patchright install chromium`（可加 `--no-shell`）。已有兼容 binary 可配置 `LOCAL_CHROME_PATH`。托管动作跳过本地浏览器准备；Linux/CI 按上文两条独立路线处理系统依赖和 Xvfb。保留已有 `conf.py`，不覆盖 `LOCAL_CHROME_HEADLESS=True`。

5. 安装完成后，优先检查：

```bash
sau --help
sau douyin --help
sau kuaishou --help
sau xiaohongshu --help
sau bilibili --help
```

6. 如果用户的目标是抖音或快手的登录、登录态校验、视频上传、图文上传，优先走 CLI：

```bash
sau douyin login
sau douyin check
sau douyin upload-video
sau douyin upload-note

sau kuaishou login
sau kuaishou check
sau kuaishou upload-video
sau kuaishou upload-note

sau xiaohongshu login
sau xiaohongshu check
sau xiaohongshu upload-video
sau xiaohongshu upload-note

sau bilibili login
sau bilibili check
sau bilibili upload-video
```

7. 如果用户明确在使用 skill 系统，再引导其阅读：

- `skills/douyin-upload/SKILL.md`
- `skills/douyin-upload/references/cli-contract.md`
- `skills/kuaishou-upload/SKILL.md`
- `skills/kuaishou-upload/references/cli-contract.md`
- `skills/xiaohongshu-upload/SKILL.md`
- `skills/xiaohongshu-upload/references/cli-contract.md`
- `skills/bilibili-upload/SKILL.md`
- `skills/bilibili-upload/references/cli-contract.md`

### 对 agent 的额外说明

- 当登录流程生成本地二维码图片时，不要只把图片路径发给用户
- 这类二维码图片本身就是给用户扫码的，agent 应优先直接展示/发送本地图片给用户扫码
- 如果环境支持查看本地图片，优先用查看图片能力把二维码展示出来；路径只作为补充信息
- Bilibili 登录当前不建议 agent 在非交互环境里直接代跑
- 正确做法是让用户自己在本地终端执行 `sau bilibili login --account <name>`；如果二维码显示不完整，再提示用户打开 `qrcode.png`
- `uploader/` 是核心实现目录
- `sau_cli.py` 是当前 CLI 主入口
- Bilibili 首次运行时可能自动下载 `biliup`

### Facebook Page 持久化登录

准备所选 Chrome/完整 Chromium 或自定义可执行文件后，运行 `sau facebook-page login --account creator --headed`，在 Business Suite 完成人工登录；正常关闭后用同配置 `sau facebook-page check --account creator --headed`。一个登录 Profile 可访问多个 Page，显式 `--page` 继续核验目标；与 Facebook 账号资料隔离。只有 login 引导登录，旧 JSON 不参与。安装成功、浏览器启动、登录有效分别验证；本票离线结果不代表真实账号已登录。无头模式仍需实际选定的完整浏览器。

### 快手登录验证

准备所选 Chrome、完整 Chromium 或自定义 binary 后，运行 `sau kuaishou login --account creator --headed` 并扫码；正常关闭后以同配置 `sau kuaishou check --account creator --headed` 检查。已有 headless 配置保留，只有 login 引导登录。旧 JSON 不参与；安装成功和真实登录有效须分别验证。快手上传会实际提交，没有 --no-publish。

### 视频号持久化登录

准备所选系统 Chrome、完整 Chromium 或自定义 binary 后，运行 `sau tencent login --account creator --headed` 完成微信扫码；正常关闭后同配置 `sau tencent check --account creator --headed`。保持原 conf.py；headless 显式参数优先，旧 JSON 不参与。登录、检查和视频预检共用持久化 Profile；只有 login 引导扫码。视频号无 `--no-publish`，离线/受控 DOM 验证不代表真实账号发布验收。

### 百家号持久化登录

按上方说明只准备所选浏览器，保留已有 `conf.py`。执行 `sau baijiahao login --account creator --headed`，扫码或完成人工验证，正常关闭后执行同配置 `sau baijiahao check --account creator`。Profile 位于 `browser_profiles/<chrome|chromium>/baijiahao/creator`，旧 Cookie JSON 不再用于登录。两类浏览器各自登录，别名允许换号；显式 `reset-profile --account creator --browser-kind chrome` 只重建一个 Profile，无需启动浏览器。视频要求横版封面；百家号没有 no-publish 开关，安装/窗口验收使用隔离受控页面，避免提交真实作品。

### 微博持久化登录

保留已有 `conf.py`；按上文准备所选系统 Chrome、完整 Chromium（`uv run patchright install --no-shell chromium`）或自定义路径。先 `sau weibo login --account creator --headed`，按需扫码/完成人工验证，正常关闭后以同配置 `sau weibo check --account creator`。Profile 位于 `browser_profiles/<chrome|chromium>/weibo/creator`；默认有头，显式参数优先于配置，不导入旧 JSON。别名可换号，两类浏览器各自登录。重建使用 `sau weibo reset-profile --account creator --browser-kind chrome`，不需 binary，拒绝占用，仅清空明确目标。发布要求封面，没有 no-publish 开关；安装、浏览器启动和账号登录分别验证，窗口回归只用隔离受控页面。

### 虎扑 Profile 登录

只准备所选系统 Chrome、完整 Chromium 或自定义路径，保留已有 conf.py；默认 Chrome 有头，显式 headed/headless 优先于配置。执行 `sau hupu login --account creator --headed` 完成 QQ 扫码或人工验证，正常关闭后同配置 `sau hupu check --account creator`。资料位于 `browser_profiles/<chrome|chromium>/hupu/creator`，旧 JSON 不参与；两种浏览器各自登录，账号别名允许换号。`sau hupu reset-profile --account creator --browser-kind chrome` 只重建该 Profile，无需安装 binary。Hupu 无 no-publish，安装与窗口验收使用隔离合成页面，不提交真实视频。

### 支付宝生活号持久化登录

保留现有 conf.py，只准备所选 Chrome/完整 Chromium 或自定义浏览器。执行 `sau alipay login --account creator --headed` 扫码，正常关闭后同配置 `sau alipay check --account creator`；Profile 位于 `browser_profiles/<chrome|chromium>/alipay/creator`，旧 Cookie 不导入/导出。内容创作入口必须可见，登录 iframe 是未登录证据，网络/HTTP/权限/结构故障单独报错。两种浏览器独立登录，别名允许换号；重建时显式指定 browser-kind，无需浏览器安装。生活号无 no-publish 开关，使用受控页面验收安装和窗口交互。

### 知乎持久化登录

保留已有配置并只准备所选浏览器。执行 `sau zhihu login --account creator --headed`，关闭后同配置 `sau zhihu check --account creator`；可统一使用 `--local-browser chromium` 切换独立资料。文章、视频及 verify 复用这一 Profile；只有 login 引导登录，旧 JSON 和身份旁文件不参与。完整参数、原作品验证及重建说明见 [知乎 CLI](CLI.md#知乎-cli-子命令)。

### 雪球持久化登录

只准备所选系统 Chrome、完整 Chromium（`uv run patchright install --no-shell chromium`）或自定义路径，保留已有 conf.py。先 `sau xueqiu login --account creator --headed` 完成人工登录，关闭后同配置 check。默认 Chrome 有头，显式 browser/headless 覆盖配置（自定义路径优先）；旧 JSON/身份旁文件不导入、不读写。别名可换号，历史作品仍核对作者；文章验证显式 `--prepare-only`，可能保存草稿。完整参数见 [雪球说明](./xueqiu.md)。
