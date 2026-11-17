# 运行前提

这个 skill 默认假设当前环境已经具备：

- 已安装 `social-auto-upload`
- 可以调用 `sau` 命令，或至少有等效调用方式
- 项目固定版本的 Patchright Python 依赖，以及实际选定的浏览器来源

## 安装与浏览器选择

在项目根目录安装依赖：`uv pip install -e .`。保留用户现有 `conf.py`。

默认使用系统 Google Chrome，由用户按 [Chrome 官方安装说明](https://support.google.com/chrome/answer/95346) 准备；项目不自动安装或更新 Chrome。显式 Chromium 使用项目版本配套的完整浏览器：

```bash
uv run patchright install --no-shell chromium
sau xiaohongshu login --account creator --local-browser chromium --headed
```

浏览器缓存环境与运行环境保持一致。普通 `chromium` 安装也可用，仅 headless shell 不满足本地持久化契约。Linux 有头环境需要显示服务，无显示 CI 使用 Xvfb。

配置优先级：非空 `LOCAL_CHROME_PATH`（已有可执行文件）优先；否则 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > `chrome`。仅要求实际选择的来源，不探测或安装另一来源；失败不换浏览器。同种浏览器的路径、headless 切换复用 Profile，两种浏览器各有独立资料。

本地资料位于 `browser_profiles/xiaohongshu/<原始别名>/<chrome|chromium>/`，与日常浏览器隔离。旧 Cookie JSON 不读写或自动清理。托管模式不要求本地浏览器安装，完全忽略本地来源配置。

## 常见调用方式

### 如果 `sau` 已经在 PATH 中

```bash
sau xiaohongshu --help
```

### 如果虚拟环境存在，但还没有激活

PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
sau xiaohongshu --help
```

### 如果你想直接调用可执行文件

PowerShell：

```powershell
.\.venv\Scripts\sau.exe xiaohongshu --help
```

### 如果你更倾向于使用 uv

```bash
uv run sau xiaohongshu --help
```

## 无头和有头模式

- 显式 `--headed` / `--headless` 优先于 `LOCAL_CHROME_HEADLESS`；未配置时为 `False`（有头）。直接调用的 `headless=None` 同样读配置，显式 `False` 保留有头。托管模式采用同一 headless 来源。
- 使用 `--headless` 表示无头模式
- 使用 `--headed` 表示有头模式
- 如果用户明确要求无头登录，也要预期 CLI 会通过控制台输出或临时图片路径提供二维码相关提示
- 如果登录过程中已经生成了本地二维码图片，agent 应优先直接把图片展示/发送给用户扫码，不要只告诉用户图片路径

## 界面语言

本地模式保留浏览器当前语言，不设置 locale、Accept-Language、UA、stealth 或固定 viewport；原有页面业务脚本和人类化交互仍运行。中文声明及部分弹窗依赖平台中文文案，入口异常时用 `--headed` 观察当前界面，不自动切换语言。托管模式继续使用 Profile 自身语言，人工保持中文。
