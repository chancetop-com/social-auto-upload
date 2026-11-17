# 运行前提

Skill 只提供操作说明。执行需要包含 Rednote 接入的 `social-auto-upload`、Python 3.10–3.12 和项目固定版本的 Patchright；`sau rednote --help` 应列出 login、check、两种上传及 reset-profile。命令可用、浏览器可启动、平台已登录是三个独立判据。

已有源码时，在该项目根目录安装：

```bash
uv pip install -e .
```

项目缺少 `conf.py` 时，按源码中的 `conf.example.py` 创建配置。保留已有配置。只安装独立 Skill 时，先取得包含 Rednote 的项目源码或发行版，再执行上述安装。

虚拟环境已安装但没有激活时，可直接调用：

```bash
# macOS / Linux
.venv/bin/sau rednote --help
```

```powershell
# Windows PowerShell
.\.venv\Scripts\sau.exe rednote --help
```

默认使用系统 Chrome，按 Google 官方方式安装；项目不自动安装或更新 Chrome。选择 Chromium 时执行 `uv run patchright install --no-shell chromium`，并传 `--local-browser chromium`；安装和运行保持相同 Python 环境及浏览器缓存设置，headless shell 不足以运行此模式。自定义兼容浏览器路径写入 `conf.py` 的 `LOCAL_CHROME_PATH`，优先于浏览器种类选择；无法识别产品或启动失败即停止。托管不要求本地 Chrome/Chromium。

本地默认有头；显式 `--headless` / `--headed` 优先于 `LOCAL_CHROME_HEADLESS`，缺省 False，保留已有值。无头登录会提供二维码图片，应将该图片展示给用户扫码，等待命令确认会话保存成功。登录在 CLI 的测试浏览器中完成，日常浏览器的会话不会自动带入。

本地保留浏览器/Profile 的语言、自然窗口和原生请求行为；托管 Profile 保留自身设置。遇到登录、验证码或二次验证提示时，交由用户在对应会话中完成，再运行 `check`。
