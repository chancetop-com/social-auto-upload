# 14 — patchright 1.64.4 升级

**What to build:** 把浏览器运行时依赖从当前版本精确升级到 `1.64.4`，并让现有离线测试套件在新版本下保持全绿。这是纯前置改动：不增加 MLX 行为，也不改变本地模式命令语义，只为后续 ticket 消除依赖噪音。

**Blocked by:** None — can start immediately.

**Status:** ready-for-agent

- [ ] `pyproject.toml` 对 patchright 使用精确 pin `1.64.4`，`uv.lock` 同步更新。
- [ ] 已重新安装对应的 Chromium（目标 156），并在提交说明或 CHANGELOG 记录浏览器版本。
- [ ] `python -m unittest discover -s tests` 全绿，没有新增 skip 或放宽断言。
- [ ] 明确记录：本票只做测试用例回归，不做真实账号的完整上传验证；stealth 差异作为已知未验证风险留给真实使用暴露。
- [ ] `requirements.txt`（旧 Web 环境，`playwright==1.52.0`）保持不变。
- [ ] 回滚路径已写入提交说明：恢复旧 pin + lock + 重装浏览器。
