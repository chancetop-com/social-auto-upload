# 运行前提

这个 skill 默认假设当前环境已经具备：

- 已安装 `social-auto-upload`
- 可以调用 `sau` 命令，或至少有等效调用方式
- 使用 Patchright，准备所选系统 Chrome、完整 Chromium 或 `LOCAL_CHROME_PATH` 指定的浏览器；只安装所选来源

## 推荐安装方式

在项目根目录执行：

```bash
uv pip install -e .
```

## 选择浏览器

默认使用用户安装的系统 Chrome；保留已有 conf.py。若选择 Chromium，显式传 `--local-browser chromium` 并安装项目固定版本配套的完整浏览器：

```sh
uv run patchright install chromium
# 可选：uv run patchright install --no-shell chromium
```

普通安装与 `--no-shell` 都包含完整 Chromium；仅 headless shell 不足。Chrome 由用户按 [Google 官方指引](https://www.google.com/chrome/)安装，项目不自动安装/更新。托管动作无需本地浏览器。需要下载镜像时由用户设置 `PLAYWRIGHT_DOWNLOAD_HOST`，安装和运行保持相同项目环境和缓存。

## 常见调用方式

### 如果 `sau` 已经在 PATH 中

```bash
sau douyin --help
```

### 如果虚拟环境存在，但还没有激活

PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
sau douyin --help
```

### 如果你想直接调用可执行文件

PowerShell：

```powershell
.\.venv\Scripts\sau.exe douyin --help
```

### 如果你更倾向于使用 uv

```bash
uv run sau douyin --help
```

## 无头和有头模式

- 使用 `--headless` 表示无头模式
- 使用 `--headed` 表示有头模式
- 如果用户明确要求无头登录，也要预期 CLI 会通过控制台输出或临时图片路径提供二维码相关提示
- 如果登录过程中已经生成了本地二维码图片，agent 应优先直接把图片展示/发送给用户扫码，不要只告诉用户图片路径

显式 headed/headless > LOCAL_CHROME_HEADLESS > False，默认有头。无自定义路径时，显式 local-browser > LOCAL_BROWSER > chrome；自定义路径优先，以识别出的实际种类隔离 Profile。无头模式也需要所选完整浏览器，失败不切换来源。Linux/CI 为所选来源准备系统库；Chrome 有头需可用显示服务。旧 JSON 不作为登录前提；安装、浏览器启动和平台登录分别验证。
