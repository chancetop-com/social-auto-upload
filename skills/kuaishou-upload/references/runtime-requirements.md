# 运行前提

需要已安装 `social-auto-upload`、可调用 `sau`，以及本次实际选择的浏览器。保留已有 `conf.py`，只在新安装缺失时复制 `conf.example.py`；安装后用 `sau kuaishou --help` 验证命令可用。

```bash
uv pip install -e .
sau kuaishou --help
```

默认使用系统 Chrome；用户从 Google 官方渠道安装适合系统和 CPU 的版本。显式 Chromium 使用项目固定 Patchright 的完整浏览器，有头和无头均需完整包：

```bash
uv run patchright install --no-shell chromium
sau kuaishou login --account creator --local-browser chromium --headed
```

仅安装所选来源，无需同时安装 Chrome 与 Chromium；headless shell 不能替代完整 Chromium。`LOCAL_CHROME_PATH` 可选择可靠识别为 Chrome/Chromium 的自定义可执行文件，优先于种类选择。启动失败停止，不换来源。Linux 有头模式需显示服务，安装系统依赖时可用 `uv run patchright install --with-deps --no-shell chromium`；仅支持无头的环境显式传 `--headless`。

## 配置与登录

`--headless` / `--headed` > `LOCAL_CHROME_HEADLESS` > False；`LOCAL_CHROME_PATH` > `--local-browser` > `LOCAL_BROWSER` > chrome。保留已有 True 配置。Profile 路径按实际种类隔离，切换 headless 或同种 binary 复用资料。不增加 stealth、固定 viewport、UA 或语言覆盖。

```bash
sau kuaishou login --account creator --headed
sau kuaishou check --account creator --headed
```

登录态存于 `browser_profiles/kuaishou/creator/chrome/`；旧 Cookie JSON 不读取或导出。登录生成的二维码图片是临时文件，应在登录等待期间展示给用户扫码。只有 login 创建资料并引导登录。安装成功、浏览器能启动和平台已登录分别验证；help 或离线测试不是登录成功证据。

## PATH 回退

可用 `uv run sau kuaishou --help`；Windows 也可运行 `.\.venv\Scripts\sau.exe kuaishou --help`，或先 `.\.venv\Scripts\Activate.ps1`。维护任务只验证命令或使用受控页面；快手没有 `--no-publish`，上传会实际提交。
