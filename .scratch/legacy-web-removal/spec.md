# 历史 Web 与旧示例清理

Status: done（2026-11-12）

## 目标

删除已停止维护的历史 Web 版本、CLI 不可达的旧小红书签名实现，以及 `examples/` 下的历史直连脚本；主线 CLI、Skills、测试与文章示例素材保持不变。

## 范围

- 删除：`sau_backend.py`、`sau_backend/`、`sau_frontend/`、`myUtils/`、`db/`、`Dockerfile`、`.dockerignore`、`start-win.bat`、`requirements.txt`
- 删除：`uploader/xhs_uploader/`、`conf.XHS_SERVER`
- 删除：`examples/` 下的历史上传/登录脚本；保留 `article.md`、`dayu_article.html`、`xueqiu_article.*`、`images/`
- 清理：`pyproject.toml`（`web` extra、`myUtils*`、不存在的 `cli_main`）、`README.md`、`docs/`、`.gitignore`、`CHANGELOG.md`、`uv.lock`

## 约束变更

本清理取代以下历史 spec / map 中“Web、`myUtils/`、`requirements.txt` 不改”的约束；只取代这些路径，各 feature 的平台行为结论仍然有效：

- `.scratch/multilogin-browser-mode/spec.md`、`map.md`、`issues/11-patchright-version.md`
- `.scratch/adspower-browser-mode/spec.md`、`map.md`、`issues/05-test-strategy.md`
- `.scratch/tiktok-browser-parity/spec.md`、`map.md`、`issues/07-test-strategy.md`
- `.scratch/instagram-browser-parity/spec.md`、`map.md`
- `.scratch/humanize-rollout/spec.md`、`map.md`
- `.scratch/xhs-publish-reliability/spec.md`、`issues/15-shared-layer-boundary.md`

## 验收

- `.venv/bin/python -m pytest -q tests` → 1507 passed, 2 skipped
- `sau --help` 正常
- `uv lock --check` 通过
