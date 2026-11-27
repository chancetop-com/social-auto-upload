# 安装说明

这个文档分成两部分：

- `For Humans`：给正常使用仓库的开发者、创作者、CLI 用户看
- `For AI Agents`：给 OpenClaw、Codex、Claude Code 一类 agent 看

如果你是“正在使用 agent 客户端的人”，想先给 agent 一段启动提示词，而不是直接阅读下面的执行细节，先看：

- [Agent Bootstrap Prompt](./agent-bootstrap.md)

## For Humans

### 1. 克隆项目

```bash
git clone git@github.com:chancetop-com/social-auto-upload.git
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

安装完成后会注册 `sau` 命令。文章渲染脚本、主题及许可证资源随包提供。

### 4. 按所选浏览器准备运行环境

七个平台的本地浏览器动作使用持久化 Profile，默认使用系统 Chrome。Python 包安装、CLI 帮助和托管动作均无需下载本地浏览器。

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

仓库根目录的可编辑安装沿用该目录中的 `conf.py`、浏览器资料和素材。需要自定义设置时，首次安装可复制示例；升级保留已有配置（包括 `LOCAL_CHROME_HEADLESS=True`）：

```bash
test -f conf.py || cp conf.example.py conf.py
```

Windows 也可以直接手动复制并重命名。

独立 wheel 安装默认将数据保存在用户主目录下的 `.social-auto-upload`。可通过 `SAU_HOME` 指定固定的绝对目录，CLI 会读取该目录中的 `conf.py`。示例中的 `BASE_DIR` 以配置文件所在目录为准。不同版本的桌面程序可指向同一个可写目录。

在仓库根目录执行 `uv build --wheel`，用 `uv pip install --python <目标解释器> <wheel路径>` 安装。安装后可在任意目录执行该环境的 `sau`。暂存后整体迁移的私有运行时使用其最终绝对路径调用 `python -I -m sau_cli`，以免引用生成入口时的解释器路径。

当前通常还会用到这些配置项：

- `LOCAL_CHROME_PATH`：非空时优先作为实际可执行文件。
- `LOCAL_BROWSER`：无路径覆盖时，显式 `--local-browser` > 此配置 > `chrome`。
- `LOCAL_CHROME_HEADLESS`：CLI 和直接调用采用显式 `--headed`/`--headless` 或布尔值 > 配置 > `False`。托管模式同样解析 headless，但完全忽略本地来源配置。

### 6. 验证 CLI 是否可用

```bash
sau --help
sau xiaohongshu --help
sau article themes
```

如果命令找不到，优先确认：

- 当前虚拟环境是否已激活
- 是否执行过 `uv pip install -e .`

### 7. 小红书主线示例

login/check/视频/图文复用专用持久化 Profile。登录扫码后正常关闭，再用同配置 check；只有 login 引导登录。`--local-browser chromium` 可选完整 Chromium，默认系统 Chrome；显式 headed/headless 覆盖配置。保留当前语言，不读写或迁移旧 Cookie JSON。安装可用、浏览器可启动和平台已登录是三项不同结果。


```bash
sau xiaohongshu login --account creator
sau xiaohongshu check --account creator
sau xiaohongshu upload-video --account creator --file videos/demo.mp4 --title "示例标题" --desc "示例简介"
sau xiaohongshu upload-note --account creator --images videos/demo1.png videos/demo2.png videos/demo.png --title "图文标题" --note "图文正文"
```

补充说明：

- `creator` 之类的名字只是示例值，真正传的是用户自定义的 `account_name`
- 本地每个浏览器种类、平台和 `account_name` 对应一个持久化 Profile。不同 Profile 可以并行使用
- 视频和图文的元数据参数分别见所选平台的 `upload-video --help` 和 `upload-note --help`。

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
sau xiaohongshu --help
sau article themes
```


6. 针对目标平台，按 `sau <平台> <动作> --help` 核对参数，按[技能目录](./skill-distribution.md)选择对应的平台 Skill。

### 对 agent 的额外说明

- 当登录流程生成本地二维码图片时，不要只把图片路径发给用户
- 这类二维码图片本身就是给用户扫码的，agent 应优先直接展示/发送本地图片给用户扫码
- 如果环境支持查看本地图片，优先用查看图片能力把二维码展示出来；路径只作为补充信息
- `cli/uploader/` 是核心实现目录
- `cli/sau_cli.py` 是当前 CLI 主入口

### Facebook Page 持久化登录

准备所选 Chrome/完整 Chromium 或自定义可执行文件后，运行 `sau facebook-page login --account creator --headed`，在 Business Suite 完成人工登录；正常关闭后用同配置 `sau facebook-page check --account creator --headed`。一个登录 Profile 可访问多个 Page，显式 `--page` 继续核验目标；与 Facebook 账号资料隔离。只有 login 引导登录，旧 JSON 不参与。安装成功、浏览器启动、登录有效分别验证；本票离线结果不代表真实账号已登录。无头模式仍需实际选定的完整浏览器。
