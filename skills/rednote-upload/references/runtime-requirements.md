# 运行前提

Skill 只提供操作说明。执行需要包含 Rednote 接入的 `social-auto-upload`、Python 3.10–3.12 和 Patchright Chromium；以 `sau rednote --help` 能列出四个子命令为就绪判据。

已有源码时，在该项目根目录安装并准备浏览器：

```bash
uv pip install -e .
patchright install chromium
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

CLI 默认有头；需要无头时显式使用 `--headless`。无头登录会提供二维码图片，应将该图片展示给用户扫码，等待命令确认会话保存成功。登录在 CLI 的测试浏览器中完成，日常浏览器的会话不会自动带入。

本地 context 使用 `en-US`，当前已验收页面仍显示中文；托管 Profile 保留自身设置。遇到登录、验证码或二次验证提示时，交由用户在对应会话中完成，再运行 `check`。
