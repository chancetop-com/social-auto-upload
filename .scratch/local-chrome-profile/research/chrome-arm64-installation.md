# Chrome ARM64 安装与 CI 运行依据

核对日期：2026-11-17（Asia/Shanghai）。范围：本地 Patchright 使用系统 Google Chrome；只做资料与文件检查，没有安装、重装或启动浏览器。

## 建议

本机直接复用 `/Applications/Google Chrome.app`。缺少 Chrome 的 macOS 机器优先从 [Google Chrome 官网](https://www.google.com/chrome/)手动安装，并放入 `/Applications`。Google 的安装帮助要求 macOS 13 Ventura 或更高，流程是打开 DMG、将 Chrome 拖入 Applications。[Google 安装说明](https://support.google.com/chrome/answer/95346?hl=en)

另一个可用途径是 `brew install --cask google-chrome`。核对时 Homebrew cask 版本为 `157.0.8103.79`，下载地址是 Google 托管的 [universal stable DMG](https://dl.google.com/chrome/mac/universal/stable/GGRO/googlechrome.dmg)，设置了 `auto_updates true`、`depends_on macos: :ventura`，应用名为 `Google Chrome.app`。它不是 Homebrew 自行编译的 Chromium。[Homebrew cask 源码](https://github.com/Homebrew/homebrew-cask/blob/master/Casks/g/google-chrome.rb)

`channel="chrome"` 可以使用其他方式安装的 Chrome；Patchright 的推荐配置为 persistent context、`headless=False`、`no_viewport=True`，不添加自定义 UA 或浏览器请求头。本项目按此采用专用自动化 profile，不增加指纹注入；此研究不涉及 managed 模式。[Patchright Python 官方 README](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#best-practice---use-chrome-without-fingerprint-injection)

## 发现逻辑与 ARM64 判断

Playwright 的 `chrome` channel 在 macOS 查找 `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`，Linux 查找 `/opt/google/chrome/chrome`；macOS 不是任意 PATH 或 `~/Applications` 搜索。启动时找不到会报错并建议安装，不会自动下载 Chrome。[registry 源码](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/src/server/registry/index.ts)

本地 `.venv` 的 Patchright Python 为 `1.64.4`，内置 `patchright-core` 为 `1.64.3`；本地 `driver/package/lib/coreBundle.js:36457` 的 macOS channel 路径与上游一致。项目 `pyproject.toml` 也固定 `patchright==1.64.4`，Python 范围为 `>=3.10,<3.13`。

没有证据支持“Darwin ARM64 的 Chrome 安装脚本不支持 Apple Silicon”。本机 Patchright 的 `reinstall_chrome_stable_mac.sh`、Playwright `v1.64.1` 和核对时的 `main` 均使用上述 universal DMG，没有拒绝 arm64 的条件。该脚本会先删除 `/Applications/Google Chrome.app` 再复制新包，因此已有安装时没有必要执行重装。未提供失败日志，也未实际重现安装错误，不能推定具体失败原因。[v1.64.1 mac 脚本](https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/bin/reinstall_chrome_stable_mac.sh)、[当前 mac 脚本](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/bin/reinstall_chrome_stable_mac.sh)

Linux ARM64 要区分版本：本机 Patchright `1.64.4` 的 Linux 安装脚本仍在 `arch=aarch64` 时退出；Playwright `v1.64.1` 同样如此。但 Google 当前官方帮助已经列出 Linux ARM64 的 `.deb` 与 `.rpm` 安装包，Playwright 当前 `main`（根包版本 `1.66.0-next`）也已按架构选择 `arm64`/`amd64` 包。因此旧脚本限制不能表述成 Google Chrome 当前不支持 Linux ARM64。[Google 安装说明](https://support.google.com/chrome/answer/95346?hl=en)、[v1.64.1 Linux 脚本](https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/bin/reinstall_chrome_stable_linux.sh)、[当前 Linux 脚本](https://github.com/microsoft/playwright/blob/main/packages/playwright-core/bin/reinstall_chrome_stable_linux.sh)、[main 版本元数据](https://github.com/microsoft/playwright/blob/main/package.json)

## 本机只读核对

本次观察：Darwin `arm64`，macOS `26.6.2`；系统 Applications 中 Chrome 版本 `157.0.8103.79`，Mach-O 包含 `x86_64` 和 `arm64`；用户 Applications 中无 Chrome；Homebrew 位于 `/opt/homebrew/bin/brew`。代码签名元数据报告 `com.google.Chrome`、TeamIdentifier `EQHXZ8M8AV` 和 stapled ticket，但未执行完整签名信任验证或浏览器启动测试。

可复查的只读命令：

```sh
uname -m
sw_vers -productVersion
test -x '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' \
  '/Applications/Google Chrome.app/Contents/Info.plist'
/usr/bin/file '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
/usr/bin/codesign -dv --verbose=2 '/Applications/Google Chrome.app'
.venv/bin/python -c 'from importlib.metadata import version; print(version("patchright"))'
```

## 一个明确的 CI 路线

README 可提供 GitHub Actions `runs-on: ubuntu-24.04` 示例；官方 runner 表中这个标签是 **x64**，不同于 `ubuntu-24.04-arm`。先安装项目要求的 Python 3.11 与 uv，再从 Google 下载 amd64 stable DEB 并用 apt 安装，依赖由 apt 和 Patchright 的 `install-deps chromium` 处理。Linux 的 `headless=False` 通过 Xvfb 提供显示服务。[GitHub runner 规格](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)、[uv CI 指南](https://docs.astral.sh/uv/guides/integration/github/)、[Playwright headed CI](https://playwright.dev/python/docs/ci#running-headed)

以下片段用于已经 checkout 并准备好 uv 的 Ubuntu 24.04 x64 job；它是依据官方文档和安装源码整理的方案，**没有在此次 macOS 研究中执行 CI 验证**：

```sh
uv sync --locked --python 3.11
curl --fail --location --retry 3 \
  'https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb' \
  --output /tmp/google-chrome.deb
sudo apt-get update
sudo apt-get install -y /tmp/google-chrome.deb xvfb xauth
uv run patchright install-deps chromium
google-chrome --version
test -x /opt/google/chrome/chrome

# 后续浏览器命令保持 headless=False，并加上 xvfb-run -a 前缀。
xvfb-run -a uv run python - <<'PY'
from tempfile import TemporaryDirectory
from patchright.sync_api import sync_playwright

with TemporaryDirectory(prefix="sau-chrome-smoke-") as profile:
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            profile, channel="chrome", headless=False, no_viewport=True
        )
        page = context.new_page()
        page.goto("about:blank")
        print("Chrome persistent context OK")
        context.close()
PY
```

DEB URL 是 Playwright `v1.64.1` 官方安装脚本使用的 Google 地址；`current` 是滚动 stable 包，固定 URL 不等于锁定浏览器版本。`install-deps` 只安装运行浏览器所需系统依赖；本地 CLI 帮助确认支持 `chromium`。无需为 `channel="chrome"` 下载另一个 Chromium 浏览器包。[Linux 安装源码](https://github.com/microsoft/playwright/blob/v1.64.1/packages/playwright-core/bin/reinstall_chrome_stable_linux.sh)、[系统依赖与 branded channel 文档](https://playwright.dev/python/docs/browsers)
