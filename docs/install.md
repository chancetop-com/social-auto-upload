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

项目保留固定版本的 Patchright。TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、视频号、百家号 已迁移到持久化 Profile；默认选择系统 Chrome，其他尚未迁移的平台仍保留原有 Chromium 要求。

- **Chrome 路线**：用户从 [Google Chrome 官方下载页](https://www.google.com/chrome/) 安装适合系统的 Chrome；项目使用 `channel="chrome"`，不会自动安装或更新它。macOS 选择相应 Apple 芯片或 Intel 版本。
- **Chromium 路线**：在项目 Python 环境执行 `uv run patchright install --no-shell chromium`，并使用 `--local-browser chromium`。有头和无头均使用完整 `channel="chromium"`；`--only-shell` 不能满足这一模式。未迁移平台仍可能使用 headless shell，保留它们需要的 `uv run patchright install chromium` 安装方式。
- **已有自定义浏览器**：在 `conf.py` 设置 `LOCAL_CHROME_PATH`。只检查该来源；启动前根据可靠产品信息识别 Chrome / Chromium，无法识别则停止。仅改文件名或传浏览器选择不能强行指定其种类。

只需准备实际选择的来源；失败不会自动换 binary 或 headless。Linux / CI 需为所选有头浏览器提供显示服务，并按其官方要求安装系统库；可为配套 Chromium 使用 `uv run patchright install --with-deps --no-shell chromium`。仅支持无头的运行环境显式传 `--headless`。若设置 `PLAYWRIGHT_BROWSERS_PATH`，安装和运行保持同一值；不新增 CI workflow。

网络受限时可按需设置 `PLAYWRIGHT_DOWNLOAD_HOST`；镜像来源及可用性由使用者确认，不替代系统 Chrome 官方安装。

### 5. 配置 conf.py

首次安装且 `conf.py` 不存在时复制示例；升级保留已有配置（包括 `LOCAL_CHROME_HEADLESS=True`）：

```bash
cp conf.example.py conf.py
```

Windows 也可以直接手动复制并重命名。

当前通常还会用到这些配置项：

- `LOCAL_CHROME_PATH`：非空时优先作为实际可执行文件。
- `LOCAL_BROWSER`：TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、视频号、百家号 无路径覆盖时，显式 `--local-browser` > 此配置 > `chrome`。
- `LOCAL_CHROME_HEADLESS`：TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、视频号、百家号 的 CLI 和直接调用采用显式 `--headed`/`--headless` 或布尔值 > 配置 > `False`；其他待迁移平台保留旧 CLI 默认。托管 TikTok、Rednote、Instagram、小红书、YouTube、Facebook、Facebook Page、视频号、百家号 同样解析 headless，但完全忽略本地来源配置。

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

抖音短信验证码补充说明：

- 视频发布过程中如果触发短信二次验证，程序会优先读取项目根目录下的 `verify_code.txt`
- 如果当前是你手动运行的交互式终端，没提供 `verify_code.txt` 时，CLI 会直接提示你在终端输入验证码
- 如果是 agent 或自动化桥接场景，仍然可以继续通过写入 `verify_code.txt` 来提供验证码
- 验证通过后，程序会自动删除 `verify_code.txt`

抖音卡login手动获取cookie:

- 目标服务器使用vnc
- 浏览器登录抖音创作者中心https://creator.douyin.com/
- 执行`bash export_douyin_cookie.sh --account <account_name>`
- 检查cookie可用性,执行`sau douyin check --account <account_name>`

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

4. 如需浏览器驱动，优先使用：

Windows PowerShell：

```powershell
$env:PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright"; patchright install chromium
```

Linux / macOS：

```bash
PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright" patchright install chromium
```

5. 安装完成后，优先检查：

```bash
sau --help
sau douyin --help
sau kuaishou --help
sau xiaohongshu --help
sau bilibili --help
```

6. 如果用户的目标是抖音或快手的登录、cookie 校验、视频上传、图文上传，优先走 CLI：

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

### 视频号持久化登录

准备所选系统 Chrome、完整 Chromium 或自定义 binary 后，运行 `sau tencent login --account creator --headed` 完成微信扫码；正常关闭后同配置 `sau tencent check --account creator --headed`。保持原 conf.py；headless 显式参数优先，旧 JSON 不参与。登录、检查和视频预检共用持久化 Profile；只有 login 引导扫码。视频号无 `--no-publish`，离线/受控 DOM 验证不代表真实账号发布验收。

### 百家号持久化登录

按上方说明只准备所选浏览器，保留已有 `conf.py`。执行 `sau baijiahao login --account creator --headed`，扫码或完成人工验证，正常关闭后执行同配置 `sau baijiahao check --account creator`。Profile 位于 `browser_profiles/baijiahao/creator/<chrome|chromium>`，旧 Cookie JSON 不再用于登录。两类浏览器各自登录，别名允许换号；显式 `reset-profile --account creator --browser-kind chrome` 只重建一个 Profile，无需启动浏览器。视频要求横版封面；百家号没有 no-publish 开关，安装/窗口验收使用隔离受控页面，避免提交真实作品。
